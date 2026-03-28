#!/bin/bash

log() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: $1"; }

error() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $1"; }

# starting Python Bot
log "Starting bot with poetry and memray..."
poetry run python3 main.py &
# poetry run memray3.14 run --native -o native_report.bin main.py &

POETRY_PID=$!
log "Python Bot started with PID: $POETRY_PID"

log "All services launched."
log "   - Python PID:  $POETRY_PID"

cleanup() {
    log "Shutting down all services..."
    kill $POETRY_PID $NGINX_PID $BGUTIL_PID 2>/dev/null
}
trap cleanup SIGTERM SIGINT

wait $POETRY_PID
EXIT_CODE=$?

log "Python process exited with code $EXIT_CODE. Shutting down."
cleanup
exit $EXIT_CODE
