"""HTTP 层测试：路由契约、认证、错误映射、并发与资源回收。

通过 TestClient 驱动真实路由与查询层，上游用会话级替身（部分用例叠加
行为注入模拟超时/饱和）；线级行为由 test_protocol.py 覆盖。
"""

from __future__ import annotations

import threading
from datetime import datetime

import pytest
from conftest import FakeSession, fake_factory, make_config
from fastapi.testclient import TestClient
from tdx_api.main import create_app
from tdx_api.tdx.commands.mac.symbols import MacSymbolBarCmd
from tdx_api.tdx.commands.standard.fundamentals import GetXdxrInfoCmd
from tdx_api.tdx.errors import TdxConnectionError, TdxDecodeError
from tdx_api.tdx.hosts import HostSelector
from tdx_api.tdx.models import XdxrRecord


def day(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _bar(d: str, close: float):
    return {
        "datetime": day(d),
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "vol": 100.0,
        "amount": 100.0,
    }


def _kline_handlers():
    history = [_bar("2024-01-04", 10.5), _bar("2024-01-05", 10.6)]

    def dispatch(cmd: MacSymbolBarCmd):
        end = len(history) - cmd.start
        return history[max(end - cmd.count, 0) : end]

    return {MacSymbolBarCmd: dispatch}


def _service(config, factory):
    from tdx_api.client import TdxService

    return TdxService(config, factory=factory)


def make_client(config=None, factory=None) -> TestClient:
    cfg = config or make_config()
    svc = _service(cfg, factory or fake_factory(_kline_handlers()))
    return TestClient(create_app(cfg, service=svc))


# --------------------------------------------------------------------- #
# 基础路由
# --------------------------------------------------------------------- #


def test_healthz_public_and_liveness_only():
    with make_client() as client:
        resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_markets_returns_capability_matrix():
    with make_client() as client:
        resp = client.get("/api/v1/markets")
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["count"] == 16
    sh = next(m for m in body["data"] if m["market"] == "cn_sh")
    assert sh["capabilities"]["finance"] is True
    assert sh["adjust"] == ["none", "qfq"]
    assert sh["protocol_market_code"] == 1  # 标准协议沪市码
    cffex = next(m for m in body["data"] if m["market"] == "cffex")
    assert cffex["capabilities"]["instruments"] is False
    assert cffex["capabilities"]["klines"] is True
    us = next(m for m in body["data"] if m["market"] == "us")
    assert us["timezone"] is None  # 时区证据欠缺 → 显式未知


def test_klines_end_to_end_with_fake_upstream():
    with make_client() as client:
        resp = client.get("/api/v1/klines", params={"market": "cn_sh", "code": "600000", "interval": "1d"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["market"] == "cn_sh"
    assert body["data"][-1]["trade_date"] == "2024-01-05"
    assert body["meta"]["fetched_at"]


def test_klines_empty_data_is_200():
    def empty(cmd):
        return []

    cfg = make_config()
    svc = _service(cfg, fake_factory({MacSymbolBarCmd: empty}))
    app = create_app(cfg, service=svc)
    with TestClient(app) as client:
        resp = client.get("/api/v1/klines", params={"market": "cn_sh", "code": "999999"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == []
    assert body["meta"]["count"] == 0
    assert body["meta"]["complete"] is True


def test_instruments_info_contract():
    from tdx_api.tdx.commands.mac.symbols import MacSymbolInfoCmd
    from tdx_api.tdx.models import MacSymbolInfo

    def info_handler(cmd):
        return MacSymbolInfo(
            market=0,
            code="000001",
            name="平安银行",
            time=datetime(2024, 1, 5, 15, 0, 0),
            pre_close=10.0,
            open=10.0,
            high=10.2,
            low=9.9,
            close=10.1,
            vol=1000,
            amount=1.0e7,
        )

    cfg = make_config()
    svc = _service(cfg, fake_factory({MacSymbolInfoCmd: info_handler}))
    app = create_app(cfg, service=svc)
    with TestClient(app) as client:
        resp = client.get("/api/v1/instruments/info", params={"market": "cn_sz", "code": "000001"})
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "平安银行"
    assert resp.json()["meta"]["found"] is True


def test_status_endpoint_shape():
    with make_client() as client:
        resp = client.get("/api/v1/status")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["ready"] is True
    assert set(body["sessions"].keys()) == {"standard", "mac", "mac_ex"}
    assert body["budget"]["max_concurrency"] == 8


# --------------------------------------------------------------------- #
# 参数与能力校验
# --------------------------------------------------------------------- #


def test_unknown_market_returns_422_stable_code():
    with make_client() as client:
        resp = client.get("/api/v1/klines", params={"market": "mars", "code": "X"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_parameter"


def test_unsupported_capability_returns_422():
    with make_client() as client:
        resp = client.get("/api/v1/klines", params={"market": "shfe", "code": "RBL8", "adjust": "qfq"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "unsupported_capability"


def test_bad_interval_rejected_by_validation():
    with make_client() as client:
        resp = client.get("/api/v1/klines", params={"market": "cn_sh", "code": "600000", "interval": "2h"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_parameter"


def test_limit_clamped_by_config():
    """limit 超出服务配置上限时静默夹紧（meta.limit 回显生效值）。"""
    cfg = make_config(max_page_limit=50)
    svc = _service(cfg, fake_factory(_kline_handlers()))
    app = create_app(cfg, service=svc)
    with TestClient(app) as client:
        resp = client.get("/api/v1/klines", params={"market": "cn_sh", "code": "600000", "limit": 100})
    assert resp.status_code == 200
    assert resp.json()["meta"]["limit"] == 50


def test_limit_over_contract_limit_rejected():
    with make_client() as client:
        resp = client.get("/api/v1/klines", params={"market": "cn_sh", "code": "600000", "limit": 1001})
    assert resp.status_code == 422


# --------------------------------------------------------------------- #
# 认证
# --------------------------------------------------------------------- #


def test_api_key_enforced_when_configured():
    cfg = make_config(api_key="secret-key")
    svc = _service(cfg, fake_factory(_kline_handlers()))
    app = create_app(cfg, service=svc)
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200  # 公开
        assert client.get("/api/v1/markets").status_code == 401
        assert client.get("/api/v1/markets", headers={"X-API-Key": "secret-key"}).status_code == 200
        assert client.get("/api/v1/markets", headers={"X-API-Key": "wrong"}).status_code == 401


def test_no_api_key_configured_allows_anonymous():
    with make_client() as client:
        assert client.get("/api/v1/markets").status_code == 200


# --------------------------------------------------------------------- #
# 错误映射
# --------------------------------------------------------------------- #


def test_upstream_unavailable_maps_to_503():
    def refuse(kind, host, budget):
        raise TdxConnectionError("refused")

    cfg = make_config()
    svc = _service(cfg, refuse)
    app = create_app(cfg, service=svc)
    with TestClient(app) as client:
        resp = client.get("/api/v1/klines", params={"market": "cn_sh", "code": "600000"})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "upstream_unavailable"


def test_decode_error_maps_to_502():
    def boom(cmd):
        raise TdxDecodeError("truncated frame")

    cfg = make_config()
    selector = HostSelector(candidates={"mac": (("127.0.0.1",), 7709)}, ttl=300.0, clock=lambda: 0.0)
    from tdx_api.client import TdxService

    svc = TdxService(cfg, selector=selector, factory=lambda kind, host, budget: FakeSession({MacSymbolBarCmd: boom}))
    app = create_app(cfg, service=svc)
    with TestClient(app) as client:
        resp = client.get("/api/v1/klines", params={"market": "cn_sh", "code": "600000"})
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "upstream_data_error"


def test_budget_exhausted_maps_to_504():
    cfg = make_config(request_budget_seconds=0.0000001)
    svc = _service(cfg, fake_factory({}))
    app = create_app(cfg, service=svc)
    with TestClient(app) as client:
        resp = client.get("/api/v1/quotes", params={"market": "cn_sh", "codes": "600000"})
    assert resp.status_code == 504
    assert resp.json()["error"]["code"] == "budget_exceeded"


def test_concurrency_saturation_maps_to_429():
    """并发名额占满且排队超限 → 429；不无限排队。"""
    cfg = make_config(max_concurrency=1, queue_wait_seconds=0.05)
    release = threading.Event()

    class HoldingSession(FakeSession):
        def execute(self, cmd):
            release.wait(timeout=5)
            return []

    def factory(kind, host, budget):
        return HoldingSession({})

    from tdx_api.client import TdxService

    svc = TdxService(cfg, factory=factory)
    app = create_app(cfg, service=svc)
    errors: list[str] = []
    results: list[int] = []

    def holder():
        # 直接占用唯一的并发名额
        svc._gate.run(lambda: release.wait(timeout=4))

    def contender():
        with TestClient(app) as client:
            resp = client.get("/api/v1/quotes", params={"market": "cn_sh", "codes": "600000"})
            results.append(resp.status_code)
            if resp.status_code != 200:
                errors.append(resp.json()["error"]["code"])

    holder_thread = threading.Thread(target=holder)
    holder_thread.start()
    try:
        threads = [threading.Thread(target=contender) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
    finally:
        release.set()
        holder_thread.join(timeout=10)
    assert results.count(429) >= 1
    assert "concurrency_saturated" in errors


def test_sessions_closed_after_request():
    """请求结束（含异常路径）后会话必须关闭（资源回收）。"""
    sessions: list[FakeSession] = []
    history = [_bar("2024-01-04", 10.5), _bar("2024-01-05", 10.6)]

    def dispatch(cmd):
        end = len(history) - cmd.start
        return history[max(end - cmd.count, 0) : end]

    factory = fake_factory({MacSymbolBarCmd: dispatch}, sessions=sessions)
    cfg = make_config()
    from tdx_api.client import TdxService

    svc = TdxService(cfg, factory=factory)
    app = create_app(cfg, service=svc)
    with TestClient(app) as client:
        client.get("/api/v1/klines", params={"market": "cn_sh", "code": "600000"})
    assert sessions and all(s.closed for s in sessions)


# --------------------------------------------------------------------- #
# 其余端点契约（参数化路由验证）
# --------------------------------------------------------------------- #


def test_xdxr_endpoint_with_fixture_records():
    records = [XdxrRecord(market=1, code="600000", date=day("2024-01-05").date(), category=1, fenhong=0.5)]

    cfg = make_config()
    from tdx_api.client import TdxService

    svc = TdxService(cfg, factory=fake_factory({GetXdxrInfoCmd: lambda cmd: records}))
    app = create_app(cfg, service=svc)
    with TestClient(app) as client:
        resp = client.get("/api/v1/xdxr", params={"market": "cn_sh", "code": "600000"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"][0]["dividend_per_share"] == 0.5
    assert body["data"][0]["category_name"] == "除权除息"


def test_invalid_date_param_rejected():
    with make_client() as client:
        resp = client.get("/api/v1/intraday", params={"market": "cn_sh", "code": "600000", "date": "2024/01/02"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_parameter"


@pytest.mark.parametrize(
    "path,params",
    [
        ("/api/v1/quotes", {"market": "cn_sh", "codes": ""}),
        ("/api/v1/instruments/search", {"market": "cn_sh", "query": ""}),
        ("/api/v1/klines", {"market": "cn_sh", "code": "600000", "offset": -1}),
        ("/api/v1/transactions", {"market": "hk", "code": "00700", "limit": 2000}),
        ("/api/v1/klines", {"market": "cn_sh"}),  # 缺必填参数（FastAPI 原生校验路径）
    ],
)
def test_param_validation_rejects(path: str, params: dict):
    with make_client() as client:
        resp = client.get(path, params=params)
    assert resp.status_code == 422
    # FastAPI/Pydantic 原生校验错误同样归一到统一错误封装（稳定 code）。
    assert resp.json()["error"]["code"] == "invalid_parameter"
