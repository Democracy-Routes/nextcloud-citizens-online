# Testing Citizens Online

Everything below is already set up and running on
**https://<your-nextcloud>**. Start at step 1.

---

## Accounts

Test participants and the service account were created for this build. Their
passwords are in a root-only file the build wrote on the server — its path is
recorded in `HANDOVER.md`, section 4.

| Account | Purpose |
|---|---|
| `admin` | Organizer. Owns the demo session. Log in as this to drive the test. |
| `co1` … `co8` | Participants. Log in as these (a second browser or a private window) to be in the deliberation. |
| `citizens-online` | Service account. Creates and moderates the Talk conversations. Do not log in as this. |

A demo session is already seeded: **“Urban mobility — demo assembly”**, two
rounds of 10 minutes, two rooms, with `co1`–`co6` as participants.

---

## 1. The organizer's side (5 minutes)

1. Log in as **admin** and open **Citizens Online** in the top menu.
2. You should see *Urban mobility — demo assembly* in the sidebar. Open it.
3. **Rounds** tab — two rounds are defined. You can edit the question or the
   duration; changes save when you leave the field.
4. **Participants** tab — `co1`–`co6` are listed. You can add more by typing
   Nextcloud usernames separated by spaces.
5. **Rooms** tab — press **Distribute randomly**. The six people are split
   between two rooms. Move someone with the dropdown next to their name.
6. **Rounds** tab → **Start round** on Round 1.

At that moment the app: creates a Talk conversation for the session, adds every
participant to it, creates two breakout rooms with exactly the membership you
planned, starts them, enables the facilitator bot in each room, and starts the
clock.

7. You land on the **Live** tab. It shows the countdown, both rooms, who is in
   them, and a speaking-share bar per person that fills as people talk.

## 2. The participant's side (the interesting part)

In a **second browser** (or a private window — Talk and the app both need a
session, so a different profile is cleanest):

1. Log in as **co1**. Open **Citizens Online**.
2. You get a **consent screen** first. It is generated from the current
   configuration — it names the speech engine, says whether anything leaves the
   server, and states the retention. Accept.
3. The screen becomes the round view: the question, a countdown, and a
   **Join the discussion** button.
4. Press it. Talk opens in a new tab and puts you straight into *your* breakout
   room — you never have to find it.
5. **Leave the Citizens Online tab open.** It is recording your microphone, and
   it says so with a red dot and an upload counter. Grant microphone access when
   the browser asks.
6. Repeat with `co2` in another profile if you want two people in a room.

Talk to each other for a minute. On the organizer's **Live** tab you should see
the speaking bars move, and the facilitator will post into the room as the
thresholds are crossed (at 2 minutes remaining, or when one person passes ~45 %
of the room's speaking time).

## 3. Ending the round and reading the result

1. Organizer → **Live** → **End round** (or wait for the clock).
2. The breakout rooms close and everyone returns to the main conversation.
3. Behind the scenes: chat messages are folded into the transcript, each
   participant's audio is assembled and transcribed, then each room is analysed
   and the rooms are clustered together. This takes a minute or two — the job
   log is visible with `docker logs -f nc_app_citizens_online`.
4. **Analysis** tab — findings per room and across rooms. Every one has an
   **evidence** section quoting who said what, with a timestamp. Approve or
   reject them.
5. **Report** tab — read it in the browser, or download **Markdown**, **PDF** or
   **JSON**. Tick *Include unapproved AI drafts* to see everything the model
   produced, including what you have not approved.

## 4. Testing without microphones

The analysis works from **chat as well as speech**, so you can exercise the whole
pipeline with typing only:

1. Start a round.
2. In each Talk breakout room, have the participants **type** a few substantive
   messages to each other.
3. End the round.
4. The findings appear with the chat lines as evidence.

This is how the pipeline was verified during the build.

---

## What works today

- Sessions, rounds, participants, room assignment (manual or random).
- Real Talk breakout rooms with exactly the planned membership; participants are
  moved automatically and moved back when the round ends.
- The facilitator bot, enabled per room, phrasing every message with the
  configured language model.
- Speaking time measured from the audio itself (not from counting transcript
  words), with the share bars and the balance thresholds that follow from it.
- Per-participant browser capture with local-first storage: chunks are hashed and
  written to IndexedDB **before** any upload, so a network drop cannot lose audio.
- Live captions through Vosk while a round runs.
- Chat folded into the transcript.
- Analysis with mandatory evidence — a finding that cannot cite a real passage is
  discarded, not stored.
- Report as Markdown, PDF and JSON, with AI drafts clearly separated from
  approved findings.
- Consent screen generated from configuration; audit log; retention sweep.

## What does not work yet

- **Calls above ~4–6 people per room.** There is no High-Performance Backend on
  this server, so Talk is peer-to-peer. Fine for a small test, not for 50 people.
- **Embedding-based matching and remix.** Rooms are assigned manually or randomly
  in this version; the "Apply plan (remix)" button on the Live tab does push the
  current plan into the open Talk rooms, but the matching itself is not yet
  embedding-based.
- **Mute / timed turns / queue mode.** The facilitator sends messages; it does
  not yet revoke audio permissions.
- **The modular builder**, surveys, polls and the other module types.
- **Mobile browsers** for the capture tab are untested; a backgrounded tab may
  throttle the uploader.
- **Guests and federated users** cannot take part — Talk breakout rooms only
  accept accounts on this server.

## If something looks wrong

```bash
# the app's own log, structured and readable
docker logs -f nc_app_citizens_online 2>&1 | grep -v urllib3

# is it healthy?
docker ps --filter name=nc_app_citizens_online

# restart it (nothing is lost: state is in the citizens_online_data volume)
docker restart nc_app_citizens_online
```

Common things:

- **“Citizens Online” missing from the menu** — hard-refresh; the app registers
  its menu entry when it is enabled.
- **The facilitator says nothing** — check Settings → the language model. The
  Live tab shows *degraded* with a count when messages missed their moment.
- **No captions** — check Settings → Speech to text → **Test**. Vosk must be
  reachable at `ws://citizens-vosk:2700`.
- **Microphone not recording** — the browser needs permission, and the Citizens
  Online tab must stay open. Chrome and Firefox both allow Talk and this app to
  hold the microphone at once; Safari is untested.
