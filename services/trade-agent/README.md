# Trade Agent

基于 agno 的多智能体交易决策系统，提供两种运行模式：

1. 固定流程分析（显式编排）
2. 对话式分析（Team 自动协调）

## 功能概览

- 技术面分析（MCP K 线 + pandas-ta + YFinance 交叉验证）
- 期权流分析（MCP options_flow）
- 新闻情绪分析（MCP news + YFinance news）
- 基本面分析（YFinanceTools）
- 宏观分析（MCP The Dial 宏观数据）
- 威科夫分析（MCP K 线）
- 风险管理（确定性硬约束 + LLM 微调）
- 威科夫结构绘图（MCP K 线 + 通用 Matplotlib 渲染工具生成 WEBP base64，便于内联展示）

## 目录结构

```
services/trade-agent/
├── config.yaml
├── src/trade_agent/
│   ├── app.py
│   ├── analysis_engine.py
│   ├── chat_team.py
│   ├── agents/
│   ├── models/
│   └── tools/
```

## 配置

`config.yaml` 支持环境变量占位符：

```
models:
  technical:
    provider: "openai"
    model_id: "gpt-4o-mini"
```

环境变量示例：

```
FA_TRADE_AGENT_CONFIG=services/trade-agent/config.yaml
FA_TRADE_AGENT_LOG_LEVEL=INFO
AXONHUB_API_KEY=...
DISCORD_BOT_TOKEN=...
OPENAI_API_KEY=...  # 当 provider 使用 openai/openai-like 且未配置其他 key env 时
```

Discord Bot 配置示例：

```
discord_bot:
  max_concurrency: 3
  run_timeout_seconds: 180
  num_history_runs: 8
  stream_events: false
  stream_member_events: false
  placeholder_text: "正在分析中..."
  min_edit_interval_ms: 700
  min_edit_chars: 24
  max_stream_chars: 1800
  max_final_chars: 1900
  final_overflow_strategy: "split" # split | truncate
```

Chart MCP 示例：

```
chart_mcp:
  url: "http://localhost:1122/mcp"
```

## 运行

推荐使用 `mise` 从仓库根目录启动（会自动注入根目录 `.env`）：

```
mise run trade-agent
```

启动 Discord Bot：

```
mise run trade-agent-bot
```

Discord Bot 行为说明：

- 全频道消息触发（不需要 @）。
- 严格过滤系统噪声：忽略 system/bot/webhook/空内容消息。
- 回复方式为单条消息流式编辑：先发送占位消息，再持续编辑。
- 超长输出默认按分段发送（可配置为截断）。

Discord 开发者后台需要开启 `Message Content Intent`，否则无法读取消息正文。

等价的 `uv` 命令（在 `services/trade-agent` 目录执行）：

```
uv run python -m trade_agent.app
uv run python -m trade_agent.discord_bot
```

启动 FastAPI（本地）：

```
uv run python -m trade_agent.app
```

接口：

- `POST /analysis/run` 固定流程分析
- `POST /analysis/wyckoff` 威科夫结构流程（返回分析结果与图表 URL）
- `POST /chat` 对话式分析
- `GET /agent-os` AgentOS UI

AgentOS 中包含 `Trade Analysis Workflow` 与 `Wyckoff Analysis Workflow`，可直接通过 UI 或 API 调用工作流运行。

## 说明

- 风险管理先计算硬性约束，再由 LLM 在硬约束内微调。
- 技术指标优先使用内部 K 线，YFinance 指标用于验证。
- 期权流与新闻只走内部数据源，YFinance 作为补充。
- Matplotlib 渲染工具通过 Pillow 输出 webp，可直接嵌入 Markdown。
