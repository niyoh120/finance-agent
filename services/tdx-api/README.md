# tdx-api

独立的通达信（TDX）行情查询服务（FastAPI）：直连公开通达信行情服务器，向调用方提供结构化 JSON。本服务持有全部协议复杂度（握手、二进制编解码、多服务器切换、复权），消费端只需 HTTP。

- 覆盖：A 股（沪深）、港美股主板/创业板、国际/香港指数、境内五大期货交易所、纽约 COMEX/NYMEX、芝加哥 CBOT、上海黄金交易所现货递延
- 运行依赖仅 `fastapi` + `uvicorn`：协议层为纯标准库实现（socket/struct/zlib），无 easy-tdx / pytdx / pandas 依赖
- 上游为公开行情端口，服务无状态：全部数据为有界进程内缓存，无落盘

## 为什么独立服务

- **协议复杂度单点持有**：三类协议（标准 TDX / MAC / MAC EX）、帧编解码、字节级容错、QFQ 复权都在服务内消化；消费端拿到的就是干净 JSON。
- **上游即公开免费端口**：无需账号凭据；服务内置候选主机池（可覆盖）与主机健康缓存，单台失效自动切换。
- **消费端已迁移**：`openbb_finance/` 的 `TdxSource` 现以 HTTP 消费本服务（`sources.tdx.base_url` 门控），运行依赖已不含 easy-tdx；本服务独立部署、独立发版。

## 快速开始

```bash
# 本地运行（默认 127.0.0.1:8011）
mise run tdx-api

# 或 Docker
mise run docker-build-tdx-api
```

```bash
curl http://127.0.0.1:8011/healthz
curl http://127.0.0.1:8011/api/v1/markets
curl "http://127.0.0.1:8011/api/v1/klines?market=cn_sh&code=600000&interval=1d&adjust=qfq&limit=10"
```

## API 一览（前缀 `/api/v1`，全部只读）

| 路径 | 输入 | 说明 |
|---|---|---|
| `GET /markets` | — | 市场清单、协议市场码、时区/币种、能力矩阵 |
| `GET /quotes` | `market`、`codes`（逗号分隔，≤80） | 批量实时报价（价格/量额/买卖一档/量比等） |
| `GET /klines` | `market`、`code`、`interval`、`adjust`、`offset`、`limit` | K 线；周期 1m/5m/15m/30m/60m/1d/1w/1M；复权 none/qfq（按市场能力） |
| `GET /instruments` | `market`、`offset`、`limit` | 标的目录分页（服务端分页，保留服务端原始代码） |
| `GET /instruments/search` | `market`、`query`、`offset`、`limit` | 代码/名称子串搜索（目录完整性见 meta） |
| `GET /instruments/info` | `market`、`code` | 单标的名称与基础元信息（不存在时 `data=null`） |
| `GET /intraday` | `market`、`code`、`date?` | 当日/历史分时（含均价） |
| `GET /transactions` | `market`、`code`、`date?`、`offset`、`limit` | 逐笔成交（协议原生倒序：最新在前） |
| `GET /finance` | `market`、`code` | A 股基础财务快照（单位：万元/万股） |
| `GET /xdxr` | `market`、`code` | A 股除权除息历史 |
| `GET /status` | — | 协议组就绪状态、最近连接结果、预算摘要 |
| `GET /healthz` | — | 存活探针（前缀外，恒公开，与上游可用性分离） |

响应统一封装 `{"data": ..., "meta": {...}}`；列表型端点 meta 含 `offset/limit/next_offset/complete` 分页语义。缺失值为 `null`，零值保留；NaN/Infinity 在编码边界转 `null`。

## 市场标识与能力矩阵

`market` 使用服务自有标识（`/markets` 返回全部 16 个）：

| market | 说明 | 协议 | 逐笔 | 分时 | 目录 | qfq |
|---|---|---|---|---|---|---|
| `cn_sh` / `cn_sz` | 沪深 A 股 | standard + mac | ✓ | ✓ | ✓ | server + 本地 XDXR 兜底 |
| `hk` / `hk_gem` | 港股主板/创业板 | mac_ex | ✓ | ✓ | ✓ | server |
| `us` | 美股 | mac_ex | ✓ | ✓ | ✓ | server |
| `intl_index` / `hk_index` | 标普/道指/纳指/纳100；恒指/国企/恒科技 | mac_ex | hk_index ✓ | ✓ | ✓ | — |
| `shfe` / `dce` / `czce` / `cffex` / `gfex` | 境内期货 | mac_ex | ✓ | ✓ | cffex ✗* | — |
| `comex` / `nymex` / `cbot` | 外盘期货 | mac_ex | ✓ | ✓ | ✓ | — |
| `sge` | 上海黄金现货递延 | mac_ex | ✗ | ✗ | ✓ | — |

\* CFFEX 合约不在扩展市场全局目录中（上游目录缺失），行情/K 线/逐笔仍可用；`/instruments` 对 cffex 返回 422 `unsupported_capability`。

矩阵之外的能力组合（如 `sge` 请求分时、`shfe` 请求 qfq）返回 422 `unsupported_capability`。

## 代码约定

- `code` 为**通达信原生代码**：A 股 6 位数字（`600000`，可带 `.SH`/`.SZ` 后缀自动剥离）；港股 5 位（`00700`，不足补零）；指数别名已映射（`SPX`→`A_SPX`、`HSCEI`→`HZ5014`）；期货主连/月合约用原生代码（`RBL8`、`IFL0`、`GC26Z`、`GC00W`）；SGE 原生名大小写敏感（`Au(T+D)`）。
- `offset=0` 表示最近一段；响应时间正序；`next_offset` 供续页。K 线满页时 `complete=false`（上游无法证明已到历史尽头）。
- K 线日线及以上返回交易日期（`YYYY-MM-DD`）；分钟线返回本地时间戳（区间起点，meta.`time_semantics=interval_start`）。交易日与自然日分别保留（`trade_date`），夜盘跨自然日场景以协议日期为准。

## 时区与单位（诚实标注）

- 协议仅提供交易所当地墙钟时间且无时区字段。CN/港/境内外期货/SGE 交易墙钟与 `Asia/Shanghai` 一致（港市 UTC+8 无夏令时）；**美股时区缺少可复核证据，矩阵显式标 `null`（未知）**。
- 成交量单位仅在参考实现验证过的场景标注：CN K 线=股、CN 报价=手（`lot_size=100`）、HK K 线=手（每手股数因标的而异，`lot_size=null`）、US K 线=股；其余标 `null`，**不做未经核验的倍数换算**。
- 财务快照单位：万元（CNY）/ 万股（meta.`units`）。

## QFQ 前复权

- A 股优先使用服务端 QFQ 并做价格质量检查（OHLC 非正/非有限即异常）；异常时自动补取原始 K 线与 XDXR 记录本地重算，meta.`adjustment_source` 标注 `server` 或 `local_xdxr`，`adjustment_events` 为参与事件数。
- 本地重算锚定最新有效交易日：取覆盖请求区间到锚点的原始窗口，因子 = (含权收盘 − 每股分红 + 配股价×配股比) / (含权收盘 × (1 + 送转比 + 配股比))，逐事件由原始含权收盘计算并连乘。周/月线在**日线复权后聚合**（标签=周期内最后交易日）；分钟线按交易日应用因子。
- 除权日停牌、无事件、缺失前收盘、非法分母等边界显式处理：无法完成复权时返回 502 `adjustment_unavailable`（不做静默跳过）。无公司行动必须是成功且明确的 XDXR 查询结果。
- 港美 QFQ 走服务端能力（质量检查异常同样 502）；期货/SGE/指数首版仅原始序列。

## 资源预算与并发

| 项 | 默认 | 环境变量 |
|---|---|---|
| 请求总预算 | 30s | `FA_TDX_REQUEST_BUDGET_SECONDS` |
| 单次连接 | 3s | `FA_TDX_CONNECT_SECONDS` |
| 单次读写 | 5s | `FA_TDX_IO_SECONDS` |
| 主机切换上限 | 2 | `FA_TDX_MAX_HOST_SWITCHES` |
| 上游并发 | 8 | `FA_TDX_MAX_CONCURRENCY` |
| 排队等待 | 1s（超限 429） | `FA_TDX_QUEUE_WAIT_SECONDS` |
| 单页返回上限 | 1000 | `FA_TDX_MAX_PAGE_LIMIT` |
| 目录缓存条目上限 | 30000/市场 | `FA_TDX_DIRECTORY_MAX_ENTRIES` |

- 请求级会话：每个请求独占上游 socket，结束即关闭；连接级故障按候选主机顺序切换并重放（读命令幂等）；预算耗尽 504，全部主机不可用 503，协议/数据质量错误 502。
- 目录、XDXR、主机选择均有界 TTL 缓存（默认 300s，`FA_TDX_CACHE_TTL_SECONDS`）。
- 错误响应统一 `{"error": {"code", "message"}}`：`unsupported_capability`/`invalid_parameter`(422)、`upstream_data_error`/`adjustment_unavailable`(502)、`upstream_unavailable`(503)、`budget_exceeded`(504)、`concurrency_saturated`(429)。

## 安全

- 可选 `X-API-Key`：设置 `FA_TDX_API_KEY` 后所有 `/api/v1/*` 验证（安全字符串比较），`/healthz` 恒公开。
- host/port 只来自管理员配置与内置候选池，查询参数不携带地址；帧解析有魔数/声明长度/精确读取校验，拒绝截断/畸形帧。
- **内网部署假设**：上游为公开明文行情端口，服务本身无 TLS。远程部署务必启用 API Key 并置于 TLS 反代之后。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `FA_TDX_HOST` / `FA_TDX_PORT` | `127.0.0.1` / `8011` | 监听地址（Compose 内绑 `0.0.0.0`） |
| `FA_TDX_API_KEY` | 未设置 | 可选共享密钥 |
| `FA_TDX_HOSTS_STANDARD` / `FA_TDX_HOSTS_MAC` / `FA_TDX_HOSTS_MAC_EX` | 内置池 | 逗号分隔候选主机覆盖 |
| 其余 | 见上表 | 预算/并发/缓存 |

## 受阻与跳过的检查

- **历史记录（easy-tdx 依赖仍在消费端时）**：`uv sync --all-packages` 与 `mise run hooks-install` 曾被供应链问题阻断——easy-tdx 1.20.6 的镜像 wheel URL 已 404。当时按计划保留锁文件原样、未手造哈希。消费端迁移移除 easy-tdx 后，`uv sync --all-packages` 已实测恢复正常，此条目仅作历史留存。
- **消费端回归**：迁移后由 `mise run openbb-finance-test`（消费端全套离线测试，含跨包 ASGI 契约用例）与 `mise run tdx-api-test`（本服务离线全套）共同覆盖。
- **诚实标注的未验证字段**：美股墙钟时区、港股报价成交量单位、境内外期货/SGE/指数成交量单位缺少可复核证据，能力矩阵显式标 `null`，不做未验证倍数换算；CFFEX 目录缺失（上游目录无此市场，行情/K线/逐笔可用）。

## 测试

```bash
mise run tdx-api-test        # 离线全套（协议黄金字节/回放/QFQ/查询/HTTP）
mise run tdx-api-check       # 离线全套 + ruff check/format
mise run tdx-api-test-live   # 显式连真实行情服务器的冒烟（小规模）
```

- 离线套件包含：请求帧与参考实现（easy-tdx 锁定版本，独立环境生成）的逐字节黄金对照、本地 TCP 服务端驱动生产 transport 的压缩/断包/截断/超时回放、手工推导的 QFQ 复权样例、查询编排与 HTTP 错误映射。
- live 套件每市场一只代表标的的小规模请求；对上游可用性敏感，失败时先怀疑网络/服务器。

## 协议来源与许可

协议层移植自 `niyoh120/easy_tdx`（批准参考提交 `e374a0da2834119ac695c1083805d1b0a60967c2`；移植对照工作副本为移植时记录的参考版本 easy-tdx 1.20.6 wheel，当时的锁定哈希一致；该依赖现已自 workspace 移除，记录保留作来源证据），并按本服务边界修改（请求级预算会话、帧硬上限、去 pandas/numpy、错误体系拆分）。溯源与逐文件说明见 `THIRD_PARTY_NOTICES.md`；原始 LICENSE 见 `licenses/easy-tdx-LICENSE`（MIT，含 pytdx/xmtdx 血统声明）。
