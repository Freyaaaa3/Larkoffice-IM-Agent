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
# 开放域名：国内默认 open.feishu.cn；海外 Lark 可设为 https://open.larksuite.com
FEISHU_BASE = _env("FEISHU_BASE", "https://open.feishu.cn").rstrip("/")

# LLM
LLM_API_KEY = _env("LLM_API_KEY")
LLM_BASE_URL = _env("LLM_BASE_URL")
LLM_MODEL = _env("LLM_MODEL", "gpt-4o")


def _env_bool(key: str, default: str = "0") -> bool:
    return _env(key, default).strip().lower() in ("1", "true", "yes", "on")


# 群聊两阶段门控：默认开启；可设 LLM_MODEL_GATE 使用更小/更便宜模型
GROUP_GATE_ENABLED = _env_bool("GROUP_GATE_ENABLED", "1")
try:
    GROUP_GATE_BUFFER_MAX = max(6, int(_env("GROUP_GATE_BUFFER_MAX", "28")))
except ValueError:
    GROUP_GATE_BUFFER_MAX = 28

# lark-cli：bot=仅应用/租户凭证（适合服务端 Agent）；user=需本机已执行 lark-cli auth login 并完成用户授权
LARK_CLI_IDENTITY = _env("LARK_CLI_IDENTITY", "bot")

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
SKILLS_DIR = PROJECT_ROOT / "skills"
LARK_SKILLS_DIR = PROJECT_ROOT / ".agents" / "skills"
