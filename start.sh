#!/bin/bash

# monitor memory usage
monitor_memory() {
    while true; do
        echo "[$(date +'%Y-%m-%d %H:%M:%S')] --- MEMORY REPORT ---"
        # total memory used by all processes in MB
        ps -eo size,rss,comm,pid --sort=-rss | awk '
            BEGIN {printf "%-10s %-10s %-20s %s\n", "PID", "RSS(MB)", "COMMAND", "TOTAL"}
            NR>1 {
                rss_mb=$2/1024;
                total+=rss_mb;
                printf "%-10s %-10.2f %-20s\n", $4, rss_mb, $3
            }
            END {printf "\nTotal Physical Memory (RSS) in use: %.2f MB\n", total}'
        echo "--------------------------"
        sleep 300
    done
}

monitor_memory &

echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Starting bot with memray..."
textual-web --config memray.toml &

# capture textual pid
TEXTUAL_PID=$!

sleep 5

# capture python pid
PYTHON_PID=$(pgrep -f "memray run --live-remote --native main.py")

echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Bot initializing... waiting 60s before starting POT provider."

# wait for bot init
sleep 60

echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Starting POT provider..."
node /app/bgutil/build/main.js --host 0.0.0.0 --port 4416 >/app/node_provider.log 2>&1 &

# capture node.js pid
NODE_PID=$!

# wait for pot init
sleep 5

# check for crashes
if ! kill -0 $NODE_PID >/dev/null 2>&1; then
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] FATAL: POT provider failed to start!"
    echo "--- node.js error logs ---"
    cat /app/node_provider.log
    echo "--- file tree ---"
    find /app -maxdepth 3 -not -path '*/.*'
fi

if [ -z "$PYTHON_PID" ]; then
    echo "FATAL: Could not find the Python process. Check serve.toml command."
    kill $MANAGER_PID
    exit 1
fi

echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Services running (Python PID: $PYTHON_PID, Node PID: $NODE_PID)."

# wait for python to finish
wait $PYTHON_PID

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
