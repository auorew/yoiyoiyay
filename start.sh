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

# starting textual
echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Starting server with textual..."
poetry run textual serve --port 5000 --host 0.0.0.0 "memray live 1337" &
TEXTUAL_PID=$!
sleep 5

# starting bot
echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Starting bot with memray..."
poetry run memray run --live-remote --live-port 1337 --native main.py &
MEMRAY_PID=$!
sleep 5

# wait...
echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Bot initializing... waiting 15s."
sleep 15

# starting pot provider
echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Starting POT provider with node..."
node /app/bgutil/build/main.js --host 0.0.0.0 --port 4416 >/app/node_provider.log 2>&1 &
NODE_PID=$!

echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: All services launched."

wait $MEMRAY_PID

echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: Services running"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: textual PID: $TEXTUAL_PID"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: python PID:  $MEMRAY_PID"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: node PID:    $NODE_PID"
