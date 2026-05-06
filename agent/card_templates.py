"""Feishu interactive card templates."""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_CARD_DIR = Path(__file__).resolve().parent.parent / "card"


def _load_card(filename: str) -> dict:
    path = _CARD_DIR / filename
    if not path.exists():
        logger.error("Card template not found: %s", path)
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("dsl", data)


def get_welcome_card() -> dict:
    """Card shown when user @bots with empty message in group."""
    return _load_card("机器人@页.card")
