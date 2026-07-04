# ConvexValue REST API 数据接口文档

**本文档基于逆向分析整理，非 ConvexValue 官方文档。**接口和参数可能随 cvforge 版本更新变化。所有接口均需 Research Plan 订阅（$19/月）。API Key 从 cvforge 的 `~/.cv-apps/*/app/.mcp.json` 获取，或通过抓包主进程获取。

# 1\. 概述

ConvexValue 后端提供完整的 REST API，覆盖美股期权实时数据、期权历史K线、以及 FMP 全量金融数据（基本面、财报、分析师预测、ETF持仓、SEC文件、内部人交易等共 210 个接口）。

## 基本信息

|项目|值|
|---|---|
|Base URL|`https://tap.convexvalue.com/api/data`|
|认证方式|Bearer Token|
|请求格式|JSON POST|
|数据来源|Massive（期权）\+ FMP（基本面）|
|可用字段|42 个（含 Greeks、IV、OI、成交量、报价等；params 单次最多 32 个）|

# 2\. 认证

所有请求必须在 Header 中携带 API Key，格式为：

```http
Authorization: Bearer <your_api_key>
Content-Type: application/json
User-Agent: cv-preview-node/0.1
```

**获取 API Key**

安装 cvforge 并登录后，在 Windows 上执行：

```powershell
Get-ChildItem "$env:USERPROFILE\cv-apps" -Recurse -Filter ".mcp.json" | ForEach-Object { Get-Content $_.FullName }
```

输出中的 `CV_API_KEY` 字段即为可用 Key。Linux 路径类似 `~/cv-apps/*/app/.mcp.json`。

# 3\. 期权链接口

获取单个标的的完整期权链，按到期日和行权价分组，每行包含 call 和 put 的对称字段。

## Endpoint

```
POST /chains
```

## 请求参数

|参数|类型|必填|说明|
|---|---|---|---|
|symbol|string|✅|标的代码，如 `SPY`、`AAPL`、`I:SPX`、`I:VIX`|
|params|string\[\]|✅|返回字段列表（**必填**，最多 32 个字段，超限报 400；可用 `list_chain_fields` MCP 工具查询完整字段清单）|

## 请求示例

```bash
curl -X POST https://tap.convexvalue.com/api/data/chains \
  -H "Authorization: Bearer $CV_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "SPY",
    "params": ["expiration_date","strike_price","contract_type",
               "implied_volatility","delta","gamma","theta","vega",
               "bid","ask","open_interest","day_volume","underlying_price"]
  }'
```

## 响应格式

```json
{
  "symbol": "SPY",
  "params": ["expiration_date","strike_price",...],
  "chain": [
    {
      "expiration": "2026-07-18",
      "strikes": [
        [
          480.0,
          [...call fields...],
          [...put fields...]
        ],
        ...
      ]
    }
  ]
}
```

每个行权价行为一个三元组：`[strike_price, call_data_array, put_data_array]`，数组元素按 `params` 字段顺序排列。

# 4\. 跨标的筛选接口

对全市场期权合约进行条件筛选，支持多字段排序和 AND 过滤。

## Endpoint

```
POST /screen
```

## 请求参数

|参数|类型|必填|说明|
|---|---|---|---|
|columns|string\[\]|否|返回字段列。缺省同 chains 的默认字段|
|filters|object\[\]|✅|AND 条件数组。传 `[]` 表示不过滤|
|sort|object\[\]|否|排序规则，`{"field":"open_interest","direction":"desc"}`|
|limit|integer|否|返回行数上限|

## 支持的过滤操作符

|操作符|含义|
|---|---|
|`eq`|=|
|`ne`|\!=|
|`gt`|\>|
|`gte`|\>=|
|`lt`|\<|
|`lte`|\<=|
|`eq_field` / `ne_field` / `gt_field` / 等|两字段比较|

## 请求示例

```bash
curl -X POST https://tap.convexvalue.com/api/data/screen \
  -H "Authorization: Bearer $CV_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "columns": ["ticker","underlying_ticker","implied_volatility",
                "open_interest","day_volume","delta"],
    "filters": [
      {"field":"open_interest","op":"gt","value":50000},
      {"field":"implied_volatility","op":"gt","value":0.3}
    ],
    "sort": [{"field":"open_interest","direction":"desc"}],
    "limit": 20
  }'
```

## 响应格式

```json
{
  "columns": ["ticker","underlying_ticker",...],
  "rows": [
    ["O:AAPL260731C00250000","AAPL",0.35,150000,1200,0.65],
    ...
  ],
  "row_count": 20,
  "truncated": false,
  "elapsed_ms": 21
}
```

# 5\. SQL 查询接口

基于 DuckDB 对 `options_snapshots` 表执行只读 SQL 查询，适合分组聚合、自定义统计。

## Endpoint

```
POST /query
```

## 请求参数

|参数|类型|必填|说明|
|---|---|---|---|
|sql|string|✅|只读 SELECT 语句|
|max\_rows|integer|否|结果行数上限|

## 请求示例

```sql
-- 按标的总 OI 排名
SELECT underlying_ticker,
       SUM(open_interest) AS total_oi,
       AVG(implied_volatility) AS avg_iv
FROM options_snapshots
GROUP BY underlying_ticker
ORDER BY total_oi DESC
LIMIT 30
```

```bash
curl -X POST https://tap.convexvalue.com/api/data/query \
  -H "Authorization: Bearer $CV_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"sql":"SELECT DISTINCT underlying_ticker FROM options_snapshots LIMIT 20"}'
```

## 响应格式

```json
{
  "rows": [
    {"underlying_ticker":"SPY","total_oi":1230000,"avg_iv":0.25},
    ...
  ],
  "row_count": 30,
  "truncated": false,
  "elapsed_ms": 35
}
```

# 6\. 期权历史K线

获取单个期权合约的聚合 OHLCV 历史数据（来自 Massive Aggregates API）。

## Endpoint

```
POST /mas/aggs
```

## 请求参数

|参数|类型|必填|说明|
|---|---|---|---|
|ticker|string|✅|期权合约代码，如 `O:SPY260731C00750000`|
|multiplier|integer|✅|K线乘数，如 `1`、`5`|
|timespan|string|✅|时间粒度：`second|minute|hour|day|week|month|quarter|year`|
|from|string|✅|起始时间，`YYYY-MM-DD` 或 epoch 毫秒|
|to|string|✅|结束时间|
|adjusted|boolean|否|是否调整拆股，默认 `true`|
|sort|string|否|排序方向：`asc` \| `desc`|
|limit|integer|否|最大条数，默认 5000，上限 50000|

## 请求示例

```bash
curl -X POST https://tap.convexvalue.com/api/data/mas/aggs \
  -H "Authorization: Bearer $CV_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "ticker": "O:SPY260731C00750000",
    "multiplier": 1,
    "timespan": "day",
    "from": "2026-06-15",
    "to": "2026-07-02"
  }'
```

## 响应格式

```json
{
  "ticker": "O:SPY260731C00750000",
  "status": "OK",
  "count": 13,
  "results": [
    {"o":17.8,"h":20.7,"l":17.8,"c":19.14,"v":416,"n":127,"t":1781496000000,"vw":19.34},
    ...
  ]
}
```

字段说明：`o`=开盘价, `h`=最高价, `l`=最低价, `c`=收盘价, `v`=成交量, `n`=交易笔数, `t`=epoch毫秒, `vw`=成交量加权均价。

# 7\. 期权日OHLCV

获取单个期权合约单日的 OHLCV。

## Endpoint

```
POST /mas/open-close
```

## 请求参数

|参数|类型|必填|说明|
|---|---|---|---|
|ticker|string|✅|期权合约代码|
|date|string|✅|交易日 `YYYY-MM-DD`|

---

# 8\. FMP 金融数据接口

通过统一入口访问 Financial Modeling Prep 的全量金融数据，共 210 个 endpoint。路径格式：`/fmp/stable/<endpoint_name>`

## Endpoint

```
POST /fmp/stable/<endpoint>
```

## 请求参数

各 endpoint 参数不同，统一传递 params 对象，键值对映射到 FMP API 的 query 参数。数组值自动逗号拼接。

## 常用 FMP 接口

|Endpoint|功能|
|---|---|
|`profile`|公司概况（名称、行业、市值、员工数等）|
|`income-statement`|利润表（年报/季报/TTM）|
|`balance-sheet-statement`|资产负债表|
|`cash-flow-statement`|现金流量表|
|`ratios`|财务比率（PE、PB、ROE等）|
|`analyst-estimates`|分析师预测（营收/EPS）|
|`sec-filings`|SEC 文件列表（10\-K/10\-Q等）|
|`insider-trades`|内部人交易|
|`etf/holdings`|ETF 持仓明细|
|`batch-quote`|批量实时报价|
|`technical-indicators/sma`|SMA/EMA/RSI 等技术指标|
|`commitment-of-traders-report`|COT 持仓报告|

## 请求示例

```bash
# 公司概况
curl -X POST https://tap.convexvalue.com/api/data/fmp/stable/profile \
  -H "Authorization: Bearer $CV_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"AAPL"}'

# 利润表
curl -X POST https://tap.convexvalue.com/api/data/fmp/stable/income-statement \
  -H "Authorization: Bearer $CV_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"AAPL","period":"annual","limit":5}'

# 批量报价
curl -X POST https://tap.convexvalue.com/api/data/fmp/stable/batch-quote \
  -H "Authorization: Bearer $CV_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"symbols":"AAPL,MSFT,NVDA"}'
```

**完整 FMP 目录**：通过 MCP 接口 `tools/call` 调用 `list_fmp_endpoints` 可列出全部 210 个 endpoint。按 category 分组的完整列表见附录。

---

# 9\. MCP 工具发现接口

JSON\-RPC 2\.0 格式，用于查询可用工具和字段列表。这不是数据接口，仅用于工具发现。

## Endpoint

```
POST /mcp
```

## 使用方法

```bash
# 列出所有可用工具
curl -X POST https://tap.convexvalue.com/api/data/mcp \
  -H "Authorization: Bearer $CV_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

# 调用特定工具（如 list_fmp_endpoints）
curl -X POST https://tap.convexvalue.com/api/data/mcp \
  -H "Authorization: Bearer $CV_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_fmp_endpoints","arguments":{}}}'
```

---

# 10\. 可用字段清单

以下 42 个字段可用于 `chains`、`screen` 的 `columns`/`filters`/`sort`，以及 `query` 的 SQL。完整字段 enum 也可通过 MCP `tools/call` 调用 `list_chain_fields` 获取。

**默认字段**（当不指定 params 时返回）：expiration\_date, strike\_price, contract\_type, implied\_volatility, delta, gamma, theta, vega, bid, ask, midpoint, open\_interest, day\_volume, underlying\_price

## 标的层面

```
underlying_ticker    underlying_symbol    underlying_price
underlying_last_updated    underlying_timeframe
underlying_change_to_break_even
```

## 合约信息

```
ticker    contract_type    exercise_style    expiration_date
strike_price    shares_per_contract    break_even_price
```

## Greeks 与定价

```
delta    gamma    theta    vega
implied_volatility    fair_market_value    midpoint
```

## 报价（Bid/Ask）

```
bid    bid_size    ask    ask_size
quote_last_updated    quote_timeframe
```

## 成交

```
trade_price    trade_size    trade_exchange
trade_conditions    trade_sip_timestamp    trade_timeframe
```

## 日统计

```
open_interest    day_volume    day_open    day_high    day_low
day_close    day_change    day_change_percent    day_vwap
day_previous_close    day_last_updated
```

## 系统

```
fetched_at
```

---

# 11\. Python SDK 示例

```python
import requests
from typing import Any, Optional

class ConvexValueAPI:
    """ConvexValue Research Plan REST API 封装"""

    BASE = "https://tap.convexvalue.com/api/data"

    def __init__(self, api_key: str):
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "cv-preview-node/0.1",
        }

    def _post(self, endpoint: str, **body) -> dict:
        r = requests.post(f"{self.BASE}/{endpoint}", headers=self._headers, json=body)
        r.raise_for_status()
        return r.json()

    # ---- 期权数据 ----

    def chain(self, symbol: str, params: Optional[list[str]] = None) -> dict:
        """获取期权链"""
        body: dict = {"symbol": symbol.upper()}
        if params:
            body["params"] = params
        return self._post("chains", **body)

    def screen(self, columns: list[str], filters: list[dict],
               sort: Optional[list[dict]] = None, limit: int = 50) -> dict:
        """跨标的筛选"""
        body = {"columns": columns, "filters": filters}
        if sort:
            body["sort"] = sort
        body["limit"] = limit
        return self._post("screen", **body)

    def query(self, sql: str, max_rows: Optional[int] = None) -> dict:
        """SQL 查询"""
        body: dict = {"sql": sql}
        if max_rows:
            body["max_rows"] = max_rows
        return self._post("query", **body)

    # ---- 期权历史 ----

    def option_bars(self, ticker: str, multiplier: int, timespan: str,
                    from_date: str, to_date: str, **kwargs) -> dict:
        """期权历史K线"""
        return self._post("mas/aggs", ticker=ticker, multiplier=multiplier,
                          timespan=timespan, from_=from_date, to=to_date, **kwargs)

    def option_daily(self, ticker: str, date: str) -> dict:
        """期权日OHLCV"""
        return self._post("mas/open-close", ticker=ticker, date=date)

    # ---- FMP 基本面 ----

    def fmp(self, endpoint: str, **params) -> Any:
        """FMP 通用请求"""
        return self._post(f"fmp/stable/{endpoint}", **params)

    def profile(self, symbol: str) -> list:
        """公司概况"""
        return self.fmp("profile", symbol=symbol)

    def income_statement(self, symbol: str, period: str = "annual", limit: int = 5) -> list:
        """利润表"""
        return self.fmp("income-statement", symbol=symbol, period=period, limit=limit)

    def balance_sheet(self, symbol: str, period: str = "annual", limit: int = 5) -> list:
        """资产负债表"""
        return self.fmp("balance-sheet-statement", symbol=symbol, period=period, limit=limit)

    def cashflow(self, symbol: str, period: str = "annual", limit: int = 5) -> list:
        """现金流量表"""
        return self.fmp("cash-flow-statement", symbol=symbol, period=period, limit=limit)

    def analyst_estimates(self, symbol: str, period: str = "quarterly") -> list:
        """分析师预测"""
        return self.fmp("analyst-estimates", symbol=symbol, period=period)

    def historical_prices(self, symbol: str, from_date: str, to_date: str) -> list:
        """股票历史价格"""
        return self.fmp("historical-price-full", symbol=symbol,
                        from_=from_date, to=to_date)


# ---- 使用示例 ----
if __name__ == "__main__":
    import os
    cv = ConvexValueAPI(os.environ["CV_API_KEY"])

    # 获取 SPY 期权链
    chain = cv.chain("SPY")

    # 筛选高 OI 高 IV 期权
    result = cv.screen(
        columns=["ticker","underlying_ticker","open_interest","implied_volatility","delta"],
        filters=[{"field":"open_interest","op":"gt","value":50000}],
        sort=[{"field":"open_interest","direction":"desc"}],
        limit=20
    )

    # 获取 AAPL 公司概况
    profile = cv.profile("AAPL")
    print(f"{profile[0]['companyName']}: ${profile[0]['marketCap'] / 1e12:.2f}T")
```

---

# 12\. 注意事项

**速率限制**

后端返回 429 时表示请求过于频繁。返回 402 表示功能超出订阅范围。Research Plan 有请求频率限制，避免高频轮询。建议：

- 批量请求优先用 screen / SQL 而非逐个标的拉链

- 缓存期权链数据，避免重复请求

- 历史K线请求量较大，合理使用 limit 参数

**数据时效性**

- 期权实时快照：实时到近实时

- FMP 新闻：\~15 分钟延迟

- FMP 财报/基本面：数小时内更新

- 分析师预测：每周更新

索引符号规则：`I:SPX`（标普500指数）、`I:VIX`（波动率指数）、`I:NDX`（纳斯达克100）、`I:RUT`（罗素2000）。普通股票直接使用 ticker。

---

# 附录：FMP 接口分类总览

共 210 个 FMP endpoint，按以下类别组织（部分列举）：

|类别|代表接口|
|---|---|
|**Company**|profile, company\-notes, enterprise\-values, rating|
|**Statements**|income\-statement, balance\-sheet\-statement, cash\-flow\-statement \(含 as\-reported / growth / ttm / bulk 变体\)|
|**Quote**|batch\-quote, batch\-quote\-short, batch\-aftermarket\-quote, batch\-exchange\-quote, batch\-etf\-quotes|
|**Chart**|historical\-price\-full, technical\-indicators/\*, historical\-chart/\*|
|**Analyst**|analyst\-estimates, analyst\-stock\-recommendations, price\-target|
|**SecFilings**|sec\-filings, all\-industry\-classification|
|**InsiderTrades**|insider\-trades, senate\-trades, acquisition\-of\-beneficial\-ownership|
|**ETFs / MutualFunds**|etf/holdings, etf/sector\-weightings, mutual\-fund\-holdings|
|**Calendar**|earnings\-calendar, dividend\-calendar, ipo\-calendar, stock\-split\-calendar|
|**CommitmentOfTraders**|commitment\-of\-traders\-report, commitment\-of\-traders\-analysis|
|**News**|stock\-news, press\-releases, fmp\-articles|
|**Market**|market\-capitalization, biggest\-gainers, biggest\-losers, most\-active|
|**Crypto**|batch\-crypto\-quotes, crypto\-list|
|**Forex**|batch\-forex\-quotes, forex\-list|
|**Commodity**|batch\-commodity\-quotes, commodities\-list|
|**Indexes**|batch\-index\-quotes, index\-list|



> (注：内容由 AI 生成，请谨慎参考）
