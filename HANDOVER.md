# Handover — what changed on the server

Build run on 2026-08-31 / 2026-09-01. Backup suffix used throughout:
`co-backup-20260831-231441`.

**Nothing was deleted.** No volume, database, file or user was removed. Every
file that was edited has a backup beside it, and every change below is
reversible with the commands given.

---

## 1. Nextcloud configuration

`config.php` was backed up first:

```
/var/www/html/config/config.php.co-backup-20260831-231441   (inside the nextcloud container)
```

Four keys were set, all of which Nextcloud's own setup checks were asking for:

| Key | Was | Now | Why |
|---|---|---|---|
| `overwrite.cli.url` | `https://localhost` | `https://<your-nextcloud>` | background jobs and notifications were generating `localhost` links |
| `trusted_proxies` | *(empty)* | `the docker bridge gateway`, `127.0.0.1` | every client appeared to come from the docker gateway |
| `default_phone_region` | *(unset)* | `IT` | Talk asks for it |
| `maintenance_window_start` | *(unset)* | `1` | lets Nextcloud schedule heavy jobs at night |

Undo: `occ config:system:set <key> --value=<old>`, or restore the backup file.

## 2. nginx

- **New file** (additive, nothing existing touched):
  `/etc/nginx/conf.d/00-co-websocket-upgrade.conf` — a `map` that lets vhosts
  proxy WebSockets correctly.
- **Edited**: `/etc/nginx/sites-available/<your-nextcloud>`
  — added `proxy_http_version 1.1`, `Upgrade`/`Connection` headers, and raised
  `proxy_read_timeout` from 300 to 3600.
  Backup: `…/<your-nextcloud>.co-backup-20260831-231441`.

Undo: `cp <backup> <original> && rm /etc/nginx/conf.d/00-co-websocket-upgrade.conf && nginx -t && nginx -s reload`.

## 3. Nextcloud apps

- **Talk (`spreed`) 24.0.4 installed and enabled.** It was not present before.
  Undo: `occ app:disable spreed` (this does not delete conversations).
- **`citizens_online` 0.1.0-alpha.1 registered as an ExApp** and enabled.
- A Talk bot named **Citizens Online** was registered by the app (`occ talk:bot:list`).
  It is removed automatically when the app is disabled.

## 4. Accounts created

| Account | Note |
|---|---|
| `citizens-online` | service account; owns and moderates the Talk conversations the app creates |
| `co1` … `co8` | test participants, all in the group `citizens-online-test` |

Passwords: `citizens-online-test-users.txt` in root's home directory (mode 0600).
Undo: `occ user:disable <uid>` — or delete them if you prefer; nothing else
depends on them.

## 5. New containers

| Name | Image | Notes |
|---|---|---|
| `nc_app_citizens_online` | `citizens-online-dev` | the app. Port 23001, on `nextcloud_nextcloud-network`, 640 MB limit, source bind-mounted from the repo with auto-reload. |

Volume `citizens_online_data` holds the app's SQLite database and captured audio.
A new AppAPI deploy daemon `manual_install_co` was registered, because a
manual-install daemon carries the container hostname and therefore cannot be
shared with the Citizens app.

Undo: `sh scripts/unregister.sh && docker rm -f nc_app_citizens_online`.
(The volume is left alone deliberately — delete it yourself if you want the data gone.)

## 6. Secrets

- The **Ollama Cloud API key already on this host** (`/etc/globstory-ai.env`) was
  copied into the app's Nextcloud AppConfig as a `sensitive` value, so the
  facilitator and the analysis work out of the box with `glm-5.2:cloud`. It was
  never printed, logged or committed. Change it in Settings whenever you like.
- The app's own AppAPI secret lives in `.app_secret` in the repo and is
  gitignored.

## 7. Untouched

The legacy Democracy Routes stack (`dr-app`, `livekit`, `coturn`, `dr-*`
workers), the Citizens ExApp (`nc_app_citizens`) and `citizens-vosk` were left
running exactly as they were. `citizens-vosk` is *read from* by this app for
live captions; nothing about it was changed.

---

## Known state and next steps

The build reached the end of the planned "vertical slice": the deliberation runs
end to end and produces a reviewed report. See `TESTING.md` for how to try it and
for the honest list of what is not implemented.

The two things worth doing next, in order:

1. **A High-Performance Backend.** Without it Talk is peer-to-peer and a room
   above ~4–6 people will struggle. This is the one blocker for a real 50-person
   pilot, and it is infrastructure rather than code.
2. **Embedding-based matching and remix** (`PLAN.md` §21, version 0.2). The
   optimiser design and the port source are already identified.

Also worth knowing:

- The app uses **SQLite**, not PostgreSQL as `PLAN.md` §12 specifies. That was a
  deliberate trade for this build: it let the whole capture and job chain be
  copied from the in-person app instead of ported. It is fine for the pilot
  sizes here, and the database layer is behind small functions so the switch is
  contained.
- `docs/spike-results.md` records what was verified about Talk's API, including
  two behaviours the documentation does not mention: bots are **not** inherited
  into breakout rooms, and the configure-breakouts response includes the parent
  conversation alongside the children.
