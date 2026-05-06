"""Feishu Agent entry point: starts the bot and workflow system."""

import asyncio
import logging
import os
import sys

# 允许 `python agent/main.py` 与 `python -m agent.main` 两种启动方式
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from agent.config import FEISHU_APP_ID, FEISHU_APP_SECRET, LLM_API_KEY
from agent.executor import Executor, LARK_CLI_PATH
from agent.feishu_bot import FeishuBot
from agent.flow import F
from agent.planner import Planner
from agent.workflows.im_to_pptx import ImToPptxWorkflow, has_pending_plan

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
# 流程日志与根日志同级，终端可见全链路
logging.getLogger("agent.flow").setLevel(logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    # Validate config
    missing = []
    if not FEISHU_APP_ID:
        missing.append("FEISHU_APP_ID")
    if not FEISHU_APP_SECRET:
        missing.append("FEISHU_APP_SECRET")
    if not LLM_API_KEY:
        missing.append("LLM_API_KEY")

    if missing:
        logger.error("Missing required config: %s. Check your .env file.", ", ".join(missing))
        sys.exit(1)

    F("boot", "env_ok", app_id_set=bool(FEISHU_APP_ID), llm_key_set=bool(LLM_API_KEY))

    # Initialize components
    bot = FeishuBot()
    F("boot", "FeishuBot 已创建")
    planner = Planner()
    F("boot", "Planner 已创建", model=getattr(planner, "_model", ""))
    executor = Executor()
    F("boot", "Executor 已创建", lark_cli_path=LARK_CLI_PATH)
    workflow = ImToPptxWorkflow(bot, planner, executor)
    F("boot", "ImToPptxWorkflow 已挂载 IntentSystem")

    # Register message handler
    bot.on_message(workflow.handle_message)
    bot._allow_unmentioned_group_msg = has_pending_plan
    F("boot", "已注册 workflow.handle_message → bot.on_message")

    # Start the bot（WebSocket 成功后会阻塞等待事件，终端不再刷日志属正常）
    logger.info("Starting Feishu Agent...")
    logger.info("连接建立后将长驻等待 IM；在群内 @ 机器人发消息即可触发（Ctrl+C 退出）。")
    F("boot", "即将启动 WebSocket（阻塞等待事件）…")
    await bot.start()


def run():
    """Synchronous entry point."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        F("boot", "收到 Ctrl+C，正在退出")
        logger.info("Shutting down...")


if __name__ == "__main__":
    run()

