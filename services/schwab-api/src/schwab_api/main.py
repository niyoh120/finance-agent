"""FastAPI app factory and process entrypoint."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request

from . import __version__
from .api import router as api_router
from .auth import router as auth_router
from .auth import status_payload
from .client import ClientManager
from .config import Config
from .keepalive import RuntimeState, run_loop
from .store import TokenStore
from .ui import router as ui_router

logger = logging.getLogger(__name__)


def create_app(config: Config | None = None, store: TokenStore | None = None) -> FastAPI:
    config = config or Config.from_env()
    store = store or TokenStore(config.tokens_db, config.tokens_encryption)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = asyncio.Event()
        task = asyncio.create_task(run_loop(store, config, app.state.runtime, stop))
        logger.info("schwab-api %s ready (keepalive interval: %sh)", __version__, config.keepalive_interval_hours)
        try:
            yield
        finally:
            stop.set()
            try:
                # 10s 上限：keepalive 可能正卡在最长 30s 的 token POST 上。
                await asyncio.wait_for(task, timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="schwab-api", version=__version__, lifespan=lifespan)
    app.state.config = config
    app.state.store = store
    app.state.clients = ClientManager(config, store)
    app.state.runtime = RuntimeState()

    app.include_router(auth_router)
    app.include_router(api_router)
    app.include_router(ui_router)

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict:
        # Liveness only: 200 whenever the process serves requests, even before
        # authorization — restarting the container cannot fix missing tokens,
        # completing the auth flow can.
        return {"status": "ok"}

    @app.get("/api/v1/status", tags=["ops"])
    def status(request: Request) -> dict:
        return status_payload(config, store, request.app.state.runtime)

    return app


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    config = Config.from_env()
    uvicorn.run(create_app(config), host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    run()
