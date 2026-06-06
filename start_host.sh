#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"
source .venv/bin/activate
set -a
source .env.host
set +a

mkdir -p runtime
docker compose -f infra/docker/docker-compose.yml up -d redis

pkill -f "python -m uvicorn services.api.app.main:app" 2>/dev/null || true
pkill -f "python -m services.worker.rq_worker" 2>/dev/null || true
pkill -f "vite --host 0.0.0.0 --port 5173" 2>/dev/null || true

nohup python -m uvicorn services.api.app.main:app --host 0.0.0.0 --port 8000 > runtime/api.log 2>&1 &
nohup python -m services.worker.rq_worker > runtime/worker.log 2>&1 &
nohup sh -lc "cd '$ROOT_DIR/apps/web' && npm run dev -- --host 0.0.0.0 --port 5173" > runtime/web.log 2>&1 &

echo "started"
echo "api log:    tail -f $ROOT_DIR/runtime/api.log"
echo "worker log: tail -f $ROOT_DIR/runtime/worker.log"
echo "web log:    tail -f $ROOT_DIR/runtime/web.log"
