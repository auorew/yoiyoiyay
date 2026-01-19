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

# starting bot
echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Starting bot with memray..."
poetry run memray run --live-remote --native main.py &
PYTHON_PID=$!
sleep 5

echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Bot initializing... waiting 15s."
sleep 15

# starting textual
echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Starting textual..."
textual serve --port 5000 --host 0.0.0.0 "memray live 5000" &
TEXTUAL_PID=$!
sleep 5

# starting pot provider
echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Starting POT provider..."
node /app/bgutil/build/main.js --host 0.0.0.0 --port 4416 >/app/node_provider.log 2>&1 &
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

echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Services running"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] textual PID: $TEXTUAL_PID"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] bot PID:     $PYTHON_PID"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] POT PID:     $NODE_PID"
