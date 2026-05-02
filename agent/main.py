"""Feishu Agent entry point: starts the bot and workflow system."""

import asyncio
import logging
import sys

from agent.config import FEISHU_APP_ID, FEISHU_APP_SECRET, LLM_API_KEY
from agent.executor import Executor
from agent.feishu_bot import FeishuBot
from agent.planner import Planner
from agent.workflows.im_to_pptx import ImToPptxWorkflow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
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

    # Initialize components
    bot = FeishuBot()
    planner = Planner()
    executor = Executor()
    workflow = ImToPptxWorkflow(bot, planner, executor)

    # Register message handler
    bot.on_message(workflow.handle_message)

    # Start the bot
    logger.info("Starting Feishu Agent...")
    await bot.start()


def run():
    """Synchronous entry point."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down...")


if __name__ == "__main__":
    run()
