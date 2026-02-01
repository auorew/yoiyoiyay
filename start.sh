#!/bin/bash

log() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: $1"; }

error() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $1"; }

# starting Netdata
log "Starting Netdata..."
/usr/sbin/netdata -D >/dev/null 2>&1 &
NETDATA_PID=$!
log "Netdata started with PID: $NETDATA_PID"

# get private key
cat /var/lib/netdata/netdata_random_session_id

# starting POT Provider
log "Starting POT provider with node..."
# Note: We bind to 127.0.0.1 because Nginx doesn't need to route to this, only Python does.
node /app/bgutil/build/main.js --host 127.0.0.1 --port 4416 >/app/node_provider.log 2>&1 &
BGUTIL_PID=$!
log "POT Provider started with PID: $BGUTIL_PID"

# health check for POT Provider
log "Checking POT provider health on port 4416..."
MAX_RETRIES=10
COUNT=0
while ! nc -z 127.0.0.1 4416; do
    sleep 1
    COUNT=$((COUNT + 1))
    if [ $COUNT -ge $MAX_RETRIES ]; then
        error "POT provider failed to start on port 4416."
        # If dependency fails, we should probably exit
        # exit 1
        break
    fi
done

# starting Nginx
log "Generating Nginx config from template..."
envsubst '${TOKEN}' </etc/nginx/nginx.conf.template >/etc/nginx/nginx.conf

log "Starting Nginx Reverse Proxy on port 8080..."
nginx -g "daemon off;" &
NGINX_PID=$!
log "Nginx started with PID: $NGINX_PID"

# starting Python Bot
log "Starting bot with poetry..."
poetry run python3 main.py &
POETRY_PID=$!
log "Python Bot started with PID: $POETRY_PID"

log "All services launched."
log "   - Netdata PID: $NETDATA_PID"
log "   - POT PID:     $BGUTIL_PID"
log "   - Nginx PID:   $NGINX_PID"
log "   - Python PID:  $POETRY_PID"

cleanup() {
    log "Shutting down all services..."
    kill $POETRY_PID $NGINX_PID $BGUTIL_PID $NETDATA_PID 2>/dev/null
}
trap cleanup SIGTERM SIGINT

wait $POETRY_PID
EXIT_CODE=$?

log "Python process exited with code $EXIT_CODE. Shutting down."
cleanup
exit $EXIT_CODE
