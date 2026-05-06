"""Test IntentSystem gate logic: strong signal bypass + local Ollama (optional)."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()

from agent.IntentSystem import (
    MESSAGE_USEFUL_MIN,
    AgentRuntimeState,
    IntentSystem,
    TriggerSignals,
    _has_strong_task_signal,
    compute_trigger_score,
    detect_triggers,
    weak_trigger_coarse_pass,
)


def test_coarse_filter():
    """Test 1: keyword coarse filter + strong signal detection."""
    cases = [
        ("帮我把今天讨论的产品功能规划整理成一份汇报PPT", "强信号: PPT请求"),
        ("写个季度总结文档", "强信号: 文档+汇报"),
        ("帮我改一下第3页", "强信号: 修改请求"),
        ("你好", "弱信号: 纯寒暄"),
        ("哈哈好的", "弱信号: 无任务"),
        ("能不能帮我做个东西", "弱信号: 模糊求助"),
    ]

    print("=" * 60)
    print("TEST 1: 粗筛 + 强信号检测")
    print("=" * 60)
    state = AgentRuntimeState()

    for text, label in cases:
        signals = detect_triggers(text)
        score = compute_trigger_score(signals)
        weak_ok, weak_score = weak_trigger_coarse_pass(signals, state)
        strong = _has_strong_task_signal(signals)
        bypass = "跳过有用性LLM" if strong else "需调有用性LLM"
        result = "通过" if weak_ok else "拦截"

        print(f"\n  输入: {text}")
        print(f"  标签: {label}")
        print(f"  信号: ppt={signals.ppt_request} doc={signals.doc_request} "
              f"report={signals.report_need} modify={signals.modify_request} "
              f"casual={signals.casual_or_opening}")
        print(f"  粗筛: {result} (score={weak_score:.2f})")
        print(f"  强信号: {strong} → {bypass}")


async def test_cycle():
    """Test 2: full IntentSystem.cycle with real LLM (if configured)."""
    print("\n" + "=" * 60)
    print("TEST 2: IntentSystem.cycle 全流程")
    print("=" * 60)

    gate_model = os.environ.get("LLM_MODEL_GATE", "")
    gate_url = os.environ.get("LLM_BASE_URL_GATE", "")
    print(f"  LLM_MODEL_GATE: {gate_model or '(未设置，用主模型)'}")
    print(f"  LLM_BASE_URL_GATE: {gate_url or '(未设置，用主URL)'}")

    system = IntentSystem()

    cases = [
        ("帮我把今天讨论的产品功能规划整理成一份汇报PPT，面向管理层，风格简洁商务", "强信号-应跳过有用性LLM"),
        ("你好", "弱信号-可能被拦截"),
        ("能不能帮我整理一下资料", "弱信号-模糊求助"),
    ]

    for text, label in cases:
        state = AgentRuntimeState(chat_id="test_chat")
        print(f"\n  --- {label} ---")
        print(f"  输入: {text}")

        result = await system.cycle(text, state=state)
        print(f"  结果: {result.outcome.value}")
        print(f"  trigger_score: {result.trigger_score:.3f}")
        if result.trigger_signals:
            s = result.trigger_signals
            print(f"  信号: ppt={s.ppt_request} doc={s.doc_request} report={s.report_need}")
        if result.plan:
            print(f"  Plan: intent={result.plan.intent} topic={result.plan.topic[:40]}")
        if result.direct_text:
            print(f"  回复: {result.direct_text[:80]}")
        if result.user_prompt:
            print(f"  追问: {result.user_prompt[:80]}")


if __name__ == "__main__":
    test_coarse_filter()

    print("\n是否测试 LLM 全流程？需要配置 .env 中的 LLM 相关变量。")
    ans = input("输入 y 测试，其他键跳过: ").strip().lower()
    if ans == "y":
        asyncio.run(test_cycle())
