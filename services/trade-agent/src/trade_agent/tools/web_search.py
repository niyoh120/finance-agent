from agno.tools.mcp import MCPTools


class ExaWebSearchTools(MCPTools):
    def __init__(self, *args, **kwargs):
        if "url" not in kwargs:
            kwargs["url"] = "https://mcp.exa.ai/mcp"
        super().__init__(*args, **kwargs)
