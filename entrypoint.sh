#!/bin/bash
set -e

APP_MODE="${APP_MODE:-bot}"
API_PORT="${API_PORT:-8080}"

if [ "$APP_MODE" = "api" ]; then
  echo "Starting webhook API on port ${API_PORT}..."
  exec uvicorn src.api.main:app --host 0.0.0.0 --port "${API_PORT}"
fi

echo "Starting bot..."
exec python src/main.py
