#!/bin/sh
# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
# Shared development configuration. Sourced by the other scripts.
set -eu

APP_ID="citizens_online"
APP_NAME="Citizens Online"
APP_VERSION="0.1.0-alpha.1"
APP_PORT="23001"
CONTAINER="nc_app_citizens_online"
IMAGE="citizens-online-dev"
NETWORK="nextcloud_nextcloud-network"
DATA_VOLUME="citizens_online_data"
NC_CONTAINER="${NC_CONTAINER:-nextcloud}"
# Your own instance. Put it in scripts/dev-env.local.sh (gitignored) or export
# it — this file is committed, so it must not carry one deployment's hostname.
NEXTCLOUD_URL="${NEXTCLOUD_URL:-https://localhost}"
DAEMON_NAME="manual_install_co"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Local, uncommitted overrides for anything above.
if [ -f "$REPO_DIR/scripts/dev-env.local.sh" ]; then
    . "$REPO_DIR/scripts/dev-env.local.sh"
fi
SECRET_FILE="$REPO_DIR/.app_secret"

# One stable secret per checkout; shared between the container and the
# AppAPI registration. Never committed (gitignored).
if [ ! -f "$SECRET_FILE" ]; then
    umask 077
    head -c 32 /dev/urandom | base64 | tr -d '=+/\n' > "$SECRET_FILE"
fi
APP_SECRET="$(cat "$SECRET_FILE")"

occ() {
    docker exec -u www-data "$NC_CONTAINER" php occ "$@"
}
