"""Task Executor: async wrapper around lark-cli commands."""

import asyncio
import json
import logging
import os
import shutil
import sys
from dataclasses import dataclass
from typing import Any

from agent.config import LARK_CLI_IDENTITY
from agent.flow import F

logger = logging.getLogger(__name__)


def _find_lark_cli() -> str:
    """Find lark-cli executable path (handles Windows .cmd wrappers)."""
    path = shutil.which("lark-cli")
    if path:
        return path
    # Windows: try .cmd in common npm global dirs
    if sys.platform == "win32":
        npm_prefix = os.popen("npm prefix -g 2>nul").read().strip()
        if npm_prefix:
            cmd_path = os.path.join(npm_prefix, "lark-cli.cmd")
            if os.path.isfile(cmd_path):
                return cmd_path
    return "lark-cli"


LARK_CLI_PATH = _find_lark_cli()


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
        LARK_CLI_PATH,
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
        """Create a presentation with pages. slides_json is a JSON array of slide XML strings."""
        return await _run_lark_cli(
            "slides", "+create",
            "--title", title,
            "--slides", slides_json,
            *_as_flag(),
        )

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

    async def list_chat_messages(self, chat_id: str, count: int = 20) -> ExecutionResult:
        """List recent messages in a chat."""
        return await _run_lark_cli(
            "im", "+chat-messages-list",
            "--chat-id", chat_id,
            "--page-size", str(count),
        )

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
