#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000/api/v1}"
STYLE_ID="${STYLE_ID:-gongbi_default}"
RESPONSE_BODY=""
RESPONSE_STATUS=""

json_get() {
  local key="$1"
  python3 -c '
import json
import sys

key = sys.argv[1]
raw = sys.stdin.read().strip()
if not raw:
    raise SystemExit(2)
obj = json.loads(raw)
if not isinstance(obj, dict):
    raise SystemExit(3)
value = obj.get(key, "")
if value is None:
    print("")
else:
    print(value)
' "$key"
}

request() {
  local method="$1"
  local url="$2"
  shift 2

  local body_file
  body_file=$(mktemp)
  RESPONSE_STATUS=$(curl -sS -o "$body_file" -w "%{http_code}" -X "$method" "$url" "$@")
  RESPONSE_BODY=$(cat "$body_file")
  rm -f "$body_file"
}

require_2xx() {
  local step="$1"
  if [[ ! "$RESPONSE_STATUS" =~ ^2 ]]; then
    echo "$step failed: HTTP $RESPONSE_STATUS"
    echo "$RESPONSE_BODY"
    exit 1
  fi
}

json_field_or_fail() {
  local step="$1"
  local key="$2"
  local value
  if ! value=$(printf '%s' "$RESPONSE_BODY" | json_get "$key"); then
    echo "$step failed: response is not valid JSON" >&2
    echo "$RESPONSE_BODY" >&2
    return 1
  fi
  printf '%s' "$value"
}

poll_job() {
  local job_id="$1"
  local timeout_sec="${2:-120}"
  local elapsed=0
  while (( elapsed < timeout_sec )); do
    request GET "$API_BASE/jobs/$job_id"
    if [[ ! "$RESPONSE_STATUS" =~ ^2 ]]; then
      echo "poll job failed: HTTP $RESPONSE_STATUS"
      echo "$RESPONSE_BODY"
      return 1
    fi

    local job status
    job="$RESPONSE_BODY"
    if ! status=$(printf '%s' "$job" | json_get status); then
      echo "poll job failed: invalid JSON"
      echo "$job"
      return 1
    fi
    if [[ "$status" == "SUCCEEDED" ]]; then
      echo "job[$job_id] => SUCCEEDED"
      return 0
    fi
    if [[ "$status" == "FAILED" ]]; then
      echo "job[$job_id] => FAILED"
      echo "$job"
      return 1
    fi
    sleep 1
    ((elapsed+=1))
  done
  echo "job[$job_id] => TIMEOUT"
  return 1
}

echo "[1/8] health"
request GET "${API_BASE%/api/v1}/healthz"
require_2xx "health"

TMP_DIR=$(mktemp -d)
export TMP_DIR
python3 - <<'PY'
import os

w, h = 96, 72
path = os.path.join(os.environ['TMP_DIR'], 'test.ppm')
with open(path, 'wb') as f:
    f.write(f"P6\n{w} {h}\n255\n".encode('ascii'))
    for y in range(h):
        for x in range(w):
            r = int(255 * x / (w - 1))
            g = int(255 * y / (h - 1))
            b = 180
            f.write(bytes((r, g, b)))
print(path)
PY
IMG_PATH="$TMP_DIR/test.ppm"

echo "[2/8] create session"
request POST "$API_BASE/sessions" -F "file=@${IMG_PATH}"
require_2xx "create session"
session_id=$(json_field_or_fail "create session" session_id)
echo "session_id=$session_id"

echo "[3/8] lock style"
request POST "$API_BASE/sessions/$session_id/style/lock" -H 'Content-Type: application/json' -d "{\"style_id\":\"$STYLE_ID\"}"
require_2xx "lock style"

echo "[4/8] render full image"
request POST "$API_BASE/sessions/$session_id/render" -H 'Content-Type: application/json' -d '{}'
require_2xx "render"
render_job=$(json_field_or_fail "render" id)
poll_job "$render_job"

echo "[5/8] mask assist"
mask_rle=$(python3 - <<'PY'
import json
import numpy as np

h, w = 72, 96
mask = np.zeros((h, w), dtype=np.uint8)
mask[18:54, 30:66] = 1
flat = mask.flatten(order="C")
counts = []
last = int(flat[0])
run = 1
for val in flat[1:]:
    val_i = int(val)
    if val_i == last:
        run += 1
    else:
        counts.append(run)
        run = 1
        last = val_i
counts.append(run)
print(json.dumps({"h": h, "w": w, "start": int(flat[0]), "counts": counts}))
PY
)
mask_rle_json=$(printf '%s' "$mask_rle" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')
request POST "$API_BASE/sessions/$session_id/mask-assist" -H 'Content-Type: application/json' -d "{\"mask_rle\":$mask_rle_json}"
require_2xx "mask assist"
assist_mask=$(json_field_or_fail "mask assist" mask_rle)
bbox_x=$(json_field_or_fail "mask assist" bbox_x)
bbox_y=$(json_field_or_fail "mask assist" bbox_y)
bbox_w=$(json_field_or_fail "mask assist" bbox_w)
bbox_h=$(json_field_or_fail "mask assist" bbox_h)

echo "[6/8] local edit"
assist_mask_json=$(printf '%s' "$assist_mask" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')
request POST "$API_BASE/sessions/$session_id/edits" -H 'Content-Type: application/json' -d "{\"mask_rle\":$assist_mask_json,\"bbox_x\":$bbox_x,\"bbox_y\":$bbox_y,\"bbox_w\":$bbox_w,\"bbox_h\":$bbox_h,\"prompt_override\":\"花瓣更淡\"}"
require_2xx "local edit"
edit_job=$(json_field_or_fail "local edit" id)
poll_job "$edit_job"

echo "[7/8] adopt latest candidate"
request GET "$API_BASE/sessions/$session_id"
require_2xx "get session"
session_json="$RESPONSE_BODY"
candidate_id=$(printf '%s' "$session_json" | python3 -c 'import json,sys; obj=json.load(sys.stdin); versions=sorted(obj["versions"], key=lambda x:x["created_at"]); print([v["id"] for v in versions if not v["is_current"]][-1])')
request POST "$API_BASE/sessions/$session_id/versions/$candidate_id/adopt" -H 'Content-Type: application/json' -d '{}'
require_2xx "adopt version"

echo "[8/8] export + final status"
request POST "$API_BASE/sessions/$session_id/export" -H 'Content-Type: application/json' -d '{}'
require_2xx "export"
final_url=$(json_field_or_fail "export" final_image_url)
manifest_url=$(json_field_or_fail "export" manifest_url)
request GET "$API_BASE/sessions/$session_id"
require_2xx "final get session"
final_status=$(json_field_or_fail "final get session" status)
[[ "$final_status" == "DONE" ]] || { echo "unexpected final status: $final_status"; exit 1; }

echo "E2E_MOCK=PASS"
echo "FINAL_IMAGE_URL=$final_url"
echo "MANIFEST_URL=$manifest_url"
