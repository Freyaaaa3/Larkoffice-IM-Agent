"""Main workflow: IM conversation → Document → Presentation → Delivery (Scenes A→B→C→D→F)."""

import asyncio
import json
import logging

from agent.executor import Executor, ExecutionResult
from agent.feishu_bot import FeishuBot
from agent.planner import Plan, Planner
from agent.workflows.content_structure import ContentStructurer

logger = logging.getLogger(__name__)

# Session state: tracks pending confirmations and active workflows
_pending_plans: dict[str, Plan] = {}  # chat_id -> Plan awaiting confirmation
_active_workflows: dict[str, bool] = {}  # chat_id -> is running


class ImToPptxWorkflow:
    def __init__(self, bot: FeishuBot, planner: Planner, executor: Executor):
        self.bot = bot
        self.planner = planner
        self.executor = executor
        self.structurer = ContentStructurer()

    async def handle_message(self, text: str, chat_id: str, message_id: str):
        """Route incoming messages: confirmation check → planner → workflow."""
        # Check if this is a confirmation for a pending plan
        if chat_id in _pending_plans:
            if text.strip() in ("确认", "确认执行", "开始", "执行", "ok", "OK", "yes"):
                plan = _pending_plans.pop(chat_id)
                await self.bot.send_text(chat_id, "好的，开始执行！")
                asyncio.create_task(self._run_workflow(plan, chat_id))
                return
            elif text.strip() in ("取消", "不", "no", "cancel"):
                _pending_plans.pop(chat_id, None)
                await self.bot.send_text(chat_id, "已取消，有什么需要调整的吗？")
                return
            else:
                # User provided modified instructions, re-plan
                _pending_plans.pop(chat_id, None)
                # Fall through to normal planning

        # Check if already running a workflow
        if _active_workflows.get(chat_id):
            await self.bot.send_text(chat_id, "正在处理上一个任务，请稍等...")
            return

        # Plan the task
        await self.bot.send_text(chat_id, "正在分析您的需求...")
        plan = await self.planner.plan(text)

        if plan.intent == "query":
            # Simple query, respond directly
            await self.bot.send_text(chat_id, plan.source_context or "我需要更多信息来帮助您。")
            return

        # Send plan for confirmation
        _pending_plans[chat_id] = plan
        await self.bot.send_text(chat_id, plan.to_confirmation_text())

    async def _run_workflow(self, plan: Plan, chat_id: str):
        """Execute the full workflow: plan → doc → slides → deliver."""
        _active_workflows[chat_id] = True
        doc_token = ""
        slides_id = ""

        try:
            # Step 1: Gather source content (if from IM history)
            source_text = ""
            if plan.source_context:
                source_text = plan.source_context

            # Step 2: Structure content (Scene C preparation)
            await self.bot.send_text(chat_id, "📝 正在整理内容结构...")
            structured = await self.structurer.structure(plan, source_text)

            if not structured.doc_content:
                await self.bot.send_text(chat_id, "内容生成失败，请重试。")
                return

            # Step 3: Create document (Scene C)
            await self.bot.send_text(chat_id, "📄 正在创建飞书文档...")
            doc_result = await self.executor.create_document(
                title=plan.topic,
                content=structured.doc_content,
                doc_format="markdown",
            )

            if doc_result.success and doc_result.data:
                doc_token = self._extract_doc_token(doc_result.data)
                if doc_token:
                    await self.bot.send_text(chat_id, f"✅ 文档已创建！")
                else:
                    logger.warning("Document created but token not found in response")
            else:
                logger.error("Document creation failed: %s", doc_result.error)
                await self.bot.send_text(chat_id, f"⚠️ 文档创建失败：{doc_result.error[:100]}")

            # Step 4: Generate slides XML and create presentation (Scene D)
            if plan.intent in ("generate_pptx",) and structured.slides_outline:
                await self.bot.send_text(chat_id, "📊 正在生成演示文稿...")
                slides_xml = await self.structurer.generate_slides_xml(
                    structured.slides_outline, plan.style
                )

                if slides_xml.slides:
                    slides_json = json.dumps(slides_xml.slides, ensure_ascii=False)
                    slides_result = await self.executor.create_slides(
                        title=plan.topic,
                        slides_json=slides_json,
                    )

                    if slides_result.success and slides_result.data:
                        slides_id = self._extract_slides_id(slides_result.data)
                        if slides_id:
                            await self.bot.send_text(chat_id, "✅ 演示文稿已创建！")
                        else:
                            logger.warning("Slides created but ID not found")
                    else:
                        logger.error("Slides creation failed: %s", slides_result.error)
                        await self.bot.send_text(
                            chat_id, f"⚠️ 演示文稿创建失败：{slides_result.error[:100]}"
                        )
                else:
                    await self.bot.send_text(chat_id, "⚠️ 幻灯片内容生成失败")

            # Step 5: Deliver results (Scene F)
            await self._deliver(chat_id, doc_token, slides_id, plan, structured)

        except Exception:
            logger.exception("Workflow execution failed")
            await self.bot.send_text(chat_id, "❌ 执行过程中出错，请重试。")
        finally:
            _active_workflows.pop(chat_id, None)

    async def _deliver(self, chat_id: str, doc_token: str, slides_id: str,
                       plan: Plan, structured):
        """Deliver results with share links."""
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

    def _extract_doc_token(self, data: dict) -> str:
        """Extract document token from create response."""
        if isinstance(data, dict):
            # lark-cli +create returns: {"document": {"document_id": "..."}}
            doc = data.get("document", {})
            if isinstance(doc, dict) and doc.get("document_id"):
                return doc["document_id"]
            # fallback
            if data.get("document_id"):
                return data["document_id"]
        return ""

    def _extract_slides_id(self, data: dict) -> str:
        """Extract presentation ID from create response."""
        if isinstance(data, dict):
            # lark-cli slides +create returns: {"xml_presentation_id": "..."}
            if data.get("xml_presentation_id"):
                return data["xml_presentation_id"]
            if data.get("id"):
                return data["id"]
        return ""

    def _extract_url(self, data: dict, token: str) -> str:
        """Extract share URL from file metadata."""
        if isinstance(data, dict):
            # drive metas batch_query returns: {"metas": [{"url": "..."}, ...]}
            metas = data.get("metas", [])
            if isinstance(metas, list):
                for meta in metas:
                    if isinstance(meta, dict) and meta.get("url"):
                        return meta["url"]
            url = data.get("url", "")
            if url:
                return url
        return f"https://mcnu49qm2u6a.feishu.cn/docx/{token}"
