FROM python:3.11-slim AS builder

WORKDIR /build
COPY pyproject.toml .
COPY app/ app/
RUN pip install --no-cache-dir .

FROM python:3.11-slim

RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn
COPY app/ app/
COPY data/ data/
COPY data/seeds.json /app/seeds/seeds.json
COPY entrypoint.sh /app/entrypoint.sh

RUN chown -R appuser:appuser /app && chmod +x /app/entrypoint.sh

EXPOSE 8080
ENTRYPOINT ["/app/entrypoint.sh"]
