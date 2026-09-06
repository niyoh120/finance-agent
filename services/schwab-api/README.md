# schwab-api

独立的 Schwab Trader API 数据服务（FastAPI）：统一对外提供 Schwab 市场数据 REST 接口（OpenBB 风格路由），内置 OAuth 授权单页 UI 与 refresh token 轮换感知定时保活。本服务是 `FA_SCHWAB_*` 凭据与 token 的**唯一持有者**，其他服务一律通过 HTTP 访问。

## 为什么要独立服务

- **schwabdev 4.x 的 7 天过期缺陷**：schwabdev 每次刷新 access token 时会把轮换出的新 refresh token 入库，但 `refresh_token_issued` 时间戳仍停留在首次授权时刻——7 天后必然强制浏览器重授权。本服务内置保活循环，用 `refresh_token` grant 自行轮换并把**双 issued 时间戳重置为 now**，只要服务活着就无限续命。
- **无头容器无法走 schwabdev 内置授权流**：无 token 时 schwabdev 会弹浏览器+stdin 阻塞等待。本服务自实现 authorization_code 交换并写库，通过 Web UI 完成授权；`schwabdev.Client` 只在 token 就绪后 lazy 构造，且注入 `call_on_auth` 阻断任何交互式授权路径。
- **凭据单点持有**：token 存本服务独占的 sqlite（schema 与 schwabdev 4.x 完全兼容，表 `schwabdev` 8 列单行，可选 Fernet 加密），避免凭据散落多个进程。

## Schwab App 申请（一次性）

1. 到 [developer.schwabapi.com](https://developer.schwabapi.com) 注册并创建 App。
2. Callback URL 填 `https://127.0.0.1`（https、无尾斜杠，与本服务 `FA_SCHWAB_CALLBACK_URL` 完全一致）。
3. 同时勾选 **Market Data Production** 与 **Accounts and Trading Production** 产品。
4. 等 App 状态变为 **Ready For Use**，记下 App key（`FA_SCHWAB_APP_KEY`）与 App secret（`FA_SCHWAB_APP_SECRET`）。

## 快速开始

```bash
# 本地运行（默认 127.0.0.1:8010）
export FA_SCHWAB_APP_KEY=... FA_SCHWAB_APP_SECRET=...
mise run schwab-api

# 或 Docker
mise run docker-build-schwab-api
```

打开 `http://127.0.0.1:8010/` 完成授权，两种方式任选：

**方式 A：浏览器自动回调（有 https 域名/证书时推荐）**

1. Schwab App 注册的 Callback URL 填 `https://<你的域名>/api/v1/auth/redirect`（https、与配置完全一致）；
2. `FA_SCHWAB_CALLBACK_URL=https://<你的域名>/api/v1/auth/redirect`；
3. 反向代理把该路径转发到 `127.0.0.1:8010`；
4. UI 点登录 → Schwab 登录同意后浏览器直接落在本服务端点，自动完成交换并显示结果。

注意：修改已处于 Ready For Use 的 App 的回调地址通常会触发重新审核，填一次就要填对。

**方式 B：手动粘贴（无公网/无域名，零依赖）**

OAuth code 落在浏览器地址栏，走人工复制，无需任何公网入口：

1. UI 点"打开 Schwab 登录页"→ 新窗口登录并同意；
2. 浏览器跳转到打不开的 `https://127.0.0.1/?code=...`（正常现象），复制地址栏完整 URL；
3. 30 秒内粘贴回页面并提交——authorization code 有效期仅 30 秒。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `FA_SCHWAB_APP_KEY` | 必填 | Schwab App key |
| `FA_SCHWAB_APP_SECRET` | 必填 | Schwab App secret |
| `FA_SCHWAB_CALLBACK_URL` | `https://127.0.0.1` | 必须与 App 注册的回调一致；https 开头、无尾斜杠 |
| `FA_SCHWAB_TOKENS_DB` | `~/.schwabdev/tokens.db` | token sqlite 路径（容器内挂 `/data/tokens.db`） |
| `FA_SCHWAB_TOKENS_ENCRYPTION` | 空 | 可选 Fernet key，token 落盘加密（`enc:` 前缀，与 schwabdev 兼容） |
| `FA_SCHWAB_HOST` | `127.0.0.1` | 监听地址；容器内运行需设 `0.0.0.0`，对外暴露面由端口映射限制 |
| `FA_SCHWAB_PORT` | `8010` | 监听端口 |
| `FA_SCHWAB_API_KEY` | 空 | 可选；设置后 9 个数据接口要求 `X-API-Key` 头，auth/status/health 豁免 |
| `FA_SCHWAB_KEEPALIVE_INTERVAL_HOURS` | `12` | 保活轮换周期（小时） |

## API

### 数据接口（透传 Schwab 原始 JSON）

| 端点 | 说明 |
|---|---|
| `GET /api/v1/equity/price/quote?symbols=&fields=&indicative=` | 实时/延时报价，symbols 逗号分隔 |
| `GET /api/v1/equity/price/historical?symbol=&interval=&start=&end=&extended=` | K 线；interval ∈ `1m 5m 10m 15m 30m 1d 1w 1M`；start/end 为 ISO 日期或日期时间（裸日期按 UTC 午夜，转 epoch ms） |
| `GET /api/v1/equity/search?symbol=&projection=` | 代码搜索（symbol-search / desc-search / …） |
| `GET /api/v1/equity/fundamental?symbol=` | 基本面（projection=fundamental） |
| `GET /api/v1/equity/cusip?cusip=` | CUSIP 查询 |
| `GET /api/v1/equity/movers?index=&sort=&frequency=` | 指数异动（仅盘中有效） |
| `GET /api/v1/options/chains?symbol=&contract_type=&dte=&range=&…` | 期权链；snake_case 自动映射 Schwab camelCase |
| `GET /api/v1/options/expirations?symbol=` | 期权到期日列表 |
| `GET /api/v1/market/hours?markets=&date=` | 开休市安排，markets 逗号分隔 |

未认证时数据接口返回 **503**；Schwab 侧错误原样透传状态码与 body；schwabdev 参数校验失败返回 422。

### 运维接口（免 API key）

| 端点 | 说明 |
|---|---|
| `GET /healthz` | 进程存活即 200（重启解决不了未授权，去 UI 登录才是正解） |
| `GET /api/v1/status` | authenticated / token TTL / 保活 last_refresh / last_error |
| `POST /api/v1/auth/start?force=` | 返回 authorize URL；已有有效 token 时 409；响应含 auto_redirect 标志 |
| `POST /api/v1/auth/callback` | body `{"callback": "完整回调 URL 或原始 code"}`，交换失败透传 Schwab 错误 |
| `GET /api/v1/auth/redirect` | 浏览器自动回调落点（`?code=`），立即交换并返回结果页 |

## 保活机制

保活循环（asyncio 后台任务）每个周期检查一次：token 存在且距上次轮换 ≥ 周期时，在 sqlite `BEGIN EXCLUSIVE` 事务内完成"读最新 refresh token → POST token 端点 → 新 token + 双 issued=now 落库"。

- EXCLUSIVE + `busy_timeout=30s` 与 schwabdev 的自动刷新互斥，跨进程安全；schwabdev 侧在锁内先重读库，永远拿到最新轮换值。
- 轮换请求失败（网络/invalid_grant）：事务回滚，**旧 token 原样保留**，错误记入 `/api/v1/status` 的 `last_error` 并在 UI 展示，按指数退避重试。
- 已知残余风险：POST 成功后、commit 前进程崩溃 → 新旧 refresh token 双双失效，需重新走 UI 授权。窗口极小，UI 重授权兜底。

## 限流与边界

- Schwab REST 全局限流 **120 req/min**（schwabdev 对 GET 内置 429/5xx 重试）。
- 期权链不设防时会触发 Schwab "Body buffer overflow"，大链（如 SPY）务必带 `dte`/`strike_count`/`range` 过滤。
- movers 仅盘中有效；指数报价需 `indicative=true`，且 Schwab 符号体系有差异（如 `$SPX.X`）。

## 数据质量评估

实测时间 2026-09-06（美东周日盘外，次日 Labor Day 休市），真实凭据端到端。

### K 线（pricehistory）

- **单次响应硬上限 40,000 根 candles**，超出从最早一侧静默截断：请求 90/180 天窗口均返回整 40,000 根。长窗口需自行用 `start` 分页。
- 分钟线 40,000 根 ≈ 33 个交易日（含盘前盘后）；30 天窗口实测 25,725 根。
- 日线深度 **≥25 年**（2001-09 至今，6,283 根）；weekly 20 年 1,043 根；monthly 25 年 300 根。
- **关键坑（已修复）**：日期区间查询 + 显式 `frequencyType` 时，Schwab 默认 `periodType=DAY`，而 DAY 仅允许 minute——daily/weekly/monthly 直接 400 "Invalid frequencyType DAILY for periodType DAY"。必须显式带 `periodType=year`（服务端 `INTERVAL_MAP` 已处理并有测试回归）。
- 盘前盘后：`extended=true` 单交易日 ~970 根分钟线（04:00–20:00 ET）vs regular 390 根。
- 边界语义：窗口起点可能带入前一交易日尾段 bar（按 bar 落窗过滤）。
- Schwab 侧 `startDate` 只收 epoch ms，直传 ISO 字符串会 400 "StartDate must be miliseconds from epoch"；本服务已做转换。

### 报价（quotes）

- 延迟：单标的 0.3–0.7s；100 个符号批量 0.44s（批量共享单次 Schwab 请求）。
- 无效符号以 `200 + {"errors":{"invalidSymbols":[...]}}` 随正常数据一并返回，消费方需检查 errors 字段。
- **指数符号：`$SPX` / `$COMPX` / `$DJI`（带 `$` 前缀、无 `.X` 后缀）有效**；旧格式 `$SPX.X` 已失效返回 invalidSymbols；指数需 `indicative=true`。
- 盘外 `isDelayed` 为 null，`quoteTime` 停留在最后成交。

### 期权链（chains）

- SPY 全链（无过滤）触发 Schwab 网关 "Body buffer overflow"，本服务原样透传为 502——**大链必须带过滤参数**：`strike_count=5` → 396KB 正常；`strike_count=10` → 791KB/680 合约；AAPL `dte=7&strike_count=5` → 280KB/240 合约/0.6s。
- 字段完整率（盘外快照，480 合约 × 54 字段）：`markChange`/`markPercentChange`/`mini`/`nonStandard` 全空（盘外正常）；`bid`/`ask`/`last`/`quoteTime` ~8% 缺失（深度虚值合约）；`inTheMoney` 50% null。盘中快照预计更完整，待交易日复测。
- 到期日：响应为 `expirationList` 新结构（非旧文档的 `expirationDates`），AAPL 24 个（2026-09-09 → 2028-12-15）。

### 其他

- **market hours**：正确反映节假日（Labor Day 周一闭市）；注意内层 product 键名不固定（`"equity"` / `"EQ"`），消费方应遍历取值而非硬编码键。
- **movers**：盘外返回 `200 + {"screeners":[]}`（静默空而非报错）；盘中可用性待交易日验证。
- **限流**：实测 ~170 req/min（127 连发/45s）全部 200、无 429、无延迟劣化（schwabdev 对 429 内置重试）；官方文档 120 req/min 未复现触发，应为带突发容忍的令牌桶，勿依赖超额配额。

### 保活

- 首次轮换实测：授权后 keepalive 触发 `refresh_token` grant，refresh TTL 重置回 604,764s（≈7.0 天）、`last_error` 空、期间数据接口连续可用——**schwabdev 7 天强制重授权缺陷确认修复**。

## 部署

见 [compose.example.yml](./compose.example.yml)：挂载 token 目录后，授权一次、重启无需再授权；healthcheck 走 `/healthz`（slim 镜像无 curl，用 python urllib）。

## 回滚

本服务零共享包依赖（仅 uv workspace 成员）：下线容器/进程 + 从 `pyproject.toml` workspace members 移除即完全回退，其余服务数据面回到现状。

## 开发

```bash
uv run --package schwab-api pytest services/schwab-api/tests -q   # 服务测试
uvx ruff check services/schwab-api && uvx ruff format --check services/schwab-api
```

测试关键哨兵：`tests/test_store.py` 用 `schwabdev.Tokens` 直接加载本服务写入的 token 库（锁 `schwabdev>=4,<5`，schema 兼容回归）；`tests/test_keepalive.py` 回归轮换后 `refresh_token_issued == now` 与失败回滚路径。
