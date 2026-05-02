"""Feishu Bot: WebSocket long-connection event handler for IM messages."""

import asyncio
import json
import logging
from typing import Any, Callable, Coroutine

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    CreateMessageResponse,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
    ReplyMessageResponse,
)

from agent.config import FEISHU_APP_ID, FEISHU_APP_SECRET

logger = logging.getLogger(__name__)

MessageHandler = Callable[[str, str, str], Coroutine[Any, Any, None]]
# Args: (text, chat_id, message_id) -> None


class FeishuBot:
    def __init__(self):
        self._app_id = FEISHU_APP_ID
        self._app_secret = FEISHU_APP_SECRET
        self._client: lark.Client | None = None
        self._ws_client: Any = None
        self._handler: MessageHandler | None = None
        self._bot_open_id: str = ""

    def on_message(self, handler: MessageHandler):
        self._handler = handler

    async def start(self):
        if not self._app_id or not self._app_secret:
            raise RuntimeError("FEISHU_APP_ID and FEISHU_APP_SECRET must be set in .env")

        self._client = (
            lark.Client.builder()
            .app_id(self._app_id)
            .app_secret(self._app_secret)
            .log_level(lark.LogLevel.WARNING)
            .build()
        )

        await self._hydrate_bot_identity()

        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_message_event)
            .build()
        )

        from lark_oapi.ws.client import WsClient

        self._ws_client = WsClient(
            app_id=self._app_id,
            app_secret=self._app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )

        logger.info("Feishu Bot starting WebSocket connection...")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._ws_client.start)

    async def _hydrate_bot_identity(self):
        try:
            resp = (
                self._client.im.v1.bot_info.with_http_client(None)
                .request(lark.BaseRequest.builder().build())
            )
            if resp.success():
                bot = resp.data.bot
                self._bot_open_id = getattr(bot, "open_id", "")
                logger.info("Bot identity: open_id=%s", self._bot_open_id)
        except Exception as e:
            logger.warning("Failed to hydrate bot identity: %s", e)

    def _on_message_event(self, data: lark.im.v1.P2ImMessageReceiveV1) -> None:
        try:
            event = data.event
            msg = event.message
            sender = event.sender

            if not msg or not sender:
                return

            msg_type = msg.message_type
            if msg_type not in ("text", "post"):
                return

            chat_id = msg.chat_id
            message_id = msg.message_id
            chat_type = msg.chat_type  # "p2p" or "group"

            # Extract text content
            text = self._extract_text(msg)

            # In group chats, only respond when @mentioned
            if chat_type == "group":
                if not self._is_mentioned(msg):
                    return
                text = self._strip_mention(text)

            if not text.strip():
                return

            if not self._handler:
                logger.warning("No message handler registered")
                return

            asyncio.create_task(
                self._safe_handle(text.strip(), chat_id, message_id)
            )
        except Exception:
            logger.exception("Error processing message event")

    async def _safe_handle(self, text: str, chat_id: str, message_id: str):
        try:
            await self._handler(text, chat_id, message_id)
        except Exception:
            logger.exception("Error in message handler")
            await self.send_text(chat_id, "抱歉，处理消息时出错了，请稍后再试。")

    def _extract_text(self, msg) -> str:
        content = msg.content or ""
        msg_type = msg.message_type

        if msg_type == "text":
            try:
                data = json.loads(content)
                return data.get("text", "")
            except (json.JSONDecodeError, TypeError):
                return content

        if msg_type == "post":
            try:
                data = json.loads(content)
                return self._extract_post_text(data)
            except (json.JSONDecodeError, TypeError):
                return content

        return ""

    def _extract_post_text(self, data: dict) -> str:
        parts = []
        content = data.get("content", {})
        for lang_blocks in content.values():
            if isinstance(lang_blocks, list):
                for block in lang_blocks:
                    if isinstance(block, list):
                        for elem in block:
                            if isinstance(elem, dict) and "text" in elem:
                                parts.append(elem["text"])
        return " ".join(parts)

    def _is_mentioned(self, msg) -> bool:
        mentions = msg.mentions
        if not mentions:
            return False
        for m in mentions:
            if hasattr(m, "id") and hasattr(m.id, "open_id"):
                if m.id.open_id == self._bot_open_id:
                    return True
            elif hasattr(m, "name"):
                return True
        return False

    def _strip_mention(self, text: str) -> str:
        return text.replace("@_user_1", "").strip()

    # -- Sending messages --

    async def send_text(self, chat_id: str, text: str, reply_to: str = "") -> bool:
        if not self._client:
            return False

        body_json = json.dumps({"text": text})

        try:
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
                resp: ReplyMessageResponse = await asyncio.to_thread(
                    self._client.im.v1.message.reply, req
                )
            else:
                req = (
                    CreateMessageRequest.builder()
                    .request_body(
                        CreateMessageRequestBody.builder()
                        .msg_type("text")
                        .content(body_json)
                        .receive_id(chat_id)
                        .receive_id_type("chat_id")
                        .build()
                    )
                    .build()
                )
                resp: CreateMessageResponse = await asyncio.to_thread(
                    self._client.im.v1.message.create, req
                )

            if not resp.success():
                logger.error("Send failed: code=%s msg=%s", resp.code, resp.msg)
                return False
            return True
        except Exception:
            logger.exception("Error sending message")
            return False

    async def send_post(
        self, chat_id: str, title: str, content_lines: list[list[dict]], reply_to: str = ""
    ) -> bool:
        if not self._client:
            return False

        body = {
            "zh_cn": {
                "title": title,
                "content": content_lines,
            }
        }
        body_json = json.dumps(body)

        try:
            if reply_to:
                req = (
                    ReplyMessageRequest.builder()
                    .message_id(reply_to)
                    .request_body(
                        ReplyMessageRequestBody.builder()
                        .msg_type("post")
                        .content(body_json)
                        .build()
                    )
                    .build()
                )
                resp = await asyncio.to_thread(self._client.im.v1.message.reply, req)
            else:
                req = (
                    CreateMessageRequest.builder()
                    .request_body(
                        CreateMessageRequestBody.builder()
                        .msg_type("post")
                        .content(body_json)
                        .receive_id(chat_id)
                        .receive_id_type("chat_id")
                        .build()
                    )
                    .build()
                )
                resp = await asyncio.to_thread(self._client.im.v1.message.create, req)

            if not resp.success():
                logger.error("Send post failed: code=%s msg=%s", resp.code, resp.msg)
                return False
            return True
        except Exception:
            logger.exception("Error sending post message")
            return False
