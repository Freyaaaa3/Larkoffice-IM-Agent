"""Configuration management for the Feishu agent."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


# Feishu Bot
FEISHU_APP_ID = _env("FEISHU_APP_ID")
FEISHU_APP_SECRET = _env("FEISHU_APP_SECRET")

# LLM
LLM_API_KEY = _env("LLM_API_KEY")
LLM_BASE_URL = _env("LLM_BASE_URL")
LLM_MODEL = _env("LLM_MODEL", "gpt-4o")

# lark-cli
LARK_CLI_IDENTITY = _env("LARK_CLI_IDENTITY", "user")

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
SKILLS_DIR = PROJECT_ROOT / "skills"
LARK_SKILLS_DIR = PROJECT_ROOT / ".agents" / "skills"
