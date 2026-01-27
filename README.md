# Finance MCP & Microservices

基于 Docker Compose 的微服务架构，包含 Discord 期权流抓取、股票数据轮询、MCP 服务以及管理后台。

## 架构概览 (Microservices Architecture)

项目采用 Monorepo 结构，所有服务共享核心逻辑 (`shared`)。

| 服务 | 目录 | 语言 | 描述 | 端口 |
| :--- | :--- | :--- | :--- | :--- |
| **db** | - | PostgreSQL | 核心数据库 (PostgreSQL 15) | 5432 |
| **stock-api** | `services/stock-api` | TypeScript | TradingView API 包装器 (Fastify) | 3000 |
| **stock-scraper** | `services/stock-scraper` | Python | 股票数据轮询 | - |
| **macro-scraper** | `services/macro-scraper` | Python | 宏观金融数据抓取 | - |
| **options-scraper** | `services/options-scraper` | Python | Discord 期权流抓取 | - |
| **mcp-server** | `services/mcp-server` | Python | Model Context Protocol 服务器 | Stdio |
| **admin** | `services/admin` | Python | 数据管理后台 (SQLAdmin) | 8000 |

## 快速开始 (Quick Start)

### 1. 环境准备
- Docker & Docker Compose
- Python 3.11+ (仅本地开发需要)
- Node.js 20+ (仅本地开发需要)

### 2. 配置
复制环境变量模版：
```bash
cp .env.example .env
```
编辑 `.env` 填入 Discord Token 和 Channel ID（主要用于 `options-scraper`）。

> 项目使用 `mise` 从根目录 `.env` 注入环境变量（见 `mise.toml`），应用代码本身不再读取 `.env`。

### 获取 TradingView Session (可选)
如果需要访问实时数据或某些特定交易所的数据，建议配置 Session。

1. 登录 [TradingView](https://www.tradingview.com/)。
2. 打开开发者工具 (F12) -> Application (应用) -> Cookies。
3. 找到 `https://www.tradingview.com` 下的 Cookies：
   - `sessionid` -> 对应环境变量 `FA_STOCK_API_TV_SESSION`
   - `sessionid_sign` -> 对应环境变量 `FA_STOCK_API_TV_SIGNATURE`

### 获取 FA_OPTIONS_SCRAPER_CHANNEL_ID

1. 在 Discord 设置中开启「开发者模式」(用户设置 → 高级 → 开发者模式)
2. 右键点击目标频道 → 「复制频道 ID」

### 获取 FA_OPTIONS_SCRAPER_DISCORD_TOKEN

> ⚠️ **风险提示**: 使用用户 token 违反 Discord ToS，有封号风险。建议使用小号。

1. 打开 Discord 网页版 (discord.com/app) 或桌面客户端
2. 按 `F12` 打开开发者工具
3. 切换到 **Network** (网络) 标签
4. 在 Discord 中随便点击一个频道触发请求
5. 找到任意请求，点击查看 **Headers** (请求头)
6. 找到 `Authorization` 字段，其值就是你的 token

或者在 Console 中执行：
```javascript
(webpackChunkdiscord_app.push([[''],{},e=>{m=[];for(let c in e.c)m.push(e.c[c])}]),m).find(m=>m?.exports?.default?.getToken!==void 0).exports.default.getToken()
```

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
- 仅负责获取 TradingView 数据，**不负责存储**（由 `stock-scraper` 写入 PostgreSQL）。
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
  - 用途：列出当前账号的私有指标（TradingView “saved” 指标）
  - 依赖：必须配置 `FA_STOCK_API_TV_SESSION`（建议同时配置 `FA_STOCK_API_TV_SIGNATURE`）
  - 示例：
    - `curl "http://localhost:3000/indicators/private"`

#### TradingView 账号与权限说明
- 默认匿名模式也可工作，但某些交易所数据、实时能力、私有/邀请制指标、部分 built-in 指标可能需要登录。
- 通过环境变量注入 TradingView Cookie：
  - `FA_STOCK_API_TV_SESSION`：对应 TradingView Cookie `sessionid`
  - `FA_STOCK_API_TV_SIGNATURE`：对应 TradingView Cookie `sessionid_sign`

### Stock Scraper
- **负责存储**：定期调用 Stock API 并将数据写入 PostgreSQL。
- **可配置**：监控列表在 `services/stock-scraper/config.yaml` 中定义。

### Macro Scraper
- 从 The Dial API (`indexbha.com`) 拉取宏观指标与历史序列并写入数据库。
- 通过 `FA_MACRO_SCRAPER_*` 控制轮询与回溯天数。

### Options Scraper
- 监听 Discord 频道，解析 Unusual Whales 格式的期权大单流。
- 去重并写入数据库。

### Admin UI
访问: `http://localhost:8000/admin`
- 查看和管理期权大单数据 (`OptionsFlow`)
- 查看股票历史数据 (`StockPrice`)
- 查看新闻数据 (`NewsArticle`)

### MCP Server
- 提供新闻、期权、股票与宏观数据查询工具。
- 宏观工具覆盖：报告快照、模块/因子快照、模块历史、总指数历史。
Claude Desktop 配置示例:
```json
{
  "mcpServers": {
    "finance": {
      "command": "docker",
      "args": ["exec", "-i", "finance-agent-mcp-server-1", "python", "src/main.py"]
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
- **Python**: v3.11+（推荐用 `mise` 管理 Python/工具链）

#### 2. 环境变量
修改根目录 `.env` 文件，将主机名从容器名改为 `localhost`：

```bash
# .env
FA_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/finance
FA_STOCK_SCRAPER_API_URL=http://localhost:3000
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

**终端 2: Stock Scraper (股票轮询)**
```bash
# 推荐：使用 mise（会从根目录 .env 注入环境变量）
mise run stock-scraper

# 如需指定配置文件路径
# FA_STOCK_SCRAPER_CONFIG_PATH=services/stock-scraper/config.yaml mise run stock-scraper
```

**终端 3: Macro Scraper (宏观抓取)**
```bash
mise run macro-scraper
```

**终端 4: Options Scraper (Discord 抓取)**
```bash
mise run options-scraper
```

**终端 5: Admin UI**
```bash
mise run admin
# 访问 http://localhost:8000/admin
```

**终端 6: MCP Server**
```bash
mise run mcp-server
```

### 目录结构
```
├── services/           # 微服务源码
│   ├── admin/          # 管理后台
│   ├── macro-scraper/  # 宏观抓取
│   ├── mcp-server/     # MCP 服务
│   ├── options-scraper/ # Discord 抓取
│   ├── stock-api/      # TS API
│   └── stock-scraper/  # 股票抓取
├── shared/             # 共享 Python 模块 (Models, DB)
├── scripts/            # 运维/迁移脚本
├── alembic/            # 数据库迁移文件
├── docker-compose.yml  # 容器编排
└── pyproject.toml      # Workspace 配置
```
