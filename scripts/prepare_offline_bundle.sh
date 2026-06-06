#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT_DIR="${1:-$ROOT_DIR/runtime/offline_bundle}"
COMPOSE_FILE="$ROOT_DIR/infra/docker/docker-compose.yml"

command -v docker >/dev/null 2>&1 || {
  echo "缺少 docker"
  exit 1
}

test -d "$ROOT_DIR/runtime/models" || {
  echo "缺少 runtime/models，请先运行 scripts/prepare_offline_models.sh"
  exit 1
}

mkdir -p "$OUTPUT_DIR"
docker compose -f "$COMPOSE_FILE" pull redis
docker compose -f "$COMPOSE_FILE" build api worker web

docker save \
  redis:7-alpine \
  brush-painting-api:offline \
  brush-painting-worker:offline \
  brush-painting-web:offline \
  -o "$OUTPUT_DIR/docker-images.tar"

tar \
  --exclude=.git \
  --exclude=.venv \
  --exclude=node_modules \
  --exclude=runtime/offline_bundle \
  --exclude=runtime/db.sqlite \
  --exclude=runtime/db.sqlite-shm \
  --exclude=runtime/db.sqlite-wal \
  --exclude=runtime/uploads \
  --exclude=runtime/outputs \
  --exclude=runtime/thumbs \
  --exclude=runtime/exports \
  --exclude=runtime/test_runtime \
  --exclude=runtime/test.db \
  --exclude=runtime/test.db-shm \
  --exclude=runtime/test.db-wal \
  -czf "$OUTPUT_DIR/project-and-models.tar.gz" \
  -C "$ROOT_DIR" .

echo "离线部署包已准备到 $OUTPUT_DIR"
