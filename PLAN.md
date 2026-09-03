# Citizens Online — Plan

**Democracy Routes as a Nextcloud ExApp.** Feasibility verdict, decisions, MVP 0.1 plan, roadmap.

- Specification: [`docs/SPEC.md`](docs/SPEC.md) (cited below as §n)
- Status: **implemented through the vertical slice**, 2026-09-01. See
  [`TESTING.md`](TESTING.md) to try it and [`HANDOVER.md`](HANDOVER.md) for what
  changed on the server.
- Scope note: this document deliberately contains **no hosting, sizing or cost reasoning**; that is decided separately.

---

## Table of contents

**Part A — Verdict and decisions**
1. [Verdict](#1-verdict)
2. [Decision log](#2-decision-log)
3. [Current state of the dev instance](#3-current-state-of-the-dev-instance)
4. [What is reused, ported, forked, new](#4-what-is-reused-ported-forked-new)

**Part B — MVP 0.1 "Citizens, but online"**
5. [Scope](#5-scope)
6. [Architecture](#6-architecture)
7. [Step 0 — Spike](#7-step-0--spike)
8. [Step 1 — Skeleton](#8-step-1--skeleton)
9. [Step 2 — Vertical slice](#9-step-2--vertical-slice)
10. [Step 3 — Session UI](#10-step-3--session-ui)
11. [Step 4 — Hardening and pilot rehearsal](#11-step-4--hardening-and-pilot-rehearsal)
12. [Data model](#12-data-model)
13. [API](#13-api)
14. [Live Transcription fork](#14-live-transcription-fork)
15. [Facilitation and moderation agents](#15-facilitation-and-moderation-agents)
16. [Speaker identity chain](#16-speaker-identity-chain)
17. [Capture instead of recording](#17-capture-instead-of-recording)
18. [Consent, privacy, retention](#18-consent-privacy-retention)
19. [Testing and failure behaviour](#19-testing-and-failure-behaviour)
20. [Repository layout](#20-repository-layout)

**Part C — Roadmap after 0.1**
21. [0.2 → 1.0](#21-roadmap-02--10)
22. [Design notes carried forward](#22-design-notes-carried-forward)
23. [Spec coverage](#23-spec-coverage)

**Appendices**
- [A. Citizens ExApp reuse map](#appendix-a--citizens-exapp-reuse-map)
- [B. Legacy Democracy Routes migration map](#appendix-b--legacy-democracy-routes-migration-map)
- [C. Talk API reference for the adapter](#appendix-c--talk-api-reference-for-the-adapter)
- [D. Live Transcription source anchors](#appendix-d--live-transcription-source-anchors)
- [E. AppAPI rules learned from Citizens](#appendix-e--appapi-rules-learned-from-citizens)
- [F. Example routes](#appendix-f--example-routes)
- [G. References](#appendix-g--references)

---

# Part A — Verdict and decisions

## 0. What was built

The MVP 0.1 vertical slice runs on `<your-nextcloud>`: a session
with rounds and participants becomes real Talk breakout rooms, each browser
records its own participant, the facilitator keeps time and speaking balance,
and what was said becomes findings with evidence and a report.

**One deliberate deviation from this document.** §12 specifies PostgreSQL; the
build uses **SQLite**, exactly as the in-person app does, because that let the
capture chain, the job runner and the live-caption engine be *copied* rather
than ported — the difference between a working slice and an unfinished one. The
WAL/`BEGIN IMMEDIATE`/read-only-session discipline and the AST guard test came
with it. Postgres remains the right destination and the database layer is behind
small functions, so the switch is contained.

## 1. Verdict

**Doable.** The architecture in §0–§2 is sound, every upstream piece it depends on exists, and a large
share of the ExApp infrastructure already exists in the same author's Citizens ExApp. The verified facts:

- **Talk 24.0.4** is available for Nextcloud 34.0.3 and provides everything the adapter needs: breakout
  rooms (`breakout-rooms-v1`, up to 20 per parent conversation, manual `attendeeMap`), bots
  (`bots-v1`, registrable from an ExApp), per-attendee permissions (`PUBLISH_AUDIO` = 16), polls, ban,
  and `participants[].sessionIds` — the key that maps media sessions back to users. Breakout rooms only
  accept `users`-type attendees, which is why participants must be registered users (decision below).
- **`nextcloud/live_transcription`** (AGPL-3.0-or-later, Python) already joins calls as a hidden
  HPB *internal* client and runs **one Vosk recogniser per participant stream**, so speaker identity is
  inherent — no acoustic diarization (§11). It lacks timestamps, a segment webhook and room-level
  sessions; all three are small, feature-flagged changes in a drop-in fork (§10 "extend rather than
  reimplement").
- **Speaking time from media activity** (§12) has two independent sources: voice-activity detection on
  the per-participant audio the transcription app already decodes, and the `speaking`/`stoppedSpeaking`
  signaling messages Talk clients broadcast to every session in a call, internal sessions included.
- **Recording without a recording server**: Talk's official recording server drives a headless Firefox
  per call; it is rejected. Per-speaker audio capture happens inside the transcription fork instead
  (section 17).
- **Citizens ExApp** provides, ready to copy: the AppAPI bootstrap, Alembic-at-startup, a durable job
  queue, the Vosk client and a patched multi-model Vosk server, an OpenAI-compatible LLM adapter with
  schema-correction retry, evidence-linked findings ("no evidence → dropped"), Mistral batch and
  realtime adapters, report rendering (MD/PDF/JSON), the Vue/Vite build served through the AppAPI
  proxy, the App Store release pipeline, and 22 documented AppAPI rules.
- **Legacy Democracy Routes** contributes ~1 000 lines of pure, tested logic to port (grouping, stance
  extraction, AI provider switch, facilitator cadence, speaking thresholds, speaker timeline, ActivityPub)
  and a clear list of what not to inherit (NextAuth, LiveKit/mediasoup, wall-clock runtime).
- **Frankly Match** is MIT-licensed Python; its group optimiser is portable with attribution (0.2).

The one hard prerequisite for everything involving speech is a **Talk High-Performance Backend**
(signaling server + Janus). It is not installed on the dev instance yet; installing a small one is the
first step (section 7).

## 2. Decision log

Decisions taken by the project owner during planning (2026-08-28 → 2026-08-31).

| Topic | Decision |
|---|---|
| Product name / app id | **Citizens Online**; app id `citizens_online` (immutable; equals the App Store signing-certificate CN). "Democracy Routes" remains the process vocabulary: Routes, modules. |
| Relationship to Citizens | A **separate ExApp**, built by copying the Citizens codebase file-by-file, not by forking the live app (Citizens is a published App Store app with its own certificate and release cadence). Convergence into one app with in-person and online modes is a later option the naming keeps open. |
| License / language | AGPL-3.0-or-later. English UI; Italian localisation later. |
| Participants | **Registered, normal Nextcloud users only** for now. No Guests-app accounts, no Talk link guests, no federated users. (Guests-app accounts are the documented path for one-off citizens later.) |
| Pilots | Small pilots of ≤ 10 people first; first real pilot **50 people, English**; no date. |
| Dev / staging instance | `<your-nextcloud>` (Nextcloud 34.0.3.2, AppAPI 34.0.0). |
| Clients | Browser first; Talk mobile/desktop apps supported but tested later. Single instance. |
| Federation | Later. Nextcloud federation only for sharing reports; ActivityPub for public objects in 1.0; federated participants in a Route are research, not a feature. |
| LLM | Any **OpenAI-compatible endpoint** (an Ollama-served model, Mistral, …) through one adapter. **The LLM always phrases facilitator messages — no templated fallback.** A message that misses its deadline is dropped and logged, never delayed. An `AgentProvider` is therefore *required* for any Route with facilitation enabled. |
| Embeddings | **Not in 0.1** (rooms assigned manually or randomly). Later: local `bge-m3` or `nomic-embed-text-v2-moe`, or OpenRouter as an admin-configured external option; answers are embedded on submission. |
| Live transcription | Vosk small English/Italian models, one recogniser per participant, **gated by voice-activity detection**. Per-Route switch `live_stt_provider = vosk \| mistral \| …`. |
| Post-call transcription | **Mistral Voxtral batch** (Citizens adapter) on VAD-trimmed per-speaker audio is the default; big Vosk models as the fully-local alternative. Replaces live segments in place, then analysis re-runs. |
| Recording | **No Talk recording server.** Per-speaker Opus capture inside the transcription fork (section 17). Counts as recording for consent and retention. End-to-end-encrypted calls are not supported in deliberation rooms. |
| Agents in pilot 1 | (1) **Time/speaking manager** — the deterministic engine decides, the LLM phrases. (2) **Offensive-language moderator** — a classifier over final transcript segments; low severity → facilitator reminder, high severity → human moderator alert. One bot voice. |
| Analysis | **Exactly the Citizens pipeline**: per-room findings with evidence → cross-room synthesis → human review → report (MD / PDF / JSON). |
| Builder | Simple list-based session/round setup in 0.1; a modular builder in the spirit of the standalone app later (0.5). |

## 3. Current state of the dev instance

Verified read-only on 2026-08-28 (`<your-nextcloud>`).

| Component | State |
|---|---|
| Nextcloud | 34.0.3.2 (`nextcloud:34-apache`), PostgreSQL 15, Redis 7, network `nextcloud_nextcloud-network` |
| AppAPI | 34.0.0; one daemon `manual_install` (deploy-id `manual-install`, not default, no HaRP); no Docker socket proxy. ExApps are started by hand and registered with `occ app_api:app:register --json-info` (Citizens `scripts/register.sh` pattern). |
| Citizens ExApp | 0.6.0-beta.11 registered and running (`nc_app_citizens`, source bind-mounted from `/root/NextCloud-Citizen`) |
| Talk (`spreed`) | **not installed**; 24.0.4 available in the App Store |
| HPB (signaling, NATS, Janus) | **not installed** |
| TURN | a `coturn` exists but is configured for the legacy LiveKit stack (`--lt-cred-mech`); the HPB expects `--use-auth-secret` |
| Live Transcription ExApp | **not installed**; not in the App Store — built from GitHub (`ghcr.io/nextcloud-releases/live_transcription:2.1.3` also exists) |
| Vosk | `citizens-vosk` container (`alphacep/kaldi-vosk-server` + Citizens' patched `asr_server.py`) on the Nextcloud network at `citizens-vosk:2700`; models `vosk-model-small-en-us-0.15`, `vosk-model-small-it-0.22`; per-connection model selection, LRU cache, word timestamps |
| Nextcloud config to fix | `overwrite.cli.url` is `https://localhost`; `trusted_proxies` empty; `default_phone_region` unset; the nginx vhost has no WebSocket upgrade headers |
| Tooling | `docker-compose` v1.29 only (no `docker compose` plugin); `rg` not installed |
| Users | 5 users; groups `admin`, `Podcast`; no LDAP/SSO |

## 4. What is reused, ported, forked, new

| How | What | Share of 0.1 |
|---|---|---|
| **Copied** (same language, framework, platform) | Citizens ExApp: bootstrap, auth, config, logging, Alembic, job queue, Vosk client/server, LLM adapter, analysis + evidence + report, Mistral adapters, frontend build, scripts, CI, tests — see Appendix A | ≈ 45 % |
| **Ported** (TypeScript/Prisma → Python; Python moved as-is) | Legacy DR: facilitator cadence, speaking thresholds, transcript segment model, speaker timeline, capture helpers — see Appendix B | ≈ 10 % |
| **Forked** | `nextcloud/live_transcription`: four flag-off additions, same app id, drop-in image — section 14 | small |
| **New** | Talk adapter, HPB event client, session/round engine, speaking-time engine, agent runtime wiring, session UI | ≈ 45 % |

---

# Part B — MVP 0.1 "Citizens, but online"

## 5. Scope

Citizens runs in-person assemblies: one phone per table records, transcribes, analyses, reports.
Citizens Online 0.1 does the same for online assemblies: **one Talk breakout room per table**, per-speaker
transcripts instead of a table microphone, two facilitator agents, and the same analysis and report.

**In 0.1**

- Create a session with N rounds; add participants (existing Nextcloud users).
- Assign participants to up to 10 breakout rooms per parent conversation, manually or randomly.
- Start / extend / end a round; rooms open and close accordingly; participants are switched automatically.
- Live per-speaker transcription (Vosk, VAD-gated) with real user identity on every segment.
- Speaking-time metrics from voice activity; round timers.
- Two agents through one Talk bot: time/speaking manager, offensive-language moderator.
- Per-speaker audio capture; post-call re-transcription (Mistral batch) replacing live segments.
- Per-room findings with evidence → cross-room synthesis → human review → report MD/PDF/JSON.
- Consent screen generated from configuration; audit log; retention sweep; Files tab (list, delete, export).

**Out of 0.1** (roadmap, section 21)

Embedding matching and remix; the builder and the generalised module engine; text_input / survey /
poll / pause / conditional modules; audio-permission actions (mute, timed turns, queue — 0.1 sends
messages only); guests; federation and ActivityPub; public results pages; external tools.

## 6. Architecture

```
                              CLIENTS
   +---------------------------------------------------------------+
   |  Browser: Nextcloud web (Citizens Online pages)  |  Talk web /  |
   |  participant + moderator screens                 |  mobile apps |
   +------------------+-------------------------------+------+------+
                      | HTTPS                                | WSS signaling + WebRTC media
                      v                                      v
   +====================================+   +=============================+
   |  NEXTCLOUD                         |   |  HPB                        |
   |  users / groups                    |   |  spreed-signaling <-> NATS  |
   |  Files . Notifications             |   |  Janus SFU  (audio, video)  |
   |  +-------------+   +------------+  |   |  coturn     (TURN / STUN)   |
   |  | Talk        |<->| AppAPI     |  |   +====^=============^==========+
   |  | rooms       |   | auth+proxy |  |        | internal WS | internal WS
   |  | breakouts   |   +-----+------+  |        | (events)    | (per-speaker audio)
   |  | chat, bots  |         |         |        |             |
   |  | permissions |         |         |        |             |
   |  +------+------+         |         |        |             |
   +=========|================|=========+        |             |
             | OCS calls      | UI + bot         |             |
             | (service user) | webhooks         |             |
             v                v                  v             v
   +===========================================================+   +=====================+
   |  ExApp  citizens_online   (Python / FastAPI / worker)     |   | ExApp               |
   |                                                           |   | live_transcription  |
   |   CORE (Nextcloud-independent)                            |   | (fork, same app id) |
   |   +---------+ +----------+ +---------+ +----------------+ |   |                     |
   |   | Session | | Speaking | | Agents  | | Analysis       | |   | 1 Vosk stream per   |
   |   | / round | | time     | | (LLM)   | | (Citizens)     | |   | participant + VAD   |
   |   | engine  | | engine   | |         | |                | |   | + Opus capture      |
   |   +----+----+ +----+-----+ +----+----+ +-------+--------+ |   |                     |
   |        +-----------+-----------+-------------+           |   | final segments +    |
   |                    | Infrastructure API (ports)          |<--+ speech on/off       |
   |   +----------------+---------------------------------+   |   | (signed webhooks)   |
   |   | Nextcloud adapter        |  fake (tests)          |   |   +=====================+
   |   | TalkAdapter, HpbEventClient, Bot, Notifications   |   |            ^
   |   +--------------------------------------------------+   |            | ws
   +======+======================+=============================+     +------+------+
          |                      |                                   | Vosk server |
          v                      v                                   | (en / it)   |
   +--------------+   +----------------------+                       +-------------+
   | PostgreSQL   |   | AI providers         |
   | sessions,    |   | OpenAI-compatible    |
   | rooms,       |   | endpoint (required   |
   | segments,    |   | when facilitation is |
   | metrics,     |   | enabled); Mistral    |
   | findings,    |   | batch STT            |
   | audit        |   +----------------------+
   +--------------+
```

Principles kept from §2 and §39 even in 0.1:

- **Core never imports Nextcloud.** Everything platform-specific sits behind `infra/ports.py` Protocols
  (`MeetingProvider`, `TranscriptSource`, `VoiceActivitySource`, `IdentityProvider`, `NotificationSink`,
  `AgentProvider`, `TranscriptionProvider`). `infra/nextcloud/` implements them; `infra/fake/` implements
  them in memory for tests; `infra/standalone/` is reserved.
- **The engine is the authority; the bot is a mouthpiece** (§14). Every consequential action is written to
  `audit_events` / `moderation_events` with the rule that fired (§28).
- **Persist every transition** so a restart resumes the round (§5, §39.15).
- **Polling, not WebSockets, between browser and ExApp** in 0.1 — the AppAPI proxy does not carry
  WebSockets (Appendix E). SSE/WebSocket arrive with HaRP later.

Two processes share the database: `api` (uvicorn, request handling) and `engine` (asyncio worker:
timers, 5-second ticks, job queue, HPB event clients).

## 7. Step 0 — Spike

*Goal: answer the four questions that decide the adapter's shape. One to two days, on the dev instance,
at dev scale (2–4 people, 2 rooms). No product code is written.*

1. **Nextcloud configuration**: set `overwrite.cli.url`, `trusted_proxies`, `default_phone_region`; add
   WebSocket upgrade headers and a long `proxy_read_timeout` to the nginx vhost.
2. **Install Talk 24.0.4** (`occ app:install spreed`); enable bots.
3. **Minimal HPB**: `strukturag/nextcloud-spreed-signaling` + NATS + Janus (docker-compose v1 file, host
   network), a `/standalone-signaling/` vhost with WebSocket upgrade, a TURN server with
   `--use-auth-secret` (or none, for a dev spike); configure the signaling URL and secret in Talk admin.
4. **Upstream Live Transcription image**, registered through the `manual_install` daemon with
   `LT_HPB_URL`, `LT_INTERNAL_SECRET`, `LT_VOSK_SERVER_URL=ws://citizens-vosk:2700`,
   `LT_DISABLE_INTERNAL_VOSK=true` (a one-line patch may be needed to align the Vosk config key
   `language` vs `model`).
5. **Verify by hand, in one sitting**:

| # | Question | Why it matters |
|---|---|---|
| a | Is a bot enabled on the parent conversation active in its **breakout rooms**, or must it be enabled per room? Do bot webhooks carry the breakout room's token? | Facilitator messages must land inside each group's room. Decides 10 extra adapter calls per round. |
| b | Does an internal HPB client receive `speaking` / `stoppedSpeaking` messages from participants? | Free, independent speaking-time signal (§12). |
| c | Does the transcription app produce per-speaker transcripts in a breakout room (not only in the parent)? | Everything downstream. |
| d | Does the chain *HPB session → Nextcloud session → attendee → user* resolve in breakout rooms, and after a reconnect? | Wrong attribution would poison evidence, metrics and messages (section 16). |

Record the answers in `docs/spike-results.md`. Any "no" changes the adapter, not the plan.

## 8. Step 1 — Skeleton

*≈ 3 days.*

Copy the Citizens shell into a new repository, package `citizens_online`; rename; delete the phone
recorder, chunk intake and QR invites. Exact files: Appendix A. Highlights:

- `main.py`: lifespan order (storage → logging → DB → migrations → `set_handlers(map_app_static=False)` →
  jobs task), `AppAPIAuthMiddleware`, `enabled_handler` registering the top-menu entry
  **"Citizens Online"** and the script/style (paths without extension), `_RevalidatedStatic` mounts,
  loopback-only `INSECURE_NO_AUTH` guard, request-id logging middleware.
- Database: SQLAlchemy 2 + Alembic, **PostgreSQL** (SQLite only for tests). Keep `TZDateTime`,
  `NAMING_CONVENTION`, `new_uuid`; drop `BEGIN IMMEDIATE` and the read-only session (SQLite-only), keep
  the rule *no Nextcloud round-trip inside an open transaction* and its AST test.
- Jobs: Citizens runner with Postgres claiming (`SELECT … FOR UPDATE SKIP LOCKED`), permanent-vs-retry
  errors, sweeps before claiming.
- `appinfo/info.xml`: id `citizens_online`, NC 32–35, routes in this order — `^js\/.*`, `^css\/.*`,
  `^img\/.*` USER; `^api\/v1\/admin\/.*` ADMIN (GET,POST,PUT,DELETE); `^api\/v1\/integrations\/.*` PUBLIC
  with `bruteforce_protection [401,403,429]`; `^api\/v1\/.*` USER. No PATCH anywhere.
- Scripts and CI: `dev-env.sh` (app secret, `occ()` helper), `dev-up.sh`, `register.sh` (numeric access
  levels), `unregister.sh`, `dev-reset.sh`, `set-version.sh` (+ version-consistency test),
  `validate_info_xml.py`, `Makefile` App Store targets, `ci.yml` (containerised ruff + pytest, bundle
  freshness, info.xml validation), `release.yml` (amd64+arm64 image, store push).
- Frontend: Vue 3 + Vite IIFE bundle written to `js/` and `css/` and committed; `detectBase()` from the
  script's own `src`; `#content` mount; `components/ui/*` atoms.

**Acceptance (§32 Phase 1):** installs on the dev instance through `register.sh`; the menu entry appears;
the current user id is available in a request; `GET /api/v1/health` reports DB, storage, providers;
migrations run at startup; unit tests green with `create_app(with_auth=False)` + `X-Test-User`.

## 9. Step 2 — Vertical slice

*≈ 2 weeks. One thin end-to-end path first, in this order, each piece demoable alone.*

```
 admin creates session (1 round, 2 rooms, 4 people)
        │
        ▼
 TalkAdapter: create parent conversation ─► add participants ─► enable bot
        │                                    configure breakouts (mode 2, attendeeMap)
        ▼
 start round ─► breakouts started ─► transcription fork attached (room-level)
        │                                      │
        │                                      ├─► POST /integrations/transcription/segments
        │                                      └─► POST /integrations/transcription/voice-activity
        ▼                                                        │
 HpbEventClient: speaking / stoppedSpeaking ─► speaking_metrics ◄┘
        │                                             │
        ▼                                             ▼
 engine tick 5 s: time & share rules ─► intent ─► agent phrases ─► bot posts in the room
        │
        ▼
 end round ─► breakouts stopped ─► captures closed ─► analysis job per room ─► findings + evidence
                                   └─► post-call transcription job ─► segments replaced ─► re-analysis
                                       ─► cross-room synthesis ─► review ─► report
```

### 9.1 TalkAdapter (`infra/nextcloud/talk_adapter.py`)

Implements `MeetingProvider` with nc_py_api where wrapped and raw `nc.ocs()` elsewhere (Appendix C).
Acts as a dedicated service user `citizens-online` that is owner/moderator of every conversation it
creates. Operations in 0.1:

| Operation | Talk call |
|---|---|
| create parent conversation | `POST /api/v4/room` (type 3 or 2, `roomName`) |
| add participants | `POST /api/v4/room/{token}/participants` (`source=users`) |
| configure rooms | `POST /api/v1/breakout-rooms/{token}` (`mode=2`, `amount`, `attendeeMap`) |
| start / stop round | `POST` / `DELETE /api/v1/breakout-rooms/{token}/rooms` |
| reassign (0.2) | `POST /api/v1/breakout-rooms/{token}/attendees` |
| message one room | bot `POST /api/v1/bot/{roomToken}/message`; fallback `POST /api/v1/chat/{token}` |
| broadcast to all rooms | `POST /api/v1/breakout-rooms/{token}/broadcast` |
| list participants / sessions | `GET /api/v4/room/{token}/participants` |
| in-call participants | `GET /api/v4/call/{token}` |
| enable bot | `POST /api/v1/bot/{token}/{botId}` (per room if the spike says so) |
| end call for all | `DELETE /api/v4/call/{token}?all=true` |
| remove attendee (moderator action) | `DELETE /api/v4/room/{token}/attendees` |

More than 20 rooms → the engine creates ⌈N/20⌉ parent conversations and pre-adds each participant to
their parent; the admin never sees this (§9). Not needed for a 50-person pilot (10 rooms) but the
data model allows it from day one (`rooms.parent_token`).

`infra/fake/meeting.py` implements the same Protocol in memory and records calls, for engine tests.

### 9.2 Transcript ingestion

`POST /api/v1/integrations/transcription/segments` — PUBLIC route, HMAC-SHA256 over the body with a
shared secret, idempotent on `(room_token, speaker_session_id, seq)`. Payload:
`roomToken, speakerSessionId, ncSessionId, langId, text, startMs, endMs, receivedAt, words?, final`.
Resolution to a participant follows section 16; unresolved segments are stored with
`participant_id = NULL` and flagged on the dashboard — **never guessed**. Segment model ported from the
legacy `transcription-hub` (`seq, start_ms, end_ms, text, speaker, mapped_user_id, confidence,
payload`, idempotency ledger).

`POST /api/v1/integrations/transcription/voice-activity` — same auth; events
`speech_started | speech_stopped` with `roomToken, speakerSessionId, tMs`.

### 9.3 Live Transcription fork

Section 14. Attached to a round by the engine through AppAPI's ExApp-to-ExApp request
(`POST /ocs/v1.php/apps/app_api/api/v1/ex-app/request/live_transcription` with `route`, `method`,
`params`), calling the fork's new room-level endpoint.

### 9.4 HpbEventClient (`infra/nextcloud/hpb_client.py`)

The signaling-client half of `spreed_client.py` without media: `hello` with `auth.type = internal`
(HMAC of a random nonce with the HPB internal secret, plus the Nextcloud backend URL), `room` join,
then consume `event.participants.update` (session ids, `nextcloudSessionId`, `inCall` flags),
`event.room.join/leave`, and `message` payloads of type `speaking` / `stoppedSpeaking`. One client per
active room, re-attached on engine restart. Feeds `participant_sessions` and, as a secondary source,
`speaking_metrics`.

### 9.5 Speaking-time engine and agents

Section 15. Engine tick every 5 s per active room: fold VAD events into per-participant
`speaking_ms`, `share`, `turn_count`, `current_turn_ms`, `longest_turn_ms`, `last_spoke_at`; evaluate the
round timer and the `soft_balanced` policy (ported gentle/strict presets: warn at 45 % / 40 % share,
stronger at 58 % / 52 %, streak limits 75 s / 60 s, minimum speech before judging 90 s / 70 s); emit
**intents**. The agent runtime turns intents into messages; the bot posts them.

### 9.6 Analysis and report

Citizens' `services/analysis.py`, `domain/analysis_schemas.py`, `Finding` / `FindingEvidence` and
`report.py` / `report_pdf.py` are reused with two renames (table → room, round stays round) and one
improvement: the speaker label is a real user, not `SPEAKER_01`, so every citation reads "who said what
when". The evidence rules are unchanged: segment ids rendered as `[id|id] Name (mm:ss): text`, ids
intersected with real segments on the way back, **a finding without evidence is dropped**, counts are
recomputed from links and never trusted from the model. Review statuses
`DRAFT / APPROVED / REJECTED / EDITED_AND_APPROVED`; `original_json` immutable; report distinguishes
approved findings from AI summaries.

Post-call job (per round, queued when the round ends): VAD-trim each speaker's capture →
`providers/transcription/mistral.py` (`voxtral-mini-latest`, segment timestamps) → replace that
speaker's live segments in place (`source = postcall`, original kept for audit) → re-run room analysis.
Big-Vosk alternative through the same `TranscriptionProvider` interface for fully-local deployments.

## 10. Step 3 — Session UI

*≈ 1 week. Vue 3, adapted from Citizens' tabs; polling every 2–4 s; all state read from the ExApp.*

**Admin / moderator**

| Tab | Content |
|---|---|
| Overview | session status, rounds, participant count, provider readiness (Talk, HPB, transcription, LLM) |
| Rounds | add / reorder rounds, question, duration; start / extend / end |
| Participants | add existing Nextcloud users (user search via OCS), remove, consent state |
| Rooms | per round: room list, manual assignment, "randomise", "copy previous round" |
| Live | per room: timer, participants, speaking shares, transcription status, alerts; actions **message room**, **extend**, **end round**; moderation alerts with evidence and **dismiss / escalate** |
| Analysis | findings per room and cross-room, review actions, re-run |
| Report | interim / final, MD / PDF / JSON, publish to participants |
| Files | captures and transcripts per room, delete, export ZIP, retention state |
| Settings (admin) | providers (Vosk URL, live STT provider, post-call provider, LLM endpoint), agent presets, retention, consent text preview |

**Participant** (a single screen that changes with the session state, §23)

consent (generated from configuration, section 18) → waiting → **Join discussion** (opens the parent
conversation; Talk switches the participant to their room) → "round in progress" with the round question
and remaining time → "round ended" → results when published.

## 11. Step 4 — Hardening and pilot rehearsal

*≈ 1 week.*

- Restart mid-round: running rounds reloaded, timers re-armed from `engine_timers.deadline_at`, HPB
  clients re-attached, transcription sessions re-requested; no duplicate messages (intent ids).
- Fault tests with the fake adapters (section 19).
- A rehearsal with ~10 people on the dev instance: full session, two rounds, both agents, post-call
  transcription, report.
- Documentation: admin guide, privacy note generated from the same source as the consent screen,
  `CHANGELOG.md`, App Store description with the data-processing block.

**Total: ≈ 4–6 weeks to a demoable 0.1.**

## 12. Data model

SQLAlchemy 2 models, Alembic revisions `0001–0006` (one per group below). PostgreSQL; UUID primary keys;
`created_at` / `updated_at` everywhere; JSONB for payloads.

| Table | Key columns | Notes |
|---|---|---|
| `sessions` | name, language, status (`DRAFT READY ACTIVE PROCESSING REVIEW COMPLETE`), created_by, analysis_instructions, closed_at, final_report_json, retention_days | = Citizens `assemblies` |
| `rounds` | session_id, position, title, question, duration_s, status (`NOT_STARTED ACTIVE ENDED PROCESSING READY_FOR_REVIEW`), started_at, ended_at, deadline_at | |
| `participants` | session_id, nc_user_id, display_name, role (`participant moderator observer`), consent JSONB, consent_at | reference to the NC identity only (§4) |
| `rooms` | round_id, number, label, parent_token, talk_token, bot_enabled, status | = Citizens `tables`; `parent_token` for > 20 rooms |
| `room_members` | round_id, room_id, participant_id | unique (round, participant) |
| `participant_sessions` | participant_id, room_id, attendee_id, nc_session_id, hpb_session_id, joined_at, left_at | identity chain (section 16) |
| `transcript_segments` | round_id, room_id, participant_id (nullable), nc_user_id, speaker_session_id, seq, start_ms, end_ms, text, language, confidence, source (`live postcall`), idempotency_key (unique), words JSONB, raw JSONB, superseded_by | |
| `voice_activity_events` | room_id, participant_id, speaker_session_id, kind (`start stop`), t_ms, source (`vad hpb`) | |
| `speaking_metrics` | round_id, room_id, participant_id, speaking_ms, share, turn_count, current_turn_ms, longest_turn_ms, last_spoke_at | materialised by the engine |
| `captures` | round_id, room_id, participant_id, path, codec, duration_ms, sha256, started_at, deleted_at | one file per speaker per round |
| `moderation_events` | round_id, room_id, participant_id, type, severity, rule, threshold, observed, evidence_segment_ids JSONB, automatic, action, message_id, reviewed_by, reviewed_at | §28 shape |
| `agent_events` | round_id, room_id, agent_type, provider, model, prompt_version, intent JSONB, input_refs JSONB, output JSONB, status (`sent missed no_reply error`), latency_ms, cost | |
| `findings` / `finding_evidence` | as Citizens (`scope room|round`, type, title, summary, support, status, ai_model, original_json, source_finding_ids, reviewed_by) / (finding_id, transcript_segment_id) | |
| `reports` | session_id, kind (`interim final`), snapshot_json, snapshot_hash, published_at | frozen snapshots |
| `consent_records` | participant_id, version, text_hash, accepted_at, revoked_at | |
| `audit_events` | event, object_type, object_id, actor, data_json | written through the caller's session |
| `app_jobs` | type, payload_json, state, attempts, next_attempt_at, locked_at, last_error | Citizens runner |
| `engine_timers` | round_id, kind, deadline_at, fired_at | survives restarts |

## 13. API

All under `/api/v1`, JSON, verbs GET/POST/PUT/DELETE only.

| Area | Endpoints |
|---|---|
| Health | `GET health` |
| Sessions | `GET/POST sessions`, `GET/PUT/DELETE sessions/{id}`, `POST sessions/{id}/close`, `DELETE sessions/{id}/close` |
| Rounds | `POST sessions/{id}/rounds`, `PUT/DELETE rounds/{id}`, `POST rounds/{id}/start`, `POST rounds/{id}/extend`, `POST rounds/{id}/end` |
| Participants | `GET/POST sessions/{id}/participants`, `DELETE participants/{id}`, `POST participants/{id}/consent` |
| Rooms | `GET rounds/{id}/rooms`, `POST rounds/{id}/rooms/randomize`, `POST rounds/{id}/rooms/copy-previous`, `POST rounds/{id}/rooms/move`, `POST rooms/{id}/message` |
| Live | `GET rounds/{id}/monitor` (rooms, timers, shares, alerts, transcription status), `GET rooms/{id}/transcript` |
| Moderation | `GET rounds/{id}/moderation`, `PUT moderation/{id}` (dismiss / escalate / note) |
| Analysis | `GET rounds/{id}/findings`, `PUT findings/{id}`, `POST rounds/{id}/analyze`, `POST rooms/{id}/transcribe` (post-call) |
| Reports | `GET sessions/{id}/report{.md,.pdf,.json}`, `POST/DELETE sessions/{id}/report/publish` |
| Files | `GET sessions/{id}/files`, `DELETE captures/{id}`, `DELETE rooms/{id}/transcript`, `GET sessions/{id}/export.zip` |
| Admin | `GET/PUT admin/providers`, `POST admin/providers/test`, `GET/PUT admin/agents` |
| Integrations (PUBLIC) | `POST integrations/talk/bot` (Talk signature), `POST integrations/transcription/segments`, `POST integrations/transcription/voice-activity` (HMAC) |
| Participant | `GET me/session` (current state for the participant screen) |

## 14. Live Transcription fork

Repository `live_transcription` fork, same app id `live_transcription` (Talk hard-codes it), drop-in
image, every addition **off by default** and proposed upstream as separate PRs.

| # | Change | Where | Enables |
|---|---|---|---|
| 1 | **Segment webhook**: on each final `Transcript`, POST `{roomToken, speakerSessionId, ncSessionId, langId, text, startMs, endMs, receivedAt, words?}` to `LT_SEGMENT_WEBHOOK_URL`, HMAC-signed with `LT_SEGMENT_WEBHOOK_SECRET`; timestamps from the first/last audio frame `pts` of the utterance; optionally `SetWords(True)` | transcript queue consumer in `spreed_client.py`, `transcriber.py` | §10, §11 |
| 2 | **Room-level session**: `POST /api/v1/call/transcribe-room {roomToken, langId, enable}` keeps the client attached while the call has ≥ 1 participant, independent of caption requesters | `main.py`, `service.py` | transcripts and captures without anyone enabling captions |
| 3 | **VAD**: voice-activity detection on the decoded PCM (webrtcvad/silero); emits `speech_started/stopped` to `LT_VAD_WEBHOOK_URL`; feeds Vosk only during speech (+ ~500 ms pre-roll) | `transcriber.py` | §12 speaking time; keeps recogniser load proportional to speech |
| 4 | **Per-speaker capture**: write each participant's Opus packets to persistent storage per room/round, closed on leave/round end; path reported in the segment webhook | `spreed_client.py` track handler | section 17, post-call transcription |

Vosk stays where Citizens put it (`citizens-vosk`, patched server with per-connection model selection
and LRU model cache) via `LT_VOSK_SERVER_URL`; the fork's internal Vosk remains available.

## 15. Facilitation and moderation agents

One facilitator voice (the Talk bot "Citizens Online"), two rule sources.

```
   engine tick (5 s)
        │
   speaking-time engine + round timer ──► policy check (deterministic)
   (VAD primary, HPB speaking events)      "Alice 34 % > 30 % for 75 s"   ← decision + audit row
        │                                        │
        │                              nothing due ──► silence
        │                                        │
        └── metrics ─────────────────► INTENT {type, room, subject, observed, threshold, tone}
                                                 │
                                        FacilitatorAgent (LLM, always)
                                        sees the intent + last ~2 min of transcript
                                        may fold in a content nudge, may answer NO_REPLY
                                        deadline 15 s (time-critical) / 45 s (content)
                                        one retry, then DROP and log `missed`
                                                 │
                                        Talk bot posts one message in that room
                                        (one in-flight request per room, cooldown per
                                         participant, maxReplies per round, intents merged)
```

- **Time/speaking manager** — intents: `time_remaining` (10, 5, 2 min), `share_warning`,
  `share_strong_warning`, `long_turn`, `silent_participant`, `round_ended`. Actions in 0.1: messages
  only. Presets *gentle* / *strict* from the legacy speaking-balance moderator.
- **Offensive-language moderator** — `ModerationAgent` classifies each final segment
  (`personal_attack, threat, harassment, hate, spam, off_topic, none`, with severity), **never treating
  disagreement or strong criticism as abuse** (§15). Low severity → an intent for the facilitator
  ("let's keep this about the proposal"); high severity → `moderation_events` alert on the Live tab with
  the segment as evidence; a human decides. No automatic mute, removal or ban in 0.1 (§15 safety policy).
- **Cadence**: engine 5 s; at most one LLM call per room per minute; classification batched per
  segment; `agent_events` records intent, prompt version, model, latency, cost, status.
- **Without an LLM** the Route cannot enable facilitation (decision log). Time rules still decide and
  still log; nothing is posted.

## 16. Speaker identity chain

```
  Alice's browser joins the breakout room
     ├─► Talk attendee            actorType users, actorId "alice", attendeeId 47
     ├─► Nextcloud session id     in GET /room/{token}/participants → sessionIds[]
     │                            (new per conversation and per reconnect; several devices possible)
     ├─► HPB session id           the signaling server's id for that connection
     └─► Janus audio stream       what the transcription fork subscribes to
```

Transcripts carry the HPB session id. Resolution: **HPB sid → Nextcloud session id** (the fork's
`nc_sid_map`, forwarded in the webhook) **→ attendee → `alice`** (participants list, cached per room
and refreshed on every HPB join/leave event). If the chain cannot be resolved the segment is stored
unattributed and surfaced on the Live tab; it is never assigned by guesswork. Spike question (d) checks
that this holds across the parent → breakout switch and after reconnects.

## 17. Capture instead of recording

Talk's recording server renders the call in a headless browser and encodes a video; that is the wrong
tool for a transcript-centric process. The transcription fork already receives every participant's audio
as a separate stream; change #4 writes it to disk with no rendering, no mixing and no extra participant.

- One Opus file per speaker per round; identity by stream; timestamps aligned with the live segments.
- Used for post-call re-transcription (section 9.6) and available in the Files tab.
- It is a recording in the legal sense: on the consent screen, in `consent_records`, under retention.
- Not possible in end-to-end-encrypted calls; deliberation rooms run without E2EE and say so.
- Talk's own recording server remains an optional add-on for organisations that want a video file.

## 18. Consent, privacy, retention

- **Consent screen generated from configuration** (Citizens `data_handling_summary` pattern): lists
  transcription (engine and where it runs), AI analysis and facilitation (which provider receives text),
  speaking-time measurement, moderation policy, audio capture, retention period. Stored per participant
  with the text hash; declining leaves the participant as an observer.
- **What leaves the server** is explicit per provider: live Vosk = nothing; Mistral post-call = audio of
  that participant's speech; LLM = pseudonymised transcript text. External providers are admin-configured
  and named on the consent screen (§26).
- **Retention**: audio purged after `retention_days` (Citizens sweep), transcripts kept unless deleted;
  deleting a transcript marks dependent findings `evidence_removed`.
- **Pseudonymisation** before any external LLM call (legacy `aiPrivacyPayload` policy, ported).
- Storage paths are server-generated UUIDs; downloads are served `no-store`; logs never contain
  transcript text (redaction processor).

## 19. Testing and failure behaviour

- Unit: engine transitions, policies, intent merging, identity resolution, evidence intersection,
  version consistency, proxy-verb guard, AST guard for Nextcloud calls inside transactions.
- Integration: full session flow against the fake adapters and a temporary database; recorded
  fixtures for HPB events, Talk participant lists, transcription webhooks.
- Fault matrix (§33): ExApp restart mid-round; Talk API unavailable (round continues, actions queue and
  retry, dashboard shows degradation); transcription unavailable (call continues, agents pause, admin
  alerted); LLM unavailable (decisions and audit continue, messages dropped and counted, "facilitator
  degraded" indicator); participant disconnect/reconnect (session chain refreshed); timer fires twice
  (idempotent intents); round ended manually; moderation false positive (human dismisses, logged).
- Ratchet tests (technique from legacy DR): counts that may only go down — dead exports, routes without
  callers, providers in the picker without an implementation.

## 20. Repository layout

```
citizens_online/
  main.py  config.py  logging_setup.py
  api/            sessions.py rounds.py participants.py rooms.py live.py moderation.py
                  findings.py reports.py files.py admin.py integrations.py me.py system.py downloads.py
  core/           engine/ (session_engine.py, timers.py, intents.py)
                  speaking/ (metrics.py, policies.py)
                  agents/ (facilitator.py, moderation.py, runtime.py, prompts/)
                  analysis/ (analysis.py, schemas.py, report.py, report_pdf.py)   ← Citizens
                  identity.py
  infra/          ports.py
                  nextcloud/ (talk_adapter.py, hpb_client.py, bot.py, users.py, notifications.py, appconfig.py)
                  fake/ (meeting.py, transcripts.py, agent.py)
                  standalone/ (reserved)
  providers/      llm/openai_compat.py   transcription/{base,vosk,mistral,whisper}.py   ← Citizens
  db/             session.py migrate.py migrations/ models/
  jobs/           runner.py handlers.py sweep.py
  security/       identity.py rate_limit.py webhooks.py
  storage/        paths.py space.py
appinfo/info.xml  Dockerfile  start.sh  Makefile  pyproject.toml  .env.example
frontend/         (Vue 3 + Vite; bundles committed to js/ and css/)
tests/            unit/ integration/ engine/ adapters/
third_party/live_transcription   (git submodule of the fork)
scripts/          dev-env.sh dev-up.sh register.sh unregister.sh dev-reset.sh set-version.sh validate_info_xml.py vosk/
docs/             SPEC.md PLAN.md (this file) spike-results.md administration.md privacy.md testing.md releasing.md
```

---

# Part C — Roadmap after 0.1

## 21. Roadmap 0.2 → 1.0

| Version | Adds | Spec |
|---|---|---|
| **0.2 Matching & remix** | `EmbeddingProvider` (local model default; OpenAI-compatible/OpenRouter optional); answers embedded on submission; participant profile vector (answers + optional round-1 speech behind a profiling-consent gate); Frankly Match optimiser ported (simulated annealing, size planning, bounds, random fallback) with strategy → objective mapping (`random similar diverse maximum_diversity stakeholder_balanced expertise_balanced cross_pollination maximum_new_contacts hybrid`), constraint penalties, `encounters` matrix, per-group diagnostics; remix executes through `breakout-rooms/{token}/attendees` | §18–§21, Phases 5–6 |
| **0.3 Speaking policies** | audio-permission actions through `PUT room/{token}/attendees/permissions` (`PUBLISH_AUDIO`): soft-balanced escalation to temporary mute, timed turns with grace period, queue mode; moderator revoke/restore from the Live tab | §13, Phase 4 |
| **0.4 Modules & engine** | generalised Route engine (RouteTemplate, RouteRun, ModuleRun state machines, event bus, conditional edges via the ported walker); modules `information, text_input, survey, poll (Talk or own), pause, synthesis (SynthesisAgent with source ids, ArgumentAgent), conditional`; list-based builder with JSON import/export; participant screen driven by the current module | §4–§7, §22–§23, Phase 7–8 |
| **0.5 Modular builder** | graph builder in the spirit of the standalone app (ported bridge logic: graph → ordered/branching modules with explicit validation errors); templates library; per-module typed config schemas | §6, §22 |
| **1.0 Ecosystem** | external tools (`ExternalModuleProvider`: Pol.is, Decidim, Harmonica, custom); ActivityPub publication of public objects (port of the legacy `fediverse.ts`: Service actors, HTTP Signatures, delivery outbox, SSRF guard, triple default-off gate) with a WebFinger companion app; Guests-app accounts and a process-specific registration flow; recruitment/sortition service; federation research (federated participants: chat/polls/permissions yes, breakout rooms no on Talk 24) | §24–§25, Phase 10 |

## 22. Design notes carried forward

- **Engine decides, LLM phrases.** Keep the boundary when adding policies and modules: numbers, thresholds
  and transitions are deterministic and audited; language is generated.
- **LLM describes people, the optimiser groups them** (§18 rule): stance scores or embeddings are features;
  group assignment is always the deterministic optimiser with diagnostics.
- **Provenance everywhere**: every generated artifact keeps `source_ids`, agent, model, prompt version,
  human edits; the trace endpoint walks result → statement → segment → participant (§17).
- **Human control over sanctions**: automatic reminders and configurable temporary interventions only;
  removal and ban require confirmation (§15).
- **Portability**: nothing in `core/` imports Nextcloud; a standalone adapter (LiveKit/mediasoup) remains
  possible (§2, §39.9–10).
- **Federation**: Nextcloud federation for institutional sharing; ActivityPub for public civic objects;
  never transcripts, recordings, identities, private analyses or moderation records (§25).

## 23. Spec coverage

| §40 deliverable | Where |
|---|---|
| A. Repository assessment | Appendix A (Citizens), Appendix B (legacy DR), section 4 |
| B. Architecture proposal | section 6 |
| C. Integration matrix | section 4, Appendices A–B, Appendix C |
| D. Data model | section 12 (0.1), section 21 (later entities per §4) |
| E. Talk API integration plan | section 9.1, Appendix C |
| F. Transcription integration plan | section 14, Appendix D |
| G. MVP implementation plan | sections 7–11 |

§39 principles: 1–2 (Talk), 3 (Vosk default), 4 (identity by stream), 5 (speaking time from VAD/HPB),
6–7 (deterministic matching, 0.2), 8 (providers replaceable; note the owner's decision that facilitation
*requires* an LLM), 9–10 (ports + fake + reserved standalone adapter), 11 (audit), 12 (human sanctions),
13 (provenance), 14 (modules, 0.4), 15 (resumable engine).

---

# Appendix A — Citizens ExApp reuse map

Source: `/root/NextCloud-Citizen` (AGPL-3.0-or-later, 0.6.0-beta.11, same author).

| Verdict | Component | Path |
|---|---|---|
| copy | app factory, lifespan, AppAPI middleware, top-menu registration, revalidated static mounts, loopback-only no-auth guard | `citizens/main.py` |
| copy | settings model over AppAPI env vars | `citizens/config.py` |
| copy | structlog setup with secret redaction, rotating JSONL | `citizens/logging_setup.py` |
| copy | current user from AppAPI headers | `citizens/security/identity.py` |
| copy | admin check via OCS `cloud/user`, fail-closed | `citizens/api/admin.py` |
| copy | Alembic at startup, env, naming convention, `TZDateTime`, `new_uuid` | `citizens/db/migrate.py`, `db/migrations/env.py`, `db/models/base.py` |
| adapt | session factory (Postgres: drop SQLite-only machinery, keep the "no OCS call inside a transaction" rule) | `citizens/db/session.py` |
| adapt | durable job runner, handlers, sweeps (Postgres claiming) | `citizens/jobs/{runner,handlers,sweep}.py` |
| copy | audit writes through the caller's session | `citizens/services/audit.py` |
| copy | download headers (`no-store`) | `citizens/api/downloads.py` |
| copy | provider settings in AppConfig (`sensitive`), single `NextcloudApp()` client, caches, consent text generator | `citizens/services/provider_config.py` |
| copy | transcription provider base types, speaker labeler, permanent-vs-retry errors | `citizens/providers/transcription/base.py` |
| copy | Vosk WebSocket client (16 kHz PCM, 0.2 s frames, literal EOF) | `citizens/providers/transcription/vosk.py` |
| copy | Mistral batch adapter; realtime session | `citizens/providers/transcription/mistral.py`, `services/live_captions.py` (`MistralSession`) |
| copy | Whisper/OpenAI-compatible adapter | `citizens/providers/transcription/whisper.py` |
| copy | LLM adapter with JSON extraction and schema-correction retry | `citizens/providers/analysis/openai_compat.py` |
| copy | analysis prompts, segment coalescing, evidence intersection, drop-without-evidence, prompt extension levels | `citizens/services/analysis.py`, `citizens/domain/analysis_schemas.py` |
| copy | findings + evidence models, review statuses | `citizens/db/models/findings.py`, `citizens/api/findings.py` |
| adapt | report builder, Markdown, PDF | `citizens/services/report.py`, `report_pdf.py` |
| adapt | close/reopen with frozen snapshot | `citizens/services/lifecycle.py` |
| adapt | Files tab inventory, deletion, export | `citizens/services/files.py`, `citizens/api/files.py` |
| adapt | retention sweep | `citizens/jobs/sweep.py` |
| copy | storage paths (UUID-only), free-space guard | `citizens/storage/{paths,space}.py` |
| copy | rate limiter (`x-origin-ip`), hashed tokens, secret vault | `citizens/security/{rate_limit,recorder_tokens,invite_vault}.py` |
| copy | patched Vosk server, model scripts, concurrency check | `scripts/vosk/asr_server.py`, `scripts/vosk-*.sh`, `scripts/vosk/check_concurrency.py` |
| copy | dev/register/version scripts, info.xml validator, Makefile App Store targets | `scripts/*.sh`, `scripts/validate_info_xml.py`, `Makefile` |
| copy | CI and release workflows | `.github/workflows/{ci,release}.yml` |
| copy | test fixtures and guard tests | `tests/conftest.py`, `tests/unit/{test_proxy_verbs,test_no_config_reads_in_transaction,test_version_consistency}.py` |
| copy | frontend build and base-URL detection, UI atoms | `frontend/vite.config.ts`, `frontend/src/api.ts`, `frontend/src/main.ts`, `frontend/src/components/ui/*` |
| adapt | admin tabs (Overview, Rounds, Participants, Tables→Rooms, Monitor→Live, Analysis, Report, Files, Settings) | `frontend/src/components/*` |
| adapt | `appinfo/info.xml` (routes, store description blocks) | `appinfo/info.xml` |
| adapt | Dockerfile, start script | `Dockerfile`, `start.sh` |
| adapt | docs (architecture, privacy, testing, releasing, administration) | `docs/*` |
| not applicable | phone recorder SPA, chunk intake and assembly, QR invites | `frontend/src/recorder/**`, `citizens/services/{recording,audio,invites,qr_sheet}.py`, `citizens/api/{recorders,public_recorder}.py` |

# Appendix B — Legacy Democracy Routes migration map

Source: `/root/Democracy Routes` (AGPL-3.0-only, owned by the project; re-licensable as
AGPL-3.0-or-later here). Items marked 0.1 are used in the MVP; others in the roadmap.

| Verdict | Component | Path | Used in |
|---|---|---|---|
| port | facilitator agent cadence: interval, cooldown, maxReplies, minTranscriptChars, window hash, `NO_REPLY` | `services/dr-app/src/lib/meetingAiAgentRuntime.ts`, models `AiAgent`, `MeetingAiAgent*` | 0.1 |
| port thresholds | speaking-balance presets (gentle/strict shares, streaks, minimum speech) | `services/dr-video/server/moderation.js:88-110` | 0.1 |
| port | transcript segment model with idempotency ledger | `services/transcription-hub/server.js` | 0.1 |
| reuse (Python) | speaker activity timeline (non-biometric attribution) | `services/dr-livekit-agent/speaker_activity.py` | 0.1 |
| reuse (Python) | segmented audio writer with backpressure; health/liveness helpers | `services/dr-livekit-agent/{room_mix,health,capture_policy,repair_policy,liveness_reasons}.py` | 0.1 fork |
| port | capture ingest contract (start/heartbeat/transcript/artifact/finalize, idempotency keys, lease) | `services/dr-app/src/app/api/internal/livekit/capture/route.ts` | 0.1 |
| port | AI provider switch, JSON-mode forcing, error normalisation | `services/dr-app/src/lib/{aiTextPrompt,aiProviderSettings,aiJson}.ts` | 0.1 |
| port | pseudonymisation policy before external AI | `services/dr-app/src/lib/aiPrivacyPayload.ts` | 0.1 |
| port | processing-consent chokepoint | `services/dr-app/src/lib/processingConsent.ts` | 0.1 |
| port | transcript turn grouping with `sourceIds[]` | `services/dr-app/src/lib/transcriptGroups.ts` | 0.1 |
| port | seating algorithms `buildStanceRooms`, `buildRemixedRooms`, `buildPairScores` | `services/dr-app/src/lib/services/flowMatching.ts` | 0.2 |
| port | stance extraction (injected model call) | `services/dr-app/src/lib/services/stanceExtraction.ts` | 0.2 |
| port | grouping strategy resolution with loud fallback | `services/dr-app/src/lib/services/flowGrouping.ts` | 0.2 |
| port (invariant) | profiling-consent gate in the data loader | `services/dr-app/src/lib/flowSemanticProfiles.ts:62-80` | 0.2 |
| port | summary schema (agreements, disagreements, proposals, open questions, actions, limitations) | `services/dr-app/src/lib/meetingAiSummary.ts:29-43`, `FlowUnitSummary` | 0.4 |
| port | branching walker and graph model | `services/dr-app/src/lib/{executionWalker,planGraph}.ts` | 0.4 |
| port | template compile checks and graph ↔ ordered blocks bridge | `services/dr-app/src/lib/{templateCompile,reactFlowBridge}.ts` | 0.4–0.5 |
| port | report lifecycle with snapshot hash and approval states | `services/dr-app/src/lib/flowReport.ts`, `FlowReport*` | 0.4 |
| port | evidence permissions | `services/dr-app/src/lib/flowEvidenceExport.ts` | 0.4 |
| port | cost ledger with frozen prices | `services/dr-app/src/lib/usage/*` | 0.4 |
| port | ActivityPub subsystem and its contract test | `services/dr-app/src/lib/fediverse.ts`, `scripts/fediverse-contract-check.ts`, `src/app/{.well-known,ap}/**` | 1.0 |
| reuse | recruitment/sortition service | `services/dr-recruitment/` | 1.0 |
| reuse (documents) | compliance pack (DPIA, Art. 30 records, AI Act inventory) | `Platform-Project-Goals/*` | all |
| inspiration | event sanitiser regex and payload caps | `services/dr-event-hub/server.js:13-90` | 0.1 logging |
| inspiration | video provider interface shape | `services/dr-app/src/lib/videoProvider/types.ts` | ports design |
| discard | NextAuth layer, LiveKit provider/agent, dr-video (mediasoup), `dr-thinker`, `dr-matching` sidecar, `audio-api/*`, wall-clock runtime, remote worker, extra builders, empty `contracts/` | — | — |

# Appendix C — Talk API reference for the adapter

Verified against the Talk 24 documentation. Base `/ocs/v2.php/apps/spreed/api/`, header
`OCS-APIRequest: true`, calls made as the service user through AppAPI authentication
(`AUTHORIZATION-APP-API` = base64 `userid:secret`). nc_py_api wraps conversations, chat, polls and the
breakout create/remove/start/stop/broadcast/switch calls; the rest goes through `nc.ocs()`.

**Conversations (v4)** — `POST room` (roomType 2 group / 3 public, roomName, objectType/objectId for
extra breakout rooms), `GET/PUT/DELETE room/{token}`, `PUT room/{token}/description`, `/read-only`,
`/lobby`, `/recording-consent`, `/listable`.

**Participants (v4)** — `GET room/{token}/participants` → `attendeeId, actorType, actorId, displayName,
participantType, inCall, permissions, attendeePermissions, sessionIds[]`; `POST room/{token}/participants`
(`newParticipant`, `source`); `DELETE room/{token}/attendees?attendeeId`; `PUT room/{token}/attendees/
permissions` (`attendeeId`, `method add|remove|set`, `permissions`); `POST/DELETE room/{token}/moderators`.

**Breakout rooms (v1)** — `POST breakout-rooms/{token}` (`mode` 1 automatic / 2 manual / 3 free,
`amount` 1–20, `attendeeMap` JSON attendeeId → 0-based room); `DELETE breakout-rooms/{token}`;
`POST/DELETE breakout-rooms/{token}/rooms` (start/stop); `POST …/attendees` (reorganise);
`POST …/broadcast` (`message`); `POST …/switch` (`target`); `POST/DELETE …/request-assistance`.
Moderators cannot be moved into breakout rooms; only `users` attendees are distributed.

**Calls (v4)** — `GET call/{token}` (in-call participants), `POST/DELETE call/{token}` (`all=true` ends
for everyone), `PUT call/{token}` (flags).

**Chat (v1)** — `POST chat/{token}` (`message`, `replyTo`, `referenceId`, `silent`); `GET chat/{token}`
(`lookIntoFuture`, `lastKnownMessageId`, `timeout ≤ 60`).

**Bots (v1)** — register from the ExApp: `POST /ocs/v1.php/apps/app_api/api/v1/talk_bot` (`name`,
`route`, `description`) — nc_py_api `TalkBot.enabled_handler` stores the secret in app config; enable
per conversation `POST bot/{token}/{botId}` (moderator); webhook payload is ActivityStreams
(`Create`, `Join`, `Leave`, `Like`, `Undo`) signed with `X-Nextcloud-Talk-Signature` =
HMAC-SHA256(random + body, secret) and `X-Nextcloud-Talk-Random`; send `POST bot/{token}/message`
(`message`, `replyTo`, `referenceId`, `silent`) with `X-Nextcloud-Talk-Bot-Random/-Signature`;
`POST bot/ask-features` (`bot-features-api`).

**Polls (v1)** — `POST poll/{token}` (`question`, `options[]`, `resultMode` 0 public / 1 hidden,
`maxVotes`), `GET/POST/DELETE poll/{token}/{pollId}`.

**Ban (v1)** — `POST ban/{token}` (`actorType`, `actorId`, `internalNote`); human-confirmed only.

**Signaling settings** — `GET /ocs/v2.php/apps/spreed/api/v3/signaling/settings` (HPB URL, STUN/TURN).

**Constants** — attendee permissions: 1 custom, 2 start call, 4 join call, 8 ignore lobby,
**16 publish audio**, 32 publish video, 64 publish screen, 128 chat, 256 reactions. In-call flags:
0 disconnected, 1 in call, 2 audio, 4 video, 8 SIP. Breakout modes 0–3, status 0 stopped / 1 started.
Bot features: 1 webhook, 2 response, 4 event, 8 reaction. Recording status: 0 none, 1 video, 2 audio,
3/4 starting, 5 failed.

**Capabilities** — `breakout-rooms-v1` (Talk 16), `bots-v1` (17.1), `session-state` (18),
`federation-v1/v2` (19/20), `ban-v1` (20), `talk-polls` (15), `config.call.live-transcription` (22,
requires external signaling and an enabled ExApp with id `live_transcription`).

**Standalone signaling (HPB) protocol used by the event client** — `hello` `{version "2.0", auth:
{type "internal", params {random, token = HMAC-SHA256(random, internal secret), backend}}}`; `room`
join `{roomid, sessionid}`; events `event.room.join/leave`, `event.participants.update` (`sessionId`,
`nextcloudSessionId`, `inCall`); `message` with `recipient {type session|room|call}` and data types
`speaking`, `stoppedSpeaking`, `nickChanged`, `offer/answer/candidate`; `control` `{type mute, audio}`;
`internal` `addsession/updatesession/removesession/incall`.

# Appendix D — Live Transcription source anchors

`nextcloud/live_transcription` `master`, `ex_app/lib/` (line numbers approximate, 2026-08).

| Where | What |
|---|---|
| `spreed_client.py` ~235–358 | `connect()`, `send_hello()` (internal auth), `send_join()`, `send_incall()` |
| `spreed_client.py` ~1115–1200 | `signalling_monitor()`: `participants update` events, `nc_sid_map[nextcloudSessionId] = sessionId` (~1154), `send_offer_request()` for users with audio (~1185), cleanup on disconnect (~1140–1167) |
| `spreed_client.py` ~1077–1085 | `handle_offer()`: one `RTCPeerConnection` per speaker, audio `recvonly` |
| `spreed_client.py` ~1205–1238 | `track` handler: `AudioStream(track)` → `VoskTranscriber(spkr_sid, room_lang_id, transcript_queue)` — **identity meets audio here**; capture hook (#4) goes here |
| `spreed_client.py` ~576–591 | `send_transcript()`: signaling `message` type `transcript` `{final, langId, message, speakerSessionId}` |
| `spreed_client.py` ~1333–1388 | `transcipt_queue_consumer()` — segment webhook (#1) goes here |
| `transcriber.py` | 48 kHz stereo → mono downmix, Vosk WebSocket feed, `is_final = 'text' in json_msg`, `Transcript(final, lang_id, message, speaker_session_id)`; VAD gating (#3) and timestamps (#1) go here |
| `service.py` `Application` | `transcript_req()`, `leave_call()`, `set_call_language()`; room-level session (#2) goes here |
| `main.py` | routes `POST /api/v1/call/transcribe` (`roomToken, ncSessionId, enable, langId`), `/call/set-language`, `/call/leave`, `GET /api/v1/languages`, `GET /capabilities`, translation endpoints; `AppAPIAuthMiddleware`; `MODELS_TO_FETCH` |
| `vosk_server.py` | in-process WebSocket Vosk server, one recogniser per connection, models by language, `COMPUTE_DEVICE`, `LT_MAX_WORKERS` |
| `livetypes.py` | `TranscribeRequest`, `Transcript`, `HPBSettings` |
| `utils.py` | `get_hpb_settings()` via `/ocs/v2.php/apps/spreed/api/v3/signaling/settings`; env validation |
| `appinfo/info.xml` | id `live_transcription`, NC 33–35, env `LT_HPB_URL`, `LT_INTERNAL_SECRET`, `LT_VOSK_SERVER_URL`, `LT_DISABLE_INTERNAL_VOSK`, `SKIP_CERT_VERIFY`, `LT_MAX_WORKERS` |
| Talk side `lib/Service/LiveTranscriptionService.php` ~43, ~89–109, ~310 | hard-coded app id; `exAppRequest('live_transcription', '/api/v1/call/transcribe', …)` |

# Appendix E — AppAPI rules learned from Citizens

1. The proxy forwards **GET, POST, PUT, DELETE only**; PATCH is answered 405 before reaching the app.
2. Route regexes use the escaped bare-path form (`^api\/v1\/.*`); matching is path **and** verb, first
   match wins — order narrow routes first, declare every verb, or a request falls through to a broader
   route (a privilege downgrade, not a 405).
3. `--json-info` registration takes numeric access levels (0 PUBLIC, 1 USER, 2 ADMIN); `info.xml` takes names.
4. The proxy stamps `Cache-Control: private, max-age=3600` on non-JSON responses that set none — every
   download sends `no-store`; static bundles send `no-cache`; asset URLs are version-stamped.
5. The proxy authenticates from the Nextcloud session; `curl` with basic auth does not work through it.
6. Proxied pages get `default-src 'none'`; a public page must ship its own CSP and end in `.html`.
7. The browser derives the API base from its own `<script src>`; never hard-code `/index.php/apps/app_api/proxy/…` or `/exapps/…`.
8. `set_script` / `set_style` take paths **without** extensions.
9. `run_app` binds 127.0.0.1 by default — the image sets `APP_HOST=0.0.0.0`.
10. `set_handlers(map_app_static=False)` when serving assets with custom cache headers.
11. `nc.users.get_user()` returns 401 for an ExApp; use OCS `cloud/user` for the current user; admin checks fail closed, only a definite 403 hides admin UI.
12. Never rely on the proxy's ADMIN route alone; re-check in the app.
13. Reading AppConfig is an HTTP round-trip — never inside an open transaction; cache hot paths; guard with an AST test.
14. Build one `NextcloudApp()` client and reuse it (each instance fetches capabilities).
15. `x-origin-ip` is the only trustworthy client address; per-IP limits are never the primary control.
16. WebSockets do not traverse the proxy on this deployment; live UI uses polling until HaRP.
17. App Store: metadata-only archive, one top-level folder named after the app id, tag = `<version>` = `<image-tag>`, `pre-info.xslt` runs before XSD validation, publish amd64 + arm64.
18. Re-issuing the signing certificate deletes all releases; installing the same id through another daemon replaces the registration.
19. The container runs as a non-root user that owns `/data`.
20. `.dockerignore` excludes dev helpers that can mint tokens; `.gitignore` covers `.app_secret` and `*.key`.

# Appendix F — Example routes

**MVP 0.1 session** (no modules yet — a session with rounds):

```json
{
  "name": "Urban mobility — online assembly",
  "language": "en",
  "rounds": [
    { "title": "Round 1", "question": "What is the most important mobility problem?", "duration_s": 1200 },
    { "title": "Round 2", "question": "Which proposal would you prioritise, and why?", "duration_s": 1200 }
  ],
  "rooms_per_round": 10,
  "assignment": "random",
  "agents": { "time_manager": "gentle", "language_moderation": true },
  "live_stt_provider": "vosk",
  "postcall_stt_provider": "mistral",
  "retention_days": 90
}
```

**Target route (§7), representable from 0.4**:

```json
{
  "name": "Urban Mobility Deliberation",
  "modules": [
    { "type": "text_input", "duration": 300, "prompt": "What is the most important mobility problem?" },
    { "type": "matching", "strategy": "diverse", "group_size": 5 },
    { "type": "talk", "duration": 1200, "transcription": true, "speaking_policy": "balanced" },
    { "type": "pause", "duration": 180 },
    { "type": "remix", "strategy": "maximum-new-contacts" },
    { "type": "talk", "duration": 1200, "transcription": true },
    { "type": "synthesis", "outputs": ["proposals", "agreements", "disagreements"] },
    { "type": "text_input", "prompt": "Did anything change your position?" }
  ]
}
```

# Appendix G — References

- Nextcloud Talk API: https://nextcloud-talk.readthedocs.io/en/latest/ (breakout-rooms, participant,
  conversation, call, chat, bots, bot-management, poll, ban, constants, capabilities)
- Standalone signaling API: https://github.com/strukturag/nextcloud-spreed-signaling/blob/master/docs/standalone-signaling-api-v1.md
- Live Transcription ExApp: https://github.com/nextcloud/live_transcription (AGPL-3.0-or-later)
- Talk recording server (rejected for this design): https://github.com/nextcloud/nextcloud-talk-recording
- AppAPI developer docs: https://docs.nextcloud.com/server/latest/developer_manual/exapp_development/
- nc_py_api: https://github.com/cloud-py-api/nc_py_api (pin `>=0.30,<0.32`)
- HaRP: https://github.com/nextcloud/HaRP
- Frankly Match (MIT): https://github.com/berkmancenter/frankly-match — `api/text_match.py`
- Vosk models (Apache-2.0): https://alphacephei.com/vosk/models
- Citizens ExApp: https://github.com/Democracy-Routes/nextcloud-citizens
- Legacy Democracy Routes: https://github.com/theRAGEhero/democracy-routes-v0.2.alpha
