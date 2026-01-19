#!/bin/bash

# starting bot
echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Starting bot with memray..."
poetry run memray run --live-remote --live-port 1337 --native main.py &
MEMRAY_PID=$!
sleep 2

# wait...
echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Bot initializing... waiting 15s."
sleep 15

# starting pot provider
echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Starting POT provider with node..."
node /app/bgutil/build/main.js --host 0.0.0.0 --port 4416 >/app/node_provider.log 2>&1 &
NODE_PID=$!
sleep 2

echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: All services launched."

wait $MEMRAY_PID

echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Services running"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: textual PID: $TEXTUAL_PID"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: python PID:  $MEMRAY_PID"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: node PID:    $NODE_PID"
