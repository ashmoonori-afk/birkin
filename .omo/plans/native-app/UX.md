# Native Application Product and UX Specification

Status: normative user-visible behavior

## 1. Product principles

1. One Python brain, one native skin.
2. A UI state is never authorization.
3. Connection and degradation are always visible.
4. Empty states are live zero-data states, not placeholders.
5. Canonical contracts override the roadmap mockup.
6. Every action closes with an event, refusal, receipt, or explicit disconnect.
7. Keyboard, VoiceOver, IME, and high contrast are release requirements.

## 2. Information architecture

The primary window retains the roadmap mockup's three-column structure.

### Left

- Sessions
- templates
- Working Memory

### Center

- Conversation
- composer
- owned Terminal

### Right

- Approvals
- Activity
- Browser Aside
- Office
- Computer Use status and consent when active

### Chrome

- live local-private connection pill
- toolbar and menu commands
- pending approval count
- current session identity

The layout is resizable. At large accessibility sizes it becomes panel navigation rather than clipping.

## 3. Global states

Every live surface implements applicable states:

| State | Rendering |
| --- | --- |
| empty | mockup-compatible zero-data copy and one primary action |
| loading | bounded skeleton before initial snapshot |
| ready | current Python projection |
| streaming/executing | incremental content and stop controls |
| waiting | approval or consent reason and jump target |
| error | canonical bounded error and allowed recovery |
| unavailable | Python capability absent, reason shown |
| disconnected | last state dimmed, all mutation disabled |
| replaying | reconnection and cursor/surface replay progress |

No spinner may run forever. A failed initial load becomes a visible disconnected or unavailable state.

## 4. Connection status

Title-bar values:

- `LOCAL · PRIVATE`
- `CONNECTING`
- `RECONNECTING`
- `DISCONNECTED`
- `VERSION MISMATCH`
- `BACKEND UNAVAILABLE`

The status includes:

- transport: Unix socket or private loopback
- last successful event time
- bounded diagnostic action

Private-loopback fallback is visibly labeled with its reason.

## 5. Sessions and templates

### Sessions

Rows show:

- name
- active/idle/running/waiting status
- last activity
- unread completion or pending approval marker

Actions are enabled only when advertised:

- create
- select
- rename
- compact

Closing or switching never creates a native copy of conversation state.

### Templates

`Research`, `Data Analysis`, `Writing`, and `Automation` are one-shot launchers.

Each:

1. creates a normal session through Python,
2. pre-fills an editable first prompt,
3. may offer suggested Working Memory content,
4. leaves send and Working Memory mutation explicit.

Templates never alter:

- tools
- network
- auto-approval
- sandbox
- Browser profile
- Computer Use consent

### Empty state

`No active session`
`Start a new session to begin.`

The New Session action has initial keyboard focus.

## 6. Conversation

### Message stream

Render:

- user messages
- assistant deltas and completion
- tool cards
- pending approval cards
- receipts
- canonical failures
- restart-interrupted commands

Provider subprocess details and tokens never appear.

Streaming text:

- updates without stealing focus
- coalesces accessibility announcements
- preserves cursor ordering
- exposes Steer and Interrupt separately

### Composer

Features:

- multiline plain text
- code block mode with language label
- attachment references
- send
- steer during a running turn
- interrupt
- retry a canonical failed turn
- resume when Python advertises resumability

The 65,536-byte command payload limit is checked before send with a visible byte count.

Korean IME composition must prevent send shortcuts until composition ends.

### Attachments

Picker and drag/drop show:

1. import target
2. copy-in-progress state
3. Python jail refusal or receipt
4. composer attachment chip after success

The UI never sends file bytes in a workspace command and never claims an import before Python returns a jailed reference.

### Code input

Code mode is presentation only. It does not execute code. Content remains an ordinary bounded chat payload.

## 7. Working Memory

Presentation:

| Row | Content |
| --- | --- |
| Goals | active Python `GoalState`; read-only in v1 |
| Context | decisions, corrections, evidence |
| Files | checkpoint-derived workspace `files_evidence`, labeled as workspace evidence |
| Constraints | constraints |
| Notes | incomplete items and next actions |

Canonical field names appear in detail views and accessibility descriptions.

Writes:

- preview the Python-defined merge
- display revision conflict inline
- display the canonical 20,000-character render-budget error
- wait for a confirming event before changing the authoritative display

Clear:

- explains the exact session-scoped data affected
- does not clear vault memory, files, or audit
- submits the Python clear operation
- waits for the updated revision

Trust footer:

`Stored locally on this device`

It opens an explanation of Python-owned storage and native non-persistence.

## 8. Owned Terminal

The Terminal is live only when Python advertises the terminal capability.

Controls:

- `+`: request a new Python-owned terminal
- split: open another view or session through Python
- trash: request close with confirmation
- interrupt: send a Python terminal signal

Rendering:

- terminal identifier and cwd
- UTF output
- process state
- exit status
- approval-waiting state
- receipts

The terminal does not use a native Process fallback.

Reconnect:

- renders a bounded Python terminal screen snapshot
- resumes output sequence
- marks exited terminals as exited
- never resurrects a closed process

## 9. Approvals

### Pending decisions

Cards show:

- canonical category
- risk label
- title and description
- redacted payload summary
- sealed digest identity where applicable
- expiry
- approval, rejection, or answer controls

The UI waits for Python resolution.

If another surface acts first:

- transition to `Answered elsewhere`
- show the terminal canonical result
- do not display a conflict error

### Policy summary

Mockup rows are conceptual:

- File Changes: projection of canonical operation/file policy
- Command Execution: projection of shell/tool policy
- Network Access: projection of egress/network policy

Controls show:

- effective value
- requested value while pending
- canonical refusal

The UI does not locally enforce the toggle.

### Notification behavior

Notifications deep-link to the approval card. They never contain an Approve action.

## 10. Activity

Activity renders append-only Python receipts for:

- commands
- tools
- approvals
- egress
- terminal
- Browser Aside
- Computer Use
- Office
- checkpoints
- recovery

Rows link to the originating session and visible artifact.

The mockup Clear button becomes:

`Hide read`

This is an in-memory view filter. It never truncates audit and is not persisted as hidden authority state.

If Python reports an activity persistence problem, show a persistent integrity warning.

## 11. Browser Aside

The Browser panel uses the private workspace profile only.

Toolbar:

- back
- forward
- reload
- navigate
- open external, subject to canonical policy

Status:

- profile generation
- control owner kind
- lease expiry
- frame revision
- network refusal
- disconnected/recovering

Frames are redacted references. A stale generation triggers refresh, not a native cache fallback.

Personal profile import or attachment has no UI path.

## 12. Computer Use

### Status

Display never-prompt capability results for:

- Accessibility
- Screen Recording
- backend support
- current app/window binding availability

The status check itself never opens an OS prompt.

### Consent

Foreground consent cards show:

- requested action summary
- application/window identity
- prior receipt
- expiry countdown
- explicit approve and reject

Consent:

- is one-shot
- expires at the Python time
- does not survive disconnect or restart unless Python says it remains valid
- cannot be approved from a notification

Results distinguish confirmed, unverifiable, refused, cancelled, and suspected-no-op states.

## 13. Office

### New

Shows Python adapter inventory and supported formats.

Flow:

1. choose a supported format
2. choose a jailed destination
3. disclose active-content or conversion constraints
4. submit
5. show document identity and receipt

### Open

Uses Python secure open and path identity.

The UI:

- displays canonical jail refusals
- never opens an external engine itself
- shows provenance and conversion loss information
- requires canonical active-content consent

## 14. Menu bar

Displays:

- connection state
- active session
- running turn
- pending approvals
- recent completion

Actions navigate or focus. They do not authorize, execute, or change policy.

## 15. Notifications

Allowed:

- turn completed
- approval pending
- disconnected
- backend recovered
- Office operation completed

Actions deep-link only.

Notification copy is bounded and redacted.

## 16. Voice

Voice is optional and appears only when the Python feature capability and product dependency are available.

Behavior:

- push to talk
- local transcription into the composer
- visible editable text
- explicit Send

Voice never submits approvals or policy changes.

## 17. Accessibility

### VoiceOver

- panels are landmarks
- cards announce type, state, risk, and primary action
- streaming updates use polite grouped announcements
- consent countdown announces meaningful thresholds, not every second
- terminal exposes text snapshot and actions without secret input

### Keyboard

- command palette exposes all commands
- panel focus shortcuts target actual panels
- `Cmd-N`: new session
- `Cmd-Return`: send when not composing IME
- `Cmd-.`: interrupt
- `Cmd-Shift-A`: oldest pending approval
- `Escape`: dismiss non-authority overlays, never silently reject

Approval and consent actions require explicit activation.

### IME

Test Korean composition in:

- composer
- code mode
- session rename
- Working Memory edit
- Office name fields
- terminal input

### Visual accessibility

- status includes text/icon, never color only
- honors Increase Contrast
- honors Reduce Transparency and Reduce Motion
- terminal font size is independent
- layout reflows at accessibility sizes

## 18. End-to-end journeys

### J1 First answer

Launch -> connect -> create session -> send -> stream -> completion -> Activity receipt.

### J2 Research approval

Research launcher -> edit draft -> send -> tool proposes command -> approve -> exactly-once execution -> receipt -> Working Memory evidence update.

### J3 Terminal and file change

Create terminal -> run command -> observe output -> model proposes file operation -> approve sealed operation -> diff and receipt.

### J4 Browser verification

Navigate to allowed local page -> obtain private frame -> run verification -> Activity artifact.

### J5 Office document

Create jailed document -> show provenance -> open -> convert with disclosed loss -> receipt.

### J6 Computer Use consent

Read capability status -> foreground escalation -> explicit one-shot consent -> perform action -> show receipt verdict.

### J7 Restart recovery

- kill and relaunch app while Python remains
- restart Python while app remains
- restart during accepted command

Each yields visible disconnect, replay, and canonical terminal outcome without duplicate execution.

### J8 Drag/drop import

Drop -> Python jailed copy -> receipt -> composer reference -> send.

### J9 Multi-surface race

Open the same approval in native and CLI -> resolve in CLI -> native transitions to Answered elsewhere -> no duplicate execution.

## 19. Visual fidelity

Compare real screenshots with `docs/assets/birkin-native-app-roadmap.png`.

Required fidelity:

- hierarchy
- panel placement
- density
- dark material and border treatment
- empty-state clarity
- status prominence

Allowed differences:

- canonical approval categories
- accessible reflow
- additional disconnected and unavailable states
- corrected template, Activity, Terminal, and policy controls

Every intentional difference is documented with its canonical reason.
