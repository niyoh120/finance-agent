# Finance MCP & Microservices

基于 Docker Compose 的微服务架构，包含 Discord 期权流抓取、股票数据轮询、MCP 服务以及管理后台。

## 架构概览 (Microservices Architecture)

项目采用 Monorepo 结构，所有服务共享核心逻辑 (`shared`)。

| 服务 | 目录 | 语言 | 描述 | 端口 |
| :--- | :--- | :--- | :--- | :--- |
| **db** | - | PostgreSQL | 核心数据库 (PostgreSQL 15) | 5432 |
| **stock-api** | `services/stock-api` | TypeScript | TradingView API 包装器 (Fastify) | 3000 |
| **stock-scraper** | `services/stock-scraper` | Python | 股票数据轮询 | - |
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
编辑 `.env` 填入 Discord Token 和 Channel ID。

### 获取 TradingView Session (可选)
如果需要访问实时数据或某些特定交易所的数据，建议配置 Session。

1. 登录 [TradingView](https://www.tradingview.com/)。
2. 打开开发者工具 (F12) -> Application (应用) -> Cookies。
3. 找到 `https://www.tradingview.com` 下的 Cookies：
   - `sessionid` -> 对应环境变量 `TV_SESSION`
   - `sessionid_sign` -> 对应环境变量 `TV_SIGNATURE`

### 获取 DISCORD_CHANNEL_ID

1. 在 Discord 设置中开启「开发者模式」(用户设置 → 高级 → 开发者模式)
2. 右键点击目标频道 → 「复制频道 ID」

### 获取 DISCORD_TOKEN

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
# 进入 stock-scraper 容器运行迁移 (因为该容器包含 shared 环境)
docker compose run --rm stock-scraper uv run alembic upgrade head
```

### 5. 数据迁移 (可选)
如果你有旧版的 SQLite 数据 (`data/options_flow.db`)：

```bash
docker compose run --rm stock-scraper python scripts/migrate_data.py
```

## 服务详情

### Stock API
- 无状态 HTTP 服务，包装 `@mathieuc/tradingview` 库。
- 提供通用接口 `GET /quote?symbol=<SYMBOL>` (例如 `NASDAQ:AAPL`, `BINANCE:BTCUSDT`)。
- 仅负责获取实时数据，**不负责存储**。

### Stock Scraper
- **负责存储**：定期调用 Stock API 并将数据写入 PostgreSQL。
- **可配置**：监控列表在 `services/stock-scraper/config.yaml` 中定义。

### Options Scraper
- 监听 Discord 频道，解析 Unusual Whales 格式的期权大单流。
- 去重并写入数据库。

### Admin UI
访问: `http://localhost:8000/admin`
- 查看和管理期权大单数据 (`OptionsFlow`)
- 查看股票历史数据 (`StockPrice`)

### MCP Server
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
- **Python**: v3.11+ (并安装 `uv`)

#### 2. 环境变量
修改根目录 `.env` 文件，将主机名从容器名改为 `localhost`：

```bash
# .env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/finance
STOCK_API_URL=http://localhost:3000
```

#### 3. 安装依赖
**Python (Monorepo)**:
在项目根目录运行，这将创建一个包含所有服务依赖的虚拟环境：
```bash
uv sync
```

**TypeScript (Stock API)**:
```bash
cd services/stock-api
npm install
```

#### 4. 启动服务 (需打开多个终端)

**终端 1: Stock API**
```bash
cd services/stock-api
# 确保该目录下也有 .env 文件，或通过 export 设置环境变量
cp ../../.env .env 
npm run dev
```

**终端 2: Stock Scraper (股票轮询)**
```bash
# 回到根目录
# 指定配置文件路径
export CONFIG_PATH=services/stock-scraper/config.yaml
uv run python services/stock-scraper/src/main.py
```

**终端 3: Options Scraper (Discord 抓取)**
```bash
uv run python services/options-scraper/src/main.py
```

**终端 4: Admin UI**
```bash
uv run python services/admin/src/main.py
# 访问 http://localhost:8000/admin
```

**终端 5: MCP Server**
```bash
uv run python services/mcp-server/src/main.py
```

### 目录结构
```
├── services/           # 微服务源码
│   ├── admin/          # 管理后台
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
