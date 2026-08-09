---
name: openbb-agent-cli
description: 使用 openbb-agent-cli 获取金融数据。支持股票历史价格、行情报价、搜索、筛选（支持3500+字段的高级过滤和自定义返回字段）、指数、ETF、期货（历史K线/报价/合约搜索，含主连与月份合约）、经济日历、宏观经济数据、技术指标、新闻、期权链/筛选/历史K线/自由SQL聚合、财报三表/财务比率/分析师预测/内部人交易/参议院交易/SEC文件、ETF持仓与行业权重、批量查询。当用户需要查询股票价格、筛选股票、获取市场数据（含期货行情）、查看宏观数据、计算技术指标、查看期权数据、获取财报/分析师预测/内部人交易、一次聚合多个金融查询时使用此 skill。
---

# OpenBB Agent CLI

Agent 友好的金融数据 CLI，所有输出均为 JSON 格式。

## 安装与运行

```bash
# 通过 mise 运行
mise run openbb-agent-cli -- <command> [options]

# 或直接运行
openbb-agent-cli <command> [options]
```

## 命令概览

| 命令 | 说明 |
|------|------|
| `equity.price.historical` | 股票历史价格 |
| `equity.price.quote` | 股票行情报价 |
| `equity.search` | 股票搜索 |
| `equity.screener` | 股票筛选器 |
| `equity.screener.fields` | 筛选字段发现（查询可用 StockField 字段名） |
| `index.available` | 可用指数列表 |
| `index.search` | 指数搜索 |
| `index.price.historical` | 指数历史价格 |
| `index.snapshots` | 指数快照 |
| `etf.historical` | ETF 历史价格 |
| `etf.search` | ETF 搜索 |
| `etf.holdings` `CV` | ETF 持仓明细（本地排序+截断） |
| `etf.sectors` `CV` | ETF 行业权重 |
| `futures.price.historical` | 期货历史价格（主连/月份合约） |
| `futures.price.quote` | 期货行情报价 |
| `futures.search` | 期货合约搜索 |
| `economy.calendar` | 经济日历 |
| `economy.available-indicators` | 可用宏观指标 |
| `economy.indicators` | 宏观经济指标 |
| `economy.gdp.nominal` | 名义 GDP |
| `economy.cpi` | CPI |
| `technical.indicators` | 技术指标 |
| `news.company` | 公司新闻 |
| `news.world` | 全球新闻 |
| `derivatives.options.chain` `CV` | 期权链（含 Greeks/IV/OI，本地过滤+排序） |
| `derivatives.options.screener` `CV` | 期权跨标的筛选（服务端过滤） |
| `derivatives.options.historical` `CV` | 期权合约历史 K 线 |
| `derivatives.options.daily` `CV` | 期权单日 OHLCV |
| `derivatives.options.query` `CV` | 期权自由 SQL 聚合查询（GEX/PCR/Max Pain） |
| `derivatives.options.unusual` | 期权异动（本地数据库） |
| `stocks.fundamental.income` `CV` | 利润表 |
| `stocks.fundamental.balance` `CV` | 资产负债表 |
| `stocks.fundamental.cash` `CV` | 现金流量表 |
| `stocks.fundamental.ratios` `CV` | 财务比率（PE/PB/ROE 等 ~60 个） |
| `stocks.estimates` `CV` | 分析师预测 |
| `stocks.insider_trading` `CV` | 内部人交易 |
| `government.trades` `CV` | 参议院交易披露 |
| `stocks.filings` `CV` | SEC 8-K 文件 |
| `batch` | 批量查询和内置模板 |

---

## equity.price.historical

获取股票历史价格数据。

```bash
openbb-agent-cli equity.price.historical SYMBOL \
  [--start-date YYYY-MM-DD] \
  [--end-date YYYY-MM-DD] \
  [--interval INTERVAL] \
  [--adjusted] \
  [--limit N]
```

**参数**:
- `SYMBOL`: 股票代码（必需）。该必需参数支持位置参数与 `--symbol SYMBOL` 两种写法。
- `--start-date`: 开始日期 (YYYY-MM-DD)
- `--end-date`: 结束日期 (YYYY-MM-DD)
- `--interval`: 时间间隔 (1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w, 1M)，默认 1d
- `--adjusted`: 是否复权
- `--limit`: 只保留最近的 N 条记录（在 CLI 侧裁剪，不下传到底层接口）

**示例**:
```bash
# 获取 AAPL 最近日线数据
openbb-agent-cli equity.price.historical AAPL

# 获取 AAPL 最近 20 条日线数据
openbb-agent-cli equity.price.historical AAPL --limit 20

# 获取指定日期范围的 1 小时 K 线
openbb-agent-cli equity.price.historical AAPL \
  --start-date 2024-01-01 \
  --end-date 2024-01-31 \
  --interval 1h
```

---

## equity.price.quote

获取股票实时行情报价。

```bash
openbb-agent-cli equity.price.quote SYMBOL
```

**示例**:
```bash
openbb-agent-cli equity.price.quote AAPL
```

---

## equity.search

搜索股票。

```bash
openbb-agent-cli equity.search QUERY [--is-symbol]
```

**参数**:
- `QUERY`: 搜索关键词（股票名称或代码）
- `--is-symbol`: 将 QUERY 视为股票代码进行精确匹配

**示例**:
```bash
# 按名称搜索
openbb-agent-cli equity.search Apple

# 按代码精确匹配
openbb-agent-cli equity.search AAPL --is-symbol
```

---

## equity.screener

股票筛选器，支持简单过滤和高级过滤。

> **未提供真实过滤条件时返回结构化帮助（JSON），不返回数据。** `--market` 只限定市场范围，`--limit`/`--fields` 只控制输出，不能单独触发查询；必须搭配价格/成交量/涨跌幅/RSI/行业/`--filters` 等真实过滤条件。筛选结果中的 `symbol` 已归一化为股票查询可直接使用的格式（例如 `NASDAQ:AAPL` → `AAPL`、`HKEX:700` → `0700.HK`、`SSE:600519` → `600519.XSHG`），原始 TradingView 代码保留在 `source_symbol`。需要发现可用过滤字段名时，先运行 `equity.screener.fields --search <关键词>`；需穷举全部字段用 `equity.screener.fields --all`。

### 简单过滤器

```bash
openbb-agent-cli equity.screener \
  [--market MARKET] \
  [--limit N] \
  [--price-min X] [--price-max X] \
  [--volume-min X] [--volume-max X] \
  [--market-cap-min X] [--market-cap-max X] \
  [--change-percent-min X] [--change-percent-max X] \
  [--rsi-min X] [--rsi-max X] \
  [--sector SECTOR]... \
  [--fields JSON_ARRAY]
```

**参数**:
- `--market`: 市场区域
  - `america`: 美股
  - `hongkong`: 港股
  - `china`: A股
  - `global`: 全球
- `--limit`: 返回数量，默认 150
- `--price-min/max`: 价格区间
- `--volume-min/max`: 成交量区间
- `--market-cap-min/max`: 市值区间
- `--change-percent-min/max`: 涨跌幅区间（百分比）
- `--rsi-min/max`: RSI(14) 区间 (0-100)
- `--sector`: 行业筛选，可多次指定
- `--fields`: 返回字段 JSON 数组，例如 `["SYMBOL","NAME","PRICE"]`

**示例**:
```bash
# 筛选美股中涨幅超过 5% 的股票
openbb-agent-cli equity.screener \
  --market america \
  --change-percent-min 5

# 筛选科技行业市值超过 1000 亿的股票
openbb-agent-cli equity.screener \
  --sector Technology \
  --market-cap-min 100000000000

# 筛选 RSI 超卖区域（RSI < 30）的股票
openbb-agent-cli equity.screener \
  --rsi-max 30

# 多行业筛选
openbb-agent-cli equity.screener \
  --sector Technology \
  --sector Healthcare
```

### 高级过滤器

使用 `--filters` 参数进行任意 StockField 字段过滤：

```bash
openbb-agent-cli equity.screener \
  --filters '{"FIELD_NAME": {"min": x, "max": y, "in": [...]}}'
```

**过滤条件格式**:
```json
{
  "FIELD_NAME": {
    "min": 最小值,
    "max": 最大值,
    "in": ["值1", "值2", ...]
  }
}
```

**支持 3500+ StockField 字段**，常用字段见 [references/fields.md](references/fields.md)。

**示例**:
```bash
# MACD 大于 0 且 Beta 小于 1.5
openbb-agent-cli equity.screener \
  --filters '{"MACD_LEVEL_12_26": {"min": 0}, "YEAR_BETA_1": {"max": 1.5}}'

# 市盈率在 10-25 之间
openbb-agent-cli equity.screener \
  --filters '{"PE_RATIO_TTM": {"min": 10, "max": 25}}'

# 股息率超过 3%
openbb-agent-cli equity.screener \
  --filters '{"DIVIDEND_YIELD": {"min": 3}}'

# 组合简单过滤和高级过滤
openbb-agent-cli equity.screener \
  --market america \
  --volume-min 1000000 \
  --filters '{"PE_RATIO_TTM": {"max": 20}, "DEBT_TO_EQUITY": {"max": 1}}'

# 指定返回字段（fields 只控制输出，仍需真实过滤条件）
openbb-agent-cli equity.screener \
  --market america \
  --change-percent-min 5 \
  --fields '["SYMBOL", "NAME", "PRICE", "MACD_LEVEL_12_26"]'
```

### 字段发现

**字段名未知时，先用 `equity.screener.fields` 发现可用字段名，再拼 `--filters`/`--fields`：**

```bash
# 模糊搜索字段名/标签（子串匹配）
openbb-agent-cli equity.screener.fields --search dividend

# 返回全部字段（约 3500+，穷尽性场景）
openbb-agent-cli equity.screener.fields --all

# 无参返回结构化帮助（含搜索提示目录与未归类字段说明）
openbb-agent-cli equity.screener.fields
```

无参帮助内置搜索提示目录（覆盖约 83% 常用字段，如均线/RSI/MACD/蜡烛形态/估值/股息等），
以及未归类字段说明（平台元数据/ETF 结构/IPO 债券/缩写财务项四类成因举例）。日常用 `--search`，
需穷举全部字段用 `--all`。常用字段速查另见 [references/fields.md](references/fields.md)。

也可在 Python 中查找特定字段：

```python
from tvscreener import StockField

# 搜索包含 "rsi" 的字段
rsi_fields = StockField.search("rsi")
for f in rsi_fields:
    print(f.name, f.label)
```

---

## equity.screener.fields

发现 `equity.screener` 可用的 `StockField` 过滤字段名。三种互斥模式：

```bash
openbb-agent-cli equity.screener.fields [--search 关键词] [--all]
```

**模式**:
- 无参：返回结构化帮助（含搜索提示目录与未归类字段说明）
- `--search 关键词`：模糊匹配字段 name 与 label（子串匹配，可能有少量噪音，建议加字段类型词缩小范围）
- `--all`：返回全部字段（约 3500+，唯一保证完整覆盖的入口）

`--search` 与 `--all` 互斥，同时传报错。`--search` 空字符串报错。

**输出格式**: `[{"name": "字段枚举名", "label": "字段显示名"}, ...]`

**示例**:
```bash
# 搜索 RSI 相关字段
openbb-agent-cli equity.screener.fields --search RSI
# [{"name":"RELATIVE_STRENGTH_INDEX_14","label":"RSI (14)"}, ...]

# 穷举全部字段
openbb-agent-cli equity.screener.fields --all

# 查看帮助与搜索提示目录
openbb-agent-cli equity.screener.fields
```

---

## index.available

获取可用指数列表。

```bash
openbb-agent-cli index.available
```

---

## index.search

搜索指数。

```bash
openbb-agent-cli index.search QUERY [--is-symbol]
```

**示例**:
```bash
openbb-agent-cli index.search "S&P"
```

---

## index.price.historical

获取指数历史价格。

```bash
openbb-agent-cli index.price.historical SYMBOL \
  [--start-date YYYY-MM-DD] \
  [--end-date YYYY-MM-DD] \
  [--limit N]
```

**参数**:
- `SYMBOL`: 指数代码（必需）。该必需参数支持位置参数与 `--symbol SYMBOL` 两种写法。
- `--start-date`: 开始日期 (YYYY-MM-DD)
- `--end-date`: 结束日期 (YYYY-MM-DD)
- `--limit`: 只保留最近的 N 条记录（在 CLI 侧裁剪，不下传到底层接口）

**示例**:
```bash
openbb-agent-cli index.price.historical SPX \
  --start-date 2024-01-01 \
  --end-date 2024-12-31

# 只取最近 10 条结果
openbb-agent-cli index.price.historical SPX --limit 10
```

---

## index.snapshots

获取指数快照数据。

```bash
openbb-agent-cli index.snapshots [--region REGION] [--symbol SYMBOL]...
```

**参数**:
- `--region`: 市场区域
  - `cn`: 中国
  - `us`: 美国
  - `hk`: 香港
- `--symbol`: 指定指数代码，可多次指定

**示例**:
```bash
# 获取中国主要指数快照
openbb-agent-cli index.snapshots --region cn

# 获取指定指数快照
openbb-agent-cli index.snapshots --symbol SPX --symbol DJI
```

---

## etf.historical

获取 ETF 历史价格。

```bash
openbb-agent-cli etf.historical SYMBOL \
  [--start-date YYYY-MM-DD] \
  [--end-date YYYY-MM-DD] \
  [--limit N]
```

**参数**:
- `SYMBOL`: ETF 代码（必需）。该必需参数支持位置参数与 `--symbol SYMBOL` 两种写法。
- `--start-date`: 开始日期 (YYYY-MM-DD)
- `--end-date`: 结束日期 (YYYY-MM-DD)
- `--limit`: 只保留最近的 N 条记录（在 CLI 侧裁剪，不下传到底层接口）

**示例**:
```bash
openbb-agent-cli etf.historical SPY

# 只取最近 5 条结果
openbb-agent-cli etf.historical SPY --limit 5
```

---

## etf.search

搜索 ETF。

```bash
openbb-agent-cli etf.search QUERY
```

**示例**:
```bash
openbb-agent-cli etf.search "technology"
```

---

## futures.price.historical

获取期货历史价格。**无 `--expiration` 表示主连合约；`--expiration YYYY-MM` 表示指定月份合约。**

```bash
openbb-agent-cli futures.price.historical SYMBOL \
  [--expiration YYYY-MM] \
  [--start-date YYYY-MM-DD] \
  [--end-date YYYY-MM-DD] \
  [--interval INTERVAL] \
  [--adjusted] \
  [--limit N]
```

**参数**:
- `SYMBOL`: 期货 symbol（必需），格式 `<品种码>.<交易所短码>`，如 `rb.SHFE`、`IF.CFFEX`、`GC.COMEX`、`AU.SGE`。支持位置参数与 `--symbol SYMBOL` 两种写法。
- `--expiration`: 月份合约到期日 (YYYY-MM)，如 `2026-10`；不传即主连
- `--start-date` / `--end-date`: 日期范围 (YYYY-MM-DD)
- `--interval`: 时间间隔，默认 `1d`
- `--limit`: 只保留最近的 N 条记录（CLI 侧裁剪）

**支持交易所与 symbol 规则**:

| 交易所 | 短码 | 示例 | 说明 |
|---|---|---|---|
| 上期所 | `SHFE` | `rb.SHFE` 螺纹钢 / `au.SHFE` 沪金 | 主连/月份 |
| 大商所 | `DCE` | `M.DCE` 豆粕 | 主连/月份 |
| 郑商所 | `CZCE` | `SR.CZCE` 白糖 | 主连/月份 |
| 中金所 | `CFFEX` | `IF.CFFEX` 沪深300股指 | 主连/月份（仅挂当月/次月/两季月） |
| 广期所 | `GFEX` | `si.GFEX` 工业硅 / `lc.GFEX` 碳酸锂 | 主连/月份 |
| 纽约COMEX | `COMEX` | `GC.COMEX` 黄金 | 主连/月份（月份用字母月代码） |
| 纽约NYMEX | `NYMEX` | `CL.NYMEX` 原油 | 主连/月份 |
| 芝加哥CBOT | `CBOT` | `ZL.CBOT` 豆油 | 主连/月份 |
| 上海黄金 | `SGE` | `AU.SGE` 黄金递延 / `AG.SGE` 白银递延 | **现货递延**，无主连无月份，固定品种 |

国际交易所月份合约底层用 `<YY><字母月>`（F/G/H/J/K/M/N/Q/U/V/X/Z 对应 1-12 月，如 2026-12 → `GC26Z`），用户层只需传 `--expiration 2026-12`。

**示例**:
```bash
# 螺纹钢主连日线
openbb-agent-cli futures.price.historical rb.SHFE
# 螺纹钢 2026-10 合约
openbb-agent-cli futures.price.historical rb.SHFE --expiration 2026-10
# COMEX 黄金 2026-12 合约
openbb-agent-cli futures.price.historical GC.COMEX --expiration 2026-12
# 沪深300 股指主连最近 10 条
openbb-agent-cli futures.price.historical IF.CFFEX --limit 10
```

未挂牌月份（如 CFFEX 股指期货不存在的月份）返回 `EMPTY_DATA`。

---

## futures.price.quote

获取期货实时行情报价。**无 `--expiration` 表示主连合约。**

```bash
openbb-agent-cli futures.price.quote SYMBOL [--expiration YYYY-MM]
```

**参数**:
- `SYMBOL`: 期货 symbol（必需），格式同上，如 `rb.SHFE`、`GC.COMEX`、`AU.SGE`
- `--expiration`: 月份合约到期日 (YYYY-MM)，不传即主连

**示例**:
```bash
# COMEX 黄金主连报价
openbb-agent-cli futures.price.quote GC.COMEX
# 上海黄金递延报价
openbb-agent-cli futures.price.quote AU.SGE
```

---

## futures.search

搜索期货合约。支持品种码、用户 symbol、中文品种名三种查询方式。

```bash
openbb-agent-cli futures.search QUERY [--is-symbol]
```

**参数**:
- `QUERY`: 搜索关键词
  - 中文品种名（默认模式）：`工业硅`、`沪深300`、`黄金`
  - 品种码（`--is-symbol`）：`si`、`si.GFEX`、`GC`
- `--is-symbol`: 将 QUERY 视为品种码进行匹配（默认按中文名匹配）

**注意**:
- 中金所（CFFEX）品种请用中文名搜索（如 `沪深300`），tdx 合约枚举不覆盖 CFFEX。
- 搜索结果含 `expiration`（月份合约）与 `code`（数据源原生代码），可用 `futures.price.historical --symbol <结果.symbol> --expiration <结果.expiration>` 直接查询；`expiration=null` 即主连。
- 次连（L7）/加权（L9）/连续（00Y）辅助合约码不返回，仅返回可直接查询的主连与月份合约。

**示例**:
```bash
# 中文名搜索广期所工业硅合约
openbb-agent-cli futures.search 工业硅
# 品种码搜索
openbb-agent-cli futures.search si --is-symbol
# 中金所中文名搜索
openbb-agent-cli futures.search 沪深300
```

---

## economy.calendar

获取经济日历事件。

```bash
openbb-agent-cli economy.calendar \
  [--start-date YYYY-MM-DD] \
  [--end-date YYYY-MM-DD]
```

**示例**:
```bash
openbb-agent-cli economy.calendar \
  --start-date 2024-01-01 \
  --end-date 2024-01-31
```

---

## economy.available-indicators

获取可用宏观经济指标列表。

```bash
openbb-agent-cli economy.available-indicators
```

---

## economy.indicators

获取宏观经济指标数据。

```bash
openbb-agent-cli economy.indicators SYMBOL \
  [--country COUNTRY] \
  [--frequency FREQUENCY] \
  [--start-date YYYY-MM-DD] \
  [--end-date YYYY-MM-DD]
```

**参数**:
- `SYMBOL`: 指标代码，例如 `GDP_YOY`、`CPI_YOY`、`PPI`、`PMI`
- `--country`: 国家或地区，默认 `china`
- `--frequency`: 频率

**示例**:
```bash
openbb-agent-cli economy.indicators GDP_YOY --country china
openbb-agent-cli economy.indicators PMI --country china --start-date 2024-01-01
```

---

## economy.gdp.nominal

获取名义 GDP 数据。

```bash
openbb-agent-cli economy.gdp.nominal \
  [--country COUNTRY] \
  [--start-date YYYY-MM-DD] \
  [--end-date YYYY-MM-DD]
```

**示例**:
```bash
openbb-agent-cli economy.gdp.nominal --country china
```

---

## economy.cpi

获取 CPI 数据。

```bash
openbb-agent-cli economy.cpi \
  [--country COUNTRY] \
  [--transform index|yoy|period] \
  [--frequency annual|quarter|monthly] \
  [--harmonized] \
  [--start-date YYYY-MM-DD] \
  [--end-date YYYY-MM-DD]
```

**示例**:
```bash
openbb-agent-cli economy.cpi --country china --transform yoy
openbb-agent-cli economy.cpi --country china --frequency annual
```

---

## technical.indicators

基于历史价格计算技术指标。默认计算 RSI、MACD、SMA、EMA、BBands、ATR、Stoch、VWAP。

```bash
openbb-agent-cli technical.indicators SYMBOL \
  [--start-date YYYY-MM-DD] \
  [--end-date YYYY-MM-DD] \
  [--interval INTERVAL] \
  [--adjusted] \
  [--indicators rsi|macd|sma|ema|bbands|atr|stoch|vwap]... \
  [--rsi-length N] \
  [--macd-fast N] \
  [--macd-slow N] \
  [--macd-signal N] \
  [--sma-lengths N]... \
  [--ema-lengths N]... \
  [--bbands-length N] \
  [--bbands-std X] \
  [--atr-length N] \
  [--stoch-k N] \
  [--stoch-d N] \
  [--limit N]
```

**参数**:
- `SYMBOL`: 股票代码（必需）。该必需参数支持位置参数与 `--symbol SYMBOL` 两种写法。
- `--start-date` / `--end-date`: 日期范围
- `--interval`: 时间间隔，默认 `1d`
- `--adjusted`: 是否复权，默认 false
- `--indicators`: 指标列表，可多次指定；默认 `rsi macd sma ema bbands atr stoch vwap`
- `--rsi-length`: RSI 周期，默认 14
- `--macd-fast` / `--macd-slow` / `--macd-signal`: MACD 参数，默认 12/26/9
- `--sma-lengths`: SMA 周期，可多次指定；默认 20、50
- `--ema-lengths`: EMA 周期，可多次指定；默认 20
- `--bbands-length` / `--bbands-std`: 布林带参数，默认 20/2.0
- `--atr-length`: ATR 周期，默认 14
- `--stoch-k` / `--stoch-d`: Stoch 参数，默认 14/3
- `--limit`: 只保留最近的 N 条记录（在 CLI 侧裁剪）

**示例**:
```bash
# 默认计算全部内置指标
openbb-agent-cli technical.indicators AAPL --start-date 2024-01-01 --limit 30

# 指定指标与参数
openbb-agent-cli technical.indicators AAPL \
  --start-date 2024-01-01 \
  --indicators rsi \
  --indicators macd \
  --rsi-length 7 \
  --macd-fast 5 \
  --macd-slow 15
```

---

## news.company

获取公司新闻。

```bash
openbb-agent-cli news.company SYMBOL \
  [--start-date YYYY-MM-DD] \
  [--end-date YYYY-MM-DD] \
  [--limit N]
```

**参数**:
- `SYMBOL`: 股票代码（必需）
- `--limit`: 返回数量，默认 100

**示例**:
```bash
openbb-agent-cli news.company AAPL --limit 20
```

---

## news.world

获取全球新闻。

```bash
openbb-agent-cli news.world \
  [--start-date YYYY-MM-DD] \
  [--end-date YYYY-MM-DD] \
  [--limit N]
```

**示例**:
```bash
openbb-agent-cli news.world --limit 50
```

---

## derivatives.options.chain `CV`

单标的完整期权链，含 Greeks/IV/OI/bid-ask/day stats/break_even/vwap。服务端返回全合约（SPY ~13000），客户端过滤+排序+截断。返回 `{results, _meta}`，`_meta.total` 为合约总数。

```bash
openbb-agent-cli derivatives.options.chain SYMBOL \
  [--expiration YYYY-MM-DD] \
  [--option-type call|put] \
  [--min-dte N] [--max-dte N] \
  [--sort-by FIELD] [--sort-dir asc|desc] \
  [--limit N]
```

**参数**:
- `SYMBOL`: 标的代码（必需，如 SPY/AAPL/I:SPX/I:VIX）
- `--expiration`: 单到期日过滤（YYYY-MM-DD，本地过滤）
- `--option-type`: `call` / `put`（本地过滤）
- `--min-dte` / `--max-dte`: DTE 区间（本地过滤）
- `--sort-by`: `expiration`|`strike`|`open_interest`|`volume`|`implied_volatility`|`delta`|`bid`|`ask`|`vwap`，默认 `open_interest`
- `--sort-dir`: `asc` / `desc`，默认 `desc`
- `--limit`: 返回条数，默认 50；传 `0` 表示返回全部过滤后结果

**示例**:
```bash
# 默认：按 OI 降序取前 50
openbb-agent-cli derivatives.options.chain SPY
# 单到期日（SPY 2026-07-17 共 ~500 合约）
openbb-agent-cli derivatives.options.chain SPY --expiration 2026-07-17
# 近月看跌，按 IV 降序
openbb-agent-cli derivatives.options.chain AAPL --option-type put --min-dte 0 --max-dte 30 --sort-by implied_volatility --limit 30
# 全部过滤后结果
openbb-agent-cli derivatives.options.chain SPY --expiration 2026-07-17 --limit 0
```

---

## derivatives.options.screener `CV`

跨标的多字段筛选（全市场扫描）。服务端过滤 + 排序，支持字段间比较（如 day_volume > open_interest）。返回 `{results, _meta}`，`_meta.row_count` 是服务端匹配数，`_meta.truncated` 表示是否还有更多。

```bash
openbb-agent-cli derivatives.options.screener \
  [--underlying-symbol SYMBOL] \
  [--option-type call|put] \
  [--min-open-interest X] [--max-open-interest X] \
  [--min-volume X] \
  [--min-iv X] [--max-iv X] \
  [--delta-min X] [--delta-max X] \
  [--expiration-date YYYY-MM-DD] \
  [--sort-by FIELD] [--sort-dir asc|desc] \
  [--limit N] \
  [--extra-filters JSON]
```

**参数**:
- `--underlying-symbol`: 限定标的
- `--option-type`: `call` / `put`
- `--min-open-interest` / `--max-open-interest`: OI 区间
- `--min-volume`: 最小日成交量
- `--min-iv` / `--max-iv`: IV 区间
- `--delta-min` / `--delta-max`: delta 区间
- `--expiration-date`: 单到期日
- `--sort-by`: CV 字段名，默认 `open_interest`
- `--sort-dir`: 默认 `desc`
- `--limit`: 默认 50
- `--extra-filters`: CV 原生 filter JSON 数组，支持操作符 `eq/ne/gt/gte/lt/lte` 及字段间比较 `eq_field/ne_field/gt_field/gte_field/lt_field/lte_field`

**示例**:
```bash
# 高 OI + 高 IV
openbb-agent-cli derivatives.options.screener --min-open-interest 100000 --min-iv 0.5 --limit 20
# 看跌、delta 区间、按 IV 排序
openbb-agent-cli derivatives.options.screener --delta-min -0.3 --delta-max -0.1 --option-type put --sort-by implied_volatility
# 字段间比较：当日成交量 > 持仓量
openbb-agent-cli derivatives.options.screener --extra-filters '[{"field":"day_volume","op":"gt_field","value":"open_interest"}]'
```

---

## derivatives.options.historical `CV`

单合约历史 OHLCV K 线（Massive Aggregates）。

```bash
openbb-agent-cli derivatives.options.historical SYMBOL \
  --start-date YYYY-MM-DD \
  --end-date YYYY-MM-DD \
  [--multiplier N] \
  [--timespan second|minute|hour|day|week|month|quarter|year]
```

**参数**:
- `SYMBOL`: OCC 合约代码（必需，如 `O:SPY260731C00750000`）
- `--start-date` / `--end-date`: 日期范围（**必填**，YYYY-MM-DD）
- `--multiplier`: K 线乘数，默认 1
- `--timespan`: 时间粒度，默认 `day`

**示例**:
```bash
openbb-agent-cli derivatives.options.historical O:SPY260731C00750000 --start-date 2026-06-15 --end-date 2026-07-02
# 5 分钟 K 线
openbb-agent-cli derivatives.options.historical O:SPY260731C00750000 --multiplier 5 --timespan minute --start-date 2026-07-01 --end-date 2026-07-02
```

---

## derivatives.options.daily `CV`

单合约单日 OHLCV（含盘前盘后）。

```bash
openbb-agent-cli derivatives.options.daily SYMBOL [--date YYYY-MM-DD]
```

**参数**:
- `SYMBOL`: OCC 合约代码（必需）
- `--date`: 交易日（YYYY-MM-DD，或用 `--start-date`/`--end-date` 代替）

**示例**:
```bash
openbb-agent-cli derivatives.options.daily O:SPY260731C00750000 --date 2026-06-30
```

---

## derivatives.options.query `CV`

自由 SQL 聚合查询（DuckDB 只读，DDL/DML 被服务端拒绝）。这是 ConvexValue 杀手级能力：跨合约聚合（GEX/Max Pain/PCR/期限结构），`chain` 和 `screener` 做不到，服务端聚合 14-27ms 返回。返回 `{results, _meta}`。

```bash
openbb-agent-cli derivatives.options.query --sql SQL [--max-rows N]
```

**参数**:
- `--sql`: 只读 SELECT/WITH 语句（必需）
- `--max-rows`: 返回行数上限，默认 5000，上限 50000

**示例**:
```bash
# GEX 排名
openbb-agent-cli derivatives.options.query --sql "SELECT underlying_ticker, SUM(gamma*open_interest) AS gex FROM options_snapshots GROUP BY underlying_ticker ORDER BY ABS(gex) DESC LIMIT 10"
```

更多 SQL 模板（GEX/期限结构/PCR/Max Pain/OI集中度）和 `options_snapshots` 表 44 字段参考见文末 [SQL 模板](#sql-聚合查询模板)。

---

## derivatives.options.unusual

获取期权异动数据。

```bash
openbb-agent-cli derivatives.options.unusual \
  [--symbol SYMBOL] \
  [--start-date YYYY-MM-DD] \
  [--end-date YYYY-MM-DD] \
  [--side SIDE] \
  [--option-type TYPE] \
  [--min-premium X] \
  [--min-vol-oi X] \
  [--limit N]
```

**参数**:
- `--symbol`: 股票代码
- `--side`: 买卖方向 (`Bid` / `Ask`)
- `--option-type`: 期权类型 (`P` 看跌 / `C` 看涨)
- `--min-premium`: 最小权利金
- `--min-vol-oi`: 最小成交量/持仓量比率
- `--limit`: 返回数量，默认 50

**示例**:
```bash
# 获取所有期权异动
openbb-agent-cli derivatives.options.unusual

# 获取 AAPL 的看涨期权异动
openbb-agent-cli derivatives.options.unusual \
  --symbol AAPL \
  --option-type C

# 获取大额权利金异动
openbb-agent-cli derivatives.options.unusual \
  --min-premium 100000
```

---

## etf.holdings `CV`

ETF 持仓明细。服务端返回全量（SPY 505），本地排序+截断。返回 `{results, _meta}`，`_meta.filtered` 是总持仓数。

```bash
openbb-agent-cli etf.holdings SYMBOL \
  [--sort-by weight_percentage|market_value|shares_number] \
  [--sort-dir asc|desc] \
  [--limit N]
```

**参数**:
- `SYMBOL`: ETF 代码（必需）
- `--sort-by`: 排序字段，默认 `weight_percentage`
- `--sort-dir`: 默认 `desc`
- `--limit`: 默认 20

**示例**:
```bash
openbb-agent-cli etf.holdings SPY --limit 20
openbb-agent-cli etf.holdings SPY --sort-by market_value --limit 50
```

---

## etf.sectors `CV`

ETF 行业权重（12 条固定，返回纯数组）。返回 12 条 sector weight 记录。

```bash
openbb-agent-cli etf.sectors SYMBOL
```

**示例**:
```bash
openbb-agent-cli etf.sectors SPY
```

---

## stocks.fundamental.income / balance / cash `CV`

财报三表（利润表/资产负债表/现金流量表）。TTM 路由到独立 `*-ttm` endpoint（真实滚动 12 个月）。返回 `{results, _meta}`，默认按期降序。

```bash
openbb-agent-cli stocks.fundamental.income SYMBOL [--period annual|quarter|ttm] [--limit N]
openbb-agent-cli stocks.fundamental.balance SYMBOL [--period annual|quarter|ttm] [--limit N]
openbb-agent-cli stocks.fundamental.cash SYMBOL [--period annual|quarter|ttm] [--limit N]
```

**参数**:
- `SYMBOL`: 股票代码（必需）
- `--period`: `annual` / `quarter` / `ttm`，默认 `annual`
- `--limit`: 默认 5

**示例**:
```bash
# 年报
openbb-agent-cli stocks.fundamental.income AAPL --period annual --limit 5
# 季报
openbb-agent-cli stocks.fundamental.balance AAPL --period quarter --limit 4
# TTM（真实滚动 12 个月）
openbb-agent-cli stocks.fundamental.cash AAPL --period ttm --limit 1
```

---

## stocks.fundamental.ratios `CV`

财务比率（PE/PB/ROE/debt-to-equity/current-ratio 等 ~60 个）。**不支持 ttm**（ratios-ttm endpoint 字段命名不同）。返回 `{results, _meta}`。

```bash
openbb-agent-cli stocks.fundamental.ratios SYMBOL [--period annual|quarter] [--limit N]
```

**参数**:
- `SYMBOL`: 股票代码（必需）
- `--period`: `annual` / `quarter`（不支持 ttm），默认 `annual`
- `--limit`: 默认 5

**示例**:
```bash
openbb-agent-cli stocks.fundamental.ratios AAPL --period annual --limit 5
```

---

## stocks.estimates `CV`

分析师预测（营收/EPS/EBITDA/SGA/NetIncome 各 low/high/avg + 分析师数量）。返回 `{results, _meta}`。

```bash
openbb-agent-cli stocks.estimates SYMBOL [--period annual|quarter] [--limit N]
```

**参数**:
- `SYMBOL`: 股票代码（必需）
- `--period`: `annual` / `quarter`，默认 `annual`
- `--limit`: 默认 10

**示例**:
```bash
openbb-agent-cli stocks.estimates AAPL --period quarter --limit 4
```

---

## stocks.insider_trading `CV`

内部人交易。服务端支持 transactionType/after 过滤。返回 `{results, _meta}`，默认按 filing_date desc。

```bash
openbb-agent-cli stocks.insider_trading SYMBOL \
  [--transaction-type CODE] \
  [--after YYYY-MM-DD] \
  [--limit N]
```

**参数**:
- `SYMBOL`: 股票代码（必需）
- `--transaction-type`: FMP 交易代码：`P-Purchase`（买入）/`S-Sale`（卖出）/`M-Exempt`/`F-InKind`/`J-Other`/`G-Gift`
- `--after`: 只返回此日期之后的交易（YYYY-MM-DD，服务端过滤）
- `--limit`: 默认 50

**示例**:
```bash
# 只看内部人买入
openbb-agent-cli stocks.insider_trading AAPL --transaction-type P-Purchase --after 2025-01-01 --limit 20
```

---

## government.trades `CV`

参议院交易披露。支持 page 翻页（0-indexed）。返回 `{results, _meta}`，默认按 transaction_date desc。

```bash
openbb-agent-cli government.trades [SYMBOL] [--page N] [--limit N]
```

**参数**:
- `SYMBOL`: 股票代码（可选，不传则返回全市场）
- `--page`: 页码（0-indexed，服务端翻页）
- `--limit`: 默认 50

**示例**:
```bash
openbb-agent-cli government.trades AAPL --limit 50
openbb-agent-cli government.trades AAPL --page 1 --limit 50
```

---

## stocks.filings `CV`

SEC 8-K 文件。服务端支持 from/to 日期 + page 翻页。返回 `{results, _meta}`，默认按 filing_date desc。

```bash
openbb-agent-cli stocks.filings SYMBOL \
  [--from-date YYYY-MM-DD] [--to-date YYYY-MM-DD] \
  [--page N] [--limit N]
```

**参数**:
- `SYMBOL`: 股票代码（必需）
- `--from-date` / `--to-date`: 日期范围（服务端过滤）
- `--page`: 页码（服务端翻页）
- `--limit`: 默认 50

**示例**:
```bash
openbb-agent-cli stocks.filings AAPL --from-date 2024-01-01 --to-date 2024-06-01 --limit 10
```

---

## batch

一次执行多个金融查询，输出结构为 `{"results": {...}, "errors": {...}}`。

```bash
openbb-agent-cli batch \
  [--queries JSON_ARRAY] \
  [--template equity-overview|market-overview|macro-overview|index-detail] \
  [--symbol SYMBOL] \
  [--region cn|us|hk] \
  [--country COUNTRY] \
  [--start-date YYYY-MM-DD] \
  [--end-date YYYY-MM-DD] \
  [--limit N] \
  [--news-limit N] \
  [--options-limit N] \
  [--max-workers N]
```

**参数**:
- `--queries`: 自定义查询 JSON 数组
- `--template`: 内置模板名称
- `--symbol`: 股票/指数代码（equity-overview、index-detail 需要）
- `--region`: 市场区域 (cn/us/hk)，默认 cn
- `--country`: 国家，默认 china
- `--start-date` / `--end-date`: 日期范围
- `--limit`: 返回数量。在 `market-overview` 模板中控制筛选股票数量；在 `equity-overview` 和 `index-detail` 模板中控制历史价格返回条数（CLI 侧裁剪）
- `--news-limit`: 新闻返回数量（equity-overview、market-overview），默认 20
- `--options-limit`: 期权异动返回数量（equity-overview），默认 50
- `--max-workers`: 并发数，默认 4（当前实际串行执行）

**内置模板**:
- `equity-overview`: 个股报价、历史价格、公司新闻、期权异动。需要 `--symbol`，建议搭配 `--limit` 控制历史价格返回条数
- `market-overview`: 指数快照、有成交股票筛选（内置 `volume_min=1` 作为真实过滤条件）、全球新闻。常用 `--region`，`--limit` 控制筛选股票数量
- `macro-overview`: GDP、CPI、PMI、经济日历。常用 `--country`
- `index-detail`: 指数快照、指数历史价格。需要 `--symbol`，建议搭配 `--limit` 控制历史价格返回条数

**示例**:
```bash
# 个股概览
openbb-agent-cli batch \
  --template equity-overview \
  --symbol AAPL \
  --start-date 2024-01-01 \
  --end-date 2024-01-31

# 个股概览，限制历史价格为最近 30 条
openbb-agent-cli batch \
  --template equity-overview \
  --symbol AAPL \
  --start-date 2024-01-01 \
  --end-date 2024-01-31 \
  --limit 30

# 市场概览
openbb-agent-cli batch --template market-overview --region cn --limit 20

# 宏观概览
openbb-agent-cli batch --template macro-overview --country china --start-date 2024-01-01

# 自定义查询
openbb-agent-cli batch --queries '[
  {"name":"quote","command":"equity.price.quote","params":{"symbol":"AAPL"}},
  {"name":"news","command":"news.company","params":{"symbol":"AAPL","limit":10}}
]'
```

---

## 输出格式

**ConvexValue 接口**（下文标注 `CV`，含期权链/筛选/历史/查询/财报/分析师/内部人/参议院/ETF持仓/SEC文件）返回 `{"results": [...], "_meta": {...}}` 对象：
- `results`: 数据记录数组
- `_meta.returned`: 实际返回条数
- `_meta.filtered`: 本地过滤后的总条数（limit 截断前）
- `_meta.total`: 服务端报告的合约总数（仅 options.chain 提供）
- `_meta.truncated`: 是否因 limit 截断（boolean）
- `_meta.sort_by`/`_meta.sort_dir`: 排序字段和方向
- `_meta.row_count`: 服务端报告的匹配数（screener/query）

当 `_meta.truncated=true` 时，调宽 `--limit` 或加严过滤可获取更多数据。

**非 ConvexValue 接口**（行情/指数/宏观/技术指标/新闻/期权异动）返回纯 JSON 数组：
```json
[{"symbol": "AAPL", "price": 175.50, ...}, ...]
```

**失败**：
```json
{"error": "错误信息", "code": "ERROR_CODE"}
```

常见错误码：`EMPTY_DATA`（无数据）、`VALIDATIONERROR`（参数错误）、`CLI_ERROR`（CLI 参数错误）。

## Setup

- `CV_API_KEY` 环境变量必须设置（ConvexValue Research Plan，$19/月，覆盖美股权权 + FMP 全量财务数据）
- `FINNHUB_API_KEY` 可选（公司新闻）

---

## 命令参考

| 命令 | 必需参数 | 可选参数 |
| :--- | :--- | :--- |
| `equity.price.historical` | `symbol` | `start-date`, `end-date`, `interval`, `adjusted`, `limit` |
| `equity.price.quote` | `symbol` | - |
| `equity.search` | `query` | `is-symbol` |
| `equity.screener` | - | `market`, `limit`, `price-min`, `price-max`, `change-percent-min`, `change-percent-max`, `volume-min`, `volume-max`, `market-cap-min`, `market-cap-max`, `rsi-min`, `rsi-max`, `sector`, `filters`, `fields` |
| `equity.screener.fields` | - | `search`, `all` |
| `index.available` | - | - |
| `index.search` | `query` | `is-symbol` |
| `index.price.historical` | `symbol` | `start-date`, `end-date`, `limit` |
| `index.snapshots` | - | `region` (cn/us/hk), `symbol` |
| `etf.historical` | `symbol` | `start-date`, `end-date`, `limit` |
| `etf.search` | `query` | - |
| `etf.holdings` `CV` | `symbol` | `sort-by` (weight_percentage/market_value/shares_number), `sort-dir`, `limit` |
| `etf.sectors` `CV` | `symbol` | - |
| `futures.price.historical` | `symbol` | `expiration` (YYYY-MM), `start-date`, `end-date`, `interval`, `adjusted`, `limit` |
| `futures.price.quote` | `symbol` | `expiration` (YYYY-MM) |
| `futures.search` | `query` | `is-symbol` |
| `economy.calendar` | - | `start-date`, `end-date` |
| `economy.available-indicators` | - | - |
| `economy.indicators` | `symbol` | `country`, `frequency`, `start-date`, `end-date` |
| `economy.gdp.nominal` | - | `country`, `start-date`, `end-date` |
| `economy.cpi` | - | `country`, `transform`, `frequency`, `harmonized`, `start-date`, `end-date` |
| `technical.indicators` | `symbol` | `start-date`, `end-date`, `interval`, `adjusted`, `indicators`, `rsi-length`, `macd-fast`, `macd-slow`, `macd-signal`, `sma-lengths`, `ema-lengths`, `bbands-length`, `bbands-std`, `atr-length`, `stoch-k`, `stoch-d`, `limit` |
| `news.company` | `symbol` | `start-date`, `end-date`, `limit` |
| `news.world` | - | `start-date`, `end-date`, `limit` |
| `derivatives.options.chain` `CV` | `symbol` | `expiration`, `option-type`, `min-dte`, `max-dte`, `sort-by`, `sort-dir`, `limit` |
| `derivatives.options.screener` `CV` | - | `underlying-symbol`, `option-type`, `min-open-interest`, `max-open-interest`, `min-volume`, `min-iv`, `max-iv`, `delta-min`, `delta-max`, `expiration-date`, `sort-by`, `sort-dir`, `limit`, `extra-filters` |
| `derivatives.options.historical` `CV` | `symbol`, `start-date`, `end-date` | `multiplier`, `timespan` |
| `derivatives.options.daily` `CV` | `symbol` | `date`, `start-date`, `end-date` |
| `derivatives.options.query` `CV` | `sql` | `max-rows` |
| `derivatives.options.unusual` | - | `symbol`, `start-date`, `end-date`, `side`, `option-type`, `min-premium`, `min-vol-oi`, `limit` |
| `stocks.fundamental.income/balance/cash` `CV` | `symbol` | `period` (annual/quarter/ttm), `limit` |
| `stocks.fundamental.ratios` `CV` | `symbol` | `period` (annual/quarter), `limit` |
| `stocks.estimates` `CV` | `symbol` | `period` (annual/quarter), `limit` |
| `stocks.insider_trading` `CV` | `symbol` | `transaction-type`, `after`, `limit` |
| `government.trades` `CV` | - | `symbol`, `page`, `limit` |
| `stocks.filings` `CV` | `symbol` | `from-date`, `to-date`, `page`, `limit` |
| `batch` | `queries` 或 `template` | `symbol`, `region`, `country`, `start-date`, `end-date`, `limit`, `news-limit`, `options-limit`, `max-workers` |

---

## SQL 聚合查询模板

`derivatives.options.query` 对 `options_snapshots` 表（DuckDB）执行只读 SELECT/WITH。后端强制 `only SELECT and WITH queries are allowed`（DDL/DML/DESCRIBE 被 400 拒）。下面是实测跑通的常用聚合模板（14-27ms 返回）。

### GEX 排名（做市商 gamma 定位）
```sql
SELECT underlying_ticker, SUM(gamma * open_interest) AS gex, SUM(open_interest) AS oi
FROM options_snapshots GROUP BY underlying_ticker ORDER BY ABS(gex) DESC LIMIT 10
```

### 期限结构（IV + OI 按到期日）
```sql
SELECT expiration_date, SUM(open_interest) AS oi, AVG(implied_volatility) AS avg_iv
FROM options_snapshots WHERE underlying_ticker = 'SPY'
GROUP BY expiration_date ORDER BY expiration_date LIMIT 15
```

### 全市场 PCR（情绪指标）
```sql
SELECT underlying_ticker,
  SUM(CASE WHEN contract_type='put' THEN open_interest ELSE 0 END) AS put_oi,
  SUM(CASE WHEN contract_type='call' THEN open_interest ELSE 0 END) AS call_oi,
  ROUND(SUM(CASE WHEN contract_type='put' THEN open_interest ELSE 0 END)::FLOAT
        / NULLIF(SUM(CASE WHEN contract_type='call' THEN open_interest ELSE 0 END), 0), 3) AS pcr
FROM options_snapshots GROUP BY underlying_ticker
HAVING SUM(open_interest) > 100000 ORDER BY pcr DESC LIMIT 10
```

### 高 IV 标的筛选
```sql
SELECT underlying_ticker, ROUND(AVG(implied_volatility), 2) AS avg_iv, SUM(open_interest) AS oi
FROM options_snapshots WHERE open_interest > 10000
GROUP BY underlying_ticker HAVING AVG(implied_volatility) > 1.0
ORDER BY avg_iv DESC LIMIT 10
```

### Max Pain（到期磁吸价）
```sql
WITH pain AS (
  SELECT strike_price,
    SUM(CASE WHEN contract_type='call' THEN open_interest * GREATEST(underlying_price - strike_price, 0) ELSE 0 END)
    + SUM(CASE WHEN contract_type='put' THEN open_interest * GREATEST(strike_price - underlying_price, 0) ELSE 0 END) AS total_pain
  FROM options_snapshots WHERE underlying_ticker = 'SPY' AND expiration_date = '2026-07-17'
  GROUP BY strike_price
)
SELECT strike_price, total_pain FROM pain ORDER BY total_pain ASC LIMIT 1
```

### OI 集中度 + IV skew（支撑阻力 + smile）
```sql
SELECT contract_type, strike_price, SUM(open_interest) AS oi, ROUND(AVG(implied_volatility),3) AS iv, AVG(delta) AS delta
FROM options_snapshots WHERE underlying_ticker = 'SPY' AND expiration_date = '2026-07-17'
GROUP BY contract_type, strike_price ORDER BY oi DESC LIMIT 20
```

### options_snapshots 表字段（44 个）

- **标的**：underlying_ticker, underlying_symbol, underlying_price, underlying_change_to_break_even, underlying_last_updated, underlying_timeframe
- **合约**：ticker（OCC 合约代码）, contract_type（call/put）, exercise_style, expiration_date, strike_price, shares_per_contract, break_even_price
- **Greeks + 定价**：delta, gamma, theta, vega, implied_volatility, fair_market_value, midpoint
- **报价**：bid, bid_size, ask, ask_size, quote_last_updated, quote_timeframe
- **成交**：trade_price, trade_size, trade_exchange, trade_conditions, trade_sip_timestamp, trade_timeframe
- **日统计**：open_interest, day_volume, day_open, day_high, day_low, day_close, day_change, day_change_percent, day_vwap, day_previous_close, day_last_updated
- **系统**：fetched_at

## 索引符号规则

`I:SPX`（标普500）、`I:VIX`（波动率指数）、`I:NDX`（纳斯达克100）、`I:RUT`（罗素2000）。普通股票直接用 ticker。

## 选择指南

| 需求 | 命令 |
|---|---|
| 单标的全合约 Greeks/IV | `derivatives.options.chain` |
| 跨标的多字段筛选 | `derivatives.options.screener` |
| 跨合约聚合（GEX/PCR/Max Pain） | `derivatives.options.query` |
| 单合约历史 K 线 | `derivatives.options.historical` |
| 单合约单日 OHLCV | `derivatives.options.daily` |
| 财报分析 | `stocks.fundamental.income/balance/cash` |
| 估值 | `stocks.fundamental.ratios` + `stocks.estimates` |
| 内部人异动 | `stocks.insider_trading` |
| 政治交易信号 | `government.trades` |
| 监管文件 | `stocks.filings` |
| ETF 持仓变动 | `etf.holdings` + `etf.sectors` |
| 期货主连/月份合约历史 | `futures.price.historical`（`--expiration` 指定月份） |
| 期货实时行情 | `futures.price.quote` |
| 期货合约/品种搜索 | `futures.search`（中文名或 `--is-symbol` 品种码） |
