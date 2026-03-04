#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000/api/v1}"
CROP_COUNT="${CROP_COUNT:-6}"
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

echo "[1/9] health"
request GET "${API_BASE%/api/v1}/healthz"
require_2xx "health"

TMP_DIR=$(mktemp -d)
export TMP_DIR
python3 - <<'PY'
import os

w, h = 64, 64
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

echo "[2/9] create session"
request POST "$API_BASE/sessions" -F "file=@${IMG_PATH}"
require_2xx "create session"
session_id=$(json_field_or_fail "create session" session_id)
[[ -n "$session_id" ]] || { echo "create session failed: session_id is empty"; echo "$RESPONSE_BODY"; exit 1; }
echo "session_id=$session_id"

echo "[3/9] segment"
request POST "$API_BASE/sessions/$session_id/segment" -H 'Content-Type: application/json' -d "{\"crop_count\":$CROP_COUNT}"
require_2xx "segment"
segment_job=$(json_field_or_fail "segment" id)
poll_job "$segment_job"

echo "[4/9] lock style"
request POST "$API_BASE/sessions/$session_id/style/lock" -H 'Content-Type: application/json' -d "{\"style_id\":\"$STYLE_ID\"}"
require_2xx "lock style"
lock_status=$(json_field_or_fail "lock style" status)
[[ -n "$lock_status" ]] || { echo "lock style failed: status is empty"; echo "$RESPONSE_BODY"; exit 1; }

echo "[5/9] generate"
request POST "$API_BASE/sessions/$session_id/crops/generate" -H 'Content-Type: application/json' -d '{}'
require_2xx "generate"
gen_job=$(json_field_or_fail "generate" id)
poll_job "$gen_job"

echo "[6/9] regenerate first crop"
request GET "$API_BASE/sessions/$session_id"
require_2xx "get session before regenerate"
session_json="$RESPONSE_BODY"
first_crop=$(printf '%s' "$session_json" | python3 -c 'import json,sys; obj=json.load(sys.stdin); print(obj["crops"][0]["id"])')
request POST "$API_BASE/crops/$first_crop/regenerate" -H 'Content-Type: application/json' -d '{}'
require_2xx "regenerate first crop"
regen_job=$(json_field_or_fail "regenerate first crop" id)
poll_job "$regen_job"

echo "[7/9] approve all crops"
request GET "$API_BASE/sessions/$session_id"
require_2xx "get session before approve"
session_json="$RESPONSE_BODY"
crop_ids=$(printf '%s' "$session_json" | python3 -c 'import json,sys; obj=json.load(sys.stdin); [print(c["id"]) for c in obj["crops"]]')
for cid in $crop_ids; do
  request POST "$API_BASE/crops/$cid/approve" -H 'Content-Type: application/json' -d '{}'
  require_2xx "approve crop $cid"
done

echo "[8/9] compose"
request POST "$API_BASE/sessions/$session_id/compose" -H 'Content-Type: application/json' -d '{"seam_pass_count":1}'
require_2xx "compose"
compose_job=$(json_field_or_fail "compose" id)
poll_job "$compose_job"

echo "[9/9] export + final status"
request POST "$API_BASE/sessions/$session_id/export" -H 'Content-Type: application/json' -d '{}'
require_2xx "export"
final_url=$(json_field_or_fail "export" final_image_url)
manifest_url=$(json_field_or_fail "export" manifest_url)
[[ -n "$final_url" && -n "$manifest_url" ]] || { echo "export failed: missing output urls"; echo "$RESPONSE_BODY"; exit 1; }
request GET "$API_BASE/sessions/$session_id"
require_2xx "final get session"
final_status=$(json_field_or_fail "final get session" status)
[[ "$final_status" == "DONE" ]] || { echo "unexpected final status: $final_status"; exit 1; }

echo "E2E_MOCK=PASS"
echo "FINAL_IMAGE_URL=$final_url"
echo "MANIFEST_URL=$manifest_url"
