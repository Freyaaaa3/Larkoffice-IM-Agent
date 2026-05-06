"""Feishu Bot: WebSocket long-connection event handler for IM messages."""

import asyncio
import json
import logging
import os
import re
from typing import Any, Callable, Coroutine

import requests
import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    CreateMessageResponse,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
    ReplyMessageResponse,
)

from agent.config import FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_BASE
from agent.flow import F, short_id

logger = logging.getLogger(__name__)


def _fmt_preview(text: str, max_len: int = 60) -> str:
    t = (text or "").replace("\n", " ").strip()
    return t if len(t) <= max_len else t[: max_len - 1] + "…"


def _is_valid_bot_open_id(value: str) -> bool:
    """机器人 open_id 为 ou_ 开头；cli_ 为应用 ID，不能用于 @ 匹配。"""
    v = (value or "").strip()
    return bool(v) and v.startswith("ou_")


def fetch_bot_open_id(app_id: str, app_secret: str, base_url: str | None = None) -> str:
    """
    GET /open-apis/bot/v3/info，响应含 bot.open_id（ou_…）。
    需先 POST tenant_access_token/internal。
    """
    base = (base_url or FEISHU_BASE).rstrip("/")
    tok = requests.post(
        f"{base}/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=30,
    )
    tok.raise_for_status()
    tj = tok.json()
    if tj.get("code", 0) != 0:
        raise RuntimeError(f"tenant_access_token: {tj}")
    token = tj.get("tenant_access_token") or ""
    if not token:
        raise RuntimeError(f"tenant_access_token 缺失: {tj}")

    info = requests.get(
        f"{base}/open-apis/bot/v3/info",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    info.raise_for_status()
    body = info.json()
    if body.get("code", 0) != 0:
        raise RuntimeError(f"bot/v3/info: {body}")
    bot = body.get("bot") or (body.get("data") or {}).get("bot") or {}
    if isinstance(bot, dict):
        return str(bot.get("open_id", "") or "").strip()
    return str(getattr(bot, "open_id", "") or "").strip()

MessageHandler = Callable[[str, str, str, str], Coroutine[Any, Any, None]]
# Args: (text, chat_id, message_id, chat_type) -> None；chat_type 为 p2p | group


class FeishuBot:
    def __init__(self):
        self._app_id = FEISHU_APP_ID
        self._app_secret = FEISHU_APP_SECRET
        self._client: lark.Client | None = None
        self._ws_client: Any = None
        self._handler: MessageHandler | None = None
        self._bot_open_id: str = ""
        # 防止 WS 重复投递同一条消息导致「分析→规划」循环
        self._processed_message_ids: set[str] = set()
        self._processed_message_ids_cap = 4000
        # 群聊未@时是否放行（由 workflow 层设置，如 pending plan 时放行确认消息）
        self._allow_unmentioned_group_msg: Callable[[str], bool] | None = None

    def _sender_is_bot_self(self, sender) -> bool:
        """忽略本机器人发出的消息，避免把「正在分析…」等回执当作用户输入再次规划。"""
        st = (getattr(sender, "sender_type", None) or "").strip().lower()
        if st in ("app", "bot"):
            return True
        sid = getattr(sender, "sender_id", None)
        oid = ""
        if sid is not None:
            oid = (getattr(sid, "open_id", None) or "").strip()
        bot = (self._bot_open_id or "").strip()
        return bool(bot and oid and oid == bot)

    def _is_duplicate_im_message(self, message_id: str) -> bool:
        if not message_id:
            return False
        if message_id in self._processed_message_ids:
            return True
        self._processed_message_ids.add(message_id)
        if len(self._processed_message_ids) > self._processed_message_ids_cap:
            self._processed_message_ids.clear()
        return False

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
        F("bot", "身份就绪", bot_open_id=short_id(self._bot_open_id, 24))

        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_message_event)
            # 飞书会推送「消息已读」事件；不注册则 SDK 反复报 processor not found
            .register_p2_im_message_message_read_v1(self._on_message_read_v1)
            .build()
        )

        try:
            from lark_oapi.ws.client import Client as WsClient
        except ImportError as e:
            raise RuntimeError(
                "当前 lark-oapi 不包含 WebSocket 模块（需 >=1.4.24）。请在项目根执行：\n"
                "  pip install -U \"lark-oapi>=1.4.24\"\n"
                "或重新安装本项目：pip install -e ."
            ) from e

        self._ws_client = WsClient(
            app_id=self._app_id,
            app_secret=self._app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )

        logger.info("Feishu Bot starting WebSocket connection...")
        F("bot.ws", "正在建立长连接（run_in_executor 阻塞）…")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._ws_client.start)

    async def _hydrate_bot_identity(self):
        """优先合法 FEISHU_BOT_OPEN_ID（ou_）；否则 GET /bot/v3/info；cli_ 应用 ID会忽略并拉取。"""
        env_oid = os.environ.get("FEISHU_BOT_OPEN_ID", "").strip()
        if env_oid and not _is_valid_bot_open_id(env_oid):
            logger.warning(
                "FEISHU_BOT_OPEN_ID=%s 不是机器人 open_id（应为 ou_ 开头，不是 cli_ 应用 ID），将调用 bot/v3/info",
                env_oid[:24],
            )
            env_oid = ""
        if env_oid:
            self._bot_open_id = env_oid
            logger.info("Bot open_id from FEISHU_BOT_OPEN_ID=%s", self._bot_open_id)
            return
        try:
            oid = await asyncio.to_thread(
                fetch_bot_open_id, self._app_id, self._app_secret, FEISHU_BASE
            )
            if oid:
                self._bot_open_id = oid
                logger.info("Bot open_id from GET /open-apis/bot/v3/info: %s", self._bot_open_id)
            else:
                logger.warning("bot/v3/info 未返回 open_id；群聊仅 @ 一条时可回退识别")
        except Exception as e:
            logger.warning("拉取机器人 open_id 失败: %s", e)

    def _on_message_read_v1(self, _data: Any) -> None:
        """消息已读回执，无业务逻辑；仅占位注册以消除 WS 层 processor not found。"""
        return

    def _on_message_event(self, data: lark.im.v1.P2ImMessageReceiveV1) -> None:
        try:
            event = data.event
            msg = event.message
            sender = event.sender

            if not msg or not sender:
                F("im.event", "忽略", reason="no_msg_or_sender")
                return

            msg_type = msg.message_type
            if msg_type not in ("text", "post"):
                F("im.event", "忽略", reason="unsupported_msg_type", msg_type=msg_type or "")
                return

            chat_id = msg.chat_id
            message_id = msg.message_id
            chat_type = msg.chat_type  # "p2p" or "group"
            sender_type = (getattr(sender, "sender_type", None) or "").strip().lower()

            F(
                "im.recv",
                "收到消息",
                chat_type=chat_type or "?",
                msg_type=msg_type,
                chat_id=short_id(chat_id),
                message_id=short_id(message_id, 18),
                sender_type=sender_type or "?",
            )

            if self._sender_is_bot_self(sender):
                F("im.filter", "跳过", reason="bot_self", message_id=short_id(message_id, 18))
                return
            if self._is_duplicate_im_message(message_id):
                F("im.filter", "跳过", reason="duplicate_message_id", message_id=short_id(message_id, 18))
                return

            # Extract text content
            text = self._extract_text(msg)

            # In group chats, only respond when @mentioned (unless callback allows)
            if chat_type == "group":
                if not self._is_mentioned(msg):
                    allow = (
                        self._allow_unmentioned_group_msg is not None
                        and self._allow_unmentioned_group_msg(chat_id)
                    )
                    if not allow:
                        F("im.filter", "跳过", reason="group_not_mentioned", chat_id=short_id(chat_id))
                        return
                text = self._strip_mention(text)

            if not text.strip():
                F("im.filter", "跳过", reason="empty_after_mention", chat_type=chat_type or "")
                if chat_type == "group" and self._client:
                    asyncio.create_task(
                        self.send_text(
                            chat_id,
                            "我在，请直接说明需求，例如：「做一份季度汇报 PPT，10 页左右」。",
                        )
                    )
                return

            if not self._handler:
                logger.warning("No message handler registered")
                F("im.error", "未注册 handler")
                return

            F(
                "im.dispatch",
                "进入 workflow",
                text_preview=_fmt_preview(text.strip(), 60),
                chat_id=short_id(chat_id),
            )
            asyncio.create_task(
                self._safe_handle(text.strip(), chat_id, message_id, chat_type or "p2p")
            )
        except Exception:
            logger.exception("Error processing message event")
            F("im.error", "事件处理异常", see="logger.exception")

    async def _safe_handle(self, text: str, chat_id: str, message_id: str, chat_type: str = "p2p"):
        F(
            "im.handler",
            "开始",
            chat_id=short_id(chat_id),
            message_id=short_id(message_id, 18),
            chat_type=chat_type or "p2p",
        )
        try:
            await self._handler(text, chat_id, message_id, chat_type or "p2p")
            F("im.handler", "正常结束", chat_id=short_id(chat_id))
        except Exception:
            logger.exception("Error in message handler")
            F("im.handler", "异常", chat_id=short_id(chat_id), see="logger.exception")
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
        oid = (self._bot_open_id or "").strip()
        if _is_valid_bot_open_id(oid):
            for m in mentions:
                if hasattr(m, "id") and hasattr(m.id, "open_id"):
                    mid = getattr(m.id, "open_id", None) or ""
                    if mid == oid:
                        return True
            return False
        # 未配置合法 ou_：仅当消息里 @ 了「一个人」时视为在叫机器人（常见误把 cli_ 填进 .env）
        if len(mentions) == 1:
            m0 = mentions[0]
            return bool(hasattr(m0, "id") and getattr(m0.id, "open_id", None))
        return False

    def _strip_mention(self, text: str) -> str:
        # 飞书占位符为 @_user_1、@_user_2 …
        return re.sub(r"@_user_\d+", "", text or "").strip()

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
                    .receive_id_type("chat_id")
                    .request_body(
                        CreateMessageRequestBody.builder()
                        .msg_type("post")
                        .content(body_json)
                        .receive_id(chat_id)
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
