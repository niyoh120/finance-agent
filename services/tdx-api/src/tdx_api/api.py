"""/api/v1 业务路由：参数校验、能力矩阵分派、响应封装。

全部为只读查询。路由为同步函数（FastAPI 线程池执行），上游并发与排队
由查询层 ``BoundedGate`` 约束。market/code/interval 等业务参数在此层
完成形态校验；能力矩阵之外的组合由查询层抛 ``UnsupportedCapabilityError``。
"""

from __future__ import annotations

import datetime
import hmac

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .errors import InvalidParameterError
from .markets import SUPPORTED_INTERVALS, get_spec
from .schemas import (
    Bar,
    Envelope,
    Instrument,
    MarketEntry,
    MinutePoint,
    Quote,
    TransactionRow,
    XdxrItem,
)

_DATE_FMT = "%Y-%m-%d"


def enforce_api_key(request: Request) -> None:
    """可选共享密钥门（``X-API-Key``）；未配置密钥时全部放行。"""
    expected = request.app.state.config.api_key
    if expected:
        provided = request.headers.get("X-API-Key", "")
        if not hmac.compare_digest(provided, expected):
            raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


def _service(request: Request):
    return request.app.state.service


def _require_market(market: str):
    """解析市场标识；未知市场 → 422。"""
    spec = get_spec(market)
    if spec is None:
        raise InvalidParameterError(f"未知 market: {market!r}（/api/v1/markets 查看全部市场）")
    return spec


def _parse_day(value: str | None, name: str = "date") -> datetime.date | None:
    if value is None:
        return None
    try:
        return datetime.datetime.strptime(value, _DATE_FMT).date()
    except ValueError as e:
        raise InvalidParameterError(f"{name} 必须为 YYYY-MM-DD: {value!r}") from e


def _normalize_codes(codes: str) -> list[str]:
    items = [c.strip() for c in codes.split(",") if c.strip()]
    if not items:
        raise InvalidParameterError("codes 不能为空")
    return items


router = APIRouter(
    prefix="/api/v1",
    tags=["market-data"],
    dependencies=[Depends(enforce_api_key)],
)


@router.get("/markets", response_model=Envelope[MarketEntry])
def list_markets(request: Request) -> dict:
    """市场枚举、协议市场码、时区与能力矩阵。"""
    return _service(request).markets()


@router.get("/quotes", response_model=Envelope[Quote])
def quotes(
    request: Request,
    market: str = Query(description="市场标识（见 /markets）"),
    codes: str = Query(description="逗号分隔的原生代码（单市场，最多 80 只）"),
) -> dict:
    """单市场批量报价。"""
    spec = _require_market(market)
    return _service(request).quotes(spec, _normalize_codes(codes))


@router.get("/klines", response_model=Envelope[Bar])
def klines(
    request: Request,
    market: str = Query(description="市场标识"),
    code: str = Query(description="原生代码"),
    interval: str = Query(default="1d", description=f"周期：{'/'.join(SUPPORTED_INTERVALS)}"),
    adjust: str = Query(default="none", description="复权：none | qfq（按市场能力）"),
    offset: int = Query(default=0, ge=0, description="距最新的偏移（0=最近一段）"),
    limit: int = Query(default=100, ge=1, le=1000, description="返回条数上限"),
) -> dict:
    """K 线（时间正序；QFQ 支持见市场能力矩阵）。"""
    spec = _require_market(market)
    limit = min(limit, request.app.state.config.max_page_limit)
    return _service(request).klines(spec, code, interval, adjust, offset, limit)


@router.get("/instruments", response_model=Envelope[Instrument])
def instruments(
    request: Request,
    market: str = Query(description="市场标识"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict:
    """标的列表（服务端目录分页；目录完整性见 meta）。"""
    spec = _require_market(market)
    limit = min(limit, request.app.state.config.max_page_limit)
    return _service(request).instruments(spec, offset, limit)


@router.get("/instruments/search", response_model=Envelope[Instrument])
def instrument_search(
    request: Request,
    market: str = Query(description="市场标识"),
    query: str = Query(min_length=1, description="代码/名称子串（大小写不敏感）"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=1000),
) -> dict:
    """目录搜索。"""
    spec = _require_market(market)
    limit = min(limit, request.app.state.config.max_page_limit)
    return _service(request).instrument_search(spec, query, offset, limit)


@router.get("/instruments/info")
def instrument_info(
    request: Request,
    market: str = Query(description="市场标识"),
    code: str = Query(description="原生代码"),
) -> dict:
    """单标的名称与基础元信息；不存在时 data=null。"""
    spec = _require_market(market)
    return _service(request).instrument_info(spec, code)


@router.get("/intraday", response_model=Envelope[MinutePoint])
def intraday(
    request: Request,
    market: str = Query(description="市场标识"),
    code: str = Query(description="原生代码"),
    date: str | None = Query(default=None, description="YYYY-MM-DD；缺省=当日"),
) -> dict:
    """当日/指定日期分时（历史范围遵循市场能力矩阵）。"""
    spec = _require_market(market)
    return _service(request).intraday(spec, code, _parse_day(date))


@router.get("/transactions", response_model=Envelope[TransactionRow])
def transactions(
    request: Request,
    market: str = Query(description="市场标识"),
    code: str = Query(description="原生代码"),
    date: str | None = Query(default=None, description="YYYY-MM-DD；缺省=当日"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=1000, ge=1, le=1000),
) -> dict:
    """当日/历史逐笔成交（协议原生倒序，保留买卖方向语义）。"""
    spec = _require_market(market)
    limit = min(limit, request.app.state.config.max_page_limit)
    return _service(request).transactions(spec, code, _parse_day(date), offset, limit)


@router.get("/finance")
def finance(request: Request, market: str, code: str) -> dict:
    """A 股基础财务快照（标准协议；单位见 meta.units）。"""
    spec = _require_market(market)
    return _service(request).finance(spec, code)


@router.get("/xdxr", response_model=Envelope[XdxrItem])
def xdxr(request: Request, market: str, code: str) -> dict:
    """A 股除权除息记录。"""
    spec = _require_market(market)
    return _service(request).xdxr(spec, code)


@router.get("/status")
def status(request: Request) -> dict:
    """协议组就绪状态与最近连接结果。"""
    return _service(request).status()
