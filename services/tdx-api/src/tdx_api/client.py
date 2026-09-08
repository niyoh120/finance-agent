"""查询层：组合三类协议会话，实现业务查询并产出 JSON 安全的 {data, meta}。

职责边界（按批准计划）：
- 请求级会话：每个查询经 ``_run`` 打开独占连接，结束即关闭；
  连接级故障按候选主机有界切换并重放整段幂等查询，预算耗尽转 504。
- 能力矩阵约束：不支持的组合抛 ``UnsupportedCapabilityError``（422）。
- 分页：offset=0 表示最近一段，响应时间正序；``next_offset``/``complete``
  显式声明分页状态（上游无法证明完整性时 complete=false）。
- 单位/时区：仅声明已验证的单位，未验证的显式 null；缺失值 null，零值保留，
  NaN/Infinity 在编码边界转为 null。
- QFQ：A 股先取服务端 QFQ 并做价格质量检查，异常时补取原始 K 线与 XDXR
  本地重算（``adjustment_source=local_xdxr``）；详见 ``tdx.adjust`` 与 README。
"""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import date as _date
from datetime import datetime, timezone
from typing import Callable, TypeVar

from .cache import TTLCache
from .concurrency import BoundedGate
from .config import Config
from .errors import (
    AdjustmentUnavailableError,
    BudgetExceededError,
    InvalidParameterError,
    UpstreamUnavailableError,
)
from .markets import (
    HK_INDEX_CODES,
    INTL_INDEX_CODES,
    SUPPORTED_INTERVALS,
    ApiMarket,
    MarketSpec,
    markets_payload,
)
from .tdx import Budget, TdxConnectionError, TdxTimeoutError, make_session_factory
from .tdx.adjust import (
    apply_factor_chain,
    build_factor_chain,
    extract_dividend_events,
    has_bad_prices,
)
from .tdx.commands.ex.extended import (
    GetExHistoryMinuteTimeDataCmd,
    GetExHistoryTransactionDataCmd,
    GetExInstrumentCountCmd,
    GetExInstrumentInfoCmd,
    GetExMinuteTimeDataCmd,
    GetExTransactionDataCmd,
)
from .tdx.commands.mac.symbols import (
    MAC_KLINE_PAGE_SIZE,
    MacSymbolBarCmd,
    MacSymbolInfoCmd,
    MacSymbolQuotesCmd,
    MacSymbolTickChartCmd,
    MacSymbolTransactionCmd,
)
from .tdx.commands.standard.fundamentals import XDXR_CATEGORY_NAMES, GetFinanceInfoCmd, GetXdxrInfoCmd
from .tdx.commands.standard.securities import GetSecurityCountCmd, GetSecurityListCmd
from .tdx.enums import Adjust, MacPeriod
from .tdx.hosts import BUILTIN_CANDIDATES, HostSelector
from .tdx.models import ExInstrumentInfo, MacQuote, MinuteBar, SecurityListEntry, Transaction, XdxrRecord
from .tdx.transport import Session, SessionFactory

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: API 周期 → MAC 族周期码。
INTERVAL_TO_PERIOD: dict[str, MacPeriod] = {
    "1m": MacPeriod.MIN_1,
    "5m": MacPeriod.MIN_5,
    "15m": MacPeriod.MIN_15,
    "30m": MacPeriod.MIN_30,
    "60m": MacPeriod.MIN_60,
    "1d": MacPeriod.DAILY,
    "1w": MacPeriod.WEEKLY,
    "1M": MacPeriod.MONTHLY,
}

#: 分钟级周期集合。
_MINUTE_INTERVALS = frozenset({"1m", "5m", "15m", "30m", "60m"})

#: 分钟线（MAC 0x122E）与分时图（0x122D）时间语义：协议时间为区间起点
# （实测 0x122D tick 量与 0x122E 分钟线量逐段对齐）。
KLINE_TIME_SEMANTICS = "interval_start"
#: A 股分时图（MAC 0x122D）时间语义：与分钟线同口径。
CN_INTRADAY_TIME_SEMANTICS = "interval_start"

#: 周月聚合的 bar 时间标签：周期内最后一个交易日。
PERIOD_LABEL = "trading_period_end"

#: 逐笔方向字段中 nature 的放大系数：direction = nature * 10000 + second。
_DIRECTION_NATURE_SCALE = 10000

#: MAC 0x122F 单页上限（参考实现默认值）。
_MAC_TRANSACTION_PAGE = 1000

#: 周月聚合内部取日线的日历日放大系数（覆盖节假日缺口）。
_WEEKLY_DAILY_RATIO = 8
_MONTHLY_DAILY_RATIO = 32
#: 内部补取日线的硬上限（受请求总预算约束，防止极端 offset 放大）。
_MAX_INTERNAL_DAILY_BARS = 4400

#: EX 目录二分探测/分页的页宽。
_EX_DIRECTORY_PAGE = 1000

#: 逐笔/分时方向语义（MAC/EX 原生；标准协议同口径）。
DIRECTION_LABELS = {0: "buy", 1: "sell", 2: "neutral", 5: "after_hours"}


def _f(value: object) -> float | None:
    """float 归一：None/空/非有限 → None；零值保留。"""
    if value is None:
        return None
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _i(value: object) -> int | None:
    f = _f(value)
    return int(f) if f is not None else None


def _normalize_code(spec: MarketSpec, code: str) -> str:
    """归一化并校验标的代码（通达信原生代码）。

    - 可选 ``.XX`` 后缀被剥离（如 600000.SH）。
    - CN：6 位数字；HK/GEM：数字补齐 5 位；SGE：原生名（如 Au(T+D)）；
      指数市场映射已确认的别名（SPX→A_SPX、HSCEI→HZ5014 等）。
    """
    value = code.strip()
    if spec.market == ApiMarket.SGE:
        # SGE 原生名大小写敏感（如 Au(T+D)），保留原样。
        return value
    if "." in value:
        value = value.partition(".")[0]
    if spec.std_market is not None:
        if not (len(value) == 6 and value.isdigit()):
            raise InvalidParameterError(f"CN 市场代码必须为 6 位数字: {code!r}")
        return value
    if spec.ex_market is None:  # pragma: no cover - 市场表保证
        raise InvalidParameterError(f"市场 {spec.market.value} 无协议市场码")
    if spec.market in (ApiMarket.HK, ApiMarket.HK_GEM):
        if not value.isdigit():
            raise InvalidParameterError(f"港股代码必须为数字: {code!r}")
        return value.zfill(5)
    if spec.market == ApiMarket.INTL_INDEX:
        upper = value.upper()
        return INTL_INDEX_CODES.get(upper, upper)
    if spec.market == ApiMarket.HK_INDEX:
        upper = value.upper()
        return HK_INDEX_CODES.get(upper, upper)
    return value.upper()


def _tail_slice(bars: list[dict], offset: int, limit: int) -> list[dict]:
    """从序列尾部取 [offset, offset+limit) 窗口（升序输入）。"""
    end = len(bars) - offset
    if end <= 0:
        return []
    start = max(end - limit, 0)
    return bars[start:end]


class RuntimeStatus:
    """最近连接结果（线程安全，每会话类型仅保留最近一次）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[str, dict] = {}

    def record_success(self, kind: str, host: str) -> None:
        with self._lock:
            self._state[kind] = {
                "last_host": host,
                "last_result": "ok",
                "last_error": None,
                "last_checked_at": datetime.now(timezone.utc).isoformat(),
            }

    def record_failure(self, kind: str, host: str, error: str) -> None:
        with self._lock:
            self._state[kind] = {
                "last_host": host,
                "last_result": "error",
                "last_error": error,
                "last_checked_at": datetime.now(timezone.utc).isoformat(),
            }

    def snapshot(self, selector: HostSelector) -> dict:
        with self._lock:
            state = {kind: dict(value) for kind, value in self._state.items()}
        for kind in BUILTIN_CANDIDATES:
            entry = state.setdefault(kind, {"last_host": None, "last_result": "never", "last_error": None})
            entry["has_cached_host"] = selector.has_fresh(kind)
        return state


class TdxService:
    """TDX 查询服务门面（线程安全）。"""

    def __init__(
        self,
        config: Config,
        *,
        selector: HostSelector | None = None,
        factory: SessionFactory | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        candidates = self._configured_candidates(config)
        self.selector = selector or HostSelector(
            candidates=candidates,
            ttl=config.cache_ttl_seconds,
            clock=clock,
        )
        self._factory = factory or make_session_factory()
        self._gate = BoundedGate(config.max_concurrency, config.queue_wait_seconds)
        self._xdxr_cache = TTLCache[dict](2000, config.cache_ttl_seconds, clock)
        self._directory_cache = TTLCache[tuple](64, config.cache_ttl_seconds, clock)
        self._status = RuntimeStatus()

    @staticmethod
    def _configured_candidates(config: Config) -> dict[str, tuple[tuple[str, ...], int]] | None:
        overrides: dict[str, tuple[tuple[str, ...], int]] = {}
        if config.hosts_standard:
            overrides["standard"] = (config.hosts_standard, BUILTIN_CANDIDATES["standard"][1])
        if config.hosts_mac:
            overrides["mac"] = (config.hosts_mac, BUILTIN_CANDIDATES["mac"][1])
        if config.hosts_mac_ex:
            overrides["mac_ex"] = (config.hosts_mac_ex, BUILTIN_CANDIDATES["mac_ex"][1])
        return overrides or None

    # ------------------------------------------------------------------ #
    # 会话执行骨架
    # ------------------------------------------------------------------ #

    def _new_budget(self) -> Budget:
        return Budget(
            total_seconds=self.config.request_budget_seconds,
            connect_seconds=self.config.connect_seconds,
            io_seconds=self.config.io_seconds,
        )

    def _run(self, kind: str, budget: Budget, fn: Callable[[Session], T]) -> T:
        """打开会话执行 fn；连接级故障按候选主机有界切换并重放。"""
        hosts, _port = self.selector.candidates_for(kind)
        max_attempts = min(1 + self.config.max_host_switches, len(hosts)) if hosts else 0
        last_error: Exception | None = None
        attempts = 0
        for host in hosts:
            if attempts >= max_attempts:
                break
            if budget.remaining() <= 0:
                raise BudgetExceededError("请求总预算耗尽") from last_error
            attempts += 1
            try:
                session = self._factory(kind, host, budget)
            except (TdxConnectionError, TdxTimeoutError) as e:
                self.selector.mark_bad(kind, host)
                self._status.record_failure(kind, host, e.__class__.__name__)
                last_error = e
                logger.warning("会话建立失败 kind=%s host=%s: %s", kind, host, e)
                continue
            try:
                result = fn(session)
            except (TdxConnectionError, TdxTimeoutError) as e:
                self.selector.mark_bad(kind, host)
                self._status.record_failure(kind, host, e.__class__.__name__)
                last_error = e
                logger.warning("会话执行失败 kind=%s host=%s: %s", kind, host, e)
                if isinstance(e, TdxTimeoutError) and budget.remaining() <= 0:
                    raise BudgetExceededError("请求总预算耗尽") from e
                continue
            finally:
                session.close()
            self.selector.mark_good(kind, host)
            self._status.record_success(kind, host)
            return result
        raise UpstreamUnavailableError(f"会话类型 {kind} 的候选主机均不可用（尝试 {attempts} 台）") from last_error

    # ------------------------------------------------------------------ #
    # 元数据
    # ------------------------------------------------------------------ #

    def _base_meta(self, spec: MarketSpec, **extra: object) -> dict:
        meta: dict = {
            "market": spec.market.value,
            "service_code": spec.service_code,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "timezone": spec.timezone,
            "currency": spec.currency,
        }
        meta.update(extra)
        return meta

    @staticmethod
    def _paging(count: int, offset: int, limit: int, exhausted: bool) -> dict:
        """分页元数据。

        exhausted=True 表示上游以短页/空页明确结束；count < limit 同样证明结束。
        count == limit 且未证明结束时 complete=false（上游无法证明完整性）。
        """
        return {
            "count": count,
            "offset": offset,
            "limit": limit,
            "next_offset": offset + count if count >= limit else None,
            "complete": exhausted or count < limit,
        }

    # ------------------------------------------------------------------ #
    # 市场清单
    # ------------------------------------------------------------------ #

    def markets(self) -> dict:
        """能力矩阵（无上游 IO）。"""
        now = datetime.now(timezone.utc).isoformat()
        return {"data": markets_payload(), "meta": {"count": len(ApiMarket), "fetched_at": now}}

    # ------------------------------------------------------------------ #
    # 报价
    # ------------------------------------------------------------------ #

    def quotes(self, spec: MarketSpec, codes: list[str]) -> dict:
        """单市场有界批量报价（协议单次上限 80 只，服务层自动拆批）。"""
        if not codes:
            raise InvalidParameterError("codes 不能为空")
        if len(codes) > self.config.quotes_batch_limit:
            raise InvalidParameterError(f"codes 单次最多 {self.config.quotes_batch_limit} 只")
        proto_codes = [_normalize_code(spec, c) for c in codes]
        market_code = _proto_market_code(spec)
        budget = self._new_budget()

        def run(session: Session) -> list[MacQuote]:
            rows: list[MacQuote] = []
            for start in range(0, len(proto_codes), self.config.quotes_batch_limit):
                chunk = proto_codes[start : start + self.config.quotes_batch_limit]
                cmd = MacSymbolQuotesCmd([(market_code, c) for c in chunk])
                rows.extend(session.execute(cmd))
            return rows

        quotes = self._gate.run(lambda: self._run(spec.protocol, budget, run))
        data = [self._quote_row(spec, q) for q in quotes]
        meta = self._base_meta(
            spec,
            count=len(data),
            requested=len(codes),
            volume_unit=spec.quote_volume_unit,
            lot_size=spec.lot_size,
        )
        return {"data": data, "meta": meta}

    @staticmethod
    def _quote_row(spec: MarketSpec, q: MacQuote) -> dict:
        f = q.fields

        def ymd(value: object) -> str | None:
            v = _i(value)
            return f"{v:08d}" if v else None

        def hms(value: object) -> str | None:
            v = _i(value)
            return f"{v:06d}" if v is not None and v >= 0 else None

        return {
            "market": spec.market.value,
            "code": q.code,
            "name": q.name or None,
            "price": _f(f.get("close")),
            "pre_close": _f(f.get("pre_close")),
            "open": _f(f.get("open")),
            "high": _f(f.get("high")),
            "low": _f(f.get("low")),
            "volume": _f(f.get("vol")),
            "amount": _f(f.get("amount")),
            "bid": _f(f.get("bid_price")),
            "ask": _f(f.get("ask_price")),
            "bid_volume": _i(f.get("bid_volume")),
            "ask_volume": _i(f.get("ask_volume")),
            "last_volume": _i(f.get("last_volume")),
            "volume_ratio": _f(f.get("vol_ratio")),
            "inside_volume": _i(f.get("inside_volume")),
            "outside_volume": _i(f.get("outside_volume")),
            "server_update_date": ymd(f.get("server_update_date")),
            "server_update_time": hms(f.get("server_update_time")),
        }

    # ------------------------------------------------------------------ #
    # K 线
    # ------------------------------------------------------------------ #

    def klines(self, spec: MarketSpec, code: str, interval: str, adjust: str, offset: int, limit: int) -> dict:
        """K 线查询（含 QFQ 路径）。offset=0 为最近一段，返回时间正序。"""
        if interval not in SUPPORTED_INTERVALS:
            raise InvalidParameterError(f"interval 必须为 {list(SUPPORTED_INTERVALS)} 之一")
        if adjust not in spec.adjust:
            from .errors import UnsupportedCapabilityError

            raise UnsupportedCapabilityError(f"市场 {spec.market.value} 支持的复权方式: {list(spec.adjust)}")
        proto_code = _normalize_code(spec, code)
        return self._gate.run(lambda: self._klines_impl(spec, proto_code, interval, adjust, offset, limit))

    def _klines_impl(
        self,
        spec: MarketSpec,
        code: str,
        interval: str,
        adjust: str,
        offset: int,
        limit: int,
    ) -> dict:
        budget = self._new_budget()
        if spec.std_market is not None:
            data, meta = self._klines_cn(spec, code, interval, adjust, offset, limit, budget)
        else:
            data, meta = self._klines_ex(spec, code, interval, adjust, offset, limit, budget)
        return {"data": data, "meta": meta}

    def _fetch_mac_bars(
        self,
        session: Session,
        market_code: int,
        code: str,
        period: MacPeriod,
        fq: Adjust,
        start: int,
        count: int,
    ) -> tuple[list[dict], bool]:
        """分页取 MAC K 线（升序），返回 (bars, exhausted)。

        页内升序、页间向更深处推进；较深的页更新，故前插保持全局升序。
        """
        bars: list[dict] = []
        offset = start
        fetched = 0
        exhausted = False
        while fetched < count:
            page_size = min(count - fetched, MAC_KLINE_PAGE_SIZE)
            page = session.execute(MacSymbolBarCmd(market_code, code, period, 1, offset, page_size, fq))
            if not page:
                exhausted = True
                break
            bars = [_mac_bar_row(b) for b in page] + bars
            fetched += len(page)
            offset += len(page)
            if len(page) < page_size:
                exhausted = True
                break
        return bars, exhausted

    def _fetch_xdxr_records(self, spec: MarketSpec, code: str, budget: Budget) -> list[dict]:
        """取 XDXR 记录（标准会话，TTL 缓存；仅缓存成功且明确的查询）。"""
        assert spec.std_market is not None
        key = f"{int(spec.std_market)}:{code}"
        cached = self._xdxr_cache.get(key)
        if cached is not None:
            return cached["records"]
        try:
            records = self._run("standard", budget, lambda s: s.execute(GetXdxrInfoCmd(spec.std_market, code)))
        except UpstreamUnavailableError as e:
            # 行情已在手但复权记录取不到：按计划映射为 adjustment_unavailable。
            raise AdjustmentUnavailableError("无法获得 XDXR 记录（标准协议上游不可用）") from e
        payload = {
            "records": [_xdxr_internal(r) for r in records],
            "query_ok": True,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        self._xdxr_cache.set(key, payload)
        return payload["records"]

    def _klines_cn(
        self,
        spec: MarketSpec,
        code: str,
        interval: str,
        adjust: str,
        offset: int,
        limit: int,
        budget: Budget,
    ) -> tuple[list[dict], dict]:
        """A 股 K 线：服务端 QFQ 优先 + 质量检查 + XDXR 本地重算兜底。"""
        assert spec.std_market is not None
        market_code = int(spec.std_market)
        period = INTERVAL_TO_PERIOD[interval]

        source = "server" if adjust == "qfq" else None
        events_count: int | None = None
        bars: list[dict] = []
        exhausted = False

        if adjust == "qfq":
            server_bars, server_exhausted = self._run(
                "mac",
                budget,
                lambda s: self._fetch_mac_bars(s, market_code, code, period, Adjust.QFQ, offset, limit),
            )
            if not server_bars:
                bars, exhausted = server_bars, server_exhausted
            elif not has_bad_prices(server_bars):
                bars, exhausted = server_bars, server_exhausted
            else:
                # 服务端 QFQ 异常（如深度历史负价）：补取原始 K 线 + XDXR 本地重算。
                bars, exhausted, events_count = self._cn_local_qfq(spec, code, interval, offset, limit, budget)
                source = "local_xdxr"
        else:
            bars, exhausted = self._run(
                "mac",
                budget,
                lambda s: self._fetch_mac_bars(s, market_code, code, period, Adjust.NONE, offset, limit),
            )

        data = [_bar_payload(b, interval) for b in bars]
        meta = self._base_meta(
            spec,
            interval=interval,
            adjust=adjust,
            adjustment_source=source,
            adjustment_events=events_count,
            volume_unit=spec.kline_volume_unit,
            time_semantics=KLINE_TIME_SEMANTICS if interval in _MINUTE_INTERVALS else None,
            period_label=PERIOD_LABEL if interval in ("1w", "1M") else None,
        )
        meta.update(self._paging(len(data), offset, limit, exhausted))
        return data, meta

    def _cn_local_qfq(
        self,
        spec: MarketSpec,
        code: str,
        interval: str,
        offset: int,
        limit: int,
        budget: Budget,
    ) -> tuple[list[dict], bool, int]:
        """A 股本地前复权重算：原始 K 线 + XDXR。

        - 1d：取 [0, offset+limit) 原始日线（覆盖到最新锚点），复权后切尾。
        - 1w/1M：原始日线复权后再聚合周/月线（计划要求）。
        - 分钟线：以原始日线构建因子链，按交易日应用到分钟 bar。
        """
        assert spec.std_market is not None
        market_code = int(spec.std_market)
        records = self._fetch_xdxr_records(spec, code, budget)
        events = extract_dividend_events(records)

        if interval == "1d":
            window_count = min(offset + limit, _MAX_INTERNAL_DAILY_BARS + MAC_KLINE_PAGE_SIZE)
            window, exhausted = self._run(
                "mac",
                budget,
                lambda s: self._fetch_mac_bars(s, market_code, code, MacPeriod.DAILY, Adjust.NONE, 0, window_count),
            )
            chain, skipped = build_factor_chain(window, events)
            _require_chain_ok(skipped)
            adjusted = apply_factor_chain(window, chain)
            return _tail_slice(adjusted, offset, limit), exhausted, len(events)

        if interval in ("1w", "1M"):
            ratio = _WEEKLY_DAILY_RATIO if interval == "1w" else _MONTHLY_DAILY_RATIO
            window_count = min((offset + limit) * ratio + 15, _MAX_INTERNAL_DAILY_BARS)
            window, daily_exhausted = self._run(
                "mac",
                budget,
                lambda s: self._fetch_mac_bars(s, market_code, code, MacPeriod.DAILY, Adjust.NONE, 0, window_count),
            )
            chain, skipped = build_factor_chain(window, events)
            _require_chain_ok(skipped)
            adjusted = apply_factor_chain(window, chain)
            aggregated = _aggregate_to_period(adjusted, interval)
            bars = _tail_slice(aggregated, offset, limit)
            # 聚合序列的完整性取决于日线是否取到历史尽头。
            return bars, daily_exhausted, len(events)

        # 分钟线：日线因子链按交易日应用。
        days = (offset + limit) // 240 + 3
        daily_window, _ = self._run(
            "mac",
            budget,
            lambda s: self._fetch_mac_bars(
                s, market_code, code, MacPeriod.DAILY, Adjust.NONE, 0, min(days, _MAX_INTERNAL_DAILY_BARS)
            ),
        )
        chain, skipped = build_factor_chain(daily_window, events)
        _require_chain_ok(skipped)
        raw_bars, exhausted = self._run(
            "mac",
            budget,
            lambda s: self._fetch_mac_bars(
                s, market_code, code, INTERVAL_TO_PERIOD[interval], Adjust.NONE, offset, limit
            ),
        )
        adjusted = apply_factor_chain(raw_bars, chain)
        return adjusted, exhausted, len(events)

    def _klines_ex(
        self,
        spec: MarketSpec,
        code: str,
        interval: str,
        adjust: str,
        offset: int,
        limit: int,
        budget: Budget,
    ) -> tuple[list[dict], dict]:
        """港美股/指数/期货 K 线：服务端 QFQ（股票类）或原始序列。"""
        assert spec.ex_market is not None
        market_code = int(spec.ex_market)
        period = INTERVAL_TO_PERIOD[interval]
        source: str | None = None
        if adjust == "qfq":
            bars, exhausted = self._run(
                "mac_ex",
                budget,
                lambda s: self._fetch_mac_bars(s, market_code, code, period, Adjust.QFQ, offset, limit),
            )
            if bars and has_bad_prices(bars):
                raise AdjustmentUnavailableError(f"服务端 QFQ 数据异常（市场 {spec.market.value} 无本地重算路径）")
            source = "server"
        else:
            bars, exhausted = self._run(
                "mac_ex",
                budget,
                lambda s: self._fetch_mac_bars(s, market_code, code, period, Adjust.NONE, offset, limit),
            )

        data = [_bar_payload(b, interval) for b in bars]
        meta = self._base_meta(
            spec,
            interval=interval,
            adjust=adjust,
            adjustment_source=source,
            adjustment_events=None,
            volume_unit=spec.kline_volume_unit,
            time_semantics=KLINE_TIME_SEMANTICS if interval in _MINUTE_INTERVALS else None,
            period_label=PERIOD_LABEL if interval in ("1w", "1M") else None,
        )
        meta.update(self._paging(len(data), offset, limit, exhausted))
        return data, meta

    # ------------------------------------------------------------------ #
    # 标的目录
    # ------------------------------------------------------------------ #

    def instruments(self, spec: MarketSpec, offset: int, limit: int) -> dict:
        """标的列表（服务端分页）。"""
        budget = self._new_budget()
        if spec.std_market is not None:
            data, meta = self._instruments_cn(spec, offset, limit, budget)
        else:
            if not spec.instruments:
                from .errors import UnsupportedCapabilityError

                raise UnsupportedCapabilityError(f"市场 {spec.market.value} 的目录列举不可用（协议目录缺失）")
            data, meta = self._instruments_ex(spec, offset, limit, budget)
        return {"data": data, "meta": meta}

    def _enumerate_cn(
        self, spec: MarketSpec, start: int, count: int, budget: Budget
    ) -> tuple[list[SecurityListEntry], int, bool]:
        """CN 目录枚举：从 start 起最多 count 条（服务端分页，页宽 1000）。

        实测约束：标准协议服务器对同一连接的目录连页请求会静默停滞
        （第 2 页起超时），故每页使用全新请求级会话；页间共享请求总预算。
        """
        assert spec.std_market is not None
        total = self._gate.run(
            lambda: self._run("standard", budget, lambda s: s.execute(GetSecurityCountCmd(spec.std_market)))
        )
        items: list[SecurityListEntry] = []
        offset = start
        exhausted = False
        pages = 0
        while len(items) < count:
            pages += 1
            if pages > 40:  # 防御：服务器无限回页时不至于拖满预算
                break
            page = self._gate.run(
                lambda: self._run(
                    "standard",
                    budget,
                    lambda s, _off=offset: s.execute(GetSecurityListCmd(spec.std_market, _off)),
                )
            )
            if not page:
                exhausted = True
                break
            take = page[: count - len(items)]
            items.extend(take)
            offset += len(page)
            if len(page) < GetSecurityListCmd.PAGE_SIZE or len(take) < len(page):
                exhausted = True
                break
        return items, total, exhausted

    def _instruments_cn(self, spec: MarketSpec, offset: int, limit: int, budget: Budget) -> tuple[list[dict], dict]:
        items, total, exhausted = self._enumerate_cn(spec, offset, limit, budget)
        data = [_instrument_row(item) for item in items]
        meta = self._base_meta(spec, total=total, directory_complete=True)
        meta.update(self._paging(len(data), offset, limit, exhausted))
        return data, meta

    def _instruments_ex(self, spec: MarketSpec, offset: int, limit: int, budget: Budget) -> tuple[list[dict], dict]:
        directory, directory_complete, from_cache = self._ex_directory(spec, budget)
        items = directory[offset : offset + limit]
        data = [_ex_instrument_row(spec, item) for item in items]
        page_exhausted = offset + len(items) >= len(directory)
        meta = self._base_meta(
            spec,
            directory_complete=directory_complete,
            directory_cached=from_cache,
        )
        meta.update(self._paging(len(data), offset, limit, page_exhausted))
        meta["complete"] = meta["complete"] and directory_complete
        return data, meta

    def _ex_directory(self, spec: MarketSpec, budget: Budget) -> tuple[list[ExInstrumentInfo], bool, bool]:
        """扩展市场目录（TTL 缓存；条目数受 directory_max_entries 上限约束）。

        Returns:
            (items, complete, from_cache)。complete=False 表示目录超过缓存上限
            或上游未证明枚举完整。
        """
        assert spec.ex_market is not None
        cached = self._directory_cache.get(spec.market.value)
        if cached is not None:
            return cached["items"], cached["complete"], True

        def run(session: Session) -> tuple[list[ExInstrumentInfo], bool]:
            total = session.execute(GetExInstrumentCountCmd())
            if total <= 0:
                return [], True
            start = _find_market_offset(session, int(spec.ex_market), total)
            if start < 0:
                return [], True
            items: list[ExInstrumentInfo] = []
            pos = start
            exhausted = False
            while pos < total and len(items) < self.config.directory_max_entries:
                page = session.execute(GetExInstrumentInfoCmd(pos, _EX_DIRECTORY_PAGE))
                if not page:
                    break
                for item in page:
                    if item.market == spec.ex_market:
                        items.append(item)
                        if len(items) >= self.config.directory_max_entries:
                            break
                    elif item.market > spec.ex_market:
                        return items, True
                pos += _EX_DIRECTORY_PAGE
                if len(page) < _EX_DIRECTORY_PAGE:
                    exhausted = True
                    break
            return items, exhausted and len(items) < self.config.directory_max_entries

        items, complete = self._run("mac_ex", budget, run)
        payload = {"items": items, "complete": complete}
        self._directory_cache.set(spec.market.value, payload)
        return items, complete, False

    def instrument_search(self, spec: MarketSpec, query: str, offset: int, limit: int) -> dict:
        """按代码/名称筛选目录（大小写不敏感子串匹配）。"""
        needle = query.strip().upper()
        if not needle:
            raise InvalidParameterError("query 不能为空")
        budget = self._new_budget()
        if spec.std_market is not None:
            # 全目录有界枚举（单页列表顺序与代码序无保证，必须全量筛选）。
            entries, _total, complete = self._enumerate_cn(spec, 0, self.config.directory_max_entries, budget)
            truncated_directory = len(entries) >= self.config.directory_max_entries and not complete
            matches = [
                _instrument_row(item) for item in entries if needle in item.code.upper() or needle in item.name.upper()
            ]
            data = matches[offset : offset + limit]
            meta = self._base_meta(
                spec,
                directory_complete=not truncated_directory,
                total_matches=len(matches),
            )
            meta.update(self._paging(len(data), offset, limit, offset + len(data) >= len(matches)))
            if truncated_directory:
                meta["complete"] = False
            return {"data": data, "meta": meta}

        if not spec.instrument_search:
            from .errors import UnsupportedCapabilityError

            raise UnsupportedCapabilityError(f"市场 {spec.market.value} 不支持目录搜索")

        directory, directory_complete, from_cache = self._ex_directory(spec, budget)
        matches = [
            item
            for item in directory
            if needle in item.code.upper() or needle in item.name.upper() or needle in item.desc.upper()
        ]
        data = [_ex_instrument_row(spec, item) for item in matches[offset : offset + limit]]
        meta = self._base_meta(
            spec, directory_complete=directory_complete, directory_cached=from_cache, total_matches=len(matches)
        )
        meta.update(self._paging(len(data), offset, limit, offset + len(data) >= len(matches)))
        meta["complete"] = meta["complete"] and directory_complete
        return {"data": data, "meta": meta}

    def instrument_info(self, spec: MarketSpec, code: str) -> dict:
        """单标的名称与基础元信息；目录/协议中不存在时 data=null。"""
        proto_code = _normalize_code(spec, code)
        budget = self._new_budget()
        if spec.std_market is not None:
            info = self._gate.run(
                lambda: self._run(
                    "mac",
                    budget,
                    lambda s: s.execute(MacSymbolInfoCmd(int(spec.std_market), proto_code)),
                )
            )
            if info is None or not info.code:
                data = None
            else:
                data = {
                    "market": spec.market.value,
                    "code": info.code,
                    "name": info.name or None,
                    "time": info.time.isoformat() if info.time else None,
                    "pre_close": _f(info.pre_close),
                    "open": _f(info.open),
                    "high": _f(info.high),
                    "low": _f(info.low),
                    "price": _f(info.close),
                    "volume": _i(info.vol),
                    "amount": _f(info.amount),
                    "volume_unit": "lot",
                    "lot_size": spec.lot_size,
                }
        else:
            if not spec.instrument_info:
                from .errors import UnsupportedCapabilityError

                raise UnsupportedCapabilityError(f"市场 {spec.market.value} 不支持标的元信息查询")
            directory, _complete, _cached = self._ex_directory(spec, budget)
            found = next((item for item in directory if item.code == proto_code), None)
            if found is None:
                data = None
            else:
                data = _ex_instrument_row(spec, found)
        return {"data": data, "meta": self._base_meta(spec, found=data is not None)}

    # ------------------------------------------------------------------ #
    # 分时与逐笔
    # ------------------------------------------------------------------ #

    def intraday(self, spec: MarketSpec, code: str, day: _date | None) -> dict:
        """当日/指定日期分时。历史范围遵循市场能力矩阵。"""
        if not spec.intraday:
            from .errors import UnsupportedCapabilityError

            raise UnsupportedCapabilityError(f"市场 {spec.market.value} 不支持分时查询")
        proto_code = _normalize_code(spec, code)
        budget = self._new_budget()
        ymd = day.year * 10000 + day.month * 100 + day.day if day else None

        if spec.std_market is not None:
            # CN：MAC 0x122D 分时图（实况验证；标准 0x051d 在部分服务器返回
            # 带代码前导的异构体，已弃用）。
            result = self._gate.run(
                lambda: self._run(
                    "mac",
                    budget,
                    lambda s: s.execute(MacSymbolTickChartCmd(int(spec.std_market), proto_code, ymd)),
                )
            )
            data = [_cn_minute_row(t) for t in result.get("ticks", [])]
            time_semantics = CN_INTRADAY_TIME_SEMANTICS
            summary = result.get("summary") or {}
        else:
            assert spec.ex_market is not None
            cmd = (
                GetExHistoryMinuteTimeDataCmd(int(spec.ex_market), proto_code, ymd)
                if ymd
                else GetExMinuteTimeDataCmd(int(spec.ex_market), proto_code)
            )
            bars = self._gate.run(lambda: self._run("mac_ex", budget, lambda s: s.execute(cmd)))
            data = [_ex_minute_row(b) for b in bars]
            time_semantics = "protocol_reported"
            summary = {}

        meta = self._base_meta(
            spec,
            date=day.isoformat() if day else None,
            period="today" if day is None else "history",
            time_semantics=time_semantics,
            amount_unit="unknown" if spec.std_market is None else None,
            name=(summary.get("name") or None) if summary else None,
            pre_close=_f(summary.get("pre_close")) if summary else None,
        )
        meta["count"] = len(data)
        meta["complete"] = True  # 分时为全天单次返回，无分页语义
        return {"data": data, "meta": meta}

    def transactions(self, spec: MarketSpec, code: str, day: _date | None, offset: int, limit: int) -> dict:
        """当日/历史逐笔成交（保留协议粒度、方向语义与原生倒序）。"""
        if not spec.transactions:
            from .errors import UnsupportedCapabilityError

            raise UnsupportedCapabilityError(f"市场 {spec.market.value} 不支持逐笔成交查询")
        proto_code = _normalize_code(spec, code)
        budget = self._new_budget()
        ymd = day.year * 10000 + day.month * 100 + day.day if day else None

        rows: list[Transaction] = []
        exhausted = False
        if spec.std_market is not None:
            # CN：MAC 0x122F（实况验证；标准 0x0fc5 在部分服务器已无数据）。
            # 协议原生倒序：start=0 为最新一段，offset 语义与 K 线一致。
            market_code = int(spec.std_market)
            page_cap = _MAC_TRANSACTION_PAGE

            def run(session: Session) -> None:
                nonlocal rows, exhausted
                fetched = 0
                start = offset
                while fetched < limit:
                    page_size = min(limit - fetched, page_cap)
                    cmd = MacSymbolTransactionCmd(market_code, proto_code, ymd, start, page_size)
                    page = session.execute(cmd)
                    if not page:
                        exhausted = True
                        break
                    rows.extend(page)
                    fetched += len(page)
                    start += len(page)
                    if len(page) < page_size:
                        exhausted = True
                        break

            self._gate.run(lambda: self._run("mac", budget, run))
        elif spec.hk_stock_market:
            # 港股逐笔：0x122F 数据源未接入港股（参考 issue #14），走 EX 协议。
            page_cap = GetExTransactionDataCmd.MAX_COUNT

            def run(session: Session) -> None:
                nonlocal rows, exhausted
                fetched = 0
                start = offset
                while fetched < limit:
                    page_size = min(limit - fetched, page_cap)
                    cmd = (
                        GetExHistoryTransactionDataCmd(int(spec.ex_market), proto_code, ymd, start, page_size)
                        if ymd
                        else GetExTransactionDataCmd(int(spec.ex_market), proto_code, start, page_size)
                    )
                    page = session.execute(cmd)
                    if not page:
                        exhausted = True
                        break
                    rows.extend(page)
                    fetched += len(page)
                    start += len(page)
                    if len(page) < page_size:
                        exhausted = True
                        break

            self._gate.run(lambda: self._run("mac_ex", budget, run))
        else:
            assert spec.ex_market is not None
            page_cap = _MAC_TRANSACTION_PAGE

            def run(session: Session) -> None:
                nonlocal rows, exhausted
                fetched = 0
                start = offset
                while fetched < limit:
                    page_size = min(limit - fetched, page_cap)
                    cmd = MacSymbolTransactionCmd(int(spec.ex_market), proto_code, ymd, start, page_size)
                    page = session.execute(cmd)
                    if not page:
                        exhausted = True
                        break
                    rows.extend(page)
                    fetched += len(page)
                    start += len(page)
                    if len(page) < page_size:
                        exhausted = True
                        break

            self._gate.run(lambda: self._run("mac_ex", budget, run))

        data = [_transaction_row(r) for r in rows]
        meta = self._base_meta(
            spec,
            date=day.isoformat() if day else None,
            period="today" if day is None else "history",
            order="newest_first",
            price_unit_note="HK/EX 市场逐笔价格为 0.001 计价货币换算（港股已验证）" if spec.hk_stock_market else None,
        )
        meta.update(self._paging(len(data), offset, limit, exhausted))
        return {"data": data, "meta": meta}

    # ------------------------------------------------------------------ #
    # 财务与 XDXR
    # ------------------------------------------------------------------ #

    def finance(self, spec: MarketSpec, code: str) -> dict:
        """A 股基础财务快照（标准协议，单位：万元/万股）。"""
        if not spec.finance:
            from .errors import UnsupportedCapabilityError

            raise UnsupportedCapabilityError(f"市场 {spec.market.value} 不支持财务快照查询")
        proto_code = _normalize_code(spec, code)
        budget = self._new_budget()
        info = self._gate.run(
            lambda: self._run(
                "standard",
                budget,
                lambda s: s.execute(GetFinanceInfoCmd(spec.std_market, proto_code)),
            )
        )
        data = None if info is None else _finance_row(info)
        meta = self._base_meta(
            spec,
            units={"monetary": "万元(CNY)", "shares": "万股"},
            found=data is not None,
        )
        return {"data": data, "meta": meta}

    def xdxr(self, spec: MarketSpec, code: str) -> dict:
        """A 股除权除息记录（标准协议）。"""
        if not spec.xdxr:
            from .errors import UnsupportedCapabilityError

            raise UnsupportedCapabilityError(f"市场 {spec.market.value} 不支持 XDXR 查询")
        proto_code = _normalize_code(spec, code)
        budget = self._new_budget()
        records = self._fetch_xdxr_records(spec, proto_code, budget)
        data = [_xdxr_payload(rec) for rec in records]
        meta = self._base_meta(
            spec,
            count=len(data),
            complete=True,
            note="category=1 的分红送配字段已从每 10 股口径归一化为每股",
        )
        return {"data": data, "meta": meta}

    # ------------------------------------------------------------------ #
    # 运行状态
    # ------------------------------------------------------------------ #

    def status(self) -> dict:
        """协议组就绪状态与最近连接结果（与外部行情可用性分离）。"""
        sessions = self._status.snapshot(self.selector)
        # 就绪 = 三类协议组均有候选主机可尝试（不代表上游当前可达）。
        ready = all(len(self.selector.candidates_for(kind)[0]) > 0 for kind in BUILTIN_CANDIDATES)
        data = {
            "ready": ready,
            "sessions": sessions,
            "budget": {
                "request_budget_seconds": self.config.request_budget_seconds,
                "connect_seconds": self.config.connect_seconds,
                "io_seconds": self.config.io_seconds,
                "max_host_switches": self.config.max_host_switches,
                "max_concurrency": self.config.max_concurrency,
            },
            "markets_supported": len(ApiMarket),
        }
        return {"data": data, "meta": {"fetched_at": datetime.now(timezone.utc).isoformat()}}


# ---------------------------------------------------------------------- #
# 行内映射辅助（模块级纯函数）
# ---------------------------------------------------------------------- #


def _proto_market_code(spec: MarketSpec) -> int:
    """业务命令的协议市场码（CN=标准市场码，EX=扩展市场码）。"""
    if spec.std_market is not None:
        return int(spec.std_market)
    assert spec.ex_market is not None
    return int(spec.ex_market)


def _find_market_offset(session: Session, market: int, total: int) -> int:
    """二分查找指定市场在 EX 全局目录中的起始偏移（移植自参考实现）。"""
    lo, hi = 0, total
    while lo < hi:
        mid = (lo + hi) // 2
        items = session.execute(GetExInstrumentInfoCmd(mid, 1))
        if not items:
            hi = mid
            continue
        if items[0].market < market:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _mac_bar_row(bar: dict) -> dict:
    """MAC bar（datetime 已组装）→ 内部行。"""
    return {
        "datetime": bar["datetime"],
        "open": _f(bar.get("open")),
        "high": _f(bar.get("high")),
        "low": _f(bar.get("low")),
        "close": _f(bar.get("close")),
        "vol": _f(bar.get("vol")),
        "amount": _f(bar.get("amount")),
    }


def _bar_payload(bar: dict, interval: str) -> dict:
    """内部 K 线行 → HTTP 载荷（日线返回交易日期，分钟线返回本地时间戳）。"""
    dt = bar["datetime"]
    if isinstance(dt, datetime):
        trade_date = dt.date().isoformat()
        if interval in _MINUTE_INTERVALS:
            stamp = dt.isoformat(timespec="seconds")
        else:
            stamp = dt.date().isoformat()
    else:
        trade_date = dt.isoformat()
        stamp = dt.isoformat()
    return {
        "datetime": stamp,
        "trade_date": trade_date,
        "open": bar.get("open"),
        "high": bar.get("high"),
        "low": bar.get("low"),
        "close": bar.get("close"),
        "volume": bar.get("vol"),
        "amount": bar.get("amount"),
    }


def _aggregate_to_period(bars: list[dict], interval: str) -> list[dict]:
    """升序日线聚合为周/月线（OHLC 合成、量额累加，标签=周期内最后一个交易日）。"""
    grouped: dict[tuple, dict] = {}
    order: list[tuple] = []
    for bar in bars:
        dt = bar.get("datetime")
        d = dt.date() if isinstance(dt, datetime) else dt
        if d is None:
            continue
        if interval == "1w":
            iso = d.isocalendar()
            key = (iso[0], iso[1])
        else:
            key = (d.year, d.month)
        if key not in grouped:
            grouped[key] = {
                "datetime": d,
                "open": bar.get("open"),
                "high": bar.get("high"),
                "low": bar.get("low"),
                "close": bar.get("close"),
                "vol": bar.get("vol") or 0.0,
                "amount": bar.get("amount") or 0.0,
            }
            order.append(key)
        else:
            g = grouped[key]
            if g["high"] is None or (bar.get("high") is not None and bar["high"] > g["high"]):
                g["high"] = bar.get("high")
            if g["low"] is None or (bar.get("low") is not None and bar["low"] < g["low"]):
                g["low"] = bar.get("low")
            if bar.get("close") is not None:
                g["close"] = bar.get("close")
            g["datetime"] = max(g["datetime"], d)
            g["vol"] = (g["vol"] or 0.0) + (bar.get("vol") or 0.0)
            g["amount"] = (g["amount"] or 0.0) + (bar.get("amount") or 0.0)
    return [grouped[key] for key in order]


def _require_chain_ok(skipped: list[_date]) -> None:
    """因子非法且影响区间 → 按计划显式失败。"""
    if skipped:
        dates = ", ".join(d.isoformat() for d in skipped[:5])
        raise AdjustmentUnavailableError(f"前复权因子非法（缺失前收盘或非法分母）: {dates}")


def _instrument_row(item: SecurityListEntry) -> dict:
    return {
        "market": "cn_sh" if item.market == 1 else "cn_sz",
        "code": item.code,
        "name": item.name or None,
        "lot_size": item.volunit,
        "price_precision": item.decimal_point,
        "pre_close": _f(item.pre_close),
    }


def _ex_instrument_row(spec: MarketSpec, item: ExInstrumentInfo) -> dict:
    return {
        "market": spec.market.value,
        "code": item.code,
        "name": item.name or None,
        "desc": item.desc or None,
        "category": item.category,
    }


def _cn_minute_row(tick: dict) -> dict:
    hour, minute = tick["time"]
    return {
        "time": f"{hour:02d}:{minute:02d}",
        "price": _f(tick["price"]),
        "volume": _f(tick["vol"]),
        "avg_price": _f(tick.get("avg_price")),
    }


def _ex_minute_row(bar: MinuteBar) -> dict:
    hour, minute = bar.time or (0, 0)
    return {
        "time": f"{hour:02d}:{minute:02d}",
        "index": None,
        "price": _f(bar.price),
        "volume": _f(bar.vol),
        "avg_price": _f(bar.avg_price),
        "amount": _f(bar.amount),
    }


def _transaction_row(r: Transaction) -> dict:
    hour, minute, second = r.time
    return {
        "time": f"{hour:02d}:{minute:02d}:{second:02d}",
        "price": _f(r.price),
        "volume": _f(r.volume),
        "direction": r.direction,
        "direction_label": DIRECTION_LABELS.get(r.direction),
        "trade_count": r.trade_count,
        "open_interest": r.open_interest,
    }


def _xdxr_internal(r: XdxrRecord) -> dict:
    """XDXR 记录 → 内部协议口径（复权层消费，保留协议字段名）。"""
    return {
        "date": r.date.isoformat(),
        "category": r.category,
        "fenhong": _f(r.fenhong),
        "peigujia": _f(r.peigujia),
        "songzhuangu": _f(r.songzhuangu),
        "peigu": _f(r.peigu),
        "suogu": _f(r.suogu),
        "xingquanjia": _f(r.xingquanjia),
        "fenshu": _f(r.fenshu),
        "panqian_liutong": _f(r.panqian_liutong),
        "qian_zongguben": _f(r.qian_zongguben),
        "panhou_liutong": _f(r.panhou_liutong),
        "hou_zongguben": _f(r.hou_zongguben),
    }


def _xdxr_payload(rec: dict) -> dict:
    """内部协议口径 → HTTP 载荷（英文字段名；category=1 已归一化为每股）。"""
    return {
        "date": rec.get("date"),
        "category": rec.get("category"),
        "category_name": XDXR_CATEGORY_NAMES.get(rec.get("category"), str(rec.get("category"))),
        "dividend_per_share": rec.get("fenhong"),
        "rights_issue_price": rec.get("peigujia"),
        "bonus_per_share": rec.get("songzhuangu"),
        "rights_issue_ratio": rec.get("peigu"),
        "share_consolidation": rec.get("suogu"),
        "warrant_strike_price": rec.get("xingquanjia"),
        "warrant_ratio": rec.get("fenshu"),
        "float_shares_before_wan": rec.get("panqian_liutong"),
        "total_shares_before_wan": rec.get("qian_zongguben"),
        "float_shares_after_wan": rec.get("panhou_liutong"),
        "total_shares_after_wan": rec.get("hou_zongguben"),
    }


def _finance_row(info) -> dict:
    """FinanceInfo → HTTP 载荷（单位：万元/万股，见 meta.units）。"""
    return {
        "market_code": info.market,
        "code": info.code,
        "updated_date": f"{info.updated_date:08d}",
        "ipo_date": f"{info.ipo_date:08d}" if info.ipo_date else None,
        "province": info.province,
        "industry": info.industry,
        "shareholder_count": info.gudong_renshu,
        "float_shares_wan": _f(info.liutong_guben),
        "total_shares_wan": _f(info.zong_guben),
        "total_assets_wan": _f(info.zong_zichan),
        "current_assets_wan": _f(info.liudong_zichan),
        "fixed_assets_wan": _f(info.guding_zichan),
        "intangible_assets_wan": _f(info.wuxing_zichan),
        "current_liabilities_wan": _f(info.liudong_fuzhai),
        "long_term_liabilities_wan": _f(info.changqi_fuzhai),
        "capital_reserve_wan": _f(info.ziben_gongjijin),
        "net_assets_wan": _f(info.jing_zichan),
        "revenue_wan": _f(info.zhuying_shouru),
        "operating_profit_wan": _f(info.yingye_lirun),
        "total_profit_wan": _f(info.lirun_zonghe),
        "net_profit_wan": _f(info.jing_lirun),
        "undistributed_profit_wan": _f(info.weifen_lirun),
        "receivables_wan": _f(info.yingshou_zhangkuan),
        "inventory_wan": _f(info.cunhuo),
        "operating_cash_flow_wan": _f(info.jingying_xianjinliu),
        "total_cash_flow_wan": _f(info.zong_xianjinliu),
        "investment_income_wan": _f(info.touzi_shouyu),
        "main_profit_wan": _f(info.zhuying_lirun),
        "book_value_per_share": _f(info.meigujing_zichan),
    }
