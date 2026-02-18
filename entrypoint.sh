#!/bin/sh
# Fix volume permissions for appuser, then drop to appuser
chown -R appuser:appuser /app/data 2>/dev/null || true
exec su -s /bin/sh appuser -c "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"
