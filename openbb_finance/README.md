# OpenBB Finance Provider

`openbb-finance` 是独立的 OpenBB provider 包，提供 `finance` provider。它依赖仓库内的 `finance-shared` 读取本地 PostgreSQL 缓存中的期权流数据，其余行情、财经日历、新闻、基本面和宏观数据通过可插拔数据源路由与聚合。

## 安装

在仓库根目录安装整个 workspace：

```bash
mise run install
```

也可以只针对本包运行命令：

```bash
uv run --package openbb-finance python -c "from openbb_finance import provider; print(provider.name)"
```

## 验证 OpenBB 注册

OpenBB 平台包仅作为开发/集成验证依赖提供，验证时启用 `dev` extra：

```bash
uv run --package openbb-finance --extra dev python - <<'PY'
from openbb import obb

print(obb.coverage.providers["finance"])
PY
```

预期包含：

- `.equity.price.historical`
- `.equity.price.quote`
- `.equity.search`
- `.index.price.historical`
- `.etf.historical`
- `.economy.calendar`
- `.news.company`
- `.derivatives.options.unusual`

## 使用示例

```python
from openbb import obb

prices = obb.equity.price.historical(
    symbol="600519.XSHG",
    start_date="2026-04-01",
    end_date="2026-04-24",
    provider="finance",
)
print(prices.to_df().head())

quote = obb.equity.price.quote(
    symbol="600519.XSHG",
    provider="finance",
)
print(quote.to_df().head())

search = obb.equity.search(
    query="茅台",
    provider="finance",
)
print(search.to_df().head())

index_prices = obb.index.price.historical(
    symbol="000001.XSHG",
    start_date="2026-04-01",
    end_date="2026-04-24",
    provider="finance",
)
print(index_prices.to_df().head())

etf_prices = obb.etf.historical(
    symbol="510300.XSHG",
    start_date="2026-04-01",
    end_date="2026-04-24",
    provider="finance",
)
print(etf_prices.to_df().head())

calendar = obb.economy.calendar(
    start_date="2026-04-01",
    end_date="2026-04-30",
    provider="finance",
)
print(calendar.to_df().head())

news = obb.news.company(
    symbol="AAPL",
    provider="finance",
)
print(news.to_df().head())

flows = obb.derivatives.options.unusual(
    symbol="AAPL",
    provider="finance",
)
print(flows.to_df().head())
```

## 数据源路由

K 线数据采用单源路由：

| 市场 | 周期 | 路由优先级 |
| :--- | :--- | :--- |
| A 股 | 分钟线 | BaoStock 数据时间范围已入库时使用 BaoStock，其余情况使用 AKShare |
| A 股 | 日/周/月线 | BaoStock 数据时间范围已入库时优先 BaoStock，随后 TickFlow、AKShare |
| 美股/港股 | 日线及以上 | TickFlow，随后 Yahoo Finance |
| 美股/港股 | 分钟线 | Yahoo Finance |

BaoStock 可用性按请求时间范围判断：

- 日 K：交易日 `17:30` 后入库
- 复权因子：交易日 `18:00` 后入库
- 分钟 K：交易日 `20:00` 后入库
- 其它财务报告：第二自然日 `01:30` 后入库
- 周 K：周六 `17:30` 后入库
- 月 K：每月 1 号 `17:30` 后入库

财经日历、新闻、基本面和宏观数据采用多源聚合。聚合按字段级优先级合并：同一数据项的同一字段取优先级最高的数据源，低优先级数据源可补充高优先级数据源缺失的字段。

默认聚合优先级：

| 数据类型 | 优先级 |
| :--- | :--- |
| 财经日历 | 富途 → AKShare → OpenBB |
| 新闻（港股/美股） | 富途 → OpenBB |
| 新闻（A 股） | 富途 → AKShare |
| A 股基本面 | BaoStock → AKShare |
| 美股/港股基本面 | OpenBB/Yahoo |
| 中国宏观 | BaoStock → AKShare |
| 全球宏观 | OpenBB |

## 配置

复制示例配置：

```bash
cp openbb_finance/openbb_finance.toml.example openbb_finance.toml
```

默认会按顺序查找以下配置文件，使用第一个存在的文件：

1. 当前工作目录的 `openbb_finance.toml`
2. 当前工作目录的 `.openbb_finance.toml`
3. `~/.config/openbb_finance/config.toml`

示例：

```toml
[database]
url = "${FA_DATABASE_URL}"

[sources.baostock]
enabled = true
priority = 90

[sources.akshare]
enabled = true
priority = 70

[sources.tickflow]
enabled = true
priority = 80
api_key = "${TICKFLOW_API_KEY}"

[sources.futunn]
enabled = true
priority = 100

[sources.yahoo]
enabled = true
priority = 60

[sources.openbb]
enabled = true
priority = 50
```

配置项：

| 配置 | 用途 |
| :--- | :--- |
| `database.url` | `finance-shared` 读取 PostgreSQL 期权流缓存所需连接串 |
| `sources.<name>.enabled` | 启用或禁用数据源 |
| `sources.<name>.priority` | 覆盖数据源优先级 |
| `sources.tickflow.api_key` | TickFlow API Key |

支持的数据源名：

- `baostock`
- `akshare`
- `tickflow`
- `futunn`
- `yahoo`
- `openbb`

敏感信息建议在 TOML 中使用 `${TOKEN}` 形式从环境变量注入，例如：

```toml
[sources.tickflow]
api_key = "${TICKFLOW_API_KEY}"
```

## 开发

```bash
uv run --package openbb-finance --extra dev pytest openbb_finance/tests -q
uv run --package openbb-finance --extra dev ruff check openbb_finance/src/openbb_finance openbb_finance/tests
uv run --package openbb-finance python -m compileall -q openbb_finance/src/openbb_finance
```
