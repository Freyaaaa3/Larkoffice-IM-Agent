"""Task Executor: async wrapper around lark-cli commands."""

import asyncio
import json
import logging
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from typing import Any

from agent.config import LARK_CLI_IDENTITY
from agent.flow import F

logger = logging.getLogger(__name__)


def _find_lark_cli() -> list[str]:
    """Find lark-cli executable path, returning [node, run.js] on Windows
    to bypass .cmd wrapper which misinterprets < > characters in arguments."""
    if sys.platform == "win32":
        node_exe = shutil.which("node")
        npm_prefix = os.popen("npm prefix -g 2>nul").read().strip()
        if node_exe and npm_prefix:
            js_entry = os.path.join(npm_prefix, "node_modules", "@larksuite", "cli", "scripts", "run.js")
            if os.path.isfile(js_entry):
                return [node_exe, js_entry]
    # Fallback: use lark-cli directly
    path = shutil.which("lark-cli")
    if path:
        return [path]
    if sys.platform == "win32":
        npm_prefix = os.popen("npm prefix -g 2>nul").read().strip()
        if npm_prefix:
            cmd_path = os.path.join(npm_prefix, "lark-cli.cmd")
            if os.path.isfile(cmd_path):
                return [cmd_path]
    return ["lark-cli"]


LARK_CLI_CMD = _find_lark_cli()


def _deep_find_str(obj: Any, keys: tuple[str, ...], depth: int = 0) -> str:
    """Recursively search a dict/list for the first matching key with a non-empty string value."""
    if depth > 12 or obj is None:
        return ""
    if isinstance(obj, dict):
        for k in keys:
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        for v in obj.values():
            r = _deep_find_str(v, keys, depth + 1)
            if r:
                return r
    elif isinstance(obj, list):
        for item in obj:
            r = _deep_find_str(item, keys, depth + 1)
            if r:
                return r
    return ""


@dataclass
class ExecutionResult:
    success: bool
    data: dict | None = None
    error: str = ""


async def _run_lark_cli(*args: str, format_json: bool = False) -> ExecutionResult:
    """Execute a lark-cli command and return parsed JSON result.

    format_json: add --format json flag (only for raw API calls, not shortcuts).
    Shortcuts (+verb) output JSON by default.
    """
    full_args = list(args)
    if format_json:
        full_args += ["--format", "json"]
    preview = " ".join(full_args[:8]) + (" …" if len(full_args) > 8 else "")
    logger.info("lark-cli %s", preview)
    F("exec.cli", "子进程启动", cmd_preview=preview[:200], argv_n=len(full_args))

    # Force UTF-8 output from lark-cli
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "LANG": "C.UTF-8"}

    proc = await asyncio.create_subprocess_exec(
        *LARK_CLI_CMD,
        *full_args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    stdout, stderr = await proc.communicate()

    out = stdout.decode("utf-8", errors="replace").strip()
    err = stderr.decode("utf-8", errors="replace").strip()

    if proc.returncode != 0:
        # Some errors go to stdout (lark-cli outputs JSON errors to stdout)
        if out and '"ok"' in out:
            try:
                data = json.loads(out)
                if not data.get("ok", True):
                    msg = data.get("error", {}).get("message", err or "unknown")
                    logger.error("lark-cli API error: %s", msg)
                    F("exec.cli", "结束 failure", rc=proc.returncode, api_err=msg[:120])
                    return ExecutionResult(success=False, error=msg)
            except json.JSONDecodeError:
                pass
        logger.error("lark-cli failed (rc=%d): %s", proc.returncode, err or out[:200])
        F("exec.cli", "结束 failure", rc=proc.returncode, stderr=(err or out)[:120])
        return ExecutionResult(success=False, error=err or out[:200])

    if not out:
        F("exec.cli", "结束 success", rc=0, empty_stdout=True)
        return ExecutionResult(success=True, data={})

    try:
        data = json.loads(out)
        F("exec.cli", "结束 success", rc=0, json_keys=list(data.keys())[:12] if isinstance(data, dict) else "list")
        return ExecutionResult(success=True, data=data)
    except json.JSONDecodeError:
        F("exec.cli", "结束 success", rc=0, raw_stdout_len=len(out))
        return ExecutionResult(success=True, data={"raw": out})


def _as_flag() -> list[str]:
    return ["--as", LARK_CLI_IDENTITY] if LARK_CLI_IDENTITY else []


class Executor:
    """High-level executor wrapping lark-cli commands for docs, slides, im, and drive."""

    # -- Document operations (Scene C) --

    async def create_document(self, title: str, content: str, doc_format: str = "markdown") -> ExecutionResult:
        """Create a Feishu document. Content can be XML or Markdown."""
        args: list[str] = [
            "docs", "+create",
            "--api-version", "v2",
            "--doc-format", doc_format,
        ]
        if (title or "").strip():
            args.extend(["--title", (title or "").strip()[:500]])
        args.extend(["--content", content])
        args.extend(_as_flag())
        return await _run_lark_cli(*args)

    async def update_document(self, doc_token: str, content: str, command: str = "append",
                              doc_format: str = "markdown") -> ExecutionResult:
        """Update a Feishu document (append, overwrite, str_replace, etc.)."""
        return await _run_lark_cli(
            "docs", "+update",
            "--api-version", "v2",
            "--doc", doc_token,
            "--command", command,
            "--doc-format", doc_format,
            "--content", content,
            *_as_flag(),
        )

    async def fetch_document(self, doc_token: str, scope: str = "outline") -> ExecutionResult:
        """Fetch document content. Scope: full, outline, range, keyword, section."""
        return await _run_lark_cli(
            "docs", "+fetch",
            "--api-version", "v2",
            "--doc", doc_token,
            "--scope", scope,
            *_as_flag(),
        )

    # -- Slides operations (Scene D) --

    async def create_slides(self, title: str, slides_json: str) -> ExecutionResult:
        """Create a presentation with pages. slides_json is a JSON array of slide XML strings.

        Strategy: split into small batches (≤3 slides) and use `slides +create --slides`
        for the first batch, then `add_slide` for remaining pages. This avoids hitting
        Windows command-line length limit while keeping the first batch on the reliable
        `+create` code path.
        """
        try:
            slides_list = json.loads(slides_json)
        except json.JSONDecodeError:
            return ExecutionResult(success=False, error="slides_json 解析失败")

        if not slides_list:
            # Empty: just create blank presentation
            return await _run_lark_cli(
                "slides", "+create",
                "--title", title,
                "--slides", "[]",
                *_as_flag(),
            )

        # Split into batches to stay under Windows ~8191 char limit
        # First batch: try up to 3 slides via +create --slides
        BATCH_SIZE = 3
        first_batch = slides_list[:BATCH_SIZE]
        remaining = slides_list[BATCH_SIZE:]

        first_json = json.dumps(first_batch, ensure_ascii=False)
        F("exec.cli", "分批创建：首批", batch=len(first_batch), remaining=len(remaining), json_len=len(first_json))

        first_result = await _run_lark_cli(
            "slides", "+create",
            "--title", title,
            "--slides", first_json,
            *_as_flag(),
        )

        if not first_result.success:
            # If first batch is too large, try single slide
            if len(first_batch) > 1:
                F("exec.cli", "首批失败，尝试单页创建")
                single_json = json.dumps([slides_list[0]], ensure_ascii=False)
                first_result = await _run_lark_cli(
                    "slides", "+create",
                    "--title", title,
                    "--slides", single_json,
                    *_as_flag(),
                )
                if first_result.success:
                    remaining = slides_list[1:]
                # else: fall through, report error
            if not first_result.success:
                return first_result

        if not remaining:
            return first_result

        # Add remaining slides one by one via xml_presentation.slide.create
        presentation_id = _deep_find_str(first_result.data, ("xml_presentation_id", "presentation_id"))
        if not presentation_id:
            return ExecutionResult(success=False, error="创建演示文稿成功但未返回 presentation_id")

        added_ok = 0
        for i, slide_xml in enumerate(remaining):
            add_result = await self.add_slide(presentation_id, slide_xml)
            if add_result.success:
                added_ok += 1
            else:
                logger.warning("添加第 %d 页幻灯片失败: %s", BATCH_SIZE + i + 1, add_result.error)

        # If ALL remaining slides failed, report partial success
        if added_ok == 0 and len(remaining) > 0:
            logger.error("所有后续幻灯片添加失败")
            return ExecutionResult(
                success=False,
                error=f"演示文稿已创建（含首批{len(first_batch)}页），但后续{len(remaining)}页全部添加失败",
                data=first_result.data,
            )

        return first_result

    async def get_slides(self, presentation_id: str) -> ExecutionResult:
        """Read full presentation XML."""
        return await _run_lark_cli(
            "slides", "xml_presentations", "get",
            "--params", json.dumps({"xml_presentation_id": presentation_id}),
            *_as_flag(),
            format_json=True,
        )

    async def replace_slide(self, presentation_id: str, slide_id: str, parts_json: str) -> ExecutionResult:
        """Block-level replace/insert on a slide."""
        return await _run_lark_cli(
            "slides", "+replace-slide",
            "--presentation", presentation_id,
            "--slide-id", slide_id,
            "--parts", parts_json,
            "--yes",
            *_as_flag(),
        )

    async def add_slide(self, presentation_id: str, slide_xml: str,
                        before_slide_id: str = "") -> ExecutionResult:
        """Add a new slide to a presentation."""
        data = {"slide": {"content": slide_xml}}
        if before_slide_id:
            data["before_slide_id"] = before_slide_id
        return await _run_lark_cli(
            "slides", "xml_presentation.slide", "create",
            "--params", json.dumps({"xml_presentation_id": presentation_id}),
            "--data", json.dumps(data),
            "--yes",
            *_as_flag(),
            format_json=True,
        )

    # -- IM operations (Scene A/F) --

    async def send_message(self, chat_id: str, msg_type: str, content: str) -> ExecutionResult:
        """Send a message to a chat."""
        return await _run_lark_cli(
            "im", "+messages-send",
            "--chat-id", chat_id,
            "--msg-type", msg_type,
            "--content", content,
        )

    async def search_messages(self, chat_id: str, query: str) -> ExecutionResult:
        """Search messages in a chat."""
        return await _run_lark_cli(
            "im", "+messages-search",
            "--chat-id", chat_id,
            "--query", query,
        )

    async def list_chat_messages(self, chat_id: str, count: int = 20,
                                 page_token: str = "") -> ExecutionResult:
        """List recent messages in a chat."""
        args = [
            "im", "+chat-messages-list",
            "--chat-id", chat_id,
            "--page-size", str(count),
        ]
        if page_token:
            args.extend(["--page-token", page_token])
        return await _run_lark_cli(*args)

    # -- Drive operations (Scene F) --

    async def get_file_meta(self, file_token: str, file_type: str = "docx") -> ExecutionResult:
        """Get file metadata with URL for sharing."""
        return await _run_lark_cli(
            "drive", "metas", "batch_query",
            "--data", json.dumps({
                "request_docs": [{"doc_type": file_type, "doc_token": file_token}],
                "with_url": True,
            }),
            format_json=True,
        )

    async def export_file(self, file_token: str, file_type: str, format: str = "pdf") -> ExecutionResult:
        """Export a file to a specific format."""
        return await _run_lark_cli(
            "drive", "+export",
            "--token", file_token,
            "--type", file_type,
            "--format", format,
        )

    # -- Drive permission operations --

    async def set_public_sharing(self, token: str, doc_type: str = "slides") -> ExecutionResult:
        """Set anyone-with-link-can-view permission for a document."""
        return await _run_lark_cli(
            "api", "PATCH", f"/open-apis/drive/v1/permissions/{token}/public",
            "--params", json.dumps({"type": doc_type}),
            "--data", json.dumps({
                "external_access_entity": "open",
                "security_entity": "anyone_can_view",
                "comment_entity": "anyone_can_view",
                "share_entity": "anyone",
                "link_share_entity": "anyone_readable",
            }),
            "--as", "bot",
        )

    # -- Whiteboard operations (Scene C optional) --

    async def update_whiteboard(self, board_token: str, content: str,
                                input_format: str = "mermaid") -> ExecutionResult:
        """Update a whiteboard with DSL/Mermaid/PlantUML."""
        return await _run_lark_cli(
            "whiteboard", "+update", board_token,
            "--source", "-",
            "--input_format", input_format,
            *_as_flag(),
            # Note: content needs to be piped via stdin; for simplicity using a temp approach
        )

    # -- Schema discovery --

    async def get_schema(self, service_resource_method: str) -> ExecutionResult:
        """Look up API parameter schema."""
        return await _run_lark_cli("schema", service_resource_method, format_json=True)
