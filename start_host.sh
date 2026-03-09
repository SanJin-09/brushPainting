#!/usr/bin/env bash
set -e

cd /home/featurize/work/brushPainting
source .venv/bin/activate
set -a
source .env.host
set +a

mkdir -p runtime runtime/media

docker compose -f infra/docker/docker-compose.yml up -d postgres redis minio

pkill -f "python -m uvicorn services.api.app.main:app" 2>/dev/null || true
pkill -f "python -m celery -A services.worker.celery_app.celery_app worker" 2>/dev/null || true
pkill -f "vite --host 0.0.0.0 --port 5173" 2>/dev/null || true

nohup python -m uvicorn services.api.app.main:app --host 0.0.0.0 --port 8000 > runtime/api.log 2>&1 &
nohup python -m celery -A services.worker.celery_app.celery_app worker -Q default --loglevel=info > runtime/worker.log 2>&1 &
nohup sh -lc 'cd /home/featurize/work/brushPainting/apps/web && npm run dev -- --host 0.0.0.0 --port 5173' > runtime/web.log 2>&1 &

echo "started"
echo "api log:    tail -f /home/featurize/work/brushPainting/runtime/api.log"
echo "worker log: tail -f /home/featurize/work/brushPainting/runtime/worker.log"
echo "web log:    tail -f /home/featurize/work/brushPainting/runtime/web.log"
