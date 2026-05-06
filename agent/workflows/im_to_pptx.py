"""Main workflow: IM conversation → Document → Presentation → Delivery (Scenes A→B→C→D→F)."""

import asyncio
import json
import logging
from typing import Any

from agent.config import GROUP_GATE_ENABLED
from agent.executor import Executor, _run_lark_cli
from agent.feishu_bot import FeishuBot
from agent.flow import F, short_id
from agent.group_two_stage_gate import GroupTwoStageGate
from agent.IntentSystem import (
    AgentRuntimeState,
    CycleOutcome,
    IntentHooks,
    IntentSystem,
    record_success_case,
)
from agent.planner import Plan, Planner
from agent.workflows.content_structure import ContentStructurer

logger = logging.getLogger(__name__)

# Session state: tracks pending confirmations and active workflows
_pending_plans: dict[str, Plan] = {}  # chat_id -> Plan awaiting confirmation


def has_pending_plan(chat_id: str) -> bool:
    return chat_id in _pending_plans
_active_workflows: dict[str, bool] = {}  # chat_id -> is running
_chat_intent_states: dict[str, AgentRuntimeState] = {}  # IntentSystem 会话状态
# 按会话保留最近用户消息，供 IntentSystem / Planner 多轮上文（WS 仅逐条推送，需本地累积）
_chat_histories: dict[str, list[dict[str, str]]] = {}
_MAX_CHAT_TURNS = 40

_DOC_ID_FIELDS = frozenset({"document_id", "document_token", "doc_token"})


def _deep_find_document_id(obj: Any, depth: int = 0) -> str:
    """深度遍历 lark-cli / OpenAPI 返回 JSON，取文档 id 字段。"""
    if depth > 18 or obj is None:
        return ""
    if isinstance(obj, dict):
        doc = obj.get("document")
        if isinstance(doc, dict):
            for k in _DOC_ID_FIELDS:
                v = doc.get(k)
                if isinstance(v, str) and (s := v.strip()):
                    return s
        for k, v in obj.items():
            if k in _DOC_ID_FIELDS and isinstance(v, str) and (s := v.strip()):
                return s
        for v in obj.values():
            if r := _deep_find_document_id(v, depth + 1):
                return r
    elif isinstance(obj, list):
        for it in obj:
            if r := _deep_find_document_id(it, depth + 1):
                return r
    return ""


def _deep_find_str_by_keys(
    obj: Any, keys: tuple[str, ...], *, max_depth: int, depth: int = 0
) -> str:
    if depth > max_depth or obj is None:
        return ""
    if isinstance(obj, dict):
        for k in keys:
            v = obj.get(k)
            if isinstance(v, str) and (s := v.strip()):
                return s
        for v in obj.values():
            if r := _deep_find_str_by_keys(v, keys, max_depth=max_depth, depth=depth + 1):
                return r
    elif isinstance(obj, list):
        for it in obj:
            if r := _deep_find_str_by_keys(it, keys, max_depth=max_depth, depth=depth + 1):
                return r
    return ""


def _append_user_history(chat_id: str, text: str) -> None:
    t = (text or "").strip()[:12000]
    if not t:
        return
    hist = _chat_histories.setdefault(chat_id, [])
    hist.append({"role": "user", "content": t})
    while len(hist) > _MAX_CHAT_TURNS:
        hist.pop(0)


def _dialogue_with_history(chat_id: str, current_text: str) -> str:
    """把本会话此前用户消息与当前条拼成 dialogue，供 Trigger 与 PlanningLayer 使用。"""
    hist = _chat_histories.get(chat_id) or []
    parts: list[str] = []
    for m in hist[-24:]:
        if m.get("role") == "user":
            c = (m.get("content") or "").strip()
            if c:
                parts.append(c)
    cur = (current_text or "").strip()
    if cur:
        parts.append(cur)
    return "\n\n".join(parts)


# Tool Grounding 目录（与 IntentSystem 内映射一致，便于扩展与遥测）
DEFAULT_TOOL_CATALOG: list[dict] = [
    {"name": "lark_cli.docs.create"},
    {"name": "lark_cli.docs.update"},
    {"name": "lark_cli.slides.create"},
    {"name": "lark_cli.slides.patch"},
    {"name": "lark_cli.im.deliver"},
    {"name": "llm.respond"},
]


class ImToPptxWorkflow:
    def __init__(self, bot: FeishuBot, planner: Planner, executor: Executor):
        self.bot = bot
        self.planner = planner
        self.executor = executor
        self.structurer = ContentStructurer()
        # Planner 仅经 PlanningLayer 由 IntentSystem 调用，形成 Trigger→Policy→Plan 闭环
        self._intent = IntentSystem(planner)
        self._group_gate = GroupTwoStageGate()

    # 按钮动作 → 模拟文本消息映射
    _CARD_ACTION_TEXT = {
        "create_doc": "帮我根据聊天记录整理成文档",
        "create_ppt": "帮我根据聊天记录生成PPT",
        "detail_page": "进入详细页面",
    }

    async def handle_card_action(
        self, action: str, chat_id: str, message_id: str
    ) -> None:
        """Handle card button callback."""
        cid = short_id(chat_id)

        # Handle confirmation card buttons
        if action == "confirm_plan":
            if chat_id not in _pending_plans:
                F("workflow.card", "确认按钮但无待确认计划", chat_id=cid)
                return
            plan = _pending_plans.pop(chat_id)
            self._group_gate.clear_buffer(chat_id)
            F("workflow.card", "确认按钮→启动执行", chat_id=cid, intent=plan.intent, topic=plan.topic[:60])
            await self.bot.send_text(chat_id, "好的，开始执行！")
            asyncio.create_task(self._run_workflow(plan, chat_id))
            return

        if action == "cancel_plan":
            _pending_plans.pop(chat_id, None)
            self._group_gate.clear_buffer(chat_id)
            F("workflow.card", "取消按钮", chat_id=cid)
            await self.bot.send_text(chat_id, "已取消，有什么需要调整的吗？")
            return

        # If there's a pending plan, clear it first
        if chat_id in _pending_plans:
            _pending_plans.pop(chat_id, None)
            self._group_gate.clear_buffer(chat_id)

        # If a workflow is already running, reject
        if _active_workflows.get(chat_id):
            F("workflow.card", "任务执行中，忽略卡片动作", chat_id=cid, action=action)
            await self.bot.send_text(chat_id, "正在处理上一个任务，请稍等...")
            return

        text = self._CARD_ACTION_TEXT.get(action, "")
        if not text:
            F("workflow.card", "未知卡片动作", chat_id=cid, action=action)
            return

        F("workflow.card", "卡片动作→直接执行", chat_id=cid, action=action, text=text[:60])
        await self.bot.send_text(chat_id, "好的，开始执行！")

        # Use planner to generate meaningful plan from chat history
        intent = "generate_pptx" if action == "create_ppt" else "generate_doc"
        chat_history_text = _dialogue_with_history(chat_id, text)

        try:
            plan = await self.planner.plan(
                chat_history_text or text,
                chat_history=None,
            )
            # Override intent to match the button action
            plan.intent = intent
            F("workflow.card", "Planner生成Plan", chat_id=cid, intent=plan.intent, topic=plan.topic[:60])
        except Exception:
            logger.exception("Card action planner failed, using default plan")
            plan = Plan(
                intent=intent,
                topic=text.replace("帮我根据聊天记录", "").replace("整理成", "").replace("生成", ""),
                audience="",
                style="简约专业",
                estimated_pages=8,
                key_points=[],
                source_context="",
            )
        F("workflow.card", "直接构建Plan并执行", chat_id=cid, intent=plan.intent, topic=plan.topic[:60])
        asyncio.create_task(self._run_workflow(plan, chat_id))

    async def handle_message(
        self, text: str, chat_id: str, message_id: str, chat_type: str = "p2p"
    ) -> None:
        """Route incoming messages: confirmation check → (群聊两阶段门控) → planner → workflow."""
        cid = short_id(chat_id)
        F(
            "workflow.enter",
            "handle_message",
            chat_id=cid,
            chat_type=chat_type,
            pending_plan=chat_id in _pending_plans,
            active=_active_workflows.get(chat_id, False),
            text_preview=(text or "").replace("\n", " ")[:80],
        )
        # Check if this is a confirmation for a pending plan
        if chat_id in _pending_plans:
            cleaned = text.strip()
            logger.info("[workflow] pending_plan check: chat=%s text=%r", cid, cleaned)
            _confirm_kw = ("确认", "确认执行", "开始", "执行", "ok", "OK", "yes", "好的", "可以", "是")
            _cancel_kw = ("取消", "不", "no", "cancel", "不了", "不要")
            if any(kw in cleaned for kw in _confirm_kw) and not any(kw in cleaned for kw in _cancel_kw):
                plan = _pending_plans.pop(chat_id)
                _append_user_history(chat_id, text)
                self._group_gate.clear_buffer(chat_id)
                F("workflow.branch", "用户确认计划，启动执行", chat_id=cid, intent=plan.intent, topic=plan.topic[:60])
                await self.bot.send_text(chat_id, "好的，开始执行！")
                asyncio.create_task(self._run_workflow(plan, chat_id))
                return
            elif any(kw in cleaned for kw in _cancel_kw):
                _pending_plans.pop(chat_id, None)
                _append_user_history(chat_id, text)
                self._group_gate.clear_buffer(chat_id)
                F("workflow.branch", "用户取消待确认计划", chat_id=cid)
                await self.bot.send_text(chat_id, "已取消，有什么需要调整的吗？")
                return
            else:
                # User provided modified instructions, re-plan
                _pending_plans.pop(chat_id, None)
                self._group_gate.clear_buffer(chat_id)
                F("workflow.branch", "待确认状态下新指令，清除旧计划并重新规划", chat_id=cid)
                # Fall through to normal planning

        # Check if already running a workflow
        if _active_workflows.get(chat_id):
            F("workflow.busy", "本会话有任务在执行，拒绝新消息", chat_id=cid)
            await self.bot.send_text(chat_id, "正在处理上一个任务，请稍等...")
            return

        force_execute_on_confirm_plan = False
        dialogue_override: str | None = None

        if chat_type == "group":
            gr = await self._group_gate.handle_incoming(
                text=text, chat_id=chat_id, message_id=message_id
            )
            if gr.action == "silent_discard":
                F("workflow.gate", "群两阶段-丢弃", chat_id=cid)
                return
            if gr.action == "silent_buffered":
                F("workflow.gate", "群两阶段-仅缓存不回复", chat_id=cid)
                return
            if gr.action == "ask_missing":
                F("workflow.gate", "群两阶段-追问补充信息", chat_id=cid)
                await self.bot.send_text(chat_id, gr.reply_text)
                return
            if gr.action == "ask_confirm_execute":
                F("workflow.gate", "群两阶段-征询是否执行", chat_id=cid)
                await self.bot.send_text(chat_id, gr.reply_text)
                return
            # proceed：用缓存合并文本进入主流程
            text = gr.merged_text.strip()
            force_execute_on_confirm_plan = gr.force_execute_on_confirm_plan
            if GROUP_GATE_ENABLED:
                dialogue_override = text
            F(
                "workflow.gate",
                "群两阶段-进入 IntentSystem",
                chat_id=cid,
                merged_len=len(text),
                force_exec=force_execute_on_confirm_plan,
            )

        await self._run_intent_pipeline(
            text,
            chat_id,
            message_id,
            dialogue_override=dialogue_override,
            force_execute_on_confirm_plan=force_execute_on_confirm_plan,
        )

    async def _run_intent_pipeline(
        self,
        text: str,
        chat_id: str,
        message_id: str,
        *,
        dialogue_override: str | None = None,
        force_execute_on_confirm_plan: bool = False,
    ) -> None:
        cid = short_id(chat_id)
        istate = _chat_intent_states.setdefault(chat_id, AgentRuntimeState(chat_id=chat_id))

        async def _before_llm() -> None:
            await self.bot.send_text(chat_id, "正在分析您的需求...")

        if dialogue_override is not None:
            dialogue = dialogue_override
        else:
            dialogue = _dialogue_with_history(chat_id, text)
        F(
            "workflow.intent",
            "调用 IntentSystem.cycle",
            chat_id=cid,
            dialogue_len=len(dialogue or ""),
        )

        result = await self._intent.cycle(
            dialogue=dialogue,
            document="",
            state=istate,
            tools=DEFAULT_TOOL_CATALOG,
            hooks=IntentHooks(before_llm_plan=_before_llm),
        )

        _append_user_history(chat_id, text)
        logger.debug(
            "chat_id=%s history_turns=%d dialogue_len=%d",
            chat_id[:12],
            len(_chat_histories.get(chat_id) or []),
            len(dialogue),
        )

        if result.grounded_actions:
            logger.info(
                "Intent cycle grounded: %s",
                [g.tool for g in result.grounded_actions],
            )
        F(
            "workflow.intent_result",
            "cycle 返回",
            chat_id=cid,
            outcome=getattr(result.outcome, "value", str(result.outcome)),
            tools=[g.tool for g in (result.grounded_actions or [])][:8],
        )

        if result.outcome == CycleOutcome.SILENT:
            F("workflow.outcome", "SILENT 不回复", chat_id=cid)
            return
        if result.outcome == CycleOutcome.SILENT_PREPARE:
            F("workflow.outcome", "SILENT_PREPARE 仅写状态", chat_id=cid)
            return
        if result.outcome == CycleOutcome.ASK_USER:
            F("workflow.outcome", "ASK_USER 发澄清", chat_id=cid)
            await self.bot.send_text(chat_id, result.user_prompt or "请补充一下具体需求。")
            return
        if result.outcome == CycleOutcome.QUERY_REPLY:
            F("workflow.outcome", "QUERY_REPLY 直接答", chat_id=cid)
            await self.bot.send_text(
                chat_id, result.direct_text or "我需要更多信息来帮助您。"
            )
            return

        plan = result.plan
        if not plan:
            F("workflow.outcome", "无 plan，提示用户重试", chat_id=cid)
            await self.bot.send_text(chat_id, "未能生成有效任务，请换一种说法重试。")
            return

        if result.outcome == CycleOutcome.AUTO_EXEC:
            F("workflow.outcome", "AUTO_EXEC 直接跑工作流", chat_id=cid, intent=plan.intent)
            await self.bot.send_text(chat_id, "已根据策略自动开始执行…")
            asyncio.create_task(self._run_workflow(plan, chat_id))
            return

        if result.outcome == CycleOutcome.CONFIRM_PLAN and force_execute_on_confirm_plan:
            F(
                "workflow.outcome",
                "群门控三维满足：跳过计划确认直接执行",
                chat_id=cid,
                intent=plan.intent,
                topic=plan.topic[:60],
            )
            await self.bot.send_text(chat_id, "群内共识与信息已满足，开始执行…")
            asyncio.create_task(self._run_workflow(plan, chat_id))
            return

        _pending_plans[chat_id] = plan
        F("workflow.outcome", "CONFIRM_PLAN 已写入待确认", chat_id=cid, intent=plan.intent, topic=plan.topic[:80])
        await self._send_confirmation_card(chat_id, plan)

    async def _send_confirmation_card(self, chat_id: str, plan: Plan) -> None:
        """Send confirmation as an interactive card with confirm/cancel buttons."""
        import json as _json
        intent_label = "生成文档" if plan.intent == "generate_doc" else "生成PPT"
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "📋 任务计划"},
                "template": "blue",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**📌 主题：**{plan.topic}\n"
                            f"**👥 受众：**{plan.audience or '通用'}\n"
                            f"**🎨 风格：**{plan.style}\n"
                            f"**📄 预计页数：**{plan.estimated_pages}\n\n"
                            + "**📝 核心要点：**\n"
                            + "\n".join(f"  {i}. {pt}" for i, pt in enumerate(plan.key_points, 1))
                        ),
                    },
                },
                {"tag": "hr"},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": f"✅ 确认{intent_label}"},
                            "type": "primary",
                            "value": {"action": "confirm_plan"},
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "❌ 取消"},
                            "type": "danger",
                            "value": {"action": "cancel_plan"},
                        },
                    ],
                },
            ],
        }
        await self.bot.send_card(chat_id, card)

    async def _run_workflow(self, plan: Plan, chat_id: str):
        """Execute the full workflow: plan → doc → slides → deliver."""
        cid = short_id(chat_id)
        F("workflow.run", "开始 _run_workflow", chat_id=cid, intent=plan.intent, topic=plan.topic[:80])
        _active_workflows[chat_id] = True
        doc_token = ""
        slides_id = ""

        try:
            # Step 1: Gather source content from chat history (user messages only)
            source_text = ""
            # Try to read recent chat messages as source material
            chat_history = await self._get_chat_history(chat_id)
            if chat_history:
                source_text = chat_history
                F("workflow.run", "步骤1 从群聊历史获取内容", chat_id=cid, source_len=len(source_text))
            elif plan.source_context:
                source_text = plan.source_context
                F("workflow.run", "步骤1 从plan.source_context", chat_id=cid, source_len=len(source_text))
            else:
                F("workflow.run", "步骤1 无源上下文", chat_id=cid)

            # Step 2: Structure content (Scene C preparation)
            await self.bot.send_text(chat_id, "📝 正在整理内容结构...")
            F("workflow.run", "步骤2 ContentStructurer.structure 调用中", chat_id=cid)
            structured = await self.structurer.structure(plan, source_text)
            F(
                "workflow.run",
                "步骤2 完成",
                chat_id=cid,
                doc_chars=len(structured.doc_content or ""),
                slides_outline=len(structured.slides_outline or []),
            )

            if not structured.doc_content:
                F("workflow.run", "中止：无 doc_content", chat_id=cid)
                await self.bot.send_text(chat_id, "内容生成失败，请重试。")
                return

            # Step 3: Create document (Scene C)
            await self.bot.send_text(chat_id, "📄 正在创建飞书文档...")
            F("workflow.run", "步骤3 create_document 调用中", chat_id=cid, title=plan.topic[:60])
            doc_result = await self.executor.create_document(
                title=plan.topic,
                content=structured.doc_content,
                doc_format="markdown",
            )

            if doc_result.success and doc_result.data:
                doc_token = self._extract_doc_token(doc_result.data)
                F("workflow.run", "步骤3 文档 API 成功", chat_id=cid, doc_token=short_id(doc_token, 20))
                if doc_token:
                    await self.bot.send_text(chat_id, f"✅ 文档已创建！")
                else:
                    logger.warning("Document created but token not found in response")
                    F("workflow.run", "步骤3 警告：响应中未解析到 token", chat_id=cid)
            else:
                logger.error("Document creation failed: %s", doc_result.error)
                F("workflow.run", "步骤3 失败", chat_id=cid, error=(doc_result.error or "")[:120])
                err_short = (doc_result.error or "")[:200]
                hint = ""
                if "need_user_authorization" in (doc_result.error or ""):
                    hint = "\n\n提示：未登录 lark-cli 用户身份时请在 .env 设置 LARK_CLI_IDENTITY=bot，或执行 lark-cli auth login --domain docs,slides,drive"
                await self.bot.send_text(chat_id, f"⚠️ 文档创建失败：{err_short}{hint}")

            # Step 4: Generate slides XML and create presentation (Scene D)
            if plan.intent in ("generate_pptx",) and structured.slides_outline:
                await self.bot.send_text(chat_id, "📊 正在生成演示文稿...")
                F("workflow.run", "步骤4 generate_slides_xml", chat_id=cid, pages=len(structured.slides_outline))
                slides_xml = await self.structurer.generate_slides_xml(
                    structured.slides_outline, plan.style
                )
                F("workflow.run", "步骤4 XML 批次数完成", chat_id=cid, xml_slides=len(slides_xml.slides or []))

                if slides_xml.slides:
                    slides_json = json.dumps(slides_xml.slides, ensure_ascii=False)
                    F("workflow.run", "步骤4 create_slides 调用中", chat_id=cid, json_chars=len(slides_json), page_count=len(slides_xml.slides))
                    slides_result = await self.executor.create_slides(
                        title=plan.topic,
                        slides_json=slides_json,
                    )

                    # Extract slides_id even from partial success (data may be present)
                    if slides_result.data:
                        slides_id = self._extract_slides_id(slides_result.data)

                    if slides_result.success:
                        F("workflow.run", "步骤4 幻灯片 API 成功", chat_id=cid, slides_id=short_id(slides_id, 20))
                        if slides_id:
                            await self.bot.send_text(chat_id, "✅ 演示文稿已创建！")
                        else:
                            logger.warning("Slides created but ID not found")
                            F("workflow.run", "步骤4 警告：未解析 slides id", chat_id=cid)
                    else:
                        logger.error("Slides creation failed: %s", slides_result.error)
                        F("workflow.run", "步骤4 失败", chat_id=cid, error=(slides_result.error or "")[:100])
                        if slides_id:
                            await self.bot.send_text(
                                chat_id, f"⚠️ 演示文稿创建部分失败：{slides_result.error[:100]}\n但已有部分内容生成，正在获取链接..."
                            )
                        else:
                            await self.bot.send_text(
                                chat_id, f"⚠️ 演示文稿创建失败：{slides_result.error[:100]}"
                            )
                else:
                    F("workflow.run", "步骤4 中止：无 slides_xml", chat_id=cid)
                    await self.bot.send_text(chat_id, "⚠️ 幻灯片内容生成失败")
            else:
                F(
                    "workflow.run",
                    "跳过步骤4 幻灯片",
                    chat_id=cid,
                    intent=plan.intent,
                    has_outline=bool(structured.slides_outline),
                )

            # Step 4.5: Set public sharing so links are accessible
            for token, dtype in [(doc_token, "docx"), (slides_id, "slides")]:
                if token:
                    perm = await self.executor.set_public_sharing(token, dtype)
                    if perm.success:
                        F("workflow.run", "步骤4.5 公开权限设置成功", chat_id=cid, dtype=dtype)
                    else:
                        logger.warning("Failed to set public sharing for %s: %s", dtype, perm.error)
                        F("workflow.run", "步骤4.5 权限设置失败", chat_id=cid, dtype=dtype, error=(perm.error or "")[:80])

            # Step 5: Deliver results (Scene F)
            F("workflow.run", "步骤5 _deliver", chat_id=cid, doc=bool(doc_token), slides=bool(slides_id))
            await self._deliver(chat_id, doc_token, slides_id, plan, structured)
            F("workflow.run", "全部完成", chat_id=cid)

        except Exception:
            logger.exception("Workflow execution failed")
            F("workflow.run", "异常终止", chat_id=cid, see="logger.exception")
            await self.bot.send_text(chat_id, "❌ 执行过程中出错，请重试。")
        finally:
            _active_workflows.pop(chat_id, None)
            F("workflow.run", "释放 active 锁", chat_id=cid)

    async def run_delivery_pipeline(self, plan: Plan, chat_id: str) -> None:
        """执行从结构化内容到 lark-cli 创建文档/幻灯片并交付的完整流程（与 Bot WebSocket 路径一致）。"""
        F("workflow.pipeline", "run_delivery_pipeline 入口", chat_id=short_id(chat_id), intent=plan.intent)
        await self._run_workflow(plan, chat_id)

    async def _deliver(self, chat_id: str, doc_token: str, slides_id: str,
                       plan: Plan, structured):
        """Deliver results with share links."""
        cid = short_id(chat_id)
        F("deliver", "拉取分享链接", chat_id=cid, has_doc_token=bool(doc_token), has_slides_id=bool(slides_id))
        doc_url = ""
        slides_url = ""

        # Get share links
        if doc_token:
            meta = await self.executor.get_file_meta(doc_token, "docx")
            if meta.success and meta.data:
                doc_url = self._extract_url(meta.data, doc_token)

        if slides_id:
            meta = await self.executor.get_file_meta(slides_id, "slides")
            if meta.success and meta.data:
                slides_url = self._extract_url(meta.data, slides_id)

        # Build delivery message
        lines = [
            "🎉 任务完成！以下是生成的材料：",
            "",
        ]

        if doc_url:
            lines.append(f"📄 文档：{doc_url}")
        elif doc_token:
            lines.append(f"📄 文档 Token：{doc_token}")

        if slides_url:
            lines.append(f"📊 演示文稿：{slides_url}")
        elif slides_id:
            lines.append(f"📊 演示文稿 ID：{slides_id}")

        lines.extend([
            "",
            f"📝 摘要：{structured.summary}",
            "",
            "如需修改，请告诉我具体调整内容。",
        ])

        await self.bot.send_text(chat_id, "\n".join(lines))
        F("deliver", "已发送交付消息", chat_id=cid, doc_url=bool(doc_url), slides_url=bool(slides_url))

        st = _chat_intent_states.get(chat_id)
        if st:
            record_success_case(st, plan, structured.summary or plan.topic)
            F("deliver", "已写入成功案例 memory", chat_id=cid)

    def _extract_doc_token(self, data: dict) -> str:
        """从 lark-cli docs +create 的 JSON 中解析文档 token（兼容 ok/data 包一层与深层嵌套）。"""
        if not isinstance(data, dict):
            return ""
        tok = _deep_find_document_id(data)
        if not tok:
            logger.warning(
                "create_document 响应中未找到 document_id，顶层 keys=%s",
                list(data.keys())[:20],
            )
        return tok

    def _extract_slides_id(self, data: dict) -> str:
        """从 lark-cli slides +create 的 JSON 中解析演示文稿 id。"""
        if not isinstance(data, dict):
            return ""
        for key in ("xml_presentation_id", "presentation_id", "id"):
            found = _deep_find_str_by_keys(data, (key,), max_depth=16)
            if found:
                return found
        return ""

    async def _get_chat_history(self, chat_id: str) -> str:
        """Read recent user messages from the chat, filtering out bot replies.

        Uses lark-cli +chat-messages-list with --as user (bot identity lacks permission).
        Paginates through messages to collect enough user content.
        """
        all_user_texts: list[str] = []
        bot_app_id = getattr(self.bot, "_app_id", "") or ""
        page_token = ""
        max_pages = 5

        for _ in range(max_pages):
            args = [
                "im", "+chat-messages-list",
                "--chat-id", chat_id,
                "--page-size", "20",
                "--as", "user",
            ]
            if page_token:
                args.extend(["--page-token", page_token])

            result = await _run_lark_cli(*args)
            if not result.success or not result.data:
                break

            data = result.data
            # Navigate: data.data.messages or data.messages
            inner = data.get("data", data) if isinstance(data, dict) else {}
            if not isinstance(inner, dict):
                break
            messages = inner.get("messages", [])

            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                sender = msg.get("sender", {})
                sender_type = sender.get("sender_type", "").lower()
                sender_id = sender.get("id", "")
                # Skip bot/app messages
                if sender_type in ("app", "bot"):
                    continue
                if bot_app_id and sender_id == bot_app_id:
                    continue

                content = msg.get("content", "")
                msg_type = msg.get("msg_type", "")
                text = ""
                if msg_type == "text":
                    try:
                        parsed = json.loads(content)
                        text = parsed.get("text", "") if isinstance(parsed, dict) else str(parsed)
                    except (json.JSONDecodeError, TypeError):
                        text = content
                elif msg_type == "post":
                    try:
                        parsed = json.loads(content)
                        text = self._extract_post_text(parsed)
                    except (json.JSONDecodeError, TypeError):
                        text = content[:200]
                else:
                    continue

                text = text.strip()
                if text:
                    all_user_texts.append(text)

            # Check if there are more pages
            if not inner.get("has_more"):
                break
            page_token = inner.get("page_token", "")
            if not page_token:
                break

        if not all_user_texts:
            return ""

        # Messages come newest-first; reverse for chronological order
        all_user_texts.reverse()
        return "\n".join(all_user_texts)

    @staticmethod
    def _extract_post_text(post_data: dict) -> str:
        """Extract plain text from a Feishu post (rich text) message."""
        if not isinstance(post_data, dict):
            return ""
        content = post_data.get("content", [])
        if not isinstance(content, list):
            return ""
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            # Each block has a list of text runs
            for run in block.get("content", []):
                if not isinstance(run, dict):
                    continue
                # text_run has text content
                text = run.get("text", "") or run.get("content", "")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
            # Also check for link, at, etc.
        return " ".join(parts)

    def _extract_url(self, data: dict, token: str) -> str:
        """Extract share URL from file metadata."""
        if isinstance(data, dict):
            # lark-cli returns the full API response, URL may be nested under data.metas
            for container in (data, data.get("data", {})):
                metas = container.get("metas", []) if isinstance(container, dict) else []
                if isinstance(metas, list):
                    for meta in metas:
                        if isinstance(meta, dict) and meta.get("url"):
                            return meta["url"]
                url = container.get("url", "") if isinstance(container, dict) else ""
                if url:
                    return url
        return f"https://mcnu49qm2u6a.feishu.cn/slides/{token}"
