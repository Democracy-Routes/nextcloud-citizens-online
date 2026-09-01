#!/bin/sh
# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
# Build the dev image and (re)start the Citizens Online dev container with the
# source bind-mounted and uvicorn auto-reload. Nextcloud reaches it as
# http://nc_app_citizens_online:23001 on the shared docker network.
set -eu
. "$(dirname "$0")/dev-env.sh"

docker build -q -t "$IMAGE" "$REPO_DIR" >/dev/null
docker volume create "$DATA_VOLUME" >/dev/null
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker run -d \
    --name "$CONTAINER" \
    --network "$NETWORK" \
    --restart unless-stopped \
    --memory 640m --memory-swap 640m \
    --add-host host.docker.internal:host-gateway \
    -v "$REPO_DIR":/app \
    -v "$DATA_VOLUME":/data \
    -e APP_ID="$APP_ID" \
    -e APP_VERSION="$APP_VERSION" \
    -e APP_HOST=0.0.0.0 \
    -e APP_PORT="$APP_PORT" \
    -e APP_SECRET="$APP_SECRET" \
    -e NEXTCLOUD_URL="$NEXTCLOUD_URL" \
    -e APP_PERSISTENT_STORAGE=/data \
    -e CO_DEV=1 \
    -e CO_LOG_LEVEL=DEBUG \
    --entrypoint sh \
    "$IMAGE" \
    -c "cd /app && exec python3 -m uvicorn citizens_online.main:APP --host 0.0.0.0 --port $APP_PORT --reload" \
    >/dev/null
echo "Container $CONTAINER running on $NETWORK (port $APP_PORT)."
