"""Content structuring helper: transforms free-form text into structured content for docs and slides."""

import json
import logging
from dataclasses import dataclass, field

from openai import OpenAI

from agent.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

logger = logging.getLogger(__name__)

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


SLIDES_XML_SYSTEM_PROMPT = """你是飞书幻灯片 XML 生成专家。根据幻灯片大纲生成符合飞书 SML 2.0 协议的 XML。

## 核心规则
1. 命名空间：<slide xmlns="http://www.larkoffice.com/sml/2.0">
2. 画布尺寸：960×540
3. 直接子元素只有 <style>、<data>、<note>
4. 文本通过 <content><p>...</p></content> 表达
5. 每页 slide 需要完整 XML：背景、文本、图形、配色
6. 渐变必须用 rgba() 格式 + 百分比停靠点

## 风格配置
- 商务汇报：背景浅灰 rgb(248,250,252)，主色深蓝 rgb(30,60,114)，文字深灰 rgb(30,41,59)
- 科技产品：背景深蓝渐变 linear-gradient(135deg,rgba(15,23,42,1) 0%,rgba(56,97,140,1) 100%)，主色蓝 rgb(59,130,246)，文字白色
- 教育培训：背景白色 rgb(255,255,255)，主色绿 rgb(34,197,94)，文字深灰 rgb(51,65,85)
- 创意设计：背景紫粉渐变 linear-gradient(135deg,rgba(88,28,135,1) 0%,rgba(190,24,93,1) 100%)，主色粉紫，文字白色
- 简约专业：背景浅灰 rgb(248,250,252) + 顶部彩色渐变条，主色蓝 rgb(59,130,246)，文字深色 rgb(15,23,42)

## 页面布局
- 封面页（cover）：居中大标题 + 副标题，渐变或深色背景
- 内容页（content）：左侧标题区 + 右侧/下方要点列表
- 数据页（data）：指标卡片 + 大号数字
- 对比页（comparison）：并列卡片
- 结尾页（ending）：居中感谢语 + 装饰线

## 输出格式
返回 JSON 数组，每个元素是一页 slide 的 XML 字符串：
["<slide>...</slide>", "<slide>...</slide>", ...]"""


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
            return StructuredContent(
                doc_content=data.get("doc_content", ""),
                slides_outline=data.get("slides", []),
                summary=data.get("summary", ""),
            )
        except Exception:
            logger.exception("Failed to structure content")
            return StructuredContent(
                doc_content=f"<title>{plan.topic}</title><p>内容生成失败，请重试。</p>",
                summary=plan.topic,
            )

    async def generate_slides_xml(self, slides_outline: list[dict], style: str) -> SlidesXML:
        """Generate slide XML from outline, page by page to avoid timeouts."""
        all_slides = []

        # Batch: generate 3 pages at a time to balance speed and token limits
        batch_size = 3
        for i in range(0, len(slides_outline), batch_size):
            batch = slides_outline[i:i + batch_size]
            batch_text = json.dumps(batch, ensure_ascii=False, indent=2)
            user_msg = f"""风格：{style}

幻灯片大纲（第{i+1}-{min(i+batch_size, len(slides_outline))}页）：
{batch_text}

请生成这些页的完整 XML。输出 JSON 数组。"""

            messages = [
                {"role": "system", "content": SLIDES_XML_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ]

            try:
                import asyncio
                response = await asyncio.to_thread(
                    self._client.chat.completions.create,
                    model=self._model,
                    messages=messages,
                    temperature=0.4,
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

                all_slides.extend(batch_slides)
            except Exception:
                logger.exception("Failed to generate slides XML batch %d-%d", i+1, i+batch_size)
                continue

        return SlidesXML(slides=all_slides)
