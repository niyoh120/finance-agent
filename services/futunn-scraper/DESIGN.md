# Futunn Scraper Service Design

## 1. 概述
`futunn-scraper` 是一个新的微服务，旨在从富途牛牛 API (`https://news.futunn.com/main/live`) 抓取实时财经快讯，并将其标准化存储到 `finance-shared` 数据库中。

## 2. 架构设计

### 2.1 模块划分
服务位于 `services/futunn-scraper`，采用 Python 编写，结构如下：

```
services/futunn-scraper/
├── pyproject.toml          # 依赖管理 (finance-shared, httpx, tenacity)
├── Dockerfile              # 容器构建
└── src/
    └── futunn_scraper/
        ├── __init__.py
        ├── main.py         # 入口点，负责主循环和信号处理
        ├── client.py       # Futu API 客户端
        ├── mapper.py       # 数据模型转换 (Futu JSON -> NewsArticle)
        └── market_resolver.py # 股票代码解析与缓存
```

### 2.2 关键组件

#### 2.2.1 FutunnClient
负责与富途 API 交互，处理 Header 伪装和重试逻辑。
- **Endpoint**: `https://news.futunn.com/news-site-api/main/get-flash-list`
- **Params**: `pageSize`, `lang`, `seqMark` (用于分页)

#### 2.2.2 MarketResolver (核心难点解决)
负责将富途的股票代码转换为 TradingView 格式。
- **静态映射**:
  - `*.HK` -> `HKEX:*`
  - `*.SH` -> `SSE:*`
  - `*.SZ` -> `SZSE:*`
- **动态映射 (.US)**:
  - 维护一个内存 LRU Cache (`functools.lru_cache` 或 `dict`)。
  - 对于 `.US` 后缀代码，首先检查缓存。
  - 缓存未命中时，调用 `stock-api` 的 `/v0/searchMarket` 接口查询。
  - **兜底策略**: 如果查询失败或超时，记录警告并暂时映射为 `US:{SYMBOL}` (非标准但保留信息)。
- **依赖**: 需要配置 `FA_STOCK_API_URL`。

#### 2.2.3 DataMapper
将 API 返回的 JSON 转换为 `shared.models.NewsArticle`。
- **ID 生成**: `external_id` = `futunn_{id}`
- **Type**: 默认为 `stock_news`。
- **Content**: 组合 `title` 和 `content`。
- **Symbols**: 调用 `MarketResolver` 获取。

### 2.3 抓取流程 (Scraper Loop)

1.  **启动/初始化**:
    - 查询 DB 获取最后一条 `futunn_` 前缀新闻的 `published_at`。
    - 如果 DB 为空，设定默认回填时间（如 30 天前）。

2.  **增量/回填循环**:
    - 调用 API 获取列表。
    - 遍历新闻条目：
        - 解析并转换。
        - 检查 `published_at`：
            - 如果 `> last_db_time`: 存入 DB。
            - 如果 `<= last_db_time`: 停止当前翻页（说明已追上），进入休眠。
    - 如果当前页所有新闻都比 `last_db_time` 新，且 `hasMore` 为真，使用 `seqMark` 继续翻页。
    - 休眠间隔：`FA_FUTUNN_SCRAPER_INTERVAL` (默认 60s)。

## 3. 数据模型映射

| Futu Field | NewsArticle Field | Note |
|------------|-------------------|------|
| `id` | `external_id` | Prefix with `futunn_` |
| `time` | `published_at` | Convert from Unix Timestamp |
| `title` | `title` | |
| `content` | `content` | |
| `detailUrl` | `url` | |
| `quote` | `symbols` | Via `MarketResolver` |
| (Fixed) | `type` | `stock_news` |
| `sourceId` | (Ignore/Log) | Optional: map specific IDs to `kol_tweet` |

## 4. 配置与环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `FA_FUTUNN_SCRAPER_INTERVAL` | `60` | 轮询间隔(秒) |
| `FA_STOCK_API_URL` | `http://stock-api:3000` | Stock API 地址 |
| `FA_LOG_LEVEL` | `INFO` | 日志级别 |

## 5. 实施计划

1.  **Scaffold**: 创建目录结构和基础文件。
2.  **Dependencies**: 添加 `httpx`, `tenacity` 到 `pyproject.toml`。
3.  **Implement Resolver**: 编写 `market_resolver.py` 并测试 `stock-api` 集成。
4.  **Implement Scraper**: 编写核心抓取逻辑。
5.  **Integration**: 编写 `main.py` 并配置 `docker-compose.yml` (如有需要，用户未提及 Docker Compose 修改，但通常需要)。

## 6. 约束检查
- [x] 使用 `finance-shared`。
- [x] 符合 Monorepo 结构。
- [x] 解决 `.US` 映射问题。
