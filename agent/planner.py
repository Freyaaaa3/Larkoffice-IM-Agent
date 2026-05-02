"""Intent Planner: LLM-driven intent recognition, task decomposition, and parameter extraction."""

import json
import logging
from dataclasses import dataclass, field

from openai import OpenAI

from agent.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

logger = logging.getLogger(__name__)

PLANNER_SYSTEM_PROMPT = """你是飞书智能体的意图规划器（场景B：任务理解与规划）。分析用户的IM消息，输出结构化任务计划。

## 你的职责
1. 识别用户意图：生成PPT、修改PPT、生成文档、查询信息等
2. 将意图拆解为可执行的子任务序列
3. 从消息中提取关键参数（主题、受众、风格、页数等）

## 支持的意图类型
- generate_pptx: 从零生成演示文稿（可能同时生成文档+PPT）
- modify_pptx: 修改已有演示文稿
- generate_doc: 仅生成文档
- query: 问答/查询，不需要生成文档或PPT

## 风格选项
- 商务汇报: 适合管理层汇报、季度总结、项目进度
- 科技产品: 适合产品发布、技术分享、AI/科技主题
- 教育培训: 适合培训课件、知识分享
- 创意设计: 适合品牌展示、创意提案
- 简约专业: 默认通用风格

## 输出格式（严格JSON）
{
  "intent": "generate_pptx | modify_pptx | generate_doc | query",
  "topic": "演示文稿/文档的主题",
  "audience": "目标受众",
  "style": "商务汇报 | 科技产品 | 教育培训 | 创意设计 | 简约专业",
  "estimated_pages": 8,
  "key_points": ["要点1", "要点2", "要点3"],
  "source_context": "用户提供的背景信息摘要",
  "subtasks": [
    {"id": 1, "type": "create_doc", "description": "创建结构化文档作为内容源"},
    {"id": 2, "type": "create_slides", "description": "基于文档内容生成演示文稿"},
    {"id": 3, "type": "deliver", "description": "交付分享链接"}
  ]
}

注意：
- key_points 是从用户消息中提取的核心内容要点
- subtasks 的 type 只能是: create_doc, update_doc, create_slides, modify_slides, deliver, query
- 对于 generate_pptx 意图，通常需要 create_doc + create_slides + deliver 三个子任务
- estimated_pages 通常在 6-15 页之间"""


@dataclass
class Plan:
    intent: str
    topic: str
    audience: str = ""
    style: str = "简约专业"
    estimated_pages: int = 10
    key_points: list[str] = field(default_factory=list)
    source_context: str = ""
    subtasks: list[dict] = field(default_factory=list)

    def to_confirmation_text(self) -> str:
        lines = [
            f"📋 任务计划",
            f"",
            f"📌 主题：{self.topic}",
            f"👥 受众：{self.audience or '通用'}",
            f"🎨 风格：{self.style}",
            f"📄 预计页数：{self.estimated_pages}",
            f"",
            f"📝 核心要点：",
        ]
        for i, pt in enumerate(self.key_points, 1):
            lines.append(f"  {i}. {pt}")
        lines.append("")
        lines.append("🔄 执行步骤：")
        for task in self.subtasks:
            lines.append(f"  {task['id']}. {task['description']}")
        lines.append("")
        lines.append("回复「确认」开始执行，或告诉我需要调整的地方。")
        return "\n".join(lines)


class Planner:
    def __init__(self):
        self._client = OpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL or None,
            timeout=120.0,
            max_retries=2,
        )
        self._model = LLM_MODEL

    async def plan(self, user_message: str, chat_history: list[dict] | None = None) -> Plan:
        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        ]

        if chat_history:
            messages.extend(chat_history[-10:])

        messages.append({"role": "user", "content": user_message})

        try:
            response = await asyncio.to_thread(
                self._client.chat.completions.create,
                model=self._model,
                messages=messages,
                temperature=0.3,
            )

            content = response.choices[0].message.content.strip()
            # Extract JSON from response (model may wrap in markdown code block)
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            data = json.loads(content)
            return Plan(
                intent=data.get("intent", "query"),
                topic=data.get("topic", ""),
                audience=data.get("audience", ""),
                style=data.get("style", "简约专业"),
                estimated_pages=data.get("estimated_pages", 10),
                key_points=data.get("key_points", []),
                source_context=data.get("source_context", ""),
                subtasks=data.get("subtasks", []),
            )
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error("Failed to parse planner response: %s", e)
            return Plan(
                intent="query",
                topic=user_message[:50],
                subtasks=[{"id": 1, "type": "query", "description": "直接回复用户问题"}],
            )


import asyncio
