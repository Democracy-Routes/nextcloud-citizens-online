#!/bin/sh
# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
# Register the manual-install deploy daemon (if missing) and the Citizens Online
# ExApp with AppAPI. The dev container must already be running (dev-up.sh).
#
# Route access levels in --json-info are numeric: PUBLIC=0, USER=1, ADMIN=2
# (the string mapping only applies to the info.xml path in AppAPI).
#
# Route URL regexes are matched against the path WITHOUT a leading slash and
# wrapped in /.../i server-side — patterns must start with e.g. ^js\/ .
#
# Verbs stay within GET/POST/PUT/DELETE: AppAPI's proxy registers handlers for
# those four only, so a PATCH never reaches this route table at all.
set -eu
. "$(dirname "$0")/dev-env.sh"

# Its own daemon, not the shared "manual_install" one: a manual-install daemon
# carries the container host, so two hand-deployed ExApps cannot share it —
# Nextcloud would look for this app inside the other app's container.
if ! occ app_api:daemon:list | grep -q "$DAEMON_NAME"; then
    occ app_api:daemon:register "$DAEMON_NAME" "Manual install (Citizens Online)" \
        manual-install http "$CONTAINER" "$NEXTCLOUD_URL"
fi

JSON_INFO=$(cat <<JSON
{"id":"$APP_ID","name":"$APP_NAME","daemon_config_name":"$DAEMON_NAME","version":"$APP_VERSION","secret":"$APP_SECRET","port":$APP_PORT,"routes":[
{"url":"^js\\\\/.*","verb":"GET","access_level":1,"headers_to_exclude":[]},
{"url":"^css\\\\/.*","verb":"GET","access_level":1,"headers_to_exclude":[]},
{"url":"^img\\\\/.*","verb":"GET","access_level":1,"headers_to_exclude":[]},
{"url":"^api\\\\/v1\\\\/admin\\\\/.*","verb":"GET,POST,PUT,DELETE","access_level":2,"headers_to_exclude":[]},
{"url":"^api\\\\/v1\\\\/integrations\\\\/.*","verb":"GET,POST","access_level":0,"headers_to_exclude":[]},
{"url":"^api\\\\/v1\\\\/.*","verb":"GET,POST,PUT,DELETE","access_level":1,"headers_to_exclude":[]}
]}
JSON
)

occ app_api:app:unregister "$APP_ID" --silent --force >/dev/null 2>&1 || true
occ app_api:app:register "$APP_ID" "$DAEMON_NAME" --json-info "$JSON_INFO" --wait-finish
