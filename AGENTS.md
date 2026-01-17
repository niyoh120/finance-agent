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

3.  **stock-scraper** (Python):
    - Path: `services/stock-scraper`
    - Logic: Polls `stock-api` and writes to DB using `finance-shared`.
    - Config: `config.yaml`.

4.  **options-scraper** (Python):
    - Path: `services/options-scraper`
    - Logic: Connects to Discord (user token) -> Parses messages -> Writes to DB using `finance-shared`.

5.  **mcp-server** (Python):
    - Path: `services/mcp-server`
    - Logic: Exposes DB data via Model Context Protocol (MCP) over Stdio.

6.  **admin** (Python):
    - Path: `services/admin`
    - Logic: SQLAdmin interface for managing data.

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
Migrations are managed by Alembic in the root, but executed in the context of a service (usually `stock-scraper` or `admin`) that has the DB driver installed.

```bash
docker compose run --rm stock-scraper uv run alembic upgrade head
```
