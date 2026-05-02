"""
IntentSystem：弱触发粗筛 → 有用性小模型 → 对话状态小模型 → Policy（仅「如何执行」）→
PlanningLayer（Planner）→ Tool Grounding。
执行器仍由上层根据 Plan / outcome 调用。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Literal

from openai import OpenAI

from agent.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from agent.flow import F, pipeline_log, short_id
from agent.planner import Plan, Planner

logger = logging.getLogger(__name__)

# --- 阈值：弱触发 / 有用性 / Policy（对话状态模型输出）---
WEAK_TRIGGER_MIN = 0.10
MESSAGE_USEFUL_MIN = 0.45
POLICY_TRIGGER_SCORE_MIN = 0.6
POLICY_READINESS_MIN = 0.5
DIALOGUE_FOR_STATE_MAX = 6000


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class TriggerSignals:
    """结构化触发信号（多标签），用于压缩搜索空间与 Policy 输入。"""

    report_need: bool = False
    modify_request: bool = False
    uncertainty: bool = False
    doc_request: bool = False
    ppt_request: bool = False
    deliver_request: bool = False
    # 寒暄 / 开场 / 泛求助：避免群 @ 后仅「你好」被策略完全静默
    casual_or_opening: bool = False

    def to_constraint_prefix(self) -> str:
        parts = [f"{k}={v}" for k, v in self.__dict__.items() if v]
        if not parts:
            return ""
        return "[触发信号: " + ", ".join(parts) + "]"


@dataclass
class IntentHypothesis:
    intent: str
    label: str
    score: float = 0.0


@dataclass
class DialogueStateSnapshot:
    """小模型对缓存/对话整体的状态估计（0~1）。

    ask_hint：在 Policy 判定 readiness 不足时，作为追问文案下发 IM（见 decide_execution_route）。
    解析时合并 missing_info / missing_info_question 等别名，避免模型字段名不一致导致追问丢失。
    """

    task_presence: float = 0.0
    readiness: float = 0.0
    consensus: float = 0.0
    trigger_score: float = 0.0
    ask_hint: str = ""


@dataclass
class GroundedAction:
    """计划步骤到工具名的落地（参数由执行层结合 Plan 再解析）。"""

    step_id: int
    subtask_type: str
    tool: str
    description: str
    params_hint: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentRuntimeState:
    """会话级状态：策略偏好、检索记忆、静默草稿。"""

    chat_id: str = ""
    user_prefers_confirm: bool = True
    silent_mode: bool = False
    memory: dict[str, Any] = field(default_factory=dict)

    def update(self, patch: dict[str, Any]) -> None:
        self.memory.update(patch)


class CycleOutcome(str, Enum):
    SILENT = "silent"  # 不介入
    QUERY_REPLY = "query_reply"  # 直接文本（问答）
    ASK_USER = "ask_user"  # 策略要求先澄清
    CONFIRM_PLAN = "confirm_plan"  # 展示计划待确认
    AUTO_EXEC = "auto_exec"  # 跳过确认直接执行
    SILENT_PREPARE = "silent_prepare"  # 仅写状态，不发 IM


@dataclass
class IntentCycleResult:
    outcome: CycleOutcome
    plan: Plan | None = None
    direct_text: str | None = None
    user_prompt: str | None = None
    trigger_score: float = 0.0
    trigger_signals: TriggerSignals | None = None
    intent_confidence: float = 0.0
    grounded_actions: list[GroundedAction] = field(default_factory=list)
    dialogue_state: DialogueStateSnapshot | None = None


@dataclass
class IntentHooks:
    """在进入高成本 LLM 规划前通知上层（例如发送「正在分析…」）。"""

    before_llm_plan: Callable[[], Awaitable[None]] | None = None


# ---------------------------------------------------------------------------
# Context & Trigger
# ---------------------------------------------------------------------------


def summarize_dialogue(dialogue: str, max_chars: int = 4000) -> str:
    """对话压缩与去噪：截断过长输入，保留尾部（通常含最新意图）。"""
    text = dialogue.strip()
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def detect_triggers(context: str) -> TriggerSignals:
    t = context.lower()
    signals = TriggerSignals()
    # 中文关键词
    signals.report_need = bool(
        re.search(r"汇报|总结|季度|年报|述职|review|deck|slides?", t, re.I)
    )
    signals.modify_request = bool(re.search(r"改|调整|替换|删页|加页|修改", t))
    signals.uncertainty = bool(re.search(r"不知道|不确定|哪个|是否|怎么|能否", t))
    signals.doc_request = bool(re.search(r"文档|docx|飞书文档|写个材料", t, re.I))
    signals.ppt_request = bool(
        re.search(r"ppt|幻灯片|演示|deck|keynote|汇报稿", t, re.I)
    )
    signals.deliver_request = bool(re.search(r"发我|分享|链接|交付|导出", t))
    signals.casual_or_opening = bool(
        re.search(
            r"你好|您好|在吗|在不在|hi|hello|hey|帮忙|帮我|请问|需要|想|要做|做个|生成|写个|ppt|幻灯片|文档",
            t,
            re.I,
        )
    )
    return signals


def compute_trigger_score(signals: TriggerSignals) -> float:
    """0~1：多信号加权，表示介入必要性。"""
    w = 0.0
    if signals.ppt_request:
        w += 0.35
    if signals.doc_request:
        w += 0.25
    if signals.report_need:
        w += 0.2
    if signals.modify_request:
        w += 0.2
    if signals.deliver_request:
        w += 0.1
    if signals.uncertainty:
        w += 0.05
    if signals.casual_or_opening:
        w += 0.2
    return min(1.0, w)


def weak_trigger_coarse_pass(
    signals: TriggerSignals, state: AgentRuntimeState
) -> tuple[bool, float]:
    """粗过滤：仅寒暄、无任务向关键词时不进入后续小模型。"""
    if state.memory.get("force_reasoning"):
        return True, 1.0
    score = compute_trigger_score(signals)
    task_like = (
        signals.ppt_request
        or signals.doc_request
        or signals.report_need
        or signals.modify_request
        or signals.deliver_request
    )
    if signals.casual_or_opening and not task_like:
        return False, score
    if state.silent_mode and score < 0.25:
        return False, score
    return score >= WEAK_TRIGGER_MIN, score


# ---------------------------------------------------------------------------
# Policy：不再决定「是否触发」，只决定「已可触发时如何执行」
# ---------------------------------------------------------------------------


ExecutionRoute = Literal["silent", "ask_user", "plan_confirm", "plan_auto"]


class PolicyEngine:
    """基于对话状态分数 + 用户偏好，只做执行路径选择。"""

    @staticmethod
    def decide_execution_route(
        ds: DialogueStateSnapshot,
        *,
        state: AgentRuntimeState,
    ) -> tuple[ExecutionRoute, str]:
        """衔接对话状态 → 执行路径（先总触发分，再信息充分度；追问句仅走 readiness 分支）。

        顺序与对话状态模型约定一致：
        - trigger_score < POLICY_TRIGGER_SCORE_MIN → silent（不读 ask_hint）
        - readiness < POLICY_READINESS_MIN → ask_user，追问正文 = ds.ask_hint（已含 missing_info* 合并）
        - 否则由 user_prefers_confirm 决定 plan_confirm / plan_auto
        """
        t = float(ds.trigger_score)
        r = float(ds.readiness)
        if t < POLICY_TRIGGER_SCORE_MIN:
            return "silent", ""
        if r < POLICY_READINESS_MIN:
            hint = (ds.ask_hint or "").strip()
            if not hint:
                hint = "为便于执行，请补充：文档还是 PPT、主题、大致页数或必须包含的要点。"
            return "ask_user", hint
        if state.user_prefers_confirm:
            return "plan_confirm", ""
        return "plan_auto", ""


# ---------------------------------------------------------------------------
# 小模型：消息有用性 + 对话状态
# ---------------------------------------------------------------------------

MESSAGE_FILTER_SYSTEM = """你是消息有用性筛选器（轻量）。给定一段用户侧对话文本（可能含多轮拼接），判断对「后续由 AI 助手落地任务（写文档/做 PPT/改材料等）」是否有信息价值。

输出仅一个 JSON：
{"useful_score": 0到1的小数, "useful": true/false, "reason": "不超过24字"}

useful_score 高表示含实质需求、主题、约束、确认执行等；低表示纯寒暄、灌水、与任务无关。"""


DIALOGUE_STATE_SYSTEM = """你是群聊/多轮对话状态分析器。输入为当前会话内与任务相关的文本（可能多条拼接）。
请输出 0~1 的连续分数（可一位小数）及一个总触发分 trigger_score。

字段含义：
- task_presence：是否存在可执行的工作项（写文档、做 PPT、修改材料、交付链接、明确问答等）。
- readiness：信息是否已足够开始规划执行（类型、主题、范围等是否基本齐）。
- consensus：时机/共识（如「确认」「开始吧」「差不多了按这个做」等推进信号，或单次强指令可视为高共识）。
- trigger_score：综合「是否值得现在让助手介入规划」的分数，应综合考虑上三项与整体语气。

只输出 JSON，不要其它文字。追问句可用以下任一字段（只填一个即可，内容会合并到 ask_hint）：
  ask_hint | missing_info | missing_info_question

{
  "task_presence": 0.0,
  "readiness": 0.0,
  "consensus": 0.0,
  "trigger_score": 0.0,
  "ask_hint": "",
  "missing_info_question": ""
}"""


def _gate_model() -> str:
    return os.environ.get("LLM_MODEL_GATE", "").strip() or LLM_MODEL


def _extract_json_block(raw: str) -> dict:
    raw = (raw or "").strip()
    if "```json" in raw:
        raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in raw:
        raw = raw.split("```", 1)[1].split("```", 1)[0].strip()
    return json.loads(raw)


def _extract_json_block_loose(raw: str) -> dict:
    """从模型回复中解析 JSON；失败时尝试截取首尾花括号内子串（常见前后缀废话）。"""
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("模型 content 为空，无法解析 JSON")
    try:
        return _extract_json_block(raw)
    except json.JSONDecodeError:
        i = raw.find("{")
        j = raw.rfind("}")
        if i >= 0 and j > i:
            return json.loads(raw[i : j + 1])
        raise


def _get_json_flexible(d: dict, *keys: str) -> Any:
    """大小写不敏感取键（缓解模型键名漂移）。"""
    lower_map = {str(k).strip().lower(): v for k, v in d.items()}
    for k in keys:
        lk = k.lower()
        if lk in lower_map:
            return lower_map[lk]
    return None


def _clamp01(x: Any) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, v))


def _merge_dialogue_ask_hints(d: dict) -> str:
    """取对话状态 JSON 里追问类字段的首个非空值，供 Policy 在 ASK_USER 时使用。"""
    for key in ("ask_hint", "missing_info_question", "missing_info", "clarification_question"):
        v = _get_json_flexible(d, key)
        if isinstance(v, str) and (s := v.strip()):
            return s[:500]
    return ""


# ---------------------------------------------------------------------------
# Intent（假设 + 轻量检索 + 排序）
# ---------------------------------------------------------------------------


def generate_intents(context: str, constraints: TriggerSignals) -> list[IntentHypothesis]:
    """基于触发约束生成少量开放式假设（非硬分类）。"""
    hypos: list[IntentHypothesis] = []
    if constraints.ppt_request or constraints.report_need:
        hypos.append(IntentHypothesis("generate_pptx", "演示生成", 0.5))
    if constraints.modify_request:
        hypos.append(IntentHypothesis("modify_pptx", "演示修改", 0.45))
    if constraints.doc_request and not constraints.ppt_request:
        hypos.append(IntentHypothesis("generate_doc", "文档生成", 0.45))
    if not hypos:
        hypos.append(IntentHypothesis("query", "问答/闲聊", 0.35))
        if constraints.uncertainty:
            hypos.append(IntentHypothesis("query", "澄清需求", 0.3))
    return hypos[:5]


def retrieve_similar_cases(context: str, state: AgentRuntimeState, top_k: int = 3) -> list[dict]:
    """从 state.memory['cases'] 里做关键词重叠检索（可替换为向量库）。"""
    cases: list[dict] = state.memory.get("cases") or []
    if not cases:
        return []
    words = set(re.findall(r"[\w\u4e00-\u9fff]+", context.lower()))
    scored: list[tuple[float, dict]] = []
    for c in cases:
        blob = (c.get("summary") or "") + " " + (c.get("intent") or "")
        cw = set(re.findall(r"[\w\u4e00-\u9fff]+", blob.lower()))
        overlap = len(words & cw) if words else 0
        scored.append((float(overlap), c))
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:top_k]]


def rank_intents(
    intents: list[IntentHypothesis], cases: list[dict]
) -> tuple[IntentHypothesis, float]:
    """综合假设与案例先验，选出主假设及置信度。"""
    boost = min(0.15, 0.05 * len(cases))
    best = max(intents, key=lambda h: h.score)
    best.score = min(1.0, best.score + boost)
    conf = min(0.95, 0.45 + best.score)
    return best, conf


# ---------------------------------------------------------------------------
# PlanningLayer：Planner 降级为子模块，仅负责「抽象意图 → Plan」
# ---------------------------------------------------------------------------


class PlanningLayer:
    def __init__(self, planner: Planner):
        self._planner = planner

    async def generate_plan(
        self,
        user_message: str,
        *,
        context_summary: str,
        document: str,
        chat_history: list[dict] | None,
        constraints: TriggerSignals,
    ) -> Plan:
        prefix_parts = [constraints.to_constraint_prefix()]
        if document.strip():
            prefix_parts.append(f"[附件/文档摘要]\n{document.strip()[:2000]}")
        prefix = "\n".join(p for p in prefix_parts if p).strip()
        # 用户原文优先；上下文摘要防漂移时作为补充
        augmented = user_message.strip()
        if context_summary and context_summary != user_message.strip():
            augmented = f"{augmented}\n\n[对话上下文摘要]\n{context_summary[:1500]}"
        if prefix:
            augmented = f"{prefix}\n\n{augmented}"
        return await self._planner.plan(augmented, chat_history)


# ---------------------------------------------------------------------------
# Tool Grounding
# ---------------------------------------------------------------------------

SUBTASK_TOOL_MAP: dict[str, str] = {
    "create_doc": "lark_cli.docs.create",
    "update_doc": "lark_cli.docs.update",
    "create_slides": "lark_cli.slides.create",
    "modify_slides": "lark_cli.slides.patch",
    "deliver": "lark_cli.im.deliver",
    "query": "llm.respond",
}


def ground_to_tools(plan: Plan, tools: list[dict] | None) -> list[GroundedAction]:
    """将子任务映射为具名工具；tools 为可选目录（用于校验/遥测）。"""
    allowed = {t.get("name") for t in (tools or []) if t.get("name")}
    grounded: list[GroundedAction] = []
    for st in plan.subtasks or []:
        sid = int(st.get("id", 0))
        stype = str(st.get("type", "query"))
        desc = str(st.get("description", ""))
        tool = SUBTASK_TOOL_MAP.get(stype, "workflow.custom")
        if allowed and tool not in allowed and tool != "workflow.custom":
            logger.debug("Tool %s not in catalog, still record as hint", tool)
        grounded.append(
            GroundedAction(
                step_id=sid,
                subtask_type=stype,
                tool=tool,
                description=desc,
                params_hint={"intent": plan.intent, "topic": plan.topic},
            )
        )
    return grounded


def merge_plan_confidence(plan: Plan, hypothesis: IntentHypothesis) -> float:
    """Planner 结果与触发假设对齐时抬高置信度。"""
    base = 0.62
    if plan.intent == hypothesis.intent:
        base = 0.88
    elif plan.intent == "query" and hypothesis.intent == "query":
        base = 0.85
    return min(0.97, base)


# ---------------------------------------------------------------------------
# IntentSystem 编排器
# ---------------------------------------------------------------------------


class IntentSystem:
    """
    消息流 → 弱触发（粗筛）→ 有用性（小模型）→ 对话状态（小模型）→ Policy（仅执行路径）→ Planner。
    """

    def __init__(self, planner: Planner | None = None):
        p = planner or Planner()
        self._planning = PlanningLayer(p)
        self._policy = PolicyEngine()
        self._oai = OpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL or None,
            timeout=90.0,
            max_retries=1,
        )

    async def _llm_json(self, system: str, user: str) -> tuple[dict, str]:
        model = _gate_model()
        resp = await asyncio.to_thread(
            self._oai.chat.completions.create,
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.12,
            max_tokens=520,
        )
        raw = (resp.choices[0].message.content or "").strip()
        return _extract_json_block_loose(raw), raw

    async def _message_useful_score(self, context: str) -> float:
        try:
            d, _raw = await self._llm_json(
                MESSAGE_FILTER_SYSTEM,
                f"对话文本：\n{(context or '')[:4000]}\n\n只输出 JSON。",
            )
            u = _clamp01(d.get("useful_score"))
            if bool(d.get("useful")) and u < 0.35:
                u = max(u, 0.5)
            return float(u)
        except Exception as e:
            logger.warning("message filter LLM 失败: %s", e)
            return 0.0

    async def _dialogue_state_scores(self, dialogue: str) -> DialogueStateSnapshot:
        blob = (dialogue or "").strip()[-DIALOGUE_FOR_STATE_MAX:]
        if not blob:
            logger.warning("对话状态: 输入文本为空，返回全零（请检查上游 dialogue / 群合并缓存）")
            pipeline_log("意图", 3, "对话状态", "输入为空→全零（未调 LLM）")
            return DialogueStateSnapshot()
        raw = ""
        try:
            d, raw = await self._llm_json(
                DIALOGUE_STATE_SYSTEM,
                f"以下为会话相关文本：\n\n{blob}\n\n只输出 JSON。",
            )
            if not raw:
                logger.warning("对话状态: 模型返回空 content，返回全零")
                pipeline_log("意图", 3, "对话状态", "模型空回复→全零")
                return DialogueStateSnapshot()
            snap = DialogueStateSnapshot(
                task_presence=_clamp01(_get_json_flexible(d, "task_presence", "taskPresence")),
                readiness=_clamp01(_get_json_flexible(d, "readiness", "ready")),
                consensus=_clamp01(_get_json_flexible(d, "consensus", "timing", "consensus_score")),
                trigger_score=_clamp01(
                    _get_json_flexible(d, "trigger_score", "triggerScore", "total_score", "score")
                ),
                ask_hint=_merge_dialogue_ask_hints(d),
            )
            if (
                snap.task_presence == 0.0
                and snap.readiness == 0.0
                and snap.consensus == 0.0
                and snap.trigger_score == 0.0
            ):
                logger.warning(
                    "对话状态解析后仍全零: json_keys=%s raw_head=%r",
                    list(d.keys())[:20],
                    raw[:200],
                )
                pipeline_log(
                    "意图",
                    3,
                    "对话状态",
                    f"解析成功但全零 keys={list(d.keys())[:8]} raw_head={raw[:80]!r}…",
                )
            return snap
        except Exception as e:
            logger.warning(
                "dialogue state LLM/JSON 失败: %s raw_head=%r",
                e,
                (raw or "")[:220],
                exc_info=logger.isEnabledFor(logging.DEBUG),
            )
            pipeline_log("意图", 3, "对话状态", f"异常→全零 err={str(e)[:100]} raw_head={(raw or '')[:80]!r}")
            return DialogueStateSnapshot()

    async def cycle(
        self,
        dialogue: str,
        *,
        document: str = "",
        state: AgentRuntimeState,
        tools: list[dict] | None = None,
        chat_history: list[dict] | None = None,
        hooks: IntentHooks | None = None,
    ) -> IntentCycleResult:
        cid = short_id(getattr(state, "chat_id", "") or "", 12)
        context = summarize_dialogue(dialogue)
        signals = detect_triggers(context)
        weak_ok, weak_score = weak_trigger_coarse_pass(signals, state)
        F(
            "intent.cycle",
            "进入",
            chat_id=cid,
            weak_score=weak_score,
            weak_ok=weak_ok,
            dialogue_len=len(dialogue or ""),
        )
        pipeline_log(
            "意图",
            1,
            "粗筛",
            f"通过={weak_ok} weak_score={weak_score:.3f} chat={cid} (阈值>={WEAK_TRIGGER_MIN})",
        )

        if not weak_ok:
            F("intent.trigger", "弱触发未通过", chat_id=cid, weak_score=weak_score)
            pipeline_log("意图", 2, "有用性", "跳过(LLM) | 粗筛未通过")
            pipeline_log("意图", 3, "对话状态", "跳过 | 粗筛未通过")
            pipeline_log("意图", 4, "policy", "沉默 | 未进入策略分支")
            return IntentCycleResult(
                outcome=CycleOutcome.SILENT,
                trigger_score=weak_score,
                trigger_signals=signals,
            )

        useful = await self._message_useful_score(context)
        F("intent.msg_filter", "有用性", chat_id=cid, useful_score=useful)
        pipeline_log(
            "意图",
            2,
            "有用性",
            f"score={useful:.3f} 判定={'通过→继续' if useful >= MESSAGE_USEFUL_MIN else '丢弃(静默)'} "
            f"阈值>={MESSAGE_USEFUL_MIN} chat={cid}",
        )
        if useful < MESSAGE_USEFUL_MIN:
            F(
                "intent.msg_filter",
                "低于阈值静默",
                chat_id=cid,
                threshold=MESSAGE_USEFUL_MIN,
            )
            pipeline_log("意图", 3, "对话状态", "跳过(LLM) | 有用性未通过")
            pipeline_log("意图", 4, "policy", "沉默 | 有用性未通过")
            return IntentCycleResult(
                outcome=CycleOutcome.SILENT,
                trigger_score=weak_score,
                trigger_signals=signals,
            )

        ds = await self._dialogue_state_scores(dialogue)
        F(
            "intent.dialogue_state",
            "对话状态",
            chat_id=cid,
            task_presence=ds.task_presence,
            readiness=ds.readiness,
            consensus=ds.consensus,
            trigger_score=ds.trigger_score,
        )
        _avg3 = (ds.task_presence + ds.readiness + ds.consensus) / 3.0
        pipeline_log(
            "意图",
            3,
            "对话状态",
            f"task_presence={ds.task_presence:.3f} readiness={ds.readiness:.3f} "
            f"consensus={ds.consensus:.3f} 三维均值={_avg3:.3f} "
            f"总触发分trigger_score={ds.trigger_score:.3f} chat={cid}",
        )
        state.update({"last_dialogue_state": asdict(ds)})

        route, ask_prompt = self._policy.decide_execution_route(ds, state=state)
        F(
            "intent.policy",
            "执行路径",
            chat_id=cid,
            route=route,
            model_trigger=ds.trigger_score,
            readiness=ds.readiness,
        )
        _route_cn = {
            "silent": "沉默(不调用 Planner)",
            "ask_user": "追问(不调用 Planner)",
            "plan_confirm": "先出计划→待用户确认→再执行",
            "plan_auto": "自动执行路径(将调用 Planner→Executor 由上层调度)",
        }
        pipeline_log(
            "意图",
            4,
            "policy",
            f"path={route} {_route_cn.get(route, route)} pref_confirm={state.user_prefers_confirm} chat={cid}",
        )

        if route == "silent":
            F("intent.exit", "SILENT", chat_id=cid, reason="policy_trigger_low")
            return IntentCycleResult(
                outcome=CycleOutcome.SILENT,
                trigger_score=ds.trigger_score,
                trigger_signals=signals,
                dialogue_state=ds,
            )

        if route == "ask_user":
            F("intent.exit", "ASK_USER", chat_id=cid, reason="readiness_low")
            state.update({"pending_clarification": True})
            return IntentCycleResult(
                outcome=CycleOutcome.ASK_USER,
                plan=None,
                user_prompt=ask_prompt,
                trigger_score=ds.trigger_score,
                trigger_signals=signals,
                dialogue_state=ds,
            )

        # Policy 已放行「可进入规划」：仅 plan_confirm / plan_auto 会走到此处；其下才有 Planner（及 hook）。
        # plan_confirm ≠ 用户已在 IM 点确认，而是「生成计划文案→待用户回复确认后再由 workflow 执行」。
        intents = generate_intents(context, signals)
        cases = retrieve_similar_cases(context, state)
        best_hypo, hypo_conf = rank_intents(intents, cases)
        F(
            "intent.hypo",
            "假设与案例",
            chat_id=cid,
            best=best_hypo.intent,
            hypo_conf=hypo_conf,
            n_intents=len(intents),
            n_cases=len(cases),
        )

        if hooks and hooks.before_llm_plan:
            F("intent.hook", "before_llm_plan（如发送「正在分析」）", chat_id=cid)
            await hooks.before_llm_plan()

        pipeline_log("意图", 5, "Planner", f"开始 PlanningLayer→Planner chat={cid}")
        F("intent.plan", "调用 PlanningLayer → Planner", chat_id=cid)
        plan = await self._planning.generate_plan(
            dialogue,
            context_summary=context,
            document=document,
            chat_history=chat_history,
            constraints=signals,
        )
        intent_conf = merge_plan_confidence(plan, best_hypo)
        intent_conf = min(1.0, (intent_conf + hypo_conf) / 2)
        F(
            "intent.plan_done",
            "Planner 返回",
            chat_id=cid,
            plan_intent=plan.intent,
            topic=(plan.topic or "")[:80],
            subtasks=len(plan.subtasks or []),
            intent_conf=intent_conf,
        )

        grounded = ground_to_tools(plan, tools)

        if plan.intent == "query":
            F("intent.exit", "问答类 QUERY_REPLY", chat_id=cid)
            state.update(
                {
                    "last_intent": plan.intent,
                    "last_plan_topic": plan.topic,
                    "last_grounded": [g.tool for g in grounded],
                    "last_trigger_score": ds.trigger_score,
                }
            )
            return IntentCycleResult(
                outcome=CycleOutcome.QUERY_REPLY,
                plan=plan,
                direct_text=plan.source_context or "我需要更多信息来帮助您。",
                trigger_score=ds.trigger_score,
                trigger_signals=signals,
                intent_confidence=intent_conf,
                grounded_actions=grounded,
                dialogue_state=ds,
            )

        state.update(
            {
                "intent": plan.intent,
                "plan_topic": plan.topic,
                "last_grounded": [g.tool for g in grounded],
                "last_trigger_score": ds.trigger_score,
            }
        )

        if route == "plan_auto":
            F("intent.exit", "AUTO_EXEC", chat_id=cid)
            return IntentCycleResult(
                outcome=CycleOutcome.AUTO_EXEC,
                plan=plan,
                trigger_score=ds.trigger_score,
                trigger_signals=signals,
                intent_confidence=intent_conf,
                grounded_actions=grounded,
                dialogue_state=ds,
            )

        F("intent.exit", "CONFIRM_PLAN", chat_id=cid)
        return IntentCycleResult(
            outcome=CycleOutcome.CONFIRM_PLAN,
            plan=plan,
            trigger_score=ds.trigger_score,
            trigger_signals=signals,
            intent_confidence=intent_conf,
            grounded_actions=grounded,
            dialogue_state=ds,
        )


def record_success_case(state: AgentRuntimeState, plan: Plan, summary: str) -> None:
    """供工作流完成后写入，增强后续 retrieve_similar_cases。"""
    cases = state.memory.setdefault("cases", [])
    cases.append({"intent": plan.intent, "topic": plan.topic, "summary": summary[:500]})
    if len(cases) > 20:
        del cases[:-20]
