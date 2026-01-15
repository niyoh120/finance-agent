# Finance MCP

Discord 期权大单数据抓取器 + MCP 服务器，供 AI 分析使用。

## 安装

```bash
uv sync
```

## 配置

复制 `.env.example` 为 `.env` 并填写：

```bash
cp .env.example .env
```

### 获取 DISCORD_TOKEN

> ⚠️ **风险提示**: 使用用户 token 违反 Discord ToS，有封号风险。建议使用小号。

1. 打开 Discord 网页版 (discord.com/app) 或桌面客户端
2. 按 `F12` 打开开发者工具
3. 切换到 **Network** (网络) 标签
4. 在 Discord 中随便点击一个频道触发请求
5. 找到任意请求，点击查看 **Headers** (请求头)
6. 找到 `Authorization` 字段，其值就是你的 token

或者在 Console 中执行：
```javascript
(webpackChunkdiscord_app.push([[''],{},e=>{m=[];for(let c in e.c)m.push(e.c[c])}]),m).find(m=>m?.exports?.default?.getToken!==void 0).exports.default.getToken()
```

### 获取 DISCORD_CHANNEL_ID

1. 在 Discord 设置中开启「开发者模式」(用户设置 → 高级 → 开发者模式)
2. 右键点击目标频道 → 「复制频道 ID」

### 环境变量

- `DISCORD_TOKEN`: Discord 用户 token
- `DISCORD_CHANNEL_ID`: 目标频道 ID

## 使用

### 启动抓取器

```bash
uv run scraper
```

### 启动 MCP 服务器

```bash
uv run mcp-server
```

### 启动管理界面

```bash
uv run admin
```

访问 http://127.0.0.1:8000/admin 即可进行数据的增删改查。

可通过环境变量配置：
- `ADMIN_HOST`: 监听地址 (默认 127.0.0.1)
- `ADMIN_PORT`: 端口号 (默认 8000)

### Claude Desktop 配置

在 `claude_desktop_config.json` 中添加：

```json
{
  "mcpServers": {
    "options-flow": {
      "command": "uv",
      "args": ["--directory", "/path/to/finance-mcp", "run", "mcp-server"]
    }
  }
}
```

## MCP 工具

- `query_options_flow`: 查询期权大单数据
- `get_flow_summary`: 获取期权流向汇总统计  
- `get_unusual_activity`: 获取异常期权活动
