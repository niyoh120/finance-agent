# Project AGENTS.md

## Commands
- Use `mise tasks ls` to discover the current task list before running project commands.
- Install workspace dependencies with `mise run install`.
- Start services through `mise run <task-name>` for app tasks such as `stock-api`, `mcp-server`, `macro-scraper`, `options-scraper`, `bubbleseek-scraper`, `futunn-scraper`, `trade-agent`, and `trade-agent-discord-bot`.
- Manage database migrations with `mise run db-upgrade`, `mise run db-downgrade <revision>`, `mise run db-revision <message>`, `mise run db-revision-manual <message>`, `mise run db-current`, and `mise run db-history`.
- Install and run hooks with `mise run hooks-install` and `mise run hooks-run`.
- Build and publish container images with the `mise run docker-build-*`, `mise run docker-push-*`, and `mise run docker-build-push-*` tasks when relevant.

## Monorepo
- Root `pyproject.toml` defines the `uv` workspace for Python services and shared packages.
- `shared/` contains reusable database models and utilities consumed as `finance-shared`.
- `services/` contains independently deployable services.
- `services/stock-api` is the only Node.js service; the rest of the services use Python.

## Environment & Dependency Management
- Manage all development environment tool versions and task entry points through `mise`.
- Use `mise.toml` as the source of truth for local development configuration.
- Manage Python dependencies and workspaces with `uv`.
- Manage Node.js dependencies in `services/stock-api` with `npm`.
- Add Python dependencies with `uv add` in the target service or shared package.
- Add Node.js dependencies with `npm install` in `services/stock-api`.

## Git Workflow
- Keep work on topic branches and merge back into `main` through reviewed pull requests.
- Sync with the latest target branch before opening or merging a pull request.
- Rebase or merge the target branch into the working branch before final validation when conflicts or drift appear.
- Run relevant validators before commit, before pull request creation, and again after conflict resolution.
- Review `git diff` and `git status` before commit to confirm the exact file set and content.

## Commit Convention
- Follow the existing Conventional Commit style such as `feat(scope): ...`, `fix(scope): ...`, and `chore(scope): ...`.
- Use a concise scope that matches the changed service or subsystem, such as `openbb`, `trade-agent`, `mcp-server`, or `db`.
- Write commit messages in Chinese, using imperative mood and describing the intent of the change.
- Keep each commit focused on one logical change so history stays easy to review and revert.

## Branch Merge Guidelines
- Prefer squash merge or rebase-friendly history when preparing a clean pull request branch.
- Resolve conflicts locally, rerun validators, and inspect the final diff before merging.
- Preserve service boundaries and shared package contracts during conflict resolution.
- Merge only after reviewers approve and required checks pass.

## Python
- Use Python 3.11+ compatible code.
- Keep service-specific dependencies inside each service `pyproject.toml`.
- Put shared DB models and reusable persistence utilities in `shared/`.
- Use `sqlalchemy` async patterns already present in the repository.
- Validate integrations and parsing logic with focused pytest coverage when behavior changes.

## TypeScript
- Use strict TypeScript.
- Avoid `any`; use `unknown` plus narrowing when needed.
- Exported functions must have explicit return types.
- Prefer discriminated unions for state machines and result types.

## Fastify / Node.js
- Follow the existing Fastify patterns in `services/stock-api`.
- Keep `stock-api` stateless and database-agnostic.
- Expose data through HTTP boundaries only.

## Architecture Constraints
- `stock-api` provides TradingView-backed market data over HTTP and does not access PostgreSQL.
- Scraper and provider services write through `finance-shared` instead of duplicating DB logic.
- Run DB migrations through Alembic from the root using a service environment that has the DB driver installed.
- Prefer the smallest service-local change that preserves current Docker Compose workflows.

## Tests
- Unit-test pure parsing and transformation logic.
- Add integration tests for API boundaries and DB write paths when behavior changes.
- Run the narrowest relevant checks during iteration and the full relevant validators before finishing.
