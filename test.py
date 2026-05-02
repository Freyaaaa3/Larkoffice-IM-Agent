"""
群聊拉取 + IntentSystem +（可选）完整 lark-cli 交付 +（可选）经 lark-oapi 发群（与 FeishuBot 同路径）。

环境变量（与主程序一致，建议配合 .env）：
  FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_CHAT_ID — 拉群消息必填
  LLM_API_KEY — IntentSystem → Planner 必填

重要：FEISHU_APP_SECRET 必须是飞书开放平台「凭证与基础信息」里的应用密钥（长字符串）。
      不能写成 1 或占位符，否则 tenant_access_token 会失败。

可选：
  TEST_FULL_AGENT=1 — 与 agent.main 相同：Executor(lark-cli) 建文档/幻灯片并交付；
                     进度与最终链接通过 lark-oapi 发群（需 im:message 等权限、机器人已在群）。
  FEISHU_TEST_SEND=1 — 仅在未开 TEST_FULL_AGENT 时，把「意图阶段拟回复」发到群里。
  TEST_DIALOGUE_MODE=full|last — 默认 full
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any

import requests

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore[misc, assignment]

FEISHU_BASE = os.environ.get("FEISHU_BASE", "https://open.feishu.cn")


def _ensure_utf8_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise SystemExit(
            f"缺少环境变量 {name}。\n"
            f"请在 PowerShell 设置：\n"
            f'  $env:{name}="..."'
        )
    return v


def get_tenant_access_token(app_id: str, app_secret: str) -> str:
    url = f"{FEISHU_BASE}/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": app_id, "app_secret": app_secret}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code", 0) != 0:
        raise RuntimeError(f"获取 tenant_access_token 失败：{data}")
    return data["tenant_access_token"]


def list_chat_messages(tenant_token: str, chat_id: str, page_size: int = 50, max_pages: int = 2):
    url = f"{FEISHU_BASE}/open-apis/im/v1/messages"
    headers = {"Authorization": f"Bearer {tenant_token}"}

    params = {
        "container_id_type": "chat",
        "container_id": chat_id,
        "page_size": page_size,
        "sort_type": "ByCreateTimeDesc",
    }

    items: list[dict] = []
    page_token = None
    for _ in range(max_pages):
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code", 0) != 0:
            raise RuntimeError(f"拉取消息失败：{data}")
        chunk = (data.get("data") or {}).get("items") or []
        items.extend(chunk)
        page_token = (data.get("data") or {}).get("page_token")
        has_more = (data.get("data") or {}).get("has_more")
        if not has_more or not page_token:
            break
        time.sleep(0.2)
    return items


def _extract_text_from_message_content(content: str) -> str:
    if not content:
        return ""
    m = re.search(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"', content)
    if not m:
        return ""
    txt = m.group(1)
    txt = txt.replace(r"\/", "/").replace(r"\n", "\n").replace(r"\\", "\\").replace(r"\"", '"')
    return txt.strip()


def _extract_sender_id(it: dict) -> str:
    sender_id = "unknown_sender"
    sender = it.get("sender")
    if isinstance(sender, str):
        return sender or sender_id
    if isinstance(sender, dict):
        sid = sender.get("id")
        if isinstance(sid, str):
            return sid or sender_id
        if isinstance(sid, dict):
            return sid.get("open_id") or sid.get("user_id") or sender_id
    return sender_id


def _extract_message_text(it: dict) -> str:
    msg_type = (it.get("msg_type") or "").strip()
    if msg_type == "text":
        content = it.get("body", {}).get("content") or ""
        return _extract_text_from_message_content(content)
    raw = it.get("body", {}).get("content")
    if raw:
        return str(raw)
    return ""


def _message_sort_key(it: dict) -> int:
    for key in ("create_time", "update_time"):
        v = it.get(key)
        if v is None:
            continue
        try:
            return int(v)
        except (TypeError, ValueError):
            continue
    return 0


def build_dialogue_for_intent(items: list[dict], mode: str) -> tuple[str, str]:
    """
    返回 (用于 IntentSystem 的 dialogue, 最后一条纯文本摘要)。
    按时间升序拼接多轮，便于上下文理解。
    """
    ordered = sorted(items, key=_message_sort_key)
    lines: list[str] = []
    last_text = ""
    for it in ordered:
        sender = _extract_sender_id(it)
        msg_type = (it.get("msg_type") or "").strip() or "unknown"
        text = _extract_message_text(it)
        if not text.strip():
            continue
        last_text = text.strip()
        lines.append(f"[{sender[:16]}…][{msg_type}] {text.strip()}")

    if mode.strip().lower() == "last" and last_text:
        return last_text, last_text
    return "\n".join(lines), last_text


def analyze_messages(items: list[dict]) -> dict[str, Any]:
    type_counter: Counter[str] = Counter()
    sender_counter: Counter[str] = Counter()
    texts: list[str] = []

    for it in items:
        msg_type = (it.get("msg_type") or "").strip() or "unknown"
        type_counter[msg_type] += 1

        sender_id = _extract_sender_id(it)
        sender_counter[sender_id] += 1

        if msg_type == "text":
            content = it.get("body", {}).get("content") or ""
            txt = _extract_text_from_message_content(content)
            if txt:
                texts.append(txt)

    token_counter: Counter[str] = Counter()
    for t in texts:
        parts = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{2,}|\d+", t)
        for p in parts:
            token_counter[p.lower()] += 1

    return {
        "total": len(items),
        "type_top": type_counter.most_common(20),
        "unique_senders": len(sender_counter),
        "sender_top": sender_counter.most_common(20),
        "text_messages": len(texts),
        "keyword_top": token_counter.most_common(30),
    }


def _fmt_now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S%z")


def send_group_text_sdk(
    app_id: str,
    app_secret: str,
    chat_id: str,
    text: str,
    *,
    reply_to: str = "",
) -> list[str]:
    """
    使用 lark-oapi 发群文本，与 agent.feishu_bot.FeishuBot.send_text 同一路径。
    超长正文拆成多条，避免单条超限导致整段失败。
    失败时抛出 RuntimeError（不再静默吞掉）。
    """
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest,
        CreateMessageRequestBody,
        CreateMessageResponse,
        ReplyMessageRequest,
        ReplyMessageRequestBody,
        ReplyMessageResponse,
    )

    client = (
        lark.Client.builder()
        .app_id(app_id)
        .app_secret(app_secret)
        .log_level(lark.LogLevel.WARNING)
        .build()
    )

    payload = (text or "").strip()
    if not payload:
        print("[发群] 跳过空文本")
        return []

    # 单条尽量控制在常见上限内（飞书文档约 15KB～量级，保守按字符拆）
    chunk_size = 10000
    chunks: list[str] = []
    rest = payload
    while rest:
        chunks.append(rest[:chunk_size])
        rest = rest[chunk_size:]

    message_ids: list[str] = []
    for idx, chunk in enumerate(chunks):
        body_json = json.dumps({"text": chunk})
        if reply_to:
            req = (
                ReplyMessageRequest.builder()
                .message_id(reply_to)
                .request_body(
                    ReplyMessageRequestBody.builder()
                    .msg_type("text")
                    .content(body_json)
                    .build()
                )
                .build()
            )
            resp: ReplyMessageResponse = client.im.v1.message.reply(req)
        else:
            req = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(
                    CreateMessageRequestBody.builder()
                    .msg_type("text")
                    .content(body_json)
                    .receive_id(chat_id)
                    .build()
                )
                .build()
            )
            resp: CreateMessageResponse = client.im.v1.message.create(req)

        if not resp.success():
            log_id = ""
            gl = getattr(resp, "get_log_id", None)
            if callable(gl):
                try:
                    log_id = str(gl())
                except Exception:
                    pass
            raise RuntimeError(
                f"Feishu 发消息失败: code={resp.code} msg={resp.msg!r} log_id={log_id!r} "
                f"分段={idx + 1}/{len(chunks)}"
            )
        mid = ""
        if resp.data is not None:
            mid = getattr(resp.data, "message_id", "") or ""
        message_ids.append(mid)
        print(
            f"[发群成功] 分段 {idx + 1}/{len(chunks)} message_id={mid!r} "
            f"chars={len(chunk)} chat_id={chat_id[:24]}…"
        )
    return message_ids


class SdkGroupBotAdapter:
    """与 FeishuBot 相同 SDK 发群；供测试脚本里 ImToPptxWorkflow 复用交付逻辑。"""

    def __init__(self, app_id: str, app_secret: str):
        self._app_id = app_id
        self._app_secret = app_secret

    async def send_text(self, chat_id: str, text: str, reply_to: str = "") -> bool:
        await asyncio.to_thread(
            send_group_text_sdk,
            self._app_id,
            self._app_secret,
            chat_id,
            text,
            reply_to=reply_to or "",
        )
        return True


def _compose_reply_preview(result: Any) -> tuple[str | None, str]:
    """
    根据 IntentSystem 结果生成「拟发送」正文与结果标签。
    返回 (正文, outcome 说明)。
    """
    from agent.IntentSystem import CycleOutcome

    oc = result.outcome
    label = f"{oc.value}"

    if oc == CycleOutcome.SILENT:
        return None, f"{label}（策略门控：本轮不生成回复）"

    if oc == CycleOutcome.SILENT_PREPARE:
        return None, f"{label}（已缓存草稿至 state，不打扰群聊）"

    if oc == CycleOutcome.QUERY_REPLY:
        return result.direct_text or "", label

    if oc == CycleOutcome.ASK_USER:
        return result.user_prompt or "", label

    if oc == CycleOutcome.AUTO_EXEC and result.plan:
        p = result.plan
        sub = "\n".join(f"  - {t.get('description', '')}" for t in (p.subtasks or [])[:8])
        body = (
            "【测试】策略为自动执行。计划摘要：\n"
            f"- 意图: {p.intent}\n"
            f"- 主题: {p.topic}\n"
            f"- 步骤:\n{sub or '  (无)'}"
        )
        return body, label

    if oc == CycleOutcome.CONFIRM_PLAN and result.plan:
        return result.plan.to_confirmation_text(), label

    return "（无可用回复）", label


async def run_agent_intent_pipeline(
    dialogue: str,
    chat_id: str,
    *,
    print_llm_phase: bool = True,
) -> Any:
    from agent.IntentSystem import AgentRuntimeState, IntentHooks, IntentSystem

    state = AgentRuntimeState(chat_id=chat_id, user_prefers_confirm=True)

    async def _hook() -> None:
        if print_llm_phase:
            print(f"\n[{_fmt_now()}] [Agent] 进入 PlanningLayer（调用 LLM）…")

    # 与主流程一致的工具目录（若 IntentSystem 未导出则本地构造）
    try:
        from agent.workflows.im_to_pptx import DEFAULT_TOOL_CATALOG as tools  # type: ignore
    except Exception:
        tools = [
            {"name": "lark_cli.docs.create"},
            {"name": "lark_cli.docs.update"},
            {"name": "lark_cli.slides.create"},
            {"name": "lark_cli.slides.patch"},
            {"name": "lark_cli.im.deliver"},
            {"name": "llm.respond"},
        ]

    intent_sys = IntentSystem()
    return await intent_sys.cycle(
        dialogue,
        document="",
        state=state,
        tools=tools,
        hooks=IntentHooks(before_llm_plan=_hook),
    )


def print_intent_debug_block(result: Any, dialogue_snippet: str) -> None:
    """打印触发、置信、落地工具等关键信息。"""
    print("\n=== IntentSystem / Agent 关键信息 ===")
    print(f"时间: {_fmt_now()}")
    print(f"outcome: {result.outcome.value}")
    print(f"trigger_score: {result.trigger_score:.3f}")
    print(f"intent_confidence: {result.intent_confidence:.3f}")

    if result.trigger_signals:
        sig = result.trigger_signals
        print(
            "trigger_signals: "
            + ", ".join(f"{k}={v}" for k, v in sig.__dict__.items() if v)
            or "(无显式正信号)"
        )

    if result.plan:
        p = result.plan
        print(f"plan.intent: {p.intent}")
        print(f"plan.topic: {p.topic}")
        print(f"plan.style: {p.style}  estimated_pages: {p.estimated_pages}")
        if p.key_points:
            print("plan.key_points:")
            for i, kp in enumerate(p.key_points[:8], 1):
                print(f"  {i}. {kp}")
        if p.subtasks:
            print("plan.subtasks:")
            for t in p.subtasks[:12]:
                print(f"  - [{t.get('type')}] {t.get('description', '')}")

    if result.grounded_actions:
        print("Tool Grounding:")
        for g in result.grounded_actions:
            print(f"  - step {g.step_id}: {g.tool}  ({g.subtask_type}) {g.description[:60]}")

    print(f"\n--- 输入 dialogue 摘要（前 800 字）---\n{dialogue_snippet[:800]}")
    print(
        "\n[说明] 默认仅跑 IntentSystem + Planner（验证触发/策略/规划与 Tool Grounding 打印）。"
        "\n      若要连 lark-cli 一起验证（与线上 agent 相同工具链），请设置 TEST_FULL_AGENT=1。"
    )

    body, outcome_note = _compose_reply_preview(result)
    print(f"\n=== 拟回复（{outcome_note}）===")
    if body is None:
        print("(本轮不向群发送文本)")
    else:
        print(body)


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


async def main_async() -> None:
    _ensure_utf8_stdout()
    repo_root = os.path.dirname(os.path.abspath(__file__))
    if load_dotenv:
        load_dotenv(os.path.join(repo_root, ".env"))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    app_id = _require_env("FEISHU_APP_ID")
    app_secret = _require_env("FEISHU_APP_SECRET")
    chat_id = _require_env("FEISHU_CHAT_ID")
    _require_env("LLM_API_KEY")

    if app_secret.strip() in ("1", "0", "test", "xxx"):
        print(
            f"\n[警告] FEISHU_APP_SECRET 当前值疑似占位符，将无法正确鉴权。"
            f"\n      请到飞书开放平台复制「应用密钥」，勿使用 1 等无效值。"
        )

    page_size = int(os.environ.get("FEISHU_PAGE_SIZE", "50"))
    max_pages = int(os.environ.get("FEISHU_MAX_PAGES", "2"))
    dialogue_mode = os.environ.get("TEST_DIALOGUE_MODE", "full")
    send_to_chat = _env_truthy("FEISHU_TEST_SEND")
    full_agent = _env_truthy("TEST_FULL_AGENT")

    print(f"[{_fmt_now()}] 获取 tenant_access_token...")
    tenant_token = get_tenant_access_token(app_id, app_secret)
    print(f"[{_fmt_now()}] 拉取群聊消息 chat_id={chat_id} page_size={page_size} max_pages={max_pages} ...")
    items = list_chat_messages(tenant_token, chat_id, page_size=page_size, max_pages=max_pages)
    print(f"[{_fmt_now()}] 拉取完成：{len(items)} 条")

    print("\n=== 消息明细（发送者、内容）===")
    for it in sorted(items, key=_message_sort_key):
        sender_id = _extract_sender_id(it)
        msg_type = (it.get("msg_type") or "").strip() or "unknown"
        text = _extract_message_text(it)
        if msg_type != "text" and text:
            print(f"{sender_id}\t[{msg_type}]\t{text}")
        else:
            print(f"{sender_id}\t{text}")

    summary = analyze_messages(items)
    print("\n=== 统计分析 ===")
    print(f"消息总数：{summary['total']}")
    print(f"文本消息：{summary['text_messages']}")
    print(f"发言人数：{summary['unique_senders']}")
    print("\n消息类型分布 Top：")
    for k, v in summary["type_top"]:
        print(f"- {k}: {v}")
    print("\nTop 发言者：")
    for k, v in summary["sender_top"][:10]:
        print(f"- {k}: {v}")
    print("\nTop 关键词：")
    for k, v in summary["keyword_top"][:20]:
        print(f"- {k}: {v}")

    dialogue, last_text = build_dialogue_for_intent(items, dialogue_mode)
    if not dialogue.strip():
        print("\n[警告] 无可用文本消息，无法进行意图分析。")
        return

    print(f"\n=== 构建对话上下文（mode={dialogue_mode}）===")
    print(f"最后一条文本（参考）: {last_text[:200]!r}")
    print(f"dialogue 总长度: {len(dialogue)} 字符")

    print(f"\n[{_fmt_now()}] 运行 IntentSystem（异步）…")
    result = await run_agent_intent_pipeline(dialogue, chat_id)
    print_intent_debug_block(result, dialogue)

    from agent.IntentSystem import CycleOutcome
    from agent.executor import Executor
    from agent.planner import Planner
    from agent.workflows.im_to_pptx import ImToPptxWorkflow

    body, _note = _compose_reply_preview(result)

    if full_agent and result.plan and result.outcome in (
        CycleOutcome.CONFIRM_PLAN,
        CycleOutcome.AUTO_EXEC,
    ):
        if result.plan.intent != "query":
            print(
                f"\n=== TEST_FULL_AGENT=1：执行 run_delivery_pipeline（lark-cli）==="
                f"\n[{_fmt_now()}] 与 agent.main 相同：Executor → create_document / create_slides / get_file_meta"
                f"\n[提示] 测试脚本跳过群聊里人工回复「确认」，直接跑工具链；进度与交付由工作流经 lark-oapi 发群。"
            )
            adapter = SdkGroupBotAdapter(app_id, app_secret)
            wf = ImToPptxWorkflow(adapter, Planner(), Executor())
            try:
                await wf.run_delivery_pipeline(result.plan, chat_id)
                print(f"\n[{_fmt_now()}] 工作流结束（含文档/演示链接的交付消息已尝试发群）。")
            except Exception as e:
                print(f"\n[{_fmt_now()}] 工作流异常: {e}")
                raise
            return
        print("\n=== TEST_FULL_AGENT：意图为 query，无 lark-cli；下面将问答文案发群（若有）===")

    if full_agent and body:
        print(f"\n[{_fmt_now()}] TEST_FULL_AGENT → 发送本轮文案到群（lark-oapi）…")
        await SdkGroupBotAdapter(app_id, app_secret).send_text(chat_id, body)
        print("发送完成: ok=True")
    elif send_to_chat and body:
        print(f"\n[{_fmt_now()}] FEISHU_TEST_SEND=1 → 发送意图阶段拟回复到群（lark-oapi）…")
        try:
            mids = await asyncio.to_thread(
                send_group_text_sdk, app_id, app_secret, chat_id, body
            )
            print(f"发送成功: message_ids={mids!r}")
        except Exception as e:
            print(f"发送异常: {e}")
            raise
    elif send_to_chat and not body:
        print(f"\n[{_fmt_now()}] FEISHU_TEST_SEND=1 但本轮无文本可发（静默或仅缓存）。")
    else:
        print(
            f"\n[{_fmt_now()}] 未发群：可设 FEISHU_TEST_SEND=1 仅发意图回复；"
            f"或 TEST_FULL_AGENT=1 跑完整 lark-cli 并由工作流发进度与文档链接。"
        )


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
