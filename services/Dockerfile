FROM python:3.12-slim

RUN pip install --no-cache-dir uv

ARG MODULE_NAME
ARG MODULE_ENTRY

RUN : "${MODULE_NAME:?Build argument MODULE_NAME is required and cannot be empty!}"
RUN : "${MODULE_ENTRY:?Build argument MODULE_ENTRY is required and cannot be empty!}"

WORKDIR /app

COPY pyproject.toml uv.lock ./

COPY shared/pyproject.toml shared/pyproject.toml

RUN uv sync --frozen --no-install-project --package finance-shared

COPY shared shared

RUN uv sync --frozen --package finance-shared

COPY services/${MODULE_NAME}/pyproject.toml services/${MODULE_NAME}/pyproject.toml

RUN uv sync --frozen --no-install-project --package ${MODULE_NAME}

COPY services/${MODULE_NAME} services/${MODULE_NAME}

RUN uv sync --frozen --package ${MODULE_NAME}

ENV MODULE_ENTRY=${MODULE_ENTRY}

CMD uv run python -m ${MODULE_ENTRY}
