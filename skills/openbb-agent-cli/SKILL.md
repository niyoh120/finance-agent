---
name: openbb-agent-cli
description: 使用 openbb-agent-cli 获取金融数据。支持股票历史价格、行情报价、搜索、筛选（支持3500+字段的高级过滤和自定义返回字段）、指数、ETF、经济日历、宏观经济数据、新闻、期权异动和批量查询。当用户需要查询股票价格、筛选股票、获取市场数据、查看宏观数据、查看期权异动或一次聚合多个金融查询时使用此 skill。
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
| `economy.calendar` | 经济日历 |
| `economy.available-indicators` | 可用宏观指标 |
| `economy.indicators` | 宏观经济指标 |
| `economy.gdp.nominal` | 名义 GDP |
| `economy.cpi` | CPI |
| `news.company` | 公司新闻 |
| `news.world` | 全球新闻 |
| `derivatives.options.unusual` | 期权异动 |
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

> **未提供真实过滤条件时返回结构化帮助（JSON），不返回数据。** `--market` 只限定市场范围，`--limit`/`--fields` 只控制输出，不能单独触发查询；必须搭配价格/成交量/涨跌幅/RSI/行业/`--filters` 等真实过滤条件。需要发现可用过滤字段名时，先运行 `equity.screener.fields --search <关键词>`；需穷举全部字段用 `equity.screener.fields --all`。

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

所有命令输出均为 JSON 格式。

**成功**:
```json
[
  {"symbol": "AAPL", "price": 175.50, ...},
  {"symbol": "MSFT", "price": 380.25, ...}
]
```

**失败**:
```json
{"error": "错误信息", "code": "ERROR_CODE"}
```

**常见错误码**:
- `EMPTY_DATA`: 无数据
- `CLI_ERROR`: CLI 参数错误
- 其他错误码为异常类名

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
| `economy.calendar` | - | `start-date`, `end-date` |
| `economy.available-indicators` | - | - |
| `economy.indicators` | `symbol` | `country`, `frequency`, `start-date`, `end-date` |
| `economy.gdp.nominal` | - | `country`, `start-date`, `end-date` |
| `economy.cpi` | - | `country`, `transform`, `frequency`, `harmonized`, `start-date`, `end-date` |
| `news.company` | `symbol` | `start-date`, `end-date`, `limit` |
| `news.world` | - | `start-date`, `end-date`, `limit` |
| `derivatives.options.unusual` | - | `symbol`, `start-date`, `end-date`, `side`, `option-type`, `min-premium`, `min-vol-oi`, `limit` |
| `batch` | `queries` 或 `template` | `symbol`, `region`, `country`, `start-date`, `end-date`, `limit`, `news-limit`, `options-limit`, `max-workers` |
