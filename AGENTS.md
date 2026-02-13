# Context for AI Agents

This file provides architectural context for AI agents working on this repository.

## Project Structure

This is a **Monorepo** using `uv` workspaces for Python and `npm` for TypeScript.

- **Root**: `pyproject.toml` defines the workspace.
- **Shared**: `shared/` contains common Python code (Database, Models). It is linked as a local dependency (`finance-shared`) in other services.
- **Services**: `services/` contains independent microservices.

### Microservices

1.  **db** (PostgreSQL):
    - Defined in `docker-compose.yml` only.
    - Credentials in `.env`.

2.  **stock-api** (TypeScript/Node.js):
    - Path: `services/stock-api`
    - Logic: Fastify server wrapping `@mathieuc/tradingview`.
    - **Constraint**: MUST NOT access the Database directly. It only provides data via HTTP API.

3.  **macro-scraper** (Python):
    - Path: `services/macro-scraper`
    - Logic: Pulls macro data from indexbha.com (The Dial) and writes to DB using `finance-shared`.

4.  **bubbleseek-scraper** (Python):
    - Path: `services/bubbleseek-scraper`
    - Logic: Fetches news and options flow data from bubbleseek.ai API and writes to DB using `finance-shared`.

5.  **mcp-server** (Python):
    - Path: `services/mcp-server`
    - Logic: Exposes DB data via Model Context Protocol (MCP) over HTTP.
    - **Direct**: Uses `akshare` library directly for A-share/HK-share fundamental data and global macro indicators.
    - **Note**: A-share market data (K-lines) uses TradingView (stock-api).

## Key Constraints

1.  **Dependency Isolation**: Each service has its own `pyproject.toml`. Do NOT add dependencies to the root `pyproject.toml` unless they are for dev tooling (e.g., `ruff`).
2.  **Shared Logic**: Any DB model or utility MUST go into `shared/`. Services import from `finance-shared`.
3.  **Docker**: The project is designed to run via `docker compose`.
4.  **No ORM in TS**: The TypeScript service (`stock-api`) is stateless and DB-agnostic.

## Common Tasks

### Adding a new dependency to a service
```bash
cd services/<service-name>
uv add <package-name>
```

### Running Migrations
Migrations are managed by Alembic in the root, but executed in the context of a service (for example `macro-scraper`) that has the DB driver installed.

```bash
docker compose run --rm macro-scraper uv run alembic upgrade head
```
