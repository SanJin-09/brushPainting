#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"
source .venv/bin/activate
set -a
if [[ -f .env ]]; then
  source .env
fi
source .env.host
set +a

: "${REDIS_PASSWORD:?请在 .env.host 或当前环境中设置至少 32 位的 REDIS_PASSWORD}"
API_BIND_HOST="${API_BIND_HOST:-127.0.0.1}"
WEB_BIND_HOST="${WEB_BIND_HOST:-127.0.0.1}"
export API_PUBLISH_HOST="$API_BIND_HOST"

mkdir -p runtime
docker compose -f infra/docker/docker-compose.yml up -d redis

pkill -f "python -m uvicorn services.api.app.main:app" 2>/dev/null || true
pkill -f "python -m services.worker.rq_worker" 2>/dev/null || true
pkill -f "vite --host .* --port 5173" 2>/dev/null || true

nohup python -m uvicorn services.api.app.main:app --host "$API_BIND_HOST" --port 8000 > runtime/api.log 2>&1 &
nohup python -m services.worker.rq_worker > runtime/worker.log 2>&1 &
nohup sh -lc "cd '$ROOT_DIR/apps/web' && npm run dev -- --host '$WEB_BIND_HOST' --port 5173" > runtime/web.log 2>&1 &

echo "started"
echo "api log:    tail -f $ROOT_DIR/runtime/api.log"
echo "worker log: tail -f $ROOT_DIR/runtime/worker.log"
echo "web log:    tail -f $ROOT_DIR/runtime/web.log"
