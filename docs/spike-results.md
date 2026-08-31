# Step 0 spike results — Talk 24.0.4 on Nextcloud 34.0.3

Run 2026-08-31 against `cloud.democracyinnovators.com` as the service user `citizens-online`,
using OCS directly. Every conversation created by the spike was deleted afterwards.

## Answers

| # | Question | Answer |
|---|---|---|
| a | Is a bot enabled on the parent conversation active in its breakout rooms? | **No.** The bot appears in the child with `state = 0` (disabled). It must be enabled per room: `POST /ocs/v2.php/apps/spreed/api/v1/bot/{roomToken}/{botId}` → `201`. **The adapter enables the bot on every breakout room after creating them, and again after every remix.** |
| b | Does the configure-breakouts response contain only the breakout rooms? | **No.** It returns the children **and the parent**. Children are identified by `objectType == "room"` and `objectId == <parentToken>`; the parent has empty `objectType`/`objectId` and carries `breakoutRoomMode = 2`. **Filter on `objectType`/`objectId`, never on array position.** |
| c | Is `attendeeMap` honoured, and does room index match response order? | **Yes.** `{co1:0, co2:0, co3:1, co4:1}` produced exactly that placement, and index *n* corresponds to the *n*-th child in the filtered response. |
| d | Can participants find their breakout room? | **Yes.** `GET /ocs/v2.php/apps/spreed/api/v4/room` as the participant lists the breakout room they were assigned to. |
| e | Do participant listings expose the fields the identity chain needs? | **Yes.** `attendeeId`, `actorType`, `actorId`, `sessionIds`, `inCall`, `permissions` are all present. |
| f | Can audio permission be revoked and restored inside a breakout room? | **Yes.** `PUT /v4/room/{token}/attendees/permissions` with `method=remove|add`, `permissions=16` → `200` both ways. (Enforcement during an actual call is still to be verified with the HPB.) |
| g | Does remix work on a live breakout set? | **Yes.** `POST /v1/breakout-rooms/{token}/attendees` with a new `attendeeMap` → `200`. |
| h | Can the service user drive all of this? | **Yes**, as the conversation owner. It creates the parent, so it is moderator everywhere. |

## Sequence the adapter implements

```
POST   /v4/room                                   roomType=2, roomName          -> parent token
POST   /v4/room/{parent}/participants             newParticipant, source=users  (per participant)
GET    /v4/room/{parent}/participants                                           -> attendeeId map
POST   /v1/breakout-rooms/{parent}                mode=2, amount=N, attendeeMap -> [children..., parent]
   filter objectType=="room" && objectId==parent  -> ordered child tokens
POST   /v1/bot/{child}/{botId}                    per child room                (NOT inherited)
POST   /v1/breakout-rooms/{parent}/rooms                                        start
   ... round runs ...
POST   /v1/breakout-rooms/{parent}/attendees      attendeeMap                   remix
DELETE /v1/breakout-rooms/{parent}/rooms                                        stop
DELETE /v1/breakout-rooms/{parent}                                              remove config
```

## Other environment findings

- **Ollama Cloud is configured and reachable.** `https://ollama.com/v1` (OpenAI-compatible) with the key
  already on this host in `/etc/globstory-ai.env`. Both `glm-5.2:cloud` and `deepseek-v4-pro:0813`
  answered a JSON-only prompt correctly. `glm-5.2:cloud` is the default for this app.
- Local Ollama (`bge-m3`, `qwen3-vl:4b`) is on `127.0.0.1:11434`; a container needs the host gateway.
- Not yet installed: HPB (signaling/NATS/Janus) and the Live Transcription ExApp. Calls therefore run
  peer-to-peer, which is fine for the small test rooms and is why browser-side capture is the
  transcription path for this build.
