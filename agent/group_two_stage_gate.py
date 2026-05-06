"""
群聊两阶段门控（小模型）：
- 阶段1：单条消息「有用 / 无用」；有用入缓存且不回复，无用丢弃。
- 阶段2：基于缓存整体判断 Task Presence / Readiness / Timing，再按规则决定是否追问、征询执行或进入主流程。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Literal

from openai import OpenAI

from agent.config import GROUP_GATE_BUFFER_MAX, GROUP_GATE_ENABLED, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from agent.flow import F, pipeline_log, short_id
from agent.IntentSystem import (
    AgentRuntimeState,
    TriggerSignals,
    _has_strong_task_signal,
    detect_triggers,
    summarize_dialogue,
    weak_trigger_coarse_pass,
)

logger = logging.getLogger(__name__)


def _gate_model() -> str:
    return os.environ.get("LLM_MODEL_GATE", "").strip() or LLM_MODEL


STAGE1_SYSTEM = """你是群聊机器人门控-阶段1（轻量分类）。用户发送了一条消息。
判断这条消息是否「对后续完成任务有用」。

【有用】包含：具体任务需求、主题/受众/页数、修改意见、方案要点、明确确认执行（如确认/开始）、推动收敛的表述等。
【无用】包含：纯寒暄（在吗/你好）、无意义测试、表情包式短句、与任务无关的闲聊、仅重复 @ 无实质内容等。

只输出一个 JSON 对象，不要其它文字：
{"useful": true 或 false, "reason": "不超过30字"}"""


STAGE2_SYSTEM = """你是群聊机器人门控-阶段2。下面多条消息是「已通过阶段1筛选」的有效消息，按时间顺序排列（可能来自不同群成员）。
请从三个维度判断当前群聊状态（每个维度 true/false）：

1) task_presence（是否存在任务）
   是否存在要做的事：例如写文档/做PPT/汇报、修改材料、生成内容等明确或可推断的工作项。

2) readiness（信息是否充分）
   是否已具备执行所需关键信息：类型（文档或PPT等）、主题或目标、大致范围（页数/篇幅/截止时间其一即可视为部分充分）、若仅泛泛说「写个材料」而无主题则偏不充分。

3) timing（时机是否合适 / 共识）
   是否出现可开干的信号：如「确认」「开始吧」「可以做了」「按这个方案执行」「差不多了就这样」「先按这个试一下」等明确推进或收敛表述；或存在足够明确的单次强指令（如「帮我做一份季度汇报PPT十页」）可视为 timing 为 true。

只输出 JSON，不要其它文字，字段如下：
{
  "task_presence": true/false,
  "readiness": true/false,
  "timing": true/false,
  "missing_info_question": "若 readiness 应为 false，这里写一句中文追问（否则空字符串）",
  "confirm_execute_prompt": "若 timing 应为 false 但 readiness 为 true，这里写一句中文征询是否开始执行（否则空字符串）",
  "note": "不超过40字说明"
}"""


GroupGateAction = Literal[
    "silent_discard",
    "silent_buffered",
    "ask_missing",
    "ask_confirm_execute",
    "proceed",
]


@dataclass
class GroupGateResult:
    action: GroupGateAction
    merged_text: str = ""
    reply_text: str = ""
    force_execute_on_confirm_plan: bool = False


def _extract_json_object(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    if "```json" in raw:
        raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in raw:
        raw = raw.split("```", 1)[1].split("```", 1)[0].strip()
    # Try strict parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Loose: extract first { ... } block and fix common issues
    i = raw.find("{")
    j = raw.rfind("}")
    if i >= 0 and j > i:
        chunk = raw[i : j + 1]
        # Fix Python-style bools
        chunk = chunk.replace("True", "true").replace("False", "false")
        # Strip trailing commas before } or ]
        chunk = re.sub(r",\s*([}\]])", r"\1", chunk)
        try:
            return json.loads(chunk)
        except json.JSONDecodeError:
            pass
    return json.loads(raw)  # re-raise original error


class GroupTwoStageGate:
    """按 chat_id 维护缓存；仅用于群聊。"""

    def __init__(self) -> None:
        self._client = OpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL or None,
            timeout=90.0,
            max_retries=1,
        )
        self._buffers: dict[str, list[dict[str, str]]] = {}

    def clear_buffer(self, chat_id: str) -> None:
        self._buffers.pop(chat_id, None)

    def _append_buffer(self, chat_id: str, message_id: str, text: str) -> None:
        buf = self._buffers.setdefault(chat_id, [])
        if any(x.get("message_id") == message_id for x in buf):
            return
        buf.append({"message_id": message_id, "text": (text or "").strip()[:8000]})
        cap = max(6, GROUP_GATE_BUFFER_MAX)
        while len(buf) > cap:
            buf.pop(0)

    def _merge_buffer(self, chat_id: str) -> str:
        buf = self._buffers.get(chat_id) or []
        parts = [f"[{i + 1}] {x['text']}" for i, x in enumerate(buf)]
        return "\n\n".join(parts).strip()

    async def _llm_json(self, system: str, user: str) -> dict[str, Any]:
        model = _gate_model()
        resp = await asyncio.to_thread(
            self._client.chat.completions.create,
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.15,
            max_tokens=600,
        )
        raw = (resp.choices[0].message.content or "").strip()
        return _extract_json_object(raw)

    async def handle_incoming(self, *, text: str, chat_id: str, message_id: str) -> GroupGateResult:
        cid = short_id(chat_id)
        if not GROUP_GATE_ENABLED:
            F("group.gate", "已关闭 GROUP_GATE_ENABLED，直通主流程", chat_id=cid)
            pipeline_log(
                "群门控",
                0,
                "旁路",
                f"GROUP_GATE_ENABLED=0 本层1-4跳过，交由意图链路 chat={cid}",
            )
            return GroupGateResult(action="proceed", merged_text=text.strip(), force_execute_on_confirm_plan=False)

        t = (text or "").strip()
        if not t:
            pipeline_log("群门控", 1, "粗筛", f"未通过 | 空消息 chat={cid}")
            return GroupGateResult(action="silent_discard")

        stub_state = AgentRuntimeState(chat_id=chat_id)
        ctx = summarize_dialogue(t)
        sig = detect_triggers(ctx)
        weak_ok, weak_score = weak_trigger_coarse_pass(sig, stub_state)
        pipeline_log(
            "群门控",
            1,
            "粗筛",
            f"通过={weak_ok} weak_score={weak_score:.3f} chat={cid}",
        )
        if not weak_ok:
            F("group.gate", "粗筛未通过", chat_id=cid, weak_score=weak_score)
            pipeline_log("群门控", 2, "有用性", "跳过(LLM) | 粗筛未通过")
            pipeline_log("群门控", 3, "对话状态", "跳过 | 粗筛未通过")
            pipeline_log("群门控", 4, "policy", "丢弃(silent_discard) | 粗筛未通过")
            return GroupGateResult(action="silent_discard")

        # 阶段1：有用性（强任务信号直接放行，跳过LLM）
        strong_task = _has_strong_task_signal(sig)
        if strong_task:
            useful = True
            F("group.gate", "阶段1跳过(强信号)", chat_id=cid)
            pipeline_log("群门控", 2, "有用性", f"跳过(LLM) | 强任务信号直接放行 chat={cid}")
        else:
            try:
                d1 = await self._llm_json(STAGE1_SYSTEM, f"消息：\n{t}\n\n只输出 JSON。")
                useful = bool(d1.get("useful"))
                F("group.gate", "阶段1", chat_id=cid, useful=useful, reason=str(d1.get("reason", ""))[:40])
            except Exception as e:
                logger.warning("group gate stage1 LLM 失败，保守丢弃: %s", e)
                F("group.gate", "阶段1 异常→丢弃", chat_id=cid, err=str(e)[:80])
                pipeline_log("群门控", 2, "有用性", f"异常→丢弃 err={str(e)[:60]} chat={cid}")
                pipeline_log("群门控", 3, "对话状态", "跳过 | 阶段1失败")
                pipeline_log("群门控", 4, "policy", "丢弃(silent_discard)")
                return GroupGateResult(action="silent_discard")

            if not useful:
                pipeline_log(
                    "群门控",
                    2,
                    "有用性",
                    f"判定=丢弃(不入缓存) reason={str(d1.get('reason', ''))[:40]} chat={cid}",
                )
                pipeline_log("群门控", 3, "对话状态", "跳过 | 本条未入缓存")
                pipeline_log("群门控", 4, "policy", "丢弃(silent_discard)")
                return GroupGateResult(action="silent_discard")

        self._append_buffer(chat_id, message_id, t)
        merged = self._merge_buffer(chat_id)
        _buf_n = len(self._buffers.get(chat_id) or [])
        pipeline_log(
            "群门控",
            2,
            "有用性",
            f"判定=加入缓存 buf条数={_buf_n} merged_len={len(merged)} chat={cid}",
        )
        F(
            "group.gate",
            "阶段1 已缓存",
            chat_id=cid,
            buf=_buf_n,
            merged_len=len(merged),
        )

        # 强任务信号直接放行，跳过阶段2 LLM
        if strong_task:
            self.clear_buffer(chat_id)
            F("group.gate", "强信号→跳过阶段2直接放行", chat_id=cid)
            pipeline_log("群门控", 3, "对话状态", f"跳过(LLM) | 强任务信号快速通道 chat={cid}")
            pipeline_log("群门控", 4, "policy", f"path=proceed 强信号直接放行 chat={cid}")
            return GroupGateResult(action="proceed", merged_text=merged, force_execute_on_confirm_plan=False)

        # 阶段2：对话状态（三维度 bool → 打印为 0/1 分 + 均值）
        try:
            d2 = await self._llm_json(
                STAGE2_SYSTEM,
                f"以下为群内与机器人相关的有效消息（按时间顺序）：\n\n{merged}\n\n只输出 JSON。",
            )
            tp = bool(d2.get("task_presence"))
            r = bool(d2.get("readiness"))
            tm = bool(d2.get("timing"))
            miss = str(d2.get("missing_info_question") or "").strip()
            cfm = str(d2.get("confirm_execute_prompt") or "").strip()
            note = str(d2.get("note") or "").strip()
            F(
                "group.gate",
                "阶段2",
                chat_id=cid,
                task_presence=tp,
                readiness=r,
                timing=tm,
                note=note[:60],
            )
            _tp = 1.0 if tp else 0.0
            _r = 1.0 if r else 0.0
            _tm = 1.0 if tm else 0.0
            _avg = (_tp + _r + _tm) / 3.0
            _gate_total = _avg
            pipeline_log(
                "群门控",
                3,
                "对话状态",
                f"task_presence={_tp:.1f} readiness={_r:.1f} timing(共识)={_tm:.1f} "
                f"三维均值={_avg:.3f} 门控总分(均值)={_gate_total:.3f} note={note[:32]} chat={cid}",
            )
        except Exception as e:
            logger.warning("group gate stage2 LLM 失败，保持静默缓存: %s", e)
            F("group.gate", "阶段2 异常→仅缓存", chat_id=cid, err=str(e)[:80])
            pipeline_log("群门控", 3, "对话状态", f"异常→仅缓存 err={str(e)[:60]} chat={cid}")
            pipeline_log("群门控", 4, "policy", "静默缓存(silent_buffered) | 阶段2失败")
            return GroupGateResult(action="silent_buffered")

        # 规则分支（与产品约定一致）
        # 强任务信号 + task_presence=true → 直接进入主流程，不等待 readiness/timing
        if strong_task and tp:
            self.clear_buffer(chat_id)
            F("group.gate", "强信号+任务存在→进入主流程", chat_id=cid)
            pipeline_log(
                "群门控",
                4,
                "policy",
                f"path=proceed 强信号快速通道(后续 IntentSystem/Planner) 已清缓存 chat={cid}",
            )
            return GroupGateResult(
                action="proceed",
                merged_text=merged,
                force_execute_on_confirm_plan=False,
            )

        if tp and r and tm:
            self.clear_buffer(chat_id)
            F("group.gate", "三维满足→进入主流程并倾向直接执行", chat_id=cid)
            pipeline_log(
                "群门控",
                4,
                "policy",
                f"path=proceed 进入意图链路(后续 Planner/Executor) 已清缓存 chat={cid}",
            )
            return GroupGateResult(
                action="proceed",
                merged_text=merged,
                force_execute_on_confirm_plan=True,
            )

        if tp and tm and not r:
            if not miss:
                miss = "为便于执行，请补充：要做文档还是 PPT、主题、大致页数或篇幅、必须包含的要点。"
            pipeline_log(
                "群门控",
                4,
                "policy",
                f"path=ask_missing 追问补充(不进入意图Planner) chat={cid}",
            )
            return GroupGateResult(action="ask_missing", reply_text=miss)

        if tp and r and not tm:
            if not cfm:
                cfm = (
                    "当前信息已较完整，但群内尚未明确「可以开始做」。"
                    "若可以执行请回复 **确认**；若还需调整请直接说明。"
                )
            pipeline_log(
                "群门控",
                4,
                "policy",
                f"path=ask_confirm_execute 征询执行(不进入意图Planner) chat={cid}",
            )
            return GroupGateResult(action="ask_confirm_execute", reply_text=cfm)

        pipeline_log(
            "群门控",
            4,
            "policy",
            f"path=silent_buffered 仅缓存不回复(不进入意图Planner) chat={cid}",
        )
        return GroupGateResult(action="silent_buffered")
