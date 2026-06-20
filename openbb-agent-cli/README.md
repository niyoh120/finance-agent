# OpenBB Agent CLI

`openbb-agent-cli` 是为 AI Agent 设计的 OpenBB finance provider 命令行工具，输出纯 JSON 格式，便于程序解析。

## 安装

在仓库根目录安装整个 workspace：

```bash
mise run install
```

## 使用

所有命令输出均为 JSON 数组或错误对象。成功时返回数据数组，失败时返回包含 `error` 和 `code` 字段的 JSON 对象。

### 股票

```bash
# 历史价格
openbb-agent-cli equity.price.historical --symbol 600519.XSHG --start-date 2026-04-01 --end-date 2026-04-24

# 实时报价
openbb-agent-cli equity.price.quote --symbol 600519.XSHG

# 搜索
openbb-agent-cli equity.search --query "茅台"

# 筛选器（简单过滤）
openbb-agent-cli equity.screener --market china --price-min 10 --volume-min 1000000 --limit 50

# 筛选器（高级过滤）
openbb-agent-cli equity.screener --market america --filters '{"MACD_LEVEL_12_26": {"min": 0}, "YEAR_BETA_1": {"max": 1.5}}'

# 筛选器（指定返回字段，fields 只控制输出，仍需真实过滤条件）
openbb-agent-cli equity.screener --market america --change-percent-min 5 --fields '["SYMBOL", "NAME", "PRICE", "MACD_LEVEL_12_26"]'

# screener 返回的 symbol 已归一化为股票查询可直接使用的格式；
# 如 TradingView 原始值 NASDAQ:AAPL 会返回 symbol=AAPL，并保留 source_symbol=NASDAQ:AAPL。
```

### 指数

```bash
# 可用指数列表
openbb-agent-cli index.available

# 指数搜索
openbb-agent-cli index.search --query "沪深"

# 历史价格
openbb-agent-cli index.price.historical --symbol 000001.XSHG --start-date 2026-04-01 --end-date 2026-04-24

# 指数快照
openbb-agent-cli index.snapshots --region cn
openbb-agent-cli index.snapshots --region us --symbol SPX --symbol DJI
```

### ETF

```bash
# 历史价格
openbb-agent-cli etf.historical --symbol 510300.XSHG --start-date 2026-04-01 --end-date 2026-04-24

# ETF 搜索
openbb-agent-cli etf.search --query "沪深300"
```

### 财经日历

```bash
openbb-agent-cli economy.calendar --start-date 2026-04-01 --end-date 2026-04-30
```

### 宏观经济数据

```bash
# 可用指标
openbb-agent-cli economy.available-indicators

# 经济指标
openbb-agent-cli economy.indicators --symbol GDP_YOY --country china
openbb-agent-cli economy.indicators --symbol CPI_YOY --country china
openbb-agent-cli economy.indicators --symbol PPI --country china
openbb-agent-cli economy.indicators --symbol PMI --country china

# GDP 名义值
openbb-agent-cli economy.gdp.nominal --country china

# CPI
openbb-agent-cli economy.cpi --country china --transform yoy
openbb-agent-cli economy.cpi --country china --frequency annual
```

### 技术指标

```bash
# 默认计算 RSI、MACD、SMA、EMA、BBands、ATR、Stoch、VWAP
openbb-agent-cli technical.indicators --symbol 600519.XSHG --start-date 2026-04-01 --limit 30

# 指定指标与参数
openbb-agent-cli technical.indicators \
  --symbol 600519.XSHG \
  --start-date 2026-04-01 \
  --indicators rsi --indicators macd \
  --rsi-length 7 --macd-fast 5 --macd-slow 15
```

### 新闻

```bash
# 公司新闻
openbb-agent-cli news.company --symbol AAPL --start-date 2026-04-01 --end-date 2026-04-30 --limit 50

# 全球新闻
openbb-agent-cli news.world --start-date 2026-04-01 --end-date 2026-04-30 --limit 50
```

### 异常期权流

```bash
# 查询特定股票
openbb-agent-cli derivatives.options.unusual --symbol AAPL --start-date 2026-04-01 --end-date 2026-04-30

# 筛选条件
openbb-agent-cli derivatives.options.unusual \
  --option-type C \
  --side Ask \
  --min-premium 50000 \
  --min-vol-oi 2.0 \
  --limit 100
```

### 批量查询

```bash
# 使用内置模板
openbb-agent-cli batch --template equity-overview --symbol AAPL --start-date 2026-04-01 --end-date 2026-04-30
openbb-agent-cli batch --template market-overview --region cn --limit 20
openbb-agent-cli batch --template macro-overview --country china --start-date 2026-01-01
openbb-agent-cli batch --template index-detail --symbol 000001.XSHG --region cn

# 自定义查询数组
openbb-agent-cli batch --queries '[
  {"name":"quote","command":"equity.price.quote","params":{"symbol":"AAPL"}},
  {"name":"news","command":"news.company","params":{"symbol":"AAPL","limit":10}}
]'
```

## 命令参考

| 命令 | 必需参数 | 可选参数 |
| :--- | :--- | :--- |
| `equity.price.historical` | `symbol` | `start-date`, `end-date`, `interval`, `adjusted` |
| `equity.price.quote` | `symbol` | - |
| `equity.search` | `query` | `is-symbol` |
| `equity.screener` | - | `market`, `limit`, `price-min`, `price-max`, `change-percent-min`, `change-percent-max`, `volume-min`, `volume-max`, `market-cap-min`, `market-cap-max`, `rsi-min`, `rsi-max`, `sector`, `filters`, `fields` |
| `index.available` | - | - |
| `index.search` | `query` | `is-symbol` |
| `index.price.historical` | `symbol` | `start-date`, `end-date` |
| `index.snapshots` | - | `region` (cn/us/hk), `symbol` |
| `etf.historical` | `symbol` | `start-date`, `end-date` |
| `etf.search` | `query` | - |
| `economy.calendar` | - | `start-date`, `end-date` |
| `economy.available-indicators` | - | - |
| `economy.indicators` | `symbol` | `country`, `frequency`, `start-date`, `end-date` |
| `economy.gdp.nominal` | - | `country`, `start-date`, `end-date` |
| `economy.cpi` | - | `country`, `transform`, `frequency`, `harmonized`, `start-date`, `end-date` |
| `technical.indicators` | `symbol` | `start-date`, `end-date`, `interval`, `adjusted`, `indicators`, `rsi-length`, `macd-fast`, `macd-slow`, `macd-signal`, `sma-lengths`, `ema-lengths`, `bbands-length`, `bbands-std`, `atr-length`, `stoch-k`, `stoch-d`, `limit` |
| `news.company` | `symbol` | `start-date`, `end-date`, `limit` |
| `news.world` | - | `start-date`, `end-date`, `limit` |
| `derivatives.options.unusual` | - | `symbol`, `start-date`, `end-date`, `side`, `option-type`, `min-premium`, `min-vol-oi`, `limit` |
| `batch` | `queries` 或 `template` | `symbol`, `region`, `country`, `start-date`, `end-date`, `limit`, `news-limit`, `options-limit`, `max-workers` |

## 批量模板

| 模板 | 用途 | 主要参数 |
| :--- | :--- | :--- |
| `equity-overview` | 个股概览：报价、历史价格、公司新闻、期权异动 | `symbol`, `start-date`, `end-date`, `news-limit`, `options-limit` |
| `market-overview` | 市场概览：指数快照、股票筛选、全球新闻 | `region`, `limit`, `start-date`, `end-date`, `news-limit` |
| `macro-overview` | 宏观概览：GDP、CPI、PMI、财经日历 | `country`, `start-date`, `end-date` |
| `index-detail` | 指数详情：快照和历史价格 | `symbol`, `region`, `start-date`, `end-date` |

## 错误处理

失败时返回 JSON 对象：

```json
{"error": "error message", "code": "ERROR_CODE"}
```

常见错误码：

- `EMPTY_DATA` - 无数据返回
- `CLI_ERROR` - 命令行参数错误
- `INTERRUPTED` - 用户中断
- 其他异常类名大写形式

## 开发

```bash
uv run --package openbb-agent-cli pytest openbb-agent-cli/tests -q
uv run --package openbb-agent-cli python -m compileall -q openbb-agent-cli/src/openbb_agent_cli
```
