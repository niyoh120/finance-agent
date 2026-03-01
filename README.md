# Finance MCP & Microservices

基于 Docker Compose 的微服务架构，包含 BubbleSeek 数据抓取、宏观金融数据抓取、Stock API、Trade Agent 与 MCP 服务。

## 架构概览 (Microservices Architecture)

项目采用 Monorepo 结构，所有服务共享核心逻辑 (`shared`)。

| 服务 | 目录 | 语言 | 描述 | 端口 |
| :--- | :--- | :--- | :--- | :--- |
| **db** | - | PostgreSQL | 核心数据库 (PostgreSQL 15) | 5432 |
| **stock-api** | `services/stock-api` | TypeScript | TradingView API 包装器 (Fastify) | 3000 |
| **macro-scraper** | `services/macro-scraper` | Python | 宏观金融数据抓取 | - |
| **bubbleseek-scraper** | `services/bubbleseek-scraper` | Python | 新闻与期权流抓取 (bubbleseek.ai) | - |
| **trade-agent** | `services/trade-agent` | Python | 多智能体交易分析与 Discord Bot | 8089 |
| **mcp-server** | `services/mcp-server` | Python | Model Context Protocol 服务器 | Stdio |

## 快速开始 (Quick Start)

### 1. 环境准备
- Docker & Docker Compose
- Python 3.12.12 (仅本地开发需要，推荐用 `mise` 管理)
- Node.js 20+ (仅本地开发需要)

### 2. 配置
复制环境变量模版：
```bash
cp .env.example .env
```

> 项目使用 `mise` 从根目录 `.env` 注入环境变量（见 `mise.toml`），应用代码本身不再读取 `.env`。

### 获取 TradingView Session (可选)
如果需要访问实时数据或某些特定交易所的数据，建议配置 Session。

1. 登录 [TradingView](https://www.tradingview.com/)。
2. 打开开发者工具 (F12) -> Application (应用) -> Cookies。
3. 找到 `https://www.tradingview.com` 下的 Cookies：
   - `sessionid` -> 对应环境变量 `FA_STOCK_API_TV_SESSION`
   - `sessionid_sign` -> 对应环境变量 `FA_STOCK_API_TV_SIGNATURE`

### 3. 启动服务
```bash
docker compose up --build -d
```

### 4. 数据库初始化
首次启动需要运行 Alembic 迁移以创建表结构：

```bash
# 使用一次性 migrate 镜像运行迁移
docker compose --profile migrate run --rm migrate
```

## 服务详情

### Stock API
- 无状态 HTTP 服务，包装 `@mathieuc/tradingview` 库。
- 仅负责获取 TradingView 数据，不负责存储。
- OpenAPI 文档：`GET /openapi.json`。

#### 接口列表

- `GET /health`
  - 用途：健康检查
  - 响应：`{"status":"ok"}`

- `GET /openapi.json`
  - 用途：返回 OpenAPI 3.0 JSON 描述（接口自说明）

- `GET /quote?symbol=<SYMBOL>`
  - 用途：获取实时行情快照
  - 参数：
    - `symbol`（必填）：例如 `NASDAQ:AAPL`、`BINANCE:BTCUSDT`
  - 响应字段（核心）：`symbol/price/volume/open/high/low/prevClose/change/changePercent/bid/ask/status/timestamp`
  - 示例：
    - `curl "http://localhost:3000/quote?symbol=NASDAQ:AAPL"`

- `GET /history?symbol=<SYMBOL>&timeframe=<TF>&range=<N>&to=<TS>`
  - 用途：获取历史 K 线（OHLCV）
  - 参数：
    - `symbol`（必填）
    - `timeframe`（可选，默认 `D`）：TradingView timeframe（如 `D`、`60`、`240` 等）
    - `range`（可选，默认 `200`）：返回 N 根 K 线
    - `to`（可选）：Unix 秒时间戳（结束时间，闭区间）
  - 响应：`{ symbol, timeframe, range, to?, candles: Candle[] }`
    - `Candle`：`{ time, timestamp, open, high, low, close, volume? }`（其中 `time` 为 Unix 秒）
  - 示例：
    - `curl "http://localhost:3000/history?symbol=NASDAQ:AAPL&timeframe=D&range=200"`

- `GET /search?q=<Q>&type=<TYPE>&offset=<N>&limit=<N>`
  - 用途：搜索 TradingView 市场，返回候选 market id（用于解决交易所前缀不确定/标的迁移上市地等问题）
  - 参数：
    - `q`（必填）：ticker、公司名或 `EXCHANGE:` 前缀提示，例如 `WMT`、`walmart`、`NASDAQ:`
    - `type`（可选，默认 `stock`）：`stock/futures/forex/cfd/crypto/index/economic`
    - `offset`（可选，默认 `0`）：分页偏移
    - `limit`（可选，默认 `10`，最大 `50`）：返回数量上限
  - 响应：`{ query, type?, offset, limit, count, results: Market[] }`
    - `Market`：`{ id, exchange, full_exchange, symbol, description, type }`
  - 示例：
    - `curl "http://localhost:3000/v0/searchMarket?q=WMT&type=stock&limit=5"`

- `GET /indicator?symbol=<SYMBOL>&indicatorId=<ID>&timeframe=<TF>&range=<N>&to=<TS>&options=<JSON>`
  - 用途：获取 TradingView 技术指标输出（含高级会员账号可访问的私有/邀请制指标，视账号权限而定）
  - 参数：
    - `symbol`（必填）
    - `indicatorId`（必填）：
      - 内置指标：例如 `STD;EMA`、`STD;Supertrend`
      - built-in 指标：形如 `Volume@tv-basicstudies-241`、`VbPFixed@tv-basicstudies-241!`
    - `timeframe`（可选，默认 `D`）
    - `range`（可选，默认 `200`）
    - `to`（可选）：Unix 秒时间戳
    - `options`（可选）：JSON 字符串（指标输入参数），例如 `{"Length":50}`
  - 响应：`IndicatorResult`：
    - `candles`: 对应 K 线（最新在前）
    - `periods`: 指标每根 K 线的 plot 值（结构因指标而异）
    - `plots`: plot 命名映射（部分指标才有）
  - 示例：
    - `curl --get "http://localhost:3000/indicator" \
      --data-urlencode "symbol=NASDAQ:AAPL" \
      --data-urlencode "indicatorId=STD;EMA" \
      --data-urlencode "timeframe=D" \
      --data-urlencode "range=200" \
      --data-urlencode 'options={"Length":50}'`

- `GET /ta?symbol=<SYMBOL>`
  - 用途：获取 TradingView Technical Analysis（Recommend）汇总
  - 参数：
    - `symbol`（必填）
  - 示例：
    - `curl "http://localhost:3000/ta?symbol=NASDAQ:AAPL"`

- `GET /indicators/private`
  - 用途：列出当前账号的私有指标（TradingView "saved" 指标）
  - 依赖：必须配置 `FA_STOCK_API_TV_SESSION`（建议同时配置 `FA_STOCK_API_TV_SIGNATURE`）
  - 示例：
    - `curl "http://localhost:3000/indicators/private"`

#### TradingView 账号与权限说明
- 默认匿名模式也可工作，但某些交易所数据、实时能力、私有/邀请制指标、部分 built-in 指标可能需要登录。
- 通过环境变量注入 TradingView Cookie：
  - `FA_STOCK_API_TV_SESSION`：对应 TradingView Cookie `sessionid`
  - `FA_STOCK_API_TV_SIGNATURE`：对应 TradingView Cookie `sessionid_sign`

### Macro Scraper
- 从 The Dial API (`indexbha.com`) 拉取宏观指标与历史序列并写入数据库。
- 通过 `FA_MACRO_SCRAPER_*` 控制轮询与回溯天数。
- 默认 `FA_MACRO_SCRAPER_ENABLE_PROTECTED_ENDPOINTS=false`，会跳过受保护端点 `export/report`。
- 跳过受保护端点时，`macro_reports`、`macro_module_snapshots`、`macro_factor_snapshots` 不会新增；历史序列表仍会持续更新。

### BubbleSeek Scraper
- 从 bubbleseek.ai API 获取新闻和期权流数据。
- 新闻类型：KOL 推文、财经新闻等。
- 期权流：解析 Unusual Whales 格式的期权大单。
- 通过 `FA_BUBBLESEEK_SCRAPER_INTERVAL` 控制轮询间隔。

### MCP Server
- 提供新闻、期权、股票与宏观数据查询工具。
- 宏观工具覆盖：报告快照、模块/因子快照、模块历史、总指数历史。
- 当 `FA_MACRO_SCRAPER_ENABLE_PROTECTED_ENDPOINTS=false` 时，`query_macro_reports`、`query_macro_module_snapshots`、`query_macro_factor_snapshots` 不会注册到 MCP 工具列表。
- TradingView 市场搜索工具 `search_market`：
  - 用途：搜索正确的 TradingView market id（解决交易所前缀不确定、标的迁移上市地等问题）
  - 用法：用 ticker/公司名搜索，拿到返回结果中的 `id`（形如 `NASDAQ:AAPL`）
- 股票历史数据工具 `fetch_stock_history`：
  - `symbol` 必须为 `EXCHANGE:SYMBOL`（TradingView market id），用于避免同名 ticker 查错。
  - 如果不确定交易所前缀，请先调用 `search_market` 搜索得到正确的 `id` 再查询历史数据。
  - 示例：`NASDAQ:AAPL`、`SSE:000001`、`HKEX:700`、`BINANCE:BTCUSDT`
Claude Desktop 配置示例:
```json
{
  "mcpServers": {
    "finance": {
      "command": "docker",
      "args": ["exec", "-i", "finance-agent-mcp-server-1", "python", "-m", "mcp_server.studio"]
    }
  }
}
```
*(注: 需根据实际容器名调整)*

## 本地开发 (Local Development)

### 方式一：使用 Docker (推荐)
最简单的方式，一键启动所有服务。
```bash
docker compose up --build
```

### 方式二：纯本地运行 (No Docker)
如果你不想使用 Docker，可以手动运行各个服务。

#### 1. 基础设施准备
- **PostgreSQL**: 确保本地安装并运行了 PostgreSQL。
  - 创建数据库: `finance`
  - 确保用户 `postgres` 密码为 `postgres` (或修改 .env)
- **Node.js**: v20+
- **Python**: v3.12.12（推荐用 `mise` 管理 Python/工具链）

#### 2. 环境变量
修改根目录 `.env` 文件，将主机名从容器名改为 `localhost`：

```bash
# .env
FA_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/finance
FA_MCP_SERVER_STOCK_API_URL=http://localhost:3000
```

#### 3. 安装依赖
推荐用 `mise` 统一安装（会执行 `uv sync --all-packages`）：
```bash
mise run install
```

（等价命令：在项目根目录运行 `uv sync --all-packages`）

**TypeScript (Stock API)**:
```bash
cd services/stock-api
npm install
```

#### 4. 启动服务 (需打开多个终端)

**终端 1: Stock API**
```bash
# 推荐：使用 mise（会从根目录 .env 注入环境变量）
mise run stock-api

# 或者手动运行
# cd services/stock-api
# npm run dev
```

**终端 2: Macro Scraper (宏观抓取)**
```bash
mise run macro-scraper
```

**终端 3: BubbleSeek Scraper (新闻与期权抓取)**
```bash
mise run bubbleseek-scraper
```

**终端 4: MCP Server**
```bash
mise run mcp-server
```

**终端 5: Trade Agent API**
```bash
mise run trade-agent
```

**终端 6: Trade Agent Discord Bot**
```bash
# 需要在 .env 中配置 DISCORD_BOT_TOKEN
mise run trade-agent-bot
```

### 目录结构
```
├── services/              # 微服务源码
│   ├── macro-scraper/     # 宏观抓取
│   ├── mcp-server/        # MCP 服务
│   ├── bubbleseek-scraper/ # 新闻与期权抓取
│   ├── stock-api/         # TS API
│   └── ...
├── shared/                # 共享 Python 模块 (Models, DB)
├── scripts/               # 运维/迁移脚本
├── alembic/               # 数据库迁移文件
├── docker-compose.yml     # 容器编排
└── pyproject.toml         # Workspace 配置
```
