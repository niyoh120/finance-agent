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
FA_MCP_SERVER_URL=http://mcp-server:8087/mcp
FA_TRADE_AGENT_STOCK_API_URL=http://stock-api:3000
FA_TRADE_AGENT_PARALLELISM=2
OPENAI_API_KEY=...
GOOGLE_API_KEY=...
```

Chart MCP 示例：

```
chart_mcp:
  url: "http://localhost:1122/mcp"
```

## 运行

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
