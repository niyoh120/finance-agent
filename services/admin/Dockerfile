FROM python:3.11-slim

WORKDIR /app

COPY shared /app/shared
COPY services/admin /app/admin

RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir /app/shared

WORKDIR /app/admin
RUN pip install --no-cache-dir .

CMD ["python", "src/main.py"]
