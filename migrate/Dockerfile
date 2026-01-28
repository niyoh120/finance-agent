FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./

COPY shared/pyproject.toml shared/pyproject.toml

RUN uv sync --frozen --no-install-project --package finance-shared

COPY shared shared

RUN uv sync --frozen --package finance-shared

COPY alembic.ini alembic.ini
COPY alembic alembic

CMD ["uv", "run", "alembic", "upgrade", "head"]
