"""FastAPI 应用工厂与进程入口。

模式沿用 services/schwab-api：``create_app`` 工厂 + ``Config.from_env``，
``/healthz`` 为前缀外存活探针（始终 200，与外部行情可用性分离），
``/api/v1/status`` 为协议组就绪状态。``/api/v1/*`` 数据接口受可选
``X-API-Key`` 保护（安全字符串比较），``/healthz`` 恒为公开。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import __version__
from .api import router as api_router
from .client import TdxService
from .config import Config
from .errors import ServiceError
from .tdx.errors import TdxError

logger = logging.getLogger(__name__)


def _error_payload(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def create_app(config: Config | None = None, service: TdxService | None = None) -> FastAPI:
    """构建应用。service 可注入（测试替身）。"""
    config = config or Config.from_env()
    service = service or TdxService(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info(
            "tdx-api %s ready (listen %s:%s, budget %.0fs, concurrency %d)",
            __version__,
            config.host,
            config.port,
            config.request_budget_seconds,
            config.max_concurrency,
        )
        yield
        # 请求级会话由各请求自行关闭；关闭时的有界等待由 uvicorn 完成。

    app = FastAPI(
        title="tdx-api",
        version=__version__,
        lifespan=lifespan,
        description="通达信行情查询服务（A 股/港美股/指数/期货/SGE，只读）",
    )
    app.state.config = config
    app.state.service = service
    app.include_router(api_router)

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict:
        # Liveness only：进程可响应即 200；上游可用性看 /api/v1/status。
        return {"status": "ok"}

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        """FastAPI/Pydantic 参数约束错误归一到统一错误封装（稳定 code）。"""
        errors = exc.errors()
        first = errors[0] if errors else {}
        loc = ".".join(str(part) for part in first.get("loc", []) if part != "body")
        message = f"{loc}: {first.get('msg', 'invalid parameter')}" if loc else "invalid parameter"
        return JSONResponse(status_code=422, content=_error_payload("invalid_parameter", message))

    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=_error_payload(exc.code, exc.message))

    @app.exception_handler(TdxError)
    async def protocol_error_handler(request: Request, exc: TdxError) -> JSONResponse:
        # 协议层未被查询层归类的错误（如帧解码失败）统一按上游数据错误处理。
        from .errors import UpstreamDataError

        logger.warning("协议错误 %s: %s", exc.__class__.__name__, exc)
        return JSONResponse(
            status_code=UpstreamDataError.http_status,
            content=_error_payload(UpstreamDataError.code, f"上游协议错误: {exc}"),
        )

    return app


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    config = Config.from_env()
    uvicorn.run(create_app(config), host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    run()
