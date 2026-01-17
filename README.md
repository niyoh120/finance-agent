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
- 提供 `GET /quote?symbol=NASDAQ:AAPL` 接口。
- 使用 `@mathieuc/tradingview` 获取实时数据。

### Stock Scraper
- 读取 `services/stock-scraper/config.yaml` 中的股票列表。
- 定期调用 Stock API 并写入数据库。

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

项目使用 `uv` 管理 Python 工作区，`npm` 管理 TypeScript 服务。

```bash
# 安装 Python 依赖
uv sync

# 安装 TS 依赖
cd services/stock-api && npm install
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
