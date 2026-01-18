FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

# 关键：把 workspace 根的锁文件拷进来
COPY pyproject.toml uv.lock ./

# 以及子包自身的 pyproject（uv 需要看到 workspace 成员定义/元数据）
COPY shared/pyproject.toml shared/pyproject.toml

# 安装依赖（只装环境，不装源码）
RUN uv sync --frozen --no-install-project --package finance-shared

# 再拷贝源码（用缓存）
COPY shared shared

# 只同步/安装这个包
RUN uv sync --frozen --package finance-shared

COPY services/options-scraper/pyproject.toml services/options-scraper/pyproject.toml

RUN uv sync --frozen --no-install-project --package options-scraper

COPY services/options-scraper services/options-scraper

RUN uv sync --frozen --package options-scraper

CMD ["uv", "run", "python", "-m", "options_scraper.main"]
