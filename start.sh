#!/bin/bash

echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Starting POT provider..."
node /app/bgutil/build/main.js >/app/node_provider.log 2>&1 &

# capture pid
NODE_PID=$!

# wait for init
sleep 5

# check for crashes
if ! kill -0 $NODE_PID >/dev/null 2>&1; then
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] FATAL: POT provider failed to start!"
    echo "--- node.js error logs ---"
    cat /app/node_provider.log
    exit 1
    echo "--- file tree ---"
    find /app -maxdepth 3 -not -path '*/.*'
fi

echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: POT provider started (PID: $NODE_PID)."

echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Starting Telegram bot..."

poetry run python3 main.py

# looking for exit code
PYTHON_EXIT_CODE=$?

# check for status
if [ $PYTHON_EXIT_CODE -ne 0 ]; then
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] FATAL: Bot exited with $PYTHON_EXIT_CODE"
    # kill it
    kill $NODE_PID 2>/dev/null
    exit $PYTHON_EXIT_CODE
else
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Bot shut down normally."
    kill $NODE_PID 2>/dev/null
    exit 0
fi
