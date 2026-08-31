# Democracy Routes for Nextcloud — Implementation Specification

> Original specification as provided by the project owner on 2026-08-28. Saved verbatim so that
> `PLAN.md` can cite its section numbers (§0–§41). Product decisions taken afterwards (name
> "Citizens Online", MVP 0.1 scope, etc.) live in `PLAN.md`, not here.

## 0. Mission

Build **Democracy Routes as a deliberation and democratic-process engine integrated with Nextcloud**.

Do not rebuild generic collaboration infrastructure that Nextcloud already provides.

Nextcloud should provide:

* identity and user accounts
* groups and institutional authentication
* Talk
* audio/video conferencing
* breakout rooms
* chat
* files
* calendar
* notifications
* federation between Nextcloud installations
* Talk High Performance Backend where required
* live speech transcription infrastructure

Democracy Routes should provide:

* Routes and reusable deliberative workflows
* modular workflow builder
* participant matching
* rematching/remixing between rounds
* structured transcripts and deliberative memory
* speaking-time measurement
* facilitation agents
* moderation policies
* semantic analysis
* synthesis
* provenance and auditability
* external deliberation-tool integrations
* optionally ActivityPub publication/federation of public civic outputs

The architectural principle is:

**Nextcloud = collaboration infrastructure**

**Democracy Routes = democratic process engine**

---

# 1. Deployment Model

Implement Democracy Routes primarily as a **Nextcloud AppAPI External App (ExApp)**.

The application must run in Docker and be installable into a Nextcloud deployment using the supported AppAPI/ExApp deployment mechanism.

Target architecture:

```text
Nextcloud
│
├── Users / Groups / LDAP / SSO
├── Files
├── Calendar
├── Notifications
│
├── Talk
│   ├── conversations
│   ├── chat
│   ├── calls
│   ├── breakout rooms
│   ├── participant permissions
│   └── HPB / WebRTC
│
├── Live Transcription ExApp
│   └── Vosk
│
└── Democracy Routes ExApp
    ├── Route engine
    ├── Builder
    ├── Matching engine
    ├── Talk controller
    ├── Transcript store
    ├── Speaking-time engine
    ├── Moderation engine
    ├── Agent runtime
    ├── Synthesis
    ├── Integration adapters
    └── Audit/provenance
```

Do not fork or modify Nextcloud core.

Where modifications to an existing Nextcloud app are needed, minimize the patch and keep a clean integration boundary.

---

# 2. Portability Requirement

Do not tightly couple the Democracy Routes core logic to Nextcloud.

Implement adapters.

The conceptual architecture should be:

```text
                 Democracy Routes Core
                         │
             ┌───────────┼───────────┐
             │           │           │
           Routes      Matching    Agents
             │           │           │
             └───────────┼───────────┘
                         │
                Infrastructure API
                         │
              ┌──────────┴──────────┐
              │                     │
       Nextcloud Adapter      Standalone Adapter
              │                     │
          Talk, Files         future LiveKit/
          Users, etc.         mediasoup implementation
```

The core workflow engine must therefore call interfaces such as:

```text
createMeeting()
createBreakoutRooms()
assignParticipants()
startBreakouts()
stopBreakouts()
muteParticipant()
unmuteParticipant()
sendMessage()
getParticipants()
storeArtifact()
```

The Nextcloud implementation of these methods should use Talk/Nextcloud APIs.

This allows Democracy Routes to remain usable outside Nextcloud later.

---

# 3. Technology Choices

Preferred backend:

* Python
* FastAPI
* Pydantic
* SQLAlchemy or equivalent ORM
* PostgreSQL in production
* SQLite allowed for development/testing
* background workers where necessary

Frontend:

Use the currently supported Nextcloud mechanism for ExApp user interfaces.

Provide a Nextcloud navigation entry:

**Democracy Routes**

If a minimal native Nextcloud companion app is required for deeper UI integration, keep it extremely small and put application logic in the ExApp.

Do not place deliberation algorithms inside PHP.

---

# 4. Core Domain Model

Implement at least the following entities.

## RouteTemplate

Reusable definition of a deliberative process.

Fields should include approximately:

```text
id
name
description
owner
version
created_at
updated_at
visibility
modules[]
settings
```

---

## RouteRun

One execution of a RouteTemplate.

```text
id
template_id
status
started_at
finished_at
current_module_id
participants
nextcloud_context
settings
```

Statuses:

```text
draft
scheduled
running
paused
completed
cancelled
failed
```

---

## Participant

Do not duplicate the full Nextcloud user database.

Store a reference to the Nextcloud identity.

```text
participant_id
nextcloud_user_id
route_run_id
display_name
role
metadata
consent_flags
```

Metadata may include:

```text
language
expertise
stakeholder_type
availability
survey_answers
free_text_response
```

---

## ModuleDefinition

```text
id
type
name
configuration
position
```

---

## ModuleRun

Execution state of a module.

```text
id
route_run_id
module_definition_id
status
started_at
finished_at
input
output
error
```

---

## GroupAssignment

```text
route_run_id
module_run_id
group_id
participant_ids[]
strategy
metrics
created_at
```

---

## TranscriptSegment

```text
id
route_run_id
module_run_id
talk_room_id
participant_id
nextcloud_user_id
start_ms
end_ms
text
language
confidence_optional
received_at
source
```

---

## SpeakingMetric

```text
participant_id
module_run_id
speaking_ms
speaking_percentage
turn_count
longest_turn_ms
last_spoke_at
```

---

## ModerationEvent

```text
id
participant_id
module_run_id
type
severity
reason
evidence
automatic
action
created_at
reviewed_by
```

---

## AgentEvent

```text
id
agent_type
module_run_id
input_refs
output
model
provider
created_at
```

---

## Artifact

Examples:

```text
summary
proposal
consensus_map
argument_map
poll_result
reflection
external_tool_result
final_report
```

Every artifact should retain provenance.

---

# 5. Route Workflow Engine

The central component must be a deterministic workflow/state-machine engine.

Every module implements approximately:

```text
prepare()
start()
handle_event()
tick()
finish()
produce_result()
```

The engine is responsible for moving:

```text
Module 1
   ↓
Module 2
   ↓
Module 3
   ↓
...
```

It must support:

* automatic transitions
* administrator transitions
* timers
* failures
* retries
* pauses
* conditional transitions
* manual override

The engine must persist state so restarting the ExApp does not destroy an active Route.

---

# 6. Modular Builder

Recreate/preserve the Democracy Routes modular-builder concept.

Administrators must be able to create a process from ordered modules.

Initial module catalogue:

### InformationModule

Display:

* text
* documents
* video
* images
* instructions
* policy material

---

### TextInputModule

Prompt participants for free text.

Examples:

```text
What is the main problem?
What outcome would you prefer?
What did you change your mind about?
```

Responses become available to subsequent modules.

---

### SurveyModule

Structured questions.

Support:

* binary
* scale
* multiple choice
* ranked choice
* free text

---

### MatchingModule

Assign participants to groups.

Strategies described below.

---

### TalkModule

Create or use a Nextcloud Talk meeting.

Configuration:

```text
duration
group_size
breakout_mode
speaking_policy
moderation_policy
transcription
recording
facilitator_agent
```

---

### RemixModule

Reassign participants after one discussion round.

Example:

```text
Round 1:
A B C D E

Round 2:
A F G H I
```

Strategies:

```text
random
maximum-new-contacts
cross-pollination
increase-diversity
decrease-diversity
stakeholder-balance
```

---

### PauseModule

Examples:

```text
silent reflection
meditation
break
reading period
```

Configuration:

```text
duration
content
audio
video
instructions
```

---

### PollModule

Use either Democracy Routes UI or Talk's poll functionality where appropriate.

---

### SynthesisModule

Run analytical agents over previous artifacts.

Possible outputs:

```text
summary
proposals
areas_of_agreement
areas_of_disagreement
unanswered_questions
argument_map
```

---

### ExternalToolModule

Generic integration module.

Do NOT hard-code Harmonica as a fundamental system dependency.

Implement:

```text
provider
launch_url/API
payload
completion_callback
result_mapping
```

Possible providers:

```text
Harmonica
Polis
Decidim
external survey
simulation
custom API
external URL
```

---

### ConditionalModule

Example:

```text
IF consensus_score > threshold
    → final vote
ELSE
    → another deliberation round
```

---

# 7. Example Route

The platform must be able to represent:

```text
INTRODUCTION
      ↓
5 min free-text reflection
      ↓
EMBEDDING MATCHING
      ↓
20 min Talk breakout
      ↓
3 min silent reflection
      ↓
REMIX
      ↓
20 min Talk breakout
      ↓
AI SYNTHESIS
      ↓
5 min text reflection
      ↓
POLL
      ↓
FINAL REPORT
```

Example serialized definition:

```json
{
  "name": "Urban Mobility Deliberation",
  "modules": [
    {
      "type": "text_input",
      "duration": 300,
      "prompt": "What is the most important mobility problem?"
    },
    {
      "type": "matching",
      "strategy": "diverse",
      "group_size": 5
    },
    {
      "type": "talk",
      "duration": 1200,
      "transcription": true,
      "speaking_policy": "balanced"
    },
    {
      "type": "pause",
      "duration": 180
    },
    {
      "type": "remix",
      "strategy": "maximum-new-contacts"
    },
    {
      "type": "talk",
      "duration": 1200,
      "transcription": true
    },
    {
      "type": "synthesis",
      "outputs": [
        "proposals",
        "agreements",
        "disagreements"
      ]
    },
    {
      "type": "text_input",
      "prompt": "Did anything change your position?"
    }
  ]
}
```

---

# 8. Nextcloud Talk Adapter

Build a dedicated integration layer.

Example class:

```python
class TalkAdapter:
    async def create_conversation(...)
    async def list_participants(...)
    async def create_breakouts(...)
    async def assign_breakouts(...)
    async def start_breakouts(...)
    async def stop_breakouts(...)
    async def send_message(...)
    async def mute(...)
    async def unmute(...)
    async def remove_participant(...)
```

Never scatter raw Talk API calls throughout the application.

---

# 9. Breakout Rooms

Democracy Routes determines group composition.

Nextcloud Talk executes it.

Flow:

```text
participants
     ↓
DR matching engine
     ↓
GroupAssignment
     ↓
Talk API
     ↓
breakout attendee mapping
     ↓
start breakout phase
```

The engine must support subsequent rematching.

Example:

```text
Round 1
20 groups × 5

↓ stop

Remix algorithm

↓ assign

Round 2
20 new groups × 5
```

If Talk has a maximum number of breakout rooms per parent conversation, create multiple parent conversations automatically when required.

The Route engine should hide this infrastructure detail from the administrator.

---

# 10. Transcription

Use **Vosk as the default transcription engine**.

Do not require Whisper, Deepgram, OpenAI, Mistral or any external API for basic operation.

Prefer integrating with or extending the official Nextcloud Live Transcription ExApp rather than independently reimplementing its media pipeline.

Target flow:

```text
Talk participant audio stream
            ↓
Live Transcription ExApp
            ↓
Vosk
            ↓
final transcript segment
            ↓
      ┌─────┴─────┐
      ↓           ↓
live captions   Democracy Routes
```

Extend the transcription system so completed segments can also be sent to Democracy Routes.

---

# 11. Speaker Identity and Diarization

Do NOT implement acoustic diarization for normal online meetings.

For one-person-per-device Talk calls, identify the speaker using the participant/session/audio-stream identity.

Target relationship:

```text
Talk participant session
        ↓
Nextcloud user ID
        ↓
audio stream
        ↓
Vosk transcript
```

Store transcript segments as:

```json
{
  "user_id": "alice",
  "display_name": "Alice",
  "start_ms": 124300,
  "end_ms": 129800,
  "text": "I think public transport should be free."
}
```

Maintain:

* meeting-relative timestamps
* server timestamps
* participant identity
* Talk room ID
* Route/Module IDs

Only consider acoustic diarization as a later optional feature for shared physical microphones.

---

# 12. Speaking-Time Engine

Speaking time MUST be calculated from audio activity / participant media state.

Do not calculate speaking time from transcript word counts.

Keep transcription and speaking-time measurement independent.

Architecture:

```text
audio stream
    │
    ├────────────→ voice activity
    │                  ↓
    │            speaking metrics
    │
    └────────────→ Vosk
                       ↓
                   transcript
```

Maintain per participant:

```text
total_speaking_time
percentage_of_group_time
turn_count
current_turn_duration
longest_turn
last_turn
```

---

# 13. Speaking Policies

Support configurable speaking policies.

## Soft balanced

Example:

```text
>30% of total speaking time
→ facilitator message

>40%
→ stronger warning
```

---

## Timed turns

Example:

```text
90 seconds per participant
```

At limit:

```text
warning
↓
grace period
↓
remove audio publishing permission
```

Later restore permission.

---

## Queue mode

Only the active participant receives permission to publish audio.

Example:

```text
Alice AUDIO ON
others AUDIO OFF

90 sec

Alice OFF
Bob ON
```

---

# 14. Facilitator Bot

Create a Democracy Routes Talk bot.

Example messages:

```text
"Ten minutes remain."

"Alice has used 34% of the group's speaking time."

"Marco, please finish your current point."

"Fatima has not spoken yet. Would you like to contribute?"

"Three proposals have appeared repeatedly."

"Two minutes remain. Try to identify one area of agreement."

"This round has ended. You will now be rematched."
```

Separate:

```text
bot = communication interface
workflow engine = authority
```

The bot must never contain the authoritative workflow state.

---

# 15. Semantic Moderation

Feed completed transcript segments to a moderation service.

Architecture:

```text
Vosk transcript
      ↓
moderation classifier
      ↓
policy engine
      ↓
possible intervention
```

Classify things such as:

```text
personal_attack
threat
harassment
hate
spam
repeated_interruption
off_topic
```

Do NOT equate political disagreement or strong criticism with abuse.

Possible interventions:

```text
none
private warning
public facilitator reminder
temporary mute
human moderator escalation
remove
ban
```

Safety policy:

* automatic reminders are acceptable
* automatic temporary interventions can be configurable
* permanent bans/removals based primarily on semantic AI classification should require human review by default

All decisions must be logged.

---

# 16. Agent Runtime

Build an agent service independent of any one LLM provider.

Interface:

```python
class AgentProvider:
    async def generate(...)
```

Adapters could include:

```text
local model
OpenAI-compatible endpoint
Mistral
Anthropic
other provider
```

No provider should be mandatory.

The default platform should remain functional without an LLM.

Possible agents:

### FacilitatorAgent

Detect:

* unanswered questions
* unrepresented perspectives
* discussion stagnation
* imbalance

---

### SynthesisAgent

Produce:

```text
summary
proposals
agreements
disagreements
open_questions
```

---

### ArgumentAgent

Produce structured:

```text
claim
supporting_argument
counter_argument
evidence
speaker_refs
transcript_refs
```

---

### ModerationAgent

Semantic classification only.

---

# 17. Provenance

This is essential.

Never produce an AI-generated civic conclusion without retaining the source information.

Example:

```text
Proposal P4
"Increase weekend buses."

derived from:
TranscriptSegment 84
TranscriptSegment 101
TextResponse 24
```

Every AI artifact should retain:

```text
source_ids
agent/model
prompt/version
timestamp
human_edits
```

The system should allow a user to trace:

```text
final result
    ↓
summary statement
    ↓
source transcript
    ↓
participant utterance
```

---

# 18. Matching Engine

Do NOT use an LLM directly to decide who belongs in which group.

Use explicit algorithms.

Borrow conceptually from Frankly Match.

Frankly's current text matcher uses:

```text
free text
   ↓
embeddings
   ↓
normalized vectors
   ↓
cosine geometry
   ↓
group optimization
```

Implement a local embedding provider abstraction.

Default should support running a multilingual embedding model locally.

Optional external embedding endpoints may also be configured.

Interface:

```python
class EmbeddingProvider:
    async def embed(texts: list[str]) -> list[list[float]]
```

---

# 19. Matching Strategies

Support:

```text
random
similar
diverse
maximum_diversity
stakeholder_balanced
expertise_balanced
cross_pollination
maximum_new_contacts
hybrid
```

Constraints may include:

```text
group_size
language
stakeholder category
expertise
availability
conflict_of_interest
previous encounters
accessibility requirements
```

Example objective:

```text
viewpoint diversity        0.35
expertise diversity        0.20
stakeholder balance        0.20
new-contact exposure       0.15
demographic constraints    0.10
```

Do not embed protected attributes unless there is a legally and ethically justified process requirement.

---

# 20. Explainable Matching

Every assignment should optionally expose diagnostics.

Example:

```text
Group A

Viewpoint diversity:      0.81
Expertise diversity:      0.68
Stakeholder balance:      satisfied
Language constraint:      satisfied
Previous-contact penalty: 0.07
```

The system should be capable of answering:

**Why were these people grouped together?**

Do not answer:

**Because the AI chose them.**

---

# 21. Modular Rematching

Track historical encounters.

Example matrix:

```text
Alice ↔ Bob      met 1 time
Alice ↔ Carla    met 0 times
Alice ↔ Marco    met 2 times
```

A remix strategy can optimize for:

```text
maximum_new_contacts
+
viewpoint_diversity
```

This allows processes such as:

```text
homogeneous groups
        ↓
discussion
        ↓
heterogeneous groups
        ↓
discussion
        ↓
cross-group synthesis
```

---

# 22. Administration UI

Inside Nextcloud provide:

## Routes

List:

```text
Templates
Active Routes
Scheduled
Completed
```

---

## Builder

Provide ordered modules.

First implementation can be list-based.

Later add drag-and-drop.

Example:

```text
1 Intro
2 Text question
3 Matching
4 Talk — 20 min
5 Reflection — 3 min
6 Remix
7 Talk — 20 min
8 Synthesis
9 Poll
```

---

## Live Moderator Dashboard

Display:

```text
active module
time remaining
groups
participants
speaking percentages
moderation alerts
agent alerts
transcription status
```

Example:

```text
GROUP 3

Alice       31%
Marco       28%
Fatima      17%
Sara        14%
Luca        10%

[Warn Alice]
[Mute]
[Message room]
[Extend round]
[End round]
```

---

# 23. Participant UI

Participants should normally remain inside one Democracy Routes flow rather than manually navigating between systems.

Screen should change according to current module.

Examples:

```text
INFORMATION
↓
TEXT RESPONSE
↓
WAITING FOR GROUP
↓
TALK
↓
REFLECTION
↓
NEW GROUP
↓
TALK
↓
POLL
```

The user should not need to understand that Talk rooms are being created behind the scenes.

---

# 24. External Tools

Implement a generic connector interface.

Example:

```python
class ExternalModuleProvider:
    async def create_session(...)
    async def get_launch_url(...)
    async def receive_callback(...)
    async def retrieve_result(...)
```

Possible adapters:

```text
Harmonica
Polis
Decidim
custom REST API
external questionnaire
```

A Route may therefore be:

```text
Talk
↓
Harmonica
↓
reflection
↓
Talk
↓
Polis
↓
final synthesis
```

---

# 25. Federation

Do not make federation a blocker for MVP.

Keep two concepts separate.

## Nextcloud federation

Use for:

```text
identity
institutional collaboration
federated Talk conversations
```

## ActivityPub

Use Democracy Routes ActivityPub support for public civic objects where appropriate:

```text
public Route
proposal
community update
public result
consultation announcement
```

Never federate automatically:

```text
private transcript
recording
participant identities
private AI analyses
moderation records
```

---

# 26. Privacy

The default architecture should be privacy-first.

Default:

```text
video → Nextcloud infrastructure
speech → local Vosk
transcript → local Democracy Routes
embeddings → local model
database → organization infrastructure
```

External AI providers must be optional.

Before sending text externally, require explicit administrator configuration and display which provider receives the data.

---

# 27. Consent

Before entering a transcribed deliberation, participants must be informed of:

```text
transcription
AI analysis
speaking-time measurement
moderation policy
recording, if enabled
data retention
```

Store consent state.

---

# 28. Audit Log

Record important workflow actions.

Examples:

```text
route_started
module_started
participant_grouped
breakout_started
participant_warned
participant_muted
agent_intervention
module_finished
route_finished
```

Moderation events must contain the rule that triggered them.

Example:

```json
{
  "participant": "alice",
  "action": "temporary_mute",
  "rule": "maximum_speaking_share",
  "threshold": 0.40,
  "observed": 0.47
}
```

---

# 29. APIs

Implement internal endpoints approximately like:

```text
POST   /routes
GET    /routes/{id}
POST   /routes/{id}/start
POST   /routes/{id}/pause
POST   /routes/{id}/advance

POST   /modules/{id}/start
POST   /modules/{id}/finish

POST   /matching/run

POST   /transcript/segment
GET    /transcript/{module_id}

POST   /speaking/activity
GET    /speaking/{module_id}

POST   /moderation/evaluate
POST   /moderation/action

POST   /agents/run

POST   /integrations/talk/events
POST   /integrations/external/callback
```

The exact external API should be versioned.

Example:

```text
/api/v1/
```

---

# 30. Event Architecture

Prefer event-driven integration.

Examples:

```text
participant_joined
participant_left
speech_started
speech_stopped
transcript_finalized
timer_expired
module_completed
moderation_triggered
```

The workflow engine consumes events and decides what happens next.

Avoid polling where a Talk/Nextcloud event mechanism exists.

---

# 31. First MVP

Do NOT implement the entire vision at once.

MVP objective:

Run one complete deliberation with 30 Nextcloud users.

Workflow:

```text
Free-text answer
      ↓
local embeddings
      ↓
6 groups of 5
      ↓
Talk breakout
      ↓
10 minutes
      ↓
Vosk transcription
      ↓
speaking-time tracking
      ↓
facilitator bot
      ↓
remix
      ↓
10-minute breakout
      ↓
final text reflection
      ↓
summary
```

---

# 32. Development Phases

## Phase 0 — Repository audit

Before coding:

1. inspect existing Democracy Routes repository
2. identify reusable modules
3. identify code tied specifically to current video/auth infrastructure
4. preserve useful matching, builder, thinker and federation logic
5. produce a short migration map

Do not rewrite functional components unnecessarily.

---

## Phase 1 — Nextcloud ExApp skeleton

Acceptance:

* ExApp installs successfully
* Nextcloud navigation entry appears
* authenticated Nextcloud user identity is available
* health endpoint works
* database migrations work

---

## Phase 2 — Talk integration

Acceptance:

* create Talk conversation
* retrieve participants
* create breakout rooms
* manually assign participants
* start breakouts
* stop breakouts
* send facilitator messages
* mute/unmute participant through supported Talk permissions

---

## Phase 3 — Persistent Vosk transcript

Acceptance:

* live Talk speech continues to produce captions
* final transcript segments are also sent to Democracy Routes
* speaker identity corresponds to Talk participant
* timestamp is stored
* complete transcript can be reconstructed

No acoustic diarization should be necessary.

---

## Phase 4 — Speaking-time engine

Acceptance:

* speaking start/stop is detected
* cumulative speaking time is correct
* participant percentages are shown
* configurable warning thresholds work
* moderator can temporarily revoke and restore audio permission

---

## Phase 5 — Matching

Acceptance:

* collect free-text response
* create local embeddings
* calculate cosine similarity
* create groups
* support random/similar/diverse
* expose matching diagnostics
* send assignments to Talk breakout rooms

---

## Phase 6 — Remix

Acceptance:

* close first breakout round
* compute second assignments
* avoid previous pairings where requested
* reconfigure groups
* start second round

---

## Phase 7 — Builder

Acceptance:

Administrator can build:

```text
text
→ matching
→ Talk
→ pause
→ remix
→ Talk
→ synthesis
→ text
```

and execute it without manually operating the underlying services.

---

## Phase 8 — Agents

Acceptance:

* facilitator receives transcript stream
* sends useful Talk messages
* synthesis produces structured output
* source transcript IDs are retained
* external LLM is optional

---

## Phase 9 — Semantic moderation

Acceptance:

* classifier can flag possible abuse
* low-level warnings can be automatic
* moderator dashboard displays evidence
* serious sanctions require confirmation by default

---

## Phase 10 — External modules/federation

Only after the core process is reliable.

---

# 33. Testing Requirements

Create:

* unit tests
* integration tests
* workflow-state tests
* Talk-adapter mocks
* transcription fixtures
* matching tests
* moderation-policy tests

Important tests:

```text
ExApp restart during meeting
Talk API unavailable
transcription unavailable
LLM unavailable
participant disconnect
participant reconnect
group assignment failure
timer fires twice
module manually advanced
moderation false positive
```

Core deliberation should continue wherever possible even if AI services fail.

---

# 34. Failure Philosophy

The system must degrade gracefully.

If:

```text
LLM fails
```

meeting continues.

If:

```text
embedding service fails
```

fallback to deterministic/random matching.

If:

```text
transcription fails
```

video discussion continues but AI features are disabled and administrator is alerted.

If:

```text
facilitator bot fails
```

Talk discussion continues.

AI must never be a single point of failure for participation.

---

# 35. Observability

Expose:

```text
/health
/ready
/metrics
```

Log:

```text
route ID
module ID
room ID
event
duration
errors
```

Do not log raw transcripts unnecessarily.

Provide configurable retention.

---

# 36. Code Quality

Requirements:

* typed interfaces
* modular architecture
* minimal coupling
* comments for non-obvious algorithms
* migrations
* no secrets committed
* `.env.example`
* Dockerfile
* local development Compose setup
* API documentation
* architectural documentation
* tests in CI

---

# 37. Licensing

Before copying code from:

* Democracy Routes
* Frankly Match
* Nextcloud
* Nextcloud Live Transcription

verify license compatibility.

Frankly Match should primarily be used as algorithmic/research inspiration unless direct reuse is confirmed compatible.

Keep attribution where legally required.

---

# 38. Product Principle

Do not build:

> "a video conference with an AI chatbot."

Build:

> **a programmable democratic-process engine using Nextcloud as its institutional collaboration infrastructure.**

The central innovation is the process definition:

```text
who meets whom
when they meet
what information they see
how long they speak
how groups change
how arguments are captured
when AI assists
how results are produced
how decisions remain traceable
```

---

# 39. Non-Negotiable Architectural Principles

1. Do not rebuild video conferencing.
2. Use Nextcloud Talk.
3. Use Vosk locally as the default transcription system.
4. Associate transcript speaker identity with Talk streams/sessions rather than acoustic diarization.
5. Calculate speaking time from media activity, not transcript word counts.
6. Use embeddings + deterministic optimization for participant matching.
7. Do not delegate group assignment directly to an LLM.
8. Make AI providers optional and replaceable.
9. Keep the Route engine independent of Nextcloud through adapters.
10. Preserve a standalone deployment path for the future.
11. Make every consequential automated action auditable.
12. Keep human control over serious moderation sanctions.
13. Preserve provenance between generated conclusions and original participant contributions.
14. Design every deliberative activity as a composable module.
15. Make workflows resumable after restart/failure.

---

# 40. Initial Deliverable Requested From Coding Agent

Do not immediately implement everything.

First produce:

### A. Repository assessment

Explain what current Democracy Routes components can be reused.

### B. Architecture proposal

Show:

```text
Nextcloud
Talk
Live Transcription
DR ExApp
database
workers
agents
matching
```

### C. Integration matrix

For each required feature classify:

```text
already provided by Nextcloud
provided by Talk
provided by Live Transcription
reuse from Democracy Routes
new code required
```

### D. Data model

Provide database schema/migrations.

### E. Talk API integration plan

Identify exact currently supported API endpoints/capabilities required for:

```text
rooms
breakouts
assignments
participants
messages
mute/permissions
remove/ban
```

Verify these against the installed Nextcloud/Talk version before implementing.

### F. Transcription integration plan

Inspect the current Nextcloud Live Transcription source.

Identify exactly where:

```text
participant identity
audio stream
Vosk final transcript
```

meet.

Propose the smallest upstream-compatible change needed to emit structured transcript segments to Democracy Routes.

### G. MVP implementation plan

Only after A–F are complete, start Phase 1.

---

# 41. Final Target

The finished system should allow an administrator to create a Route such as:

```text
100 citizens

↓
read background material

↓
answer one free-text question

↓
embedding-based diverse matching

↓
20-minute Talk breakout discussion

↓
AI + deterministic speaking-time facilitation

↓
three-minute silent reflection

↓
remix participants

↓
20-minute second discussion

↓
individual written reflection

↓
AI synthesis with traceable citations to transcript contributions

↓
poll or decision

↓
public or private final report
```

The infrastructure should remain locally hostable and usable without commercial AI, transcription, video, or database services.

That is the target architecture.
