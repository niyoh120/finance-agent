# Streamlit intranet dashboard for options trading assistance.
# Built from repo root so workspace members (shared, openbb_finance, this pkg)
# resolve under a single uv sync.
FROM python:3.12-slim

RUN pip install --no-cache-dir "uv==0.9.26"

WORKDIR /app

# --- copy lockfile + all workspace manifests --------------------------------
COPY pyproject.toml uv.lock ./
COPY shared/pyproject.toml shared/pyproject.toml
COPY openbb_finance/pyproject.toml openbb_finance/pyproject.toml
COPY services/options-dashboard/pyproject.toml services/options-dashboard/pyproject.toml

# Pre-install pure PyPI dependencies (cached layer). --no-install-project skips
# workspace members so this layer stays valid when only source files change.
# We intentionally do NOT pass --package here; workspace members need their
# source copied (next layer) before they can build.
RUN uv sync --frozen --no-install-workspace

# --- source layer: copy workspace members and build the dashboard package ---
COPY shared shared
COPY openbb_finance openbb_finance
COPY services/options-dashboard services/options-dashboard

RUN uv sync --frozen --package options-dashboard

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=3); sys.exit(0)" || exit 1

CMD ["uv", "run", "--package", "options-dashboard", "streamlit", "run", "services/options-dashboard/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
