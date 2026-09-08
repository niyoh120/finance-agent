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

## 验证 OpenBB Provider

```bash
uv run --package openbb-finance python - <<'PY'
from openbb_finance import provider

print(provider.name)
print(provider.fetcher_dict.keys())
PY
```

预期包含：

- `.equity.price.historical`
- `.equity.price.quote`
- `.equity.search`
- `.equity.screener`
- `.index.available`
- `.index.search`
- `.index.price.historical`
- `.index.snapshots`
- `.etf.historical`
- `.etf.search`
- `.economy.calendar`
- `.economy.available_indicators`
- `.economy.indicators`
- `.economy.gdp.nominal`
- `.economy.cpi`
- `.news.company`
- `.news.world`
- `.derivatives.options.unusual`
- `.technical.indicators`

## 使用示例

```python
from openbb import obb

# 股票历史价格
prices = obb.equity.price.historical(
    symbol="600519.XSHG",
    start_date="2026-04-01",
    end_date="2026-04-24",
    provider="finance",
)
print(prices.to_df().head())

# 股票实时报价
quote = obb.equity.price.quote(
    symbol="600519.XSHG",
    provider="finance",
)
print(quote.to_df().head())

# 股票搜索
search = obb.equity.search(
    query="茅台",
    provider="finance",
)
print(search.to_df().head())

# 股票筛选器
screener = obb.equity.screener(
    market="china",
    limit=50,
    price_min=10,
    volume_min=1000000,
    fields='["SYMBOL", "NAME", "PRICE", "VOLUME"]',
    provider="finance",
)
print(screener.to_df().head())
# screener 的 symbol 已归一化为可直接用于 quote/historical 的格式，原始 TradingView 代码保留在 source_symbol。

# 指数列表
indices = obb.index.available(provider="finance")
print(indices.to_df().head())

# 指数搜索
index_search = obb.index.search(
    query="沪深",
    provider="finance",
)
print(index_search.to_df().head())

# 指数历史价格
index_prices = obb.index.price.historical(
    symbol="000001.XSHG",
    start_date="2026-04-01",
    end_date="2026-04-24",
    provider="finance",
)
print(index_prices.to_df().head())

# 指数快照
snapshots = obb.index.snapshots(
    region="cn",
    provider="finance",
)
print(snapshots.to_df().head())

# ETF 历史价格
etf_prices = obb.etf.historical(
    symbol="510300.XSHG",
    start_date="2026-04-01",
    end_date="2026-04-24",
    provider="finance",
)
print(etf_prices.to_df().head())

# ETF 搜索
etf_search = obb.etf.search(
    query="沪深300",
    provider="finance",
)
print(etf_search.to_df().head())

# 财经日历
calendar = obb.economy.calendar(
    start_date="2026-04-01",
    end_date="2026-04-30",
    provider="finance",
)
print(calendar.to_df().head())

# 可用宏观指标
indicators = obb.economy.available_indicators(provider="finance")
print(indicators.to_df().head())

# 宏观指标
macro = obb.economy.indicators(
    symbol="PMI",
    country="china",
    provider="finance",
)
print(macro.to_df().head())

# 名义 GDP
gdp = obb.economy.gdp.nominal(
    country="china",
    provider="finance",
)
print(gdp.to_df().head())

# CPI
cpi = obb.economy.cpi(
    country="china",
    transform="yoy",
    provider="finance",
)
print(cpi.to_df().head())

# 公司新闻
news = obb.news.company(
    symbol="AAPL",
    provider="finance",
)
print(news.to_df().head())

# 全球新闻
world_news = obb.news.world(
    start_date="2026-04-01",
    end_date="2026-04-30",
    limit=50,
    provider="finance",
)
print(world_news.to_df().head())

# 异常期权流
flows = obb.derivatives.options.unusual(
    symbol="AAPL",
    provider="finance",
)
print(flows.to_df().head())

# 技术指标
technical = obb.technical.indicators(
    symbol="600519.XSHG",
    start_date="2026-04-01",
    end_date="2026-04-24",
    indicators=["rsi", "macd", "sma"],
    provider="finance",
)
print(technical.to_df().head())
```

## 期货 Futures

期货 endpoint 通过 CLI 直接驱动 fetcher（未安装 openbb_futures router extension），命令为：

```bash
# 历史行情（无 --expiration = 主连合约）
openbb-agent-cli futures.price.historical --symbol rb.SHFE
openbb-agent-cli futures.price.historical --symbol rb.SHFE --expiration 2026-10
openbb-agent-cli futures.price.historical --symbol GC.COMEX --expiration 2026-12
# 实时报价
openbb-agent-cli futures.price.quote --symbol GC.COMEX
openbb-agent-cli futures.price.quote --symbol AU.SGE
# 合约搜索（品种码 / 用户 symbol / 中文名）
openbb-agent-cli futures.search --query 工业硅
openbb-agent-cli futures.search --query si --is-symbol
# 中金所品种请用中文名搜索（tdx 服务目录不含 CFFEX，akshare 按品种名匹配）
openbb-agent-cli futures.search --query 沪深300
```

### Symbol 规则

用户层 symbol 为 `<品种码>.<交易所短码>`：品种码小写、交易所短码大写，查询时大小写均可（standard model 会归一化为大写）。

| 场景 | symbol | expiration | 说明 |
|---|---|---|---|
| 螺纹钢主连 | `rb.SHFE` | None | 无 expiration = 主连 |
| 螺纹钢 2026-10 合约 | `rb.SHFE` | `2026-10` | 月份合约 |
| 沪深300 主连 | `IF.CFFEX` | None | 中金所仅挂当月/次月/两季月 |
| COMEX 黄金主连 | `GC.COMEX` | None | |
| COMEX 黄金 2612 合约 | `GC.COMEX` | `2026-12` | 国际月份代码为 `GC26Z` |
| 黄金递延（SGE 现货） | `AU.SGE` | — | SGE 无主连，固定递延品种 |

支持交易所：国内 SHFE/DCE/CZCE/CFFEX/GFEX，国际 COMEX/NYMEX/CBOT。国际月份字母月：F/G/H/J/K/M/N/Q/U/V/X/Z 对应 1–12 月。

搜索说明：tdx 按服务目录分页匹配品种码/中文名/用户 symbol（SGE 用户别名如 `AU9999.SGE` 同样可匹配）；搜索采用严格完整性策略：任一目标市场失败、目录不完整或预算耗尽时整体失败并回退，绝不返回部分结果；次连（L7）/加权（L9）/连续（00Y）辅助合约码不返回，仅返回可直接查询的主连与月份合约。CFFEX 目录在服务端不可用（目录能力关闭），CFFEX 搜索返回空并由 fetcher 回退 akshare；行情与 K 线仍请求 cffex 市场。

### 数据源

- 全部交易所以 tdx（tdx-api HTTP 服务）为主源：中金所主连 `<CODE>L0`、其余国内主连 `<CODE>L8`、月份 `<CODE><YYMM>`；国际主连 `<CODE>00W`、月份 `<CODE><YY><字母月>`；SGE 用专用映射 `Au(T+D)`/`Ag(T+D)`/`Au99.99`。
- akshare 新浪兜底（`futures_zh_daily_sina`，`<CODE>0` 主连全历史、`<CODE><YYMM>` 月份合约），未挂牌月份返回 `EMPTY_DATA`；tdx 整体失败时同样走此兜底。
- SGE 现货递延产品与商品期货性质不同：无主连、无月份合约，仅 tdx 提供数据。

## 数据源路由

K 线数据采用单源路由（第一个返回数据的源胜出，失败自动回退到下一个源）：

| 市场 | 周期 | 路由优先级 |
| :--- | :--- | :--- |
| A 股 | 分钟线 | tdx → tickflow → baostock/akshare（baostock/akshare 按入库时间排序） |
| A 股 | 日/周/月线 | tdx → tickflow → baostock/akshare（baostock/akshare 按入库时间排序） |
| 美股/港股 | 日线及以上 | schwab → tdx → tickflow（港股：tdx → tickflow） |
| 美股/港股 | 分钟线 | schwab → tdx（港股分钟线仅 tdx） |
| 指数 | — | cn 同 A 股；us 为 schwab → tdx；其余仅 tdx |
| 期货 | 日线及以上 | tdx → akshare（国际交易所/SGE/分钟线仅 tdx） |

BaoStock 可用性按请求时间范围判断（仅当其排在 akshare 之前时生效）：

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
| 新闻（A 股） | 富途 → AKShare → OpenBB |
| A 股基本面 | BaoStock → AKShare |
| 美股/港股基本面 | OpenBB/Yahoo |
| 中国宏观 | BaoStock → AKShare |
| 全球宏观 | OpenBB |

## TDX 数据源（tdx-api 消费端）

`tdx` 源是 `services/tdx-api` 的 HTTP 消费端：服务持有全部通达信协议复杂度（握手、二进制编解码、多主机切换、QFQ 复权），消费端只发 HTTP 请求，运行依赖不含任何 TDX SDK。

### 启用顺序

1. 部署并启动 `tdx-api`（`mise run tdx-api` 或 Docker），用 `/healthz` 与 `/api/v1/status` 确认进程与协议组就绪。
2. 设置 `TDX_API_BASE_URL`（服务根地址，如 `http://127.0.0.1:8011`，内部自动追加 `/api/v1`）；服务开启 `FA_TDX_API_KEY` 时同时设置一致的 `TDX_API_KEY`。
3. 地址缺失/为空时 TDX 源自动禁用（零成本回退到其余源）；此时港股、国际期货、SGE 等 TDX 独占路由会返回 `EMPTY_DATA`。

### 资源预算

| 项 | 值 | 说明 |
| :--- | :--- | :--- |
| 连接超时 | 5s | 每次 HTTP 请求 |
| 读取超时 | 35s | 覆盖服务端 30s 请求预算；超时即服务端真实超支 |
| 单次 fetch 总预算 | 60s | 覆盖排队、全部分页与跨市场请求，超时抛 `SourceError` |
| K 线分页 | 单页 ≤1000，最多 20 页 | 超页数预算整体失败（不返回截断序列） |
| 搜索分页 | 每市场单页 ≤1000，最多 10 页 | 跨市场并发上限 3 |
| 搜索结果预算 | 单次 ≤10000 条 | 超出整体失败 |

### 历史分页与完整性

- K 线从最新窗口向历史方向翻页（`offset`/`meta.next_offset`）。指定 `start_date` 时翻到覆盖起点或服务明确历史尽头为止，输出按起止日期（含两端）过滤；未指定 `start_date` 时返回最近 700 根（有 `end_date` 时为截止该日的最近 700 根）。
- 服务 `complete=true`（含明确历史尽头）为正常结束；游标停滞/回退、整页无新增、空页但未完结、页数或时间预算耗尽均抛 `SourceError` 触发路由回退，绝不把截断序列当成功返回。
- offset 分页无跨请求快照保证：实时新增 K 线可能移动 offset，重叠边界按时间去重（以较新页为准），去重只能消除重复，无法证明绝对快照一致。

### 搜索（严格完整性）

- 股票搜索覆盖 `cn_sh/cn_sz/hk/hk_gem/us` 五个市场；明确的 A 股完整代码与带 `.HK` 后缀的港股代码走 `/instruments/info` 快路径，其余关键词走 `/instruments/search` 完整分页。
- 期货搜索按 `/instruments` 有界分页后在客户端匹配 code/名称/规范 symbol（覆盖 `AU9999.SGE` 等用户别名）。
- 任一目标市场失败、目录不完整或预算耗尽 → 整个搜索抛 `SourceError` 并取消其余市场，交由路由回退；CFFEX 目录能力在服务端关闭，CFFEX 搜索返回 `[]`（行情/K 线仍可用）。

### 成交量单位（诚实标注）

单位以服务元数据为准，客户端只做已验证换算：A 股报价单位为手（`lot_size=100`）换算为股；A 股/美股 K 线服务返回即为股；**港股 K 线返回原始手数**（相对旧 easy-tdx 客户端的固定 ×100，数值变为原值的 1/100，跨源比较时注意口径）；其余未知单位保留原始值。K 线日线及以上输出交易日（date），分钟线输出服务本地时间（datetime，区间起点）。

### 实服务验收记录（2026-09-09）

对本地运行的 tdx-api（真实上游行情服务器）执行的小规模验收；服务端 live 套件（`mise run tdx-api-test-live`）13/13 通过。消费端实测：

- A 股日线 qfq 跨两页历史：600519 自 2019-01-02 起 1808 根，升序无重复，`start_date` 覆盖即停止翻页。
- 港股 700.HK 日线 700 根（volume 为原始手数，×100 旧倍数已移除）；AAPL 日线正常。
- 期货：rb.SHFE 主连、GC26Z 月合约、IF.CFFEX 主连（L0）与 IF2612 月合约均返回数据；AU.SGE 报价返回名称。
- 搜索：中文“茅台”命中 600519.XSHG；快路径 600519/700.HK 即时返回；EN 片段 AAP 命中 13 条；BRK.B 可搜索；期货目录“螺纹”13 个合约（含 RBL8）、AU9999 别名命中 AU9999.SGE；CFFEX 搜索为空（目录能力关闭，回退 akshare）。
- 时段观察：凌晨非交易时段 CN/US/SGE 报价数值字段为 null（上游 NaN→null 诚实映射，name/code 正常），盘中行为待交易时段复测；报价路由本就 schwab 优先，tdx 报价缺失时自动回退。
- 上游覆盖限制：BRK.B 在 US 目录中存在但上游 K 线命令对其返回空（complete=true），消费端按契约返回 []，路由干净回退；属上游数据缺口，客户端无异常。


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

[sources.futunn]
enabled = true
priority = 100

[sources.sina]
enabled = true
priority = 98

[sources.eastmoney]
enabled = true
priority = 95

[sources.baostock]
enabled = true
priority = 90

[sources.tickflow]
enabled = true
priority = 80
api_key = "${TICKFLOW_API_KEY}"
base_url = "https://api.tickflow.org"

[sources.akshare]
enabled = true
priority = 70

[sources.openbb]
enabled = true
priority = 50

[sources.tdx]
enabled = true
# tdx-api 服务地址（services/tdx-api，默认 http://127.0.0.1:8011）。
# 占位符在环境变量未设置时展开为空，此时该源自动禁用，路由回退其余源。
base_url = "${TDX_API_BASE_URL}"
# 可选：仅当 tdx-api 开启 FA_TDX_API_KEY 鉴权时需一致。
api_key = "${TDX_API_KEY}"

[sources.schwab]
enabled = true
base_url = "${SCHWAB_API_BASE_URL}"
api_key = "${SCHWAB_API_KEY}"
```

配置项：

| 配置 | 用途 |
| :--- | :--- |
| `database.url` | `finance-shared` 读取 PostgreSQL 期权流缓存所需连接串 |
| `sources.<name>.enabled` | 启用或禁用数据源 |
| `sources.<name>.priority` | 覆盖数据源优先级（仅兼容保留，路由顺序由代码决定） |
| `sources.tickflow.api_key` | TickFlow API Key |
| `sources.tickflow.base_url` | TickFlow API 地址（可选，用于覆盖默认地址） |
| `sources.tdx.base_url` | tdx-api 服务根地址；为空时 TDX 源自动禁用 |
| `sources.tdx.api_key` | 与服务端 `FA_TDX_API_KEY` 一致的共享密钥（X-API-Key 头） |
| `sources.schwab.base_url` / `api_key` | schwab-api 服务地址与可选密钥 |

支持的数据源名：

- `tdx` - tdx-api（通达信行情 HTTP 服务，需先部署 `services/tdx-api`）
- `futunn` - 富途
- `sina` - 新浪
- `eastmoney` - 东方财富
- `baostock` - BaoStock
- `tickflow` - TickFlow
- `akshare` - AKShare
- `openbb` - OpenBB 内置数据源
- `schwab` - schwab-api（美股，需先部署 `services/schwab-api`）

敏感信息建议在 TOML 中使用 `${TOKEN}` 形式从环境变量注入，例如：

```toml
[sources.tickflow]
api_key = "${TICKFLOW_API_KEY}"
```

## 开发

```bash
mise run openbb-finance-test    # 消费端 + cli 全套离线测试（含跨包 ASGI 契约用例）
mise run openbb-finance-check   # 上述测试 + ruff check/format --check
mise run tdx-api-check          # tdx-api 服务端离线测试 + ruff（独立 frozen 环境）
mise run tdx-api-test-live      # 连真实行情服务器的小规模冒烟（显式执行）
```

跨包契约测试（`test_tdx_http_contract.py`）在测试内导入 `tdx_api` 并经 ASGITransport 驱动真实服务应用，因此测试任务依赖 workspace 全量安装（`mise run install`）。
