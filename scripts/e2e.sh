#!/usr/bin/env bash
# e2e.sh — 一键启动环境 + 运行 Playwright E2E 认证测试
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------- 测试配置 ----------
export API_AUTH_MODE="api_key"
export BRUSH_API_KEYS="e2e-test-key-32-chars-minimum-xyz"
export API_SESSION_SECRET="e2e-session-secret-32-chars-xyzw"
export API_PUBLISH_HOST="127.0.0.1"
export ALLOWED_ORIGINS="http://127.0.0.1:5173"
export ALLOWED_HOSTS="localhost,127.0.0.1,::1,testserver"
export APP_ENV="development"
export MODEL_BACKEND="mock"
export SAM3_BACKEND="mock"

API_PORT="${API_PORT:-8000}"

# ---------- 清理函数 ----------
cleanup() {
  echo ">>> 清理..."
  if [ -n "${API_PID:-}" ]; then
    kill "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

# ---------- 启动 API ----------
echo ">>> 启动 API (端口 $API_PORT, $API_AUTH_MODE 模式)..."
cd "$ROOT"
python -m uvicorn services.api.app.main:app \
  --host 127.0.0.1 \
  --port "$API_PORT" \
  --reload &
API_PID=$!

# 等待 API 就绪
echo ">>> 等待 API 就绪..."
for i in $(seq 1 30); do
  if curl -s "http://127.0.0.1:$API_PORT/healthz" > /dev/null 2>&1; then
    echo ">>> API 已就绪"
    break
  fi
  sleep 1
done

# ---------- 运行 E2E ----------
echo ">>> 运行 Playwright E2E..."
cd "$ROOT/apps/web"
VITE_API_BASE="http://127.0.0.1:$API_PORT/api" npx playwright test "$@"
EXIT_CODE=$?

if [ "$EXIT_CODE" -eq 0 ]; then
  echo ""
  echo "========== ✓ E2E 全部通过 =========="
else
  echo ""
  echo "========== ✗ E2E 存在失败 =========="
fi

exit "$EXIT_CODE"
