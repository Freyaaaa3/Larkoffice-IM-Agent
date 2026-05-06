"""End-to-end test: simulate the full agent workflow without Feishu bot."""

import asyncio
import io
import json
import logging
import sys

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, ".")

from agent.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from agent.planner import Planner, Plan
from agent.executor import Executor
from agent.workflows.content_structure import ContentStructurer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def test_planner():
    """Test 1: Planner intent recognition."""
    print("\n" + "=" * 60)
    print("TEST 1: Planner - Intent Recognition")
    print("=" * 60)

    planner = Planner()
    test_messages = [
        "帮我把这周的产品讨论整理成一份汇报PPT，面向管理层，风格简洁商务",
    ]

    for msg in test_messages:
        print(f"\n输入: {msg}")
        plan = await planner.plan(msg)
        print(f"意图: {plan.intent}")
        print(f"主题: {plan.topic}")
        print(f"风格: {plan.style}")
        print(f"子任务: {json.dumps(plan.subtasks, ensure_ascii=False)}")
        print(f"确认文本:\n{plan.to_confirmation_text()}")
        print("-" * 40)

    return plan


async def test_content_structure(plan: Plan):
    """Test 2: Content structuring."""
    print("\n" + "=" * 60)
    print("TEST 2: Content Structurer - Document + Slides Outline")
    print("=" * 60)

    structurer = ContentStructurer()
    result = await structurer.structure(plan)

    print(f"\n文档内容 (前200字):\n{result.doc_content[:200]}...")
    print(f"\n幻灯片大纲 ({len(result.slides_outline)} 页):")
    for i, slide in enumerate(result.slides_outline, 1):
        print(f"  {i}. [{slide.get('layout', '?')}] {slide.get('title', '?')}")
        for pt in slide.get("key_points", []):
            print(f"     - {pt}")
    print(f"\n摘要: {result.summary}")

    return result


async def test_slides_xml(structured, style: str):
    """Test 3: Slides XML generation."""
    print("\n" + "=" * 60)
    print("TEST 3: Slides XML Generation")
    print("=" * 60)

    structurer = ContentStructurer()
    slides_xml = await structurer.generate_slides_xml(structured.slides_outline, style)

    print(f"\n生成了 {len(slides_xml.slides)} 页 XML")
    for i, xml in enumerate(slides_xml.slides, 1):
        print(f"\n--- Slide {i} (前150字) ---")
        print(xml[:150] + "...")

    return slides_xml


async def test_executor_doc(plan, structured):
    """Test 4: Create document via lark-cli."""
    print("\n" + "=" * 60)
    print("TEST 4: Executor - Document Creation")
    print("=" * 60)

    executor = Executor()
    result = await executor.create_document(
        title=plan.topic,
        content=structured.doc_content,
        doc_format="markdown",
    )

    print(f"成功: {result.success}")
    if result.success and result.data:
        doc = result.data.get("document", {})
        print(f"Document ID: {doc.get('document_id', 'N/A')}")
        print(f"URL: {doc.get('url', 'N/A')}")
    else:
        print(f"错误: {result.error}")

    return result


async def test_executor_slides(plan, slides_xml):
    """Test 5: Create slides via lark-cli."""
    print("\n" + "=" * 60)
    print("TEST 5: Executor - Slides Creation")
    print("=" * 60)

    executor = Executor()

    if not slides_xml.slides:
        print("没有幻灯片 XML 可创建，跳过")
        return None

    slides_json = json.dumps(slides_xml.slides, ensure_ascii=False)
    result = await executor.create_slides(
        title=plan.topic,
        slides_json=slides_json,
    )

    print(f"成功: {result.success}")
    if result.success and result.data:
        print(f"Presentation ID: {result.data.get('xml_presentation_id', 'N/A')}")
        print(f"URL: {result.data.get('url', 'N/A')}")
        print(f"Pages: {result.data.get('slides_added', 'N/A')}")
    else:
        print(f"错误: {result.error}")

    return result


async def test_executor_share(doc_result, slides_result):
    """Test 6: Get share links."""
    print("\n" + "=" * 60)
    print("TEST 6: Executor - Share Links")
    print("=" * 60)

    executor = Executor()

    # Extract tokens
    doc_token = ""
    slides_id = ""

    if doc_result and doc_result.success and doc_result.data:
        doc_token = doc_result.data.get("document", {}).get("document_id", "")

    if slides_result and slides_result.success and slides_result.data:
        slides_id = slides_result.data.get("xml_presentation_id", "")

    tokens = []
    if doc_token:
        tokens.append(("docx", doc_token))
    if slides_id:
        tokens.append(("slides", slides_id))

    if not tokens:
        print("没有可分享的文件，跳过")
        return

    for doc_type, token in tokens:
        result = await executor.get_file_meta(token, doc_type)
        if result.success and result.data:
            metas = result.data.get("metas", [])
            for meta in metas:
                print(f"  {meta.get('doc_type')}: {meta.get('title')} -> {meta.get('url')}")
        else:
            print(f"  获取 {doc_type}/{token} 失败: {result.error}")


async def main():
    print("Agent-Pilot 端到端测试")
    print("=" * 60)
    print(f"LLM: {LLM_MODEL} @ {LLM_BASE_URL or 'default'}")
    print(f"API Key: {'OK' if LLM_API_KEY else 'MISSING'}")

    if not LLM_API_KEY:
        print("\n[ERROR] LLM_API_KEY not set")
        return

    # Test 1: Planner
    plan = await test_planner()

    # Only proceed with workflow tests for generate_pptx intent
    if plan.intent != "generate_pptx":
        print("\n[WARN] Intent is not generate_pptx, skipping workflow tests")
        print(f"意图为: {plan.intent}")
        return

    # Test 2: Content structuring (may fail due to network, continue anyway)
    structured = await test_content_structure(plan)

    # Fallback if content structuring failed
    if not structured.doc_content or "内容生成失败" in structured.doc_content:
        print("\n[WARN] Content structuring failed, using fallback content")
        structured.doc_content = f'<title>{plan.topic}</title><h2>概述</h2><p>这是自动生成的{plan.topic}文档。</p><h2>核心要点</h2><ul><li>{"</li><li>".join(plan.key_points[:5])}</li></ul>'
        structured.slides_outline = [
            {"title": plan.topic, "layout": "cover", "key_points": []},
            {"title": "核心要点", "layout": "content", "key_points": plan.key_points[:5]},
            {"title": "总结", "layout": "ending", "key_points": []},
        ]
        structured.summary = plan.topic

    # Test 3: Slides XML
    slides_xml = await test_slides_xml(structured, plan.style)

    # Test 4: Create document
    doc_result = await test_executor_doc(plan, structured)

    # Test 5: Create slides
    slides_result = await test_executor_slides(plan, slides_xml)

    # Test 6: Share links
    await test_executor_share(doc_result, slides_result)

    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
