---
name: lark-workflow-im-to-pptx
version: 1.0.0
description: "IM对话到演示稿一键闭环工作流：从飞书IM消息中提取用户意图，规划子任务，自动生成文档/画板内容，创建演示文稿，并交付分享链接。当用户需要从聊天内容生成PPT、把讨论整理成演示稿、一键生成汇报幻灯片时使用。"
metadata:
  requires:
    bins: ["lark-cli"]
---

# IM对话到演示稿一键闭环工作流

**CRITICAL — 开始前 MUST 先用 Read 工具读取 [`../lark-shared/SKILL.md`](../../.agents/skills/lark-shared/SKILL.md)，其中包含认证、权限处理**

## 适用场景

- "帮我把这段对话整理成PPT" / "生成演示稿" / "做个汇报"
- "把讨论结果做成幻灯片" / "整理成文档和PPT"
- "一键生成演示" / "IM内容转PPT"
- "帮我做个项目汇报PPT" / "产品讨论整理成演示"

## 前置条件

仅支持 **user 身份**。执行前确保已授权：

```bash
lark-cli auth login --domain docs,slides,drive,im
```

## 工作流

```
IM消息 ─► 意图提取 & 任务规划 ─┬─► 文档生成 (lark-doc)
   (场景A)        (场景B)      ├─► 画板生成 (lark-whiteboard, 可选)
                               └─► 演示文稿生成 (lark-slides)
                                          │
                                          ▼
                                    交付 & 分享 (场景F)
```

### Step 1: 意图提取（场景B）

解析用户消息，提取：
- **主题**：演示文稿/文档的核心主题
- **受众**：面向谁（管理层、技术团队、客户等）
- **风格**：商务汇报 | 科技产品 | 教育培训 | 创意设计 | 简约专业
- **核心要点**：从消息中提取 3-5 个关键内容点
- **预计页数**：通常 8-12 页

输出结构化计划发送给用户确认。

### Step 2: 内容结构化

将自由文本/讨论内容转化为：
1. **文档内容**（Markdown/XML 格式，用于飞书文档）
2. **幻灯片大纲**（每页标题 + 要点 + 布局类型）
3. **内容摘要**（用于交付展示）

### Step 3: 文档生成（场景C）

```bash
# 创建文档
lark-cli docs +create --api-version v2 --doc-format markdown \
  --content '<title>主题</title><h2>章节</h2><p>内容</p>' --as user

# 更新文档（如需追加内容）
lark-cli docs +update --api-version v2 --doc "<token>" \
  --command append --doc-format markdown --content '<h2>新章节</h2><p>内容</p>' --as user
```

可选：在文档中插入画板（用于架构图、流程图）

```bash
# 先在文档中添加空白画板
lark-cli docs +update --api-version v2 --doc "<token>" \
  --command append --content '<whiteboard type="blank"></whiteboard>' --as user

# 用 Mermaid 更新画板
lark-cli whiteboard +update <board_token> --source - --input_format mermaid --as user < flowchart.mmd
```

### Step 4: 演示文稿生成（场景D）

**CRITICAL — 生成任何 XML 之前，MUST 先用 Read 工具读取 [xml-schema-quick-ref.md](../../.agents/skills/lark-slides/references/xml-schema-quick-ref.md)，禁止凭记忆猜测 XML 结构。**

```bash
# 一步创建含内容的PPT（推荐）
lark-cli slides +create --title "演示文稿标题" \
  --slides '["<slide xmlns=\"http://www.larkoffice.com/sml/2.0\">...</slide>", ...]' \
  --as user
```

风格配置速查：

| 风格 | 背景 | 主色 | 文字色 |
|------|------|------|--------|
| 商务汇报 | 浅灰 rgb(248,250,252) | 深蓝 rgb(30,60,114) | 深灰 rgb(30,41,59) |
| 科技产品 | 深蓝渐变 | 蓝色 rgb(59,130,246) | 白色 |
| 教育培训 | 白色 rgb(255,255,255) | 绿色 rgb(34,197,94) | 深灰 rgb(51,65,85) |
| 创意设计 | 紫粉渐变 | 粉紫色系 | 白色 |
| 简约专业 | 浅灰 + 顶部渐变条 | 蓝色 rgb(59,130,246) | 深色 rgb(15,23,42) |

### Step 5: 质量检查

```bash
# 读取幻灯片全文验证
lark-cli slides xml_presentations get \
  --params '{"xml_presentation_id":"<id>"}' --as user

# 局部修正（不需要整页重建）
lark-cli slides +replace-slide --presentation <id> --slide-id <sid> \
  --parts '[{"action":"block_replace","target_id":"<block_id>","content":"<shape ...>"}]' --as user
```

### Step 6: 交付分享（场景F）

```bash
# 获取分享链接
lark-cli drive metas batch_query \
  --data '{"request_docs":[{"doc_type":"docx","doc_token":"<token>"},{"doc_type":"slides","doc_token":"<id>"}],"with_url":true}' \
  --as user

# 通过 IM 发送结果链接
lark-cli im +messages-send --chat-id <chat_id> \
  --msg-type post --content '{"zh_cn":{"title":"汇报材料已生成","content":[[{"tag":"text","text":"📄 文档: "},{"tag":"a","href":"<url>","text":"点击查看"}]]}}'
```

## 大纲模板

生成大纲时使用以下格式：

```text
[PPT 标题] — [定位描述]，面向 [目标受众]

页面结构（N 页）：
1. 封面页：[标题文案]
2. [页面主题]：[要点1]、[要点2]、[要点3]
3. [页面主题]：[要点描述]
...
N. 结尾页：[结尾文案]

风格：[配色方案]，[排版风格]
```

## 错误恢复

| 错误 | 解决方案 |
|------|----------|
| 权限不足 | 检查 `--as user` 是否指定，重新 `lark-cli auth login` |
| XML 格式错误 | 读取 xml-schema-quick-ref.md，检查标签闭合和属性格式 |
| 渐变背景变白 | 必须用 `rgba()` 格式 + 百分比停靠点 |
| 图片不显示 | 先 `slides +media-upload` 上传拿 file_token，再写进 `<img src>` |

## 参考

- [lark-shared](../../.agents/skills/lark-shared/SKILL.md) — 认证、权限（必读）
- [lark-doc](../../.agents/skills/lark-doc/SKILL.md) — 文档创建、编辑详细用法
- [lark-slides](../../.agents/skills/lark-slides/SKILL.md) — 幻灯片创建、编辑详细用法
- [lark-drive](../../.agents/skills/lark-drive/SKILL.md) — 文件分享、导出
- [lark-im](../../.agents/skills/lark-im/SKILL.md) — 消息发送详细用法
- [lark-whiteboard](../../.agents/skills/lark-whiteboard/SKILL.md) — 画板更新
