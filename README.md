# Finance Agent

Python monorepo for finance data ingestion, shared database models, and the OpenBB provider.

## Services

| 服务 | 目录 | 描述 |
| :--- | :--- | :--- |
| macro-scraper | `services/macro-scraper` | 抓取宏观金融数据并写入数据库 |
| options-scraper | `services/options-scraper` | 抓取 Discord `UW Live Options Flow` 消息并写入数据库 |
| options-dashboard | `services/options-dashboard` | 内网 Streamlit 期权交易辅助面板（期权链、策略构建器、财报 IV Crush） |
| migrate | `migrate/Dockerfile` | 运行 Alembic 数据库迁移 |
| shared | `shared` | 共享数据库模型、连接和日志工具 |
| openbb-finance | `openbb_finance` | OpenBB provider |
| openbb-agent-cli | `openbb-agent-cli` | 面向 agent 的 JSON CLI |

## 环境

- Python 3.12.12，推荐用 `mise` 管理
- PostgreSQL
- `uv`

复制环境变量模板：

```bash
cp .env.example .env
```

## 常用命令

先查看当前任务：

```bash
mise tasks ls
```

安装依赖：

```bash
mise run install
```

运行迁移：

```bash
mise run db-upgrade
```

启动服务：

```bash
mise run macro-scraper
mise run options-scraper
mise run openbb-agent-cli
mise run options-dashboard
```

`options-dashboard` 默认监听 `http://localhost:8501`，仅适用于内网。生产部署建议置于反向代理（Nginx/Caddy/Authelia）之后，由代理统一负责 TLS 与访问认证；容器本身不实现登录。所需环境变量：

- `CV_API_KEY`（ConvexValue Research Plan，覆盖美股期权 + FMP 全量财务数据）

镜像构建与发布：

```bash
mise run docker-build-options-dashboard
mise run docker-push-options-dashboard
mise run docker-build-push-options-dashboard
```

发布镜像相关任务：

```bash
mise run docker-build-all
mise run docker-push-all
mise run docker-build-push-all
```

当前镜像：

- `finance-migrate`
- `finance-macro-scraper`
- `finance-options-scraper`

## OpenBB Finance Provider

`openbb_finance/` 是独立的 OpenBB provider 包，注册名为 `finance` 的 provider，并依赖 `finance-shared` 读取本地 PostgreSQL 缓存中的期权流数据。

使用说明、数据源路由、环境变量和开发命令见 [`openbb_finance/README.md`](openbb_finance/README.md)。

## 目录结构

```text
├── alembic/               # 数据库迁移
├── migrate/               # 迁移镜像
├── openbb-agent-cli/      # JSON CLI
├── openbb_finance/        # OpenBB provider
├── services/
│   ├── macro-scraper/     # 宏观抓取
│   ├── options-dashboard/ # 期权面板
│   └── options-scraper/   # Discord 期权流抓取
├── shared/                # 共享 Python 模块
├── mise.toml              # 本地任务
└── pyproject.toml         # uv workspace
```
