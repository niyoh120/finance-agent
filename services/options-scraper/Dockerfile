FROM python:3.11-slim

WORKDIR /app

# Install git for discord.py-self dependency
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

COPY shared /app/shared
COPY services/options-scraper /app/scraper

RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir /app/shared

WORKDIR /app/scraper
RUN pip install --no-cache-dir .

CMD ["python", "src/main.py"]
