"""终端流程日志：统一前缀 [AGENT]，便于观察全链路执行步骤。"""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger("agent.flow")


def short_id(s: str | None, max_len: int = 12) -> str:
    if not s:
        return ""
    t = str(s)
    return t if len(t) <= max_len else t[: max_len - 1] + "…"


def _fmt(v: Any, max_len: int = 120) -> str:
    if isinstance(v, float):
        return f"{v:.4g}"
    if isinstance(v, bool):
        return "true" if v else "false"
    s = str(v).replace("\n", "\\n")
    if len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


def pipeline_log(scope: str, step: int, title: str, detail: str) -> None:
    """终端一行打印：门控/意图链路的 1-粗筛、2-有用性、3-对话状态、4-policy 等。"""
    print(f"[AGENT][{scope}] {step}-{title} | {detail}", flush=True)


def F(phase: str, detail: str = "", **kv: Any) -> None:
    """打印一条流程状态：phase 为步骤名，detail 为短说明，kv 为键值上下文。"""
    parts: list[str] = [f"[AGENT] {phase}"]
    if detail:
        parts.append(detail)
    if kv:
        parts.append(" ".join(f"{k}={_fmt(v)}" for k, v in kv.items()))
    _log.info(" | ".join(parts))
