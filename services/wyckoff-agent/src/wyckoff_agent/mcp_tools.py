"""MCP toolset 封装，用于 wyckoff agent

该模块封装了 Finance MCP Server 的 toolset 创建逻辑，
使 Agent 能够通过 MCP 协议调用数据获取工具（如 fetch_stock_history）。
"""

from __future__ import annotations

import logging
import os

from pydantic_ai import AbstractToolset
from pydantic_ai.mcp import MCPServerStdio

from .logging_utils import configure_logging

logger = logging.getLogger(__name__)


def create_mcp_toolset() -> AbstractToolset:
    """创建 Finance MCP Server toolset

    该 toolset 会启动 MCP server 子进程，并通过 stdio 通信。
    Agent 可以使用该 toolset 调用以下工具：
    - fetch_stock_history: 获取股票 K 线数据
    - query_options_flow: 查询期权大单流向
    - query_news_articles: 查询新闻文章
    - 等等...

    配置通过环境变量：
    - WYCKOFF_MCP_COMMAND: MCP server 启动命令 (默认: uv)
    - WYCKOFF_MCP_ARGS: MCP server 参数 (默认: "run python -m mcp_server.studio")

    Returns:
        配置好的 MCPServerStdio 实例
    """
    configure_logging()

    cmd = os.getenv("FA_WYCKOFF_MCP_COMMAND", "uv")
    args_s = os.getenv("FA_WYCKOFF_MCP_ARGS", "run python -m mcp_server.studio")
    timeout = int(os.getenv("FA_WYCKOFF_MCP_TIMEOUT", "120"))
    env = dict(os.environ)

    # MCP 子进程必须显式传递 parent env，否则在某些 studio/子进程模式下可能丢失配置。
    env.setdefault(
        "FA_MCP_SERVER_STOCK_API_URL",
        os.getenv("FA_MCP_SERVER_STOCK_API_URL", "http://stock-api:3000"),
    )

    logger.info("MCP toolset start: cmd=%s args=%s timeout=%ss", cmd, args_s, timeout)
    logger.debug(
        "MCP toolset env: FA_MCP_SERVER_STOCK_API_URL=%s",
        env.get("FA_MCP_SERVER_STOCK_API_URL"),
    )

    return MCPServerStdio(
        cmd,
        args=args_s.split(),
        env=env,
        timeout=timeout,  # MCP server 启动和工具调用超时
    ).filtered(lambda ctx, tool_def: "history" in tool_def.name)
