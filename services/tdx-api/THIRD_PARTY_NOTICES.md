# 第三方代码溯源声明（THIRD_PARTY NOTICES）

本服务 `src/tdx_api/tdx/` 协议层移植自开源项目 **easy-tdx**（GitHub:
`niyoh120/easy_tdx`），并按本服务的工程边界做了修改。easy-tdx 本身衍生自
pytdx / xmtdx（均为 MIT）。原始项目的 LICENSE 副本与版权声明保留在本目录
`licenses/easy-tdx-LICENSE`。

## 参考版本

- **批准参考提交**：`niyoh120/easy_tdx@e374a0da2834119ac695c1083805d1b0a60967c2`
- **实际对照工作副本**：PyPI `easy-tdx` 1.20.6 wheel（同一上游项目的发布物，
  与上述提交同源；移植时逐文件审阅其解包源码）。
- 上游项目协议字节常量（握手、命令模板）本身来自 pytdx 并已在真实
  通达信服务器上验证；本服务保持这些字节逐字不变。

## 移植范围（按命令最小依赖闭包）

| 本服务文件 | 参考来源 | 说明 |
|---|---|---|
| `tdx/codec/primitives.py` | `_binary.py`、`codec/price.py`、`codec/volume.py`、`codec/datetime_.py` | varint/自定义浮点/时间解码；异常类型改为服务内 `TdxDecodeError` |
| `tdx/codec/frame.py` | `codec/frame.py`、`codec/mac_frame.py` | 帧构建/解析；新增解压硬上限（4 MiB / 16 MiB）与命令码回显提取 |
| `tdx/commands/base.py` | `commands/base.py` | 帧标识参数化（MAC 0x1C / MAC EX 0x01） |
| `tdx/commands/standard/setup.py` | `commands/setup.py` | 三条握手命令字节逐字保留 |
| `tdx/commands/standard/securities.py` | `commands/security_count.py`、`commands/security_list.py` | GBK errors='replace' 与自定义浮点昨收（上游 Bug #2/#3 修复）保留 |
| `tdx/commands/standard/fundamentals.py` | `commands/finance_info.py`、`commands/xdxr_info.py` | 逐条读取修复（Bug #1）、每 10 股→每股归一化保留 |
| `tdx/commands/mac/bitmap.py` | `codec/bitmap.py` | 仅保留本服务报价字段子集（QUOTE_FIELDS） |
| `tdx/commands/mac/symbols.py` | `mac/commands/symbol_bar.py`、`symbol_quotes.py`、`symbol_info.py`、`symbol_transaction.py`、`symbol_tick_chart.py` | 解析逻辑与越界保护逐项对齐；分时图 0x122D 经实况验证后替代标准协议分时命令 |
| `tdx/commands/ex/extended.py` | `ex/commands/login.py`、`get_instrument_count.py`、`get_instrument_info.py`、`get_minute_time.py`、`get_transaction.py` | 登录体 80 字节常量逐字保留；港股价格 ÷1000 语义保留 |
| `tdx/transport.py` | `transport/sync.py`、`ex/transport/sync.py` | 去除心跳/健康分/全局配置；新增请求级预算（deadline）、解压上限校验、回显校验 |
| `tdx/hosts.py` | `config.py`（内嵌候选池） | 候选主机表缩小为参考池子集；主机选择改为进程内 TTL 缓存 + 并发探测 |
| `tdx/adjust.py` | `mac/adjust.py` | 去 pandas/numpy；锚定/含权基准/非法因子语义逐项保留，新增因子链构建 |

## 主要修改点（相对参考实现）

1. **传输边界**：请求级会话（无后台心跳/自动重连），所有 IO 受请求总预算
   约束；响应帧新增魔数、声明长度硬上限与命令码回显校验。
2. **异常体系**：参考实现的单一错误类拆分为连接/超时/解码/协议四类，
   分别驱动「换主机重试 / 立即失败」的差异化策略。
3. **无第三方运行依赖**：pandas/numpy 的 DataFrame 逻辑改为纯 dataclass/dict。
4. **未移植**：技术指标、缠论、回测、板块、文件下载、离线行情、Web/UI、
   异步变体、标准协议 bars/quotes 命令（A 股行情走 MAC 会话），以及标准协议
   分时/逐笔命令（实况验证发现部分真实服务器对 0x051d/0x0fc5 返回与 pytdx
   文档不一致的响应体，改走 MAC 0x122D/0x122F，见 `commands/standard/__init__.py`）。

## 授权

本服务协议层遵循上游 MIT 许可证发布；完整许可证文本见
`licenses/easy-tdx-LICENSE`。
