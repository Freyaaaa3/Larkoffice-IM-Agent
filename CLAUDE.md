# Feishu Agent - Agent-Pilot

参赛项目：Agent-Pilot · 从 IM 对话到演示稿的一键智能闭环

## 项目定位
飞书智能体，通过 IM 对话触发，AI Agent 驱动文档和演示文稿自动生成。

## 技术栈
- **飞书 Bot SDK**: lark-oapi (WebSocket 长连接)
- **LLM**: OpenAI 兼容 API (意图规划 + 内容生成)
- **飞书 API**: lark-cli v1.0.20 (文档/幻灯片/IM/Drive 操作)
- **语言**: Python 3.11+

## 核心场景
- A: 意图入口 (IM 群聊/单聊 @bot)
- B: 任务理解与规划 (LLM Planner)
- C: 文档/画板生成与编辑 (lark-cli docs)
- D: 演示文稿生成 (lark-cli slides)
- F: 总结与交付 (lark-cli im/drive)
- 跳过 E (多端协作，飞书原生覆盖)

## 项目结构
- `agent/` — 核心 Agent 代码
  - `main.py` — 入口
  - `feishu_bot.py` — 飞书 Bot 事件处理
  - `planner.py` — 意图规划器
  - `executor.py` — lark-cli 命令执行器
  - `workflows/im_to_pptx.py` — 主工作流
  - `workflows/content_structure.py` — 内容结构化
  - `config.py` — 配置
- `skills/` — Agent 技能 (SKILL.md)
- `.agents/skills/` — lark-cli 官方技能 (已有)

## 运行方式
```bash
# 1. 配置 .env (复制 .env.example 填入实际值)
cp .env.example .env

# 2. 安装依赖
pip install -e .

# 3. lark-cli 认证（应用/租户 + 可选用户 OAuth）
lark-cli config init   # 若尚未配置应用
lark-cli auth login --domain docs,slides,drive,im   # 可选；仅当 .env 中 LARK_CLI_IDENTITY=user 时需要

# 4. 启动
python -m agent.main
```

## 关键约定
- lark-cli 默认 `--as bot`（`LARK_CLI_IDENTITY`，无需用户 OAuth）；若以用户身份写「我的空间」文档则设 `user` 并完成 `auth login`
- 文档创建使用 `--api-version v2`
- 幻灯片 XML 必须符合 SML 2.0 协议，生成前必须读取 xml-schema-quick-ref.md
- 渐变色必须用 rgba() 格式 + 百分比停靠点
- 图片必须先上传 (slides +media-upload) 再用 file_token
- 用户中文对话时回复中文
