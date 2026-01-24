from .mcp import mcp

if __name__ == "__main__":
    mcp.run(transport="http", port=8087, json_response=True)
