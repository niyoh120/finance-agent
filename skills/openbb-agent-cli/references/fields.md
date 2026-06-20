# StockField 常用字段参考

> **运行时真相源**：字段全集随 `tvscreener` 版本变动，请优先用 CLI 子命令发现字段名：
> `openbb-agent-cli equity.screener.fields --search <关键词>`（模糊匹配）/ `--all`（全量）/ 无参（含搜索提示目录）。
> 本文件为常用字段人工速查，可能滞后，不作完整清单。

股票筛选器支持 3500+ 字段，以下是常用字段分类。

## 价格相关

| 字段名 | 说明 |
|--------|------|
| `PRICE` | 当前价格 |
| `CHANGE_PERCENT` | 涨跌幅 (%) |
| `CHANGE_1D` | 1日涨跌 |
| `CHANGE_1W` | 1周涨跌 |
| `CHANGE_1M` | 1月涨跌 |
| `CHANGE_3M` | 3月涨跌 |
| `CHANGE_6M` | 6月涨跌 |
| `CHANGE_1Y` | 1年涨跌 |
| `CHANGE_YTD` | 年初至今涨跌 |
| `HIGH_52W` | 52周最高 |
| `LOW_52W` | 52周最低 |
| `PRECLOSE` | 前收盘价 |
| `OPEN` | 开盘价 |
| `HIGH` | 最高价 |
| `LOW` | 最低价 |

## 成交量相关

| 字段名 | 说明 |
|--------|------|
| `VOLUME` | 成交量 |
| `AVG_VOLUME_10D` | 10日平均成交量 |
| `AVG_VOLUME_20D` | 20日平均成交量 |
| `AVG_VOLUME_60D` | 60日平均成交量 |
| `VOLUME_RELATIVE` | 相对成交量 |
| `VOLATILITY_10D` | 10日波动率 |
| `VOLATILITY_30D` | 30日波动率 |
| `VOLATILITY_60D` | 60日波动率 |

## 市值相关

| 字段名 | 说明 |
|--------|------|
| `MARKET_CAPITALIZATION` | 市值 |
| `MARKET_CAP_FTM` | 远期市值 |
| `ENTERPRISE_VALUE` | 企业价值 |

## 估值指标

| 字段名 | 说明 |
|--------|------|
| `PE_RATIO_TTM` | 市盈率 (TTM) |
| `PE_RATIO_FTM` | 远期市盈率 |
| `PB_RATIO` | 市净率 |
| `PS_RATIO` | 市销率 |
| `EV_EBITDA` | EV/EBITDA |
| `EV_SALES` | EV/销售额 |
| `PEG_RATIO` | PEG 比率 |
| `PRICE_TO_FCF` | 价格/自由现金流 |
| `PRICE_TO_BOOK` | 市净率 (同 PB_RATIO) |
| `PRICE_TO_SALES` | 市销率 (同 PS_RATIO) |

## 盈利能力

| 字段名 | 说明 |
|--------|------|
| `EPS_DILUTED_TTM` | 每股收益 (TTM, 稀释) |
| `EPS_BASIC_TTM` | 每股收益 (TTM, 基本) |
| `EPS_GROWTH` | EPS 增长率 |
| `REVENUE_GROWTH` | 营收增长率 |
| `PROFIT_MARGIN` | 利润率 |
| `OPERATING_MARGIN` | 营业利润率 |
| `GROSS_MARGIN` | 毛利率 |
| `ROE` | 净资产收益率 |
| `ROA` | 总资产收益率 |
| `ROI` | 投资回报率 |
| `EBITDA_MARGIN` | EBITDA 利润率 |

## 股息相关

| 字段名 | 说明 |
|--------|------|
| `DIVIDEND_YIELD` | 股息率 (%) |
| `DIVIDEND_GROWTH` | 股息增长率 |
| `EXPECTED_ANNUAL_DIVIDENDS` | 预期年度股息 |
| `PAYOUT_RATIO` | 分红比率 |
| `DIVIDENDS_TTM` | 过去12个月股息 |

## 技术指标

### RSI (相对强弱指数)

| 字段名 | 说明 |
|--------|------|
| `RELATIVE_STRENGTH_INDEX_14` | RSI(14) |
| `RSI_7` | RSI(7) |
| `RSI_21` | RSI(21) |

### MACD

| 字段名 | 说明 |
|--------|------|
| `MACD_LEVEL_12_26` | MACD 线 (12,26) |
| `MACD_SIGNAL_12_26` | MACD 信号线 |
| `MACD_HISTOGRAM_12_26` | MACD 柱状图 |

### 移动平均线

| 字段名 | 说明 |
|--------|------|
| `SMA_20` | 20日简单移动平均 |
| `SMA_50` | 50日简单移动平均 |
| `SMA_100` | 100日简单移动平均 |
| `SMA_200` | 200日简单移动平均 |
| `EMA_20` | 20日指数移动平均 |
| `EMA_50` | 50日指数移动平均 |
| `EMA_100` | 100日指数移动平均 |
| `EMA_200` | 200日指数移动平均 |

### 布林带

| 字段名 | 说明 |
|--------|------|
| `BOLLINGER_UPPER_20` | 布林带上轨 |
| `BOLLINGER_MIDDLE_20` | 布林带中轨 |
| `BOLLINGER_LOWER_20` | 布林带下轨 |
| `BOLLINGER_WIDTH_20` | 布林带宽度 |

### 其他技术指标

| 字段名 | 说明 |
|--------|------|
| `STOCH_K_14` | 随机指标 K 值 |
| `STOCH_D_14` | 随机指标 D 值 |
| `WILLIAMS_R_14` | 威廉指标 |
| `CCI_20` | 商品通道指数 |
| `MFI_14` | 资金流量指标 |
| `ATR_14` | 真实波动幅度 |
| `ADX_14` | 平均趋向指数 |

## 风险指标

| 字段名 | 说明 |
|--------|------|
| `YEAR_BETA_1` | Beta 系数 (1年) |
| `DEBT_TO_EQUITY` | 负债权益比 |
| `DEBT_TO_ASSETS` | 资产负债率 |
| `CURRENT_RATIO` | 流动比率 |
| `QUICK_RATIO` | 速动比率 |
| `INTEREST_COVERAGE` | 利息保障倍数 |
| `ALTMAN_Z_SCORE` | Altman Z 分数 |

## 行业分类

| 字段名 | 说明 |
|--------|------|
| `SECTOR` | 行业板块 |
| `INDUSTRY` | 具体行业 |
| `SUBINDUSTRY` | 子行业 |

**常见行业值**:
- `Technology` - 科技
- `Healthcare` - 医疗健康
- `Financial Services` - 金融服务
- `Consumer Cyclical` - 非必需消费
- `Consumer Defensive` - 必需消费
- `Industrials` - 工业
- `Energy` - 能源
- `Utilities` - 公用事业
- `Real Estate` - 房地产
- `Basic Materials` - 基础材料
- `Communication Services` - 通信服务

## 分析师评级

| 字段名 | 说明 |
|--------|------|
| `RECOMMENDATION_RATING` | 分析师评级 (1-5) |
| `RECOMMENDATION_MEAN` | 评级均值 |
| `TARGET_PRICE` | 目标价 |
| `TARGET_PRICE_UPSIDE` | 目标价上涨空间 (%) |
| `NUM_ANALYSTS` | 分析师数量 |

## 其他

| 字段名 | 说明 |
|--------|------|
| `SHORT_INTEREST` | 做空利息 |
| `SHORT_RATIO` | 做空比率 |
| `INSIDER_OWNERSHIP` | 内部人持股比例 |
| `INSTITUTIONAL_OWNERSHIP` | 机构持股比例 |
| `SHARES_OUTSTANDING` | 流通股数 |
| `FLOAT` | 公众流通股 |

---

## 字段发现方法

使用 Python 查找特定字段：

```python
from tvscreener import StockField

# 搜索包含关键词的字段
results = StockField.search("dividend")
for field in results:
    print(f"{field.name}: {field.label}")

# 获取所有技术指标字段
technicals = StockField.technicals()

# 获取所有推荐字段
recommendations = StockField.recommendations()
```

## 使用示例

```bash
# 筛选低估值股票：市盈率 < 15，市净率 < 1.5
openbb-agent-cli equity.screener \
  --filters '{"PE_RATIO_TTM": {"max": 15}, "PB_RATIO": {"max": 1.5}}'

# 筛选高股息股票：股息率 > 4%，分红比率 < 60%
openbb-agent-cli equity.screener \
  --filters '{"DIVIDEND_YIELD": {"min": 4}, "PAYOUT_RATIO": {"max": 60}}'

# 筛选技术形态：RSI 超卖，价格在 50 日均线下方
openbb-agent-cli equity.screener \
  --filters '{"RELATIVE_STRENGTH_INDEX_14": {"max": 30}}'

# 筛选低风险股票：Beta < 1，负债权益比 < 0.5
openbb-agent-cli equity.screener \
  --filters '{"YEAR_BETA_1": {"max": 1}, "DEBT_TO_EQUITY": {"max": 0.5}}'

# 筛选成长股：营收增长 > 20%，EPS 增长 > 15%
openbb-agent-cli equity.screener \
  --filters '{"REVENUE_GROWTH": {"min": 20}, "EPS_GROWTH": {"min": 15}}'
```
