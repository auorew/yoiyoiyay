#!/bin/bash

# starting bot
echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Starting bot with memray..."
poetry run memray3.14 run --live-remote --live-port 1337 --native main.py &
POETRY_PID=$!
sleep 2

# starting memray
echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Starting memray..."
memray3.14 live 1337 &
MEMRAY_PID=$!
sleep 2

# starting pot provider
echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Starting POT provider with node..."
node /app/bgutil/build/main.js --host 0.0.0.0 --port 4416 >/app/node_provider.log 2>&1 &
BGUTIL_PID=$!
sleep 2

echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: All services launched."

echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Services running"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: python PID:  $POETRY_PID"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: memray PID:  $MEMRAY_PID"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: bgutil PID:  $BGUTIL_PID"
