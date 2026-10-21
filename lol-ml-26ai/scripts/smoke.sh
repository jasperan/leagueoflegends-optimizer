#!/usr/bin/env bash
# End-to-end smoke test of the core path on the small committed sample. No downloads, no API keys, no cloud.
# About 3 minutes on a laptop. Usage: bash scripts/smoke.sh   (or: make smoke)
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python}"
export LOLML_SMOKE=1 LOLML_HOME="$(mktemp -d)" PYTHONUNBUFFERED=1
echo "== smoke test, work dir $LOLML_HOME"

echo "== unit tests"
"$PY" tests/test_liveclient.py
"$PY" tests/test_riot_mock.py

echo "== notebooks 01-04 and 07 (headless)"
"$PY" scripts/run_notebooks.py 01 02 03 04 07 2>&1 | grep -v IPKernelApp

echo "== serving model + ONNX parity"
"$PY" scripts/train_serving_model.py | tail -3

echo "== live scoring against the mock Live Client (recorded-match replay)"
"$PY" scripts/mock_liveclient.py --replay --speed 120 --port 2998 > "$LOLML_HOME/mock.log" 2>&1 &
MOCK=$!
trap 'kill $MOCK 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do grep -q "mock Live Client on" "$LOLML_HOME/mock.log" && break; sleep 1; done
"$PY" scripts/score_live.py --base-url http://127.0.0.1:2998 --max-polls 5 --interval 0.5

if [ -n "${LOLML_DB_DSN:-}" ]; then
  echo "== database lab (LOLML_DB_DSN is set)"
  "$PY" tests/test_db.py
else
  echo "== database lab skipped (set LOLML_DB_DSN, LOLML_DB_USER, LOLML_DB_PASSWORD to include it)"
fi
echo "== SMOKE TEST PASSED"
