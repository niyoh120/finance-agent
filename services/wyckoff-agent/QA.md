# Wyckoff Agent QA

## Prereqs
- `mise run install`
- Ensure `STOCK_API_URL` points to running `stock-api` (e.g. `http://localhost:3000`)
- Ensure OpenAI-compatible endpoint configured:
  - `OPENAI_API_KEY`
  - `OPENAI_BASE_URL` (optional, defaults to `https://api.openai.com/v1`)
  - `OPENAI_MODEL` (optional, defaults `gpt-4o`)

## Run services
1) Start stock-api:
- `mise run stock-api`

2) Start wyckoff agent (will spawn mcp-server subprocess via stdio):
- `mise run wyckoff-agent`

## Manual Flow
- On first load, input `NASDAQ:AAPL`
- Expect:
  - Plotly interactive candlestick chart (with MA50/MA200 + volume subplot)
  - Attachments: `wyckoff.png`, `analysis.json`, `figure.json`
- Then run `/update` and confirm chart refresh.

## Known limitations
- If `STOCK_API_URL` is unset or stock-api is not running, data will be empty (candles=0).
- Phase/Zone/Event accuracy currently depends heavily on LLM overlay prompt; deterministic Wyckoff detection is not fully implemented yet.
