FROM python:3.11-slim

WORKDIR /app

COPY shared /app/shared
COPY services/mcp-server /app/mcp-server

RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir /app/shared

WORKDIR /app/mcp-server
RUN pip install --no-cache-dir .

CMD ["python","src/main.py"]
