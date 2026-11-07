#!/usr/bin/env bash
# Reproduce the full verification run.
#   bash tools/run-tests.sh
set -e
cd "$(dirname "$0")/.."

EDGE="/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
[ -f "$EDGE" ] || EDGE="/c/Program Files/Microsoft/Edge/Application/msedge.exe"

echo "==> serving on 127.0.0.1:8777"
python -m http.server 8777 --bind 127.0.0.1 >/dev/null 2>&1 &
SRV=$!

echo "==> starting headless Edge with CDP on 9222"
"$EDGE" --headless=new --remote-debugging-port=9222 \
        --user-data-dir="${TEMP:-/tmp}/edge-cdp" --no-first-run --disable-gpu \
        about:blank >/dev/null 2>&1 &
BROWSER=$!

sleep 5
node tools/test.js
CODE=$?

kill $SRV $BROWSER 2>/dev/null || true
exit $CODE
