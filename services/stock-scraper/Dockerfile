FROM python:3.11-slim

WORKDIR /app

# Copy shared module
COPY shared /app/shared

# Copy scraper service
COPY services/stock-scraper /app/scraper

# Install build dependencies
RUN pip install --no-cache-dir --upgrade pip

# Install shared module
RUN pip install --no-cache-dir /app/shared

# Install scraper service
WORKDIR /app/scraper
RUN pip install --no-cache-dir .

CMD ["python", "src/main.py"]
