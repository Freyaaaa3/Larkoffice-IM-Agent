"""Content structuring helper: transforms free-form text into structured content for docs and slides."""

import json
import logging
from dataclasses import dataclass, field

from openai import OpenAI

from agent.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from agent.flow import F

logger = logging.getLogger(__name__)


def _validate_slide_xml(xml: str) -> bool:
    """Basic validation that slide XML conforms to SML 2.0 structure rules."""
    if not xml or "<slide" not in xml:
        return False
    # Must have xmlns
    if 'xmlns="http://www.larkoffice.com/sml/2.0"' not in xml:
        return False
    # Must have <data> element
    if "<data>" not in xml:
        return False
    # Must have closing </slide>
    if "</slide>" not in xml:
        return False
    # No direct <title> or <body> under <slide> (must be inside <content>)
    # Simple check: <slide> should not be immediately followed by <title> or <body>
    import re
    if re.search(r"<slide[^>]*>\s*<(title|body)[>\s]", xml):
        return False
    return True


def _fix_slide_xml(xml: str) -> str:
    """Attempt to fix common XML issues."""
    import re
    # Add xmlns if missing
    if 'xmlns=' not in xml:
        xml = xml.replace("<slide", '<slide xmlns="http://www.larkoffice.com/sml/2.0"', 1)
    # Remove http(s) image URLs (they won't render)
    xml = re.sub(r'<img[^>]*src="https?://[^"]*"[^>]*/>', '', xml)
    return xml

STRUCTURE_SYSTEM_PROMPT = """你是内容结构化专家。将用户提供的自由文本/讨论内容转化为结构化的文档和幻灯片内容。

## 文档内容格式
输出飞书文档 XML 格式（v2 API），使用以下标签：
- <title>文档标题</title>
- <h1>一级标题</h1>
- <h2>二级标题</h2>
- <p>正文段落</p>
- <ul><li>列表项</li></ul>
- <ol><li>有序列表项</li></ol>
- <callout type="info">提示框</callout>

## 文档详细度要求
- 每个主题章节必须包含：背景说明、核心论点、详细展开、数据/案例支撑（如有）
- 每个段落至少3-5句话，充分展开论述，不要只写一句话就结束
- 关键结论要用 <callout> 突出显示
- 优先保留原始讨论中的具体细节、人名、时间、数据，不要过度概括
- 文档总长度至少2000字以上

## 输出格式（严格JSON）
{
  "doc_content": "<title>...</title><h2>...</h2><p>...</p>...",
  "slides": [
    {
      "title": "幻灯片标题",
      "layout": "cover | content | data | comparison | ending",
      "key_points": ["要点1", "要点2"],
      "speaker_note": "演讲备注（可选）"
    }
  ],
  "summary": "文档内容摘要，用于交付时展示"
}"""


SLIDES_XML_SYSTEM_PROMPT = """你是飞书幻灯片 XML 生成专家。根据幻灯片大纲生成严格符合飞书 SML 2.0 协议的 XML。

## 严格规则（违反会导致 API 报错，必须遵守）

1. 每页 slide 必须带命名空间：`<slide xmlns="http://www.larkoffice.com/sml/2.0">`
2. `<slide>` 直接子元素只有三种：`<style>`、`<data>`、`<note>`
3. 文本只能放在 `<shape type="text">` 内的 `<content>` 中，不能在 `<slide>` 下直接写 `<title>` 或 `<body>`
4. `<content>` 的子元素只能是 `<p>`、`<ul>`、`<ol>`
5. 所有 `<shape>` 必须有属性：`type`、`topLeftX`、`topLeftY`、`width`、`height`
6. `type="text"` 表示文本框，文本放在其 `<content>` 子元素中
7. 渐变色必须用 `rgba()` 格式 + 百分比停靠点，例如 `linear-gradient(135deg,rgba(30,60,114,1) 0%,rgba(59,130,246,1) 100%)`
8. 禁止使用 http(s) 外链图片（img src 只能用 file_token 或 @本地路径）
9. 画布坐标系：宽 960，高 540

## 正确的 XML 结构示例

封面页：
<slide xmlns="http://www.larkoffice.com/sml/2.0">
  <style>
    <fill>
      <fillColor color="linear-gradient(135deg,rgba(30,60,114,1) 0%,rgba(59,130,246,1) 100%)"/>
    </fill>
  </style>
  <data>
    <shape type="text" topLeftX="120" topLeftY="160" width="720" height="100">
      <content textType="title" textAlign="center">
        <p>演示文稿标题</p>
      </content>
    </shape>
    <shape type="text" topLeftX="120" topLeftY="280" width="720" height="60">
      <content textType="sub-headline" textAlign="center">
        <p>副标题</p>
      </content>
    </shape>
  </data>
</slide>

内容页：
<slide xmlns="http://www.larkoffice.com/sml/2.0">
  <style>
    <fill>
      <fillColor color="rgb(248,250,252)"/>
    </fill>
  </style>
  <data>
    <shape type="text" topLeftX="80" topLeftY="40" width="800" height="60">
      <content textType="headline" textAlign="left">
        <p>页面标题</p>
      </content>
    </shape>
    <shape type="rect" topLeftX="80" topLeftY="100" width="800" height="2">
      <fill>
        <fillColor color="rgb(59,130,246)"/>
      </fill>
    </shape>
    <shape type="text" topLeftX="80" topLeftY="120" width="800" height="380">
      <content textType="body" textAlign="left">
        <p>内容要点</p>
        <ul>
          <li><p>要点一</p></li>
          <li><p>要点二</p></li>
          <li><p>要点三</p></li>
        </ul>
      </content>
    </shape>
  </data>
</slide>

结尾页：
<slide xmlns="http://www.larkoffice.com/sml/2.0">
  <style>
    <fill>
      <fillColor color="linear-gradient(135deg,rgba(30,60,114,1) 0%,rgba(59,130,246,1) 100%)"/>
    </fill>
  </style>
  <data>
    <shape type="text" topLeftX="120" topLeftY="200" width="720" height="100">
      <content textType="title" textAlign="center">
        <p>谢谢！</p>
      </content>
    </shape>
  </data>
</slide>

## 风格配色
- 商务汇报：背景 rgb(248,250,252)，主色 rgb(30,60,114)，文字 rgb(30,41,59)
- 科技产品：背景渐变 rgba(15,23,42,1)→rgba(56,97,140,1)，主色 rgb(59,130,246)，文字 rgb(255,255,255)
- 教育培训：背景 rgb(255,255,255)，主色 rgb(34,197,94)，文字 rgb(51,65,85)
- 创意设计：背景渐变 rgba(88,28,135,1)→rgba(190,24,93,1)，文字 rgb(255,255,255)
- 简约专业：背景 rgb(248,250,252) + 顶部渐变条，主色 rgb(59,130,246)，文字 rgb(15,23,42)

## 输出格式
返回 JSON 数组，每个元素是一页 slide 的完整 XML 字符串：
["<slide xmlns=\\\"http://www.larkoffice.com/sml/2.0\\\">...</slide>", ...]

重要：每个 XML 字符串中的双引号必须转义为 \\\"（因为外层是 JSON 字符串）。"""


@dataclass
class StructuredContent:
    doc_content: str = ""
    slides_outline: list[dict] = field(default_factory=list)
    summary: str = ""


@dataclass
class SlidesXML:
    slides: list[str] = field(default_factory=list)


class ContentStructurer:
    def __init__(self):
        self._client = OpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL or None,
            timeout=120.0,
            max_retries=2,
        )
        self._model = LLM_MODEL

    async def structure(self, plan, source_text: str = "") -> StructuredContent:
        """Transform plan + source text into structured document content and slides outline."""
        user_msg = f"""请将以下内容结构化为文档和幻灯片大纲：

主题：{plan.topic}
受众：{plan.audience or '通用'}
风格：{plan.style}
预计页数：{plan.estimated_pages}
核心要点：{', '.join(plan.key_points) if plan.key_points else '从内容中提取'}

内容来源：
{source_text or plan.source_context or '请根据主题和要点生成合理内容'}"""

        messages = [
            {"role": "system", "content": STRUCTURE_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        try:
            import asyncio

            F(
                "struct.llm",
                "structure 请求",
                model=self._model,
                topic=(plan.topic or "")[:80],
                user_msg_len=len(user_msg),
            )
            response = await asyncio.to_thread(
                self._client.chat.completions.create,
                model=self._model,
                messages=messages,
                temperature=0.5,
            )

            content = response.choices[0].message.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            data = json.loads(content)
            sc = StructuredContent(
                doc_content=data.get("doc_content", ""),
                slides_outline=data.get("slides", []),
                summary=data.get("summary", ""),
            )
            F(
                "struct.ok",
                "structure 完成",
                doc_len=len(sc.doc_content or ""),
                outline_pages=len(sc.slides_outline or []),
                summary_len=len(sc.summary or ""),
            )
            return sc
        except Exception:
            logger.exception("Failed to structure content")
            F("struct.err", "structure 异常，返回占位", topic=(plan.topic or "")[:60])
            return StructuredContent(
                doc_content=f"<title>{plan.topic}</title><p>内容生成失败，请重试。</p>",
                summary=plan.topic,
            )

    async def generate_slides_xml(self, slides_outline: list[dict], style: str) -> SlidesXML:
        """Generate slide XML from outline, one page at a time for best schema compliance."""
        all_slides = []
        total = len(slides_outline)
        F("slides_xml", "开始逐页生成", total_pages=total, style=style[:40])

        for i, page_outline in enumerate(slides_outline):
            outline_text = json.dumps(page_outline, ensure_ascii=False, indent=2)
            user_msg = f"""风格：{style}

第{i+1}/{total}页大纲：
{outline_text}

请生成这一页的完整 SML 2.0 XML。输出 JSON 数组（只包含这1页）。"""

            messages = [
                {"role": "system", "content": SLIDES_XML_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ]

            try:
                import asyncio

                F("slides_xml", "页面 LLM", page=i + 1, total=total)
                response = await asyncio.to_thread(
                    self._client.chat.completions.create,
                    model=self._model,
                    messages=messages,
                    temperature=0.3,
                )

                raw = response.choices[0].message.content.strip()
                if "```json" in raw:
                    raw = raw.split("```json")[1].split("```")[0].strip()
                elif "```" in raw:
                    raw = raw.split("```")[1].split("```")[0].strip()

                data = json.loads(raw)

                if isinstance(data, dict) and "slides" in data:
                    batch_slides = data["slides"]
                elif isinstance(data, list):
                    batch_slides = data
                else:
                    batch_slides = [str(data)]

                # Basic validation: check that each slide XML has required elements
                valid_slides = []
                for slide_xml in batch_slides:
                    if isinstance(slide_xml, str) and _validate_slide_xml(slide_xml):
                        valid_slides.append(slide_xml)
                    elif isinstance(slide_xml, str):
                        logger.warning("Slide XML validation failed for page %d, attempting fix", i + 1)
                        # Try to fix common issues
                        fixed = _fix_slide_xml(slide_xml)
                        if _validate_slide_xml(fixed):
                            valid_slides.append(fixed)
                        else:
                            logger.warning("Could not fix slide XML for page %d, skipping", i + 1)

                all_slides.extend(valid_slides)
                F("slides_xml", "页面解析成功", page=i + 1, valid=len(valid_slides), cumulative=len(all_slides))
            except Exception:
                logger.exception("Failed to generate slides XML page %d", i + 1)
                F("slides_xml", "页面失败已跳过", page=i + 1)
                continue

        F("slides_xml", "全部页面结束", slides=len(all_slides))
        return SlidesXML(slides=all_slides)
