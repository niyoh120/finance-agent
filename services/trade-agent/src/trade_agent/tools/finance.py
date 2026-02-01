from agno.tools.mcp import MCPTools

from ..config import load_config

config = load_config()


class FinanceTools(MCPTools):
    def __init__(self, *args, **kwargs):
        if "url" not in kwargs:
            kwargs["url"] = config.mcp_server.url
        super().__init__(*args, **kwargs)
