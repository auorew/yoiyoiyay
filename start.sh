#!/bin/bash

# starting bot
echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Starting bot with memray..."
poetry run python3 main.py &
POETRY_PID=$!
sleep 2

# starting pot provider
echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Starting POT provider with node..."
node /app/bgutil/build/main.js --host 0.0.0.0 --port 4416 >/app/node_provider.log 2>&1 &
BGUTIL_PID=$!
sleep 2

echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Checking POT provider health on port 4416..."
MAX_RETRIES=5
COUNT=0

while ! nc -z localhost 4416; do
    sleep 1
    COUNT=$((COUNT + 1))
    if [ $COUNT -ge $MAX_RETRIES ]; then
        echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: POT provider failed to start on port 4416"
    fi
done

echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: POT provider is UP and listening."

echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: All services launched."

echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Services running"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: python PID:  $POETRY_PID"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: bgutil PID:  $BGUTIL_PID"

wait $POETRY_PID
