"""MCP toolset 封装，用于 wyckoff agent

该模块封装了 Finance MCP Server 的 toolset 创建逻辑，
使 Agent 能够通过 MCP 协议调用数据获取工具（如 fetch_stock_history）。
"""

from __future__ import annotations

import os

from pydantic_ai.mcp import MCPServerStdio


def create_mcp_toolset() -> MCPServerStdio:
    """创建 Finance MCP Server toolset

    该 toolset 会启动 MCP server 子进程，并通过 stdio 通信。
    Agent 可以使用该 toolset 调用以下工具：
    - fetch_stock_history: 获取股票 K 线数据
    - query_options_flow: 查询期权大单流向
    - query_news_articles: 查询新闻文章
    - 等等...

    配置通过环境变量：
    - WYCKOFF_MCP_COMMAND: MCP server 启动命令 (默认: uv)
    - WYCKOFF_MCP_ARGS: MCP server 参数 (默认: "run python -m mcp_server.main")

    Returns:
        配置好的 MCPServerStdio 实例
    """
    cmd = os.getenv("WYCKOFF_MCP_COMMAND", "uv")
    args_s = os.getenv("WYCKOFF_MCP_ARGS", "run python -m mcp_server.main")

    return MCPServerStdio(
        cmd,
        args=args_s.split(),
        timeout=60,  # MCP server 启动和工具调用超时
    )
