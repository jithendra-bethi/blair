# Architecture and data flow

BLAIR is a small local event pipeline. Agent-specific code ends at the adapter;
briefing composition, consent, speech, playback, and controls are provider-neutral.

```mermaid
flowchart LR
    A[Claude Code Stop hook<br/>or Codex notify] --> B[Provider adapter]
    B --> C[Authenticated local pipe]
    C --> D[Background service]
    D --> E[Session consent store]
    D --> F[Deterministic briefing composer]
    F --> G{Local TTS}
    G -->|preferred| H[Persistent local Kokoro helper<br/>bf_emma]
    G -->|fallback| I[Windows SAPI]
    H --> J[Rolling WAV cache]
    I --> J
    J --> K[Interruptible playback]
    L[CLI and global hotkeys] --> E
    L --> K
```

No microphone or speech-recognition component exists in this graph. Win+H, when
used, belongs to Windows and is outside BLAIR.

## Component boundaries

### Provider adapters

Adapters validate a bounded provider payload and produce a `NormalizedEvent` with
an event ID, provider, provider session ID, final assistant text, event name,
working directory, and limited metadata.

- Codex accepts only `agent-turn-complete` notifications and uses the stable
  `thread-id` plus `turn-id` as its event identity.
- Claude accepts `Stop` and `StopFailure`. A Stop event supplies the final
  assistant message; a failure event is normalized into an explicit failure.
- The generic adapter exists for fixtures and future integrations.

Unsupported or malformed events are recorded as content-light diagnostics and the
hook returns success. BLAIR must never break the parent agent.

### Hook entry point and local service

The provider hook parses its payload, connects to an authenticated local IPC
endpoint, and enqueues the event synchronously. It waits only for local queue
acceptance, never for synthesis or playback. If the service is absent, the hook
starts it and retries briefly. Every exception is caught so the provider still
receives a successful hook exit.

On Windows the endpoint is a named pipe derived from the resolved BLAIR home. A
random 32-byte authentication key is stored in the runtime directory. The service
serializes synthesis and playback so two completions do not talk over each other.

Runtime status reads, publication, and cleanup share `runtime/daemon-state.lock`.
This prevents Windows file-sharing errors when shutdown overlaps a status check.
Each service publishes a random instance ID and removes only its own record,
preserving a replacement service's record even if the PID is reused. A status read
failure is reported as an error; it does not delete a potentially live record.

Duplicate event IDs and identical provider/session/text events within the
deduplication window are rejected before touching audio or the pending queue.
Globally muted events are dropped before session processing. When globally unmuted,
new launch-scoped consent is applied before checking session permission; a completion
from a muted session is also rejected without interrupting another briefing.

The queue remains **latest-wins** for admitted events: the newer event replaces
an older pending completion. An enabled session also stops current playback on
arrival. An unknown session does not stop audio on arrival; its consent prompt
runs in the worker, and playback starts only after permission is granted.

### Session and consent state

`sessions.json` is an atomic, lock-protected store. Each provider session records
its provider, working directory, tri-state consent, last briefing, and last WAV
path. Session commands and replay can target an exact session; without an ID they
target the most recently active one. `Ctrl+Alt+B` and the `mute`/`unmute` commands
instead control the persistent global `speech_muted` flag in the same store
(absent in older files means unmuted). They preserve all session permissions.

Global mute cancels the current playback token and blocks admission, composition,
and playback, including manual speech and replay. The playback controller checks
the flag again under its playback lock, covering a mute during synthesis. Muting
holds that same lock while updating the flag and cancelling the current token;
lock ordering is playback then sessions. Unmuting allows new speech without
automatically replaying events dropped while muted.

The toggle hotkey reserves a cancellable playback token for one fixed control
phrase: "Blair muted" or "Blair unmuted". This control worker alone bypasses the
global mute gate, so the mute confirmation can be heard after briefing playback
stops. It synthesizes/caches the phrase in the configured voice outside briefing
history. Token checks before and after synthesis discard stale confirmations;
new toggles, CLI unmute, and Stop cancel pending control audio. Synthesis runs in
the hidden worker, keeping the hotkey message loop responsive.

Consent can come from the `blair run` terminal question or, for an unseen session
whose hook fires outside the wrapper, a Windows Yes/No dialog. Each wrapper process
has a random launch ID: its selection is applied once on the first completion and
manual toggles then persist. A declined session is normalized but does not proceed
to briefing composition or TTS.

### Deterministic composer

The composer performs no model call. It:

1. removes ANSI sequences, Markdown noise, code blocks, diffs, and table rows;
2. replaces common secrets, URLs, paths, and long identifiers;
3. classifies the response as success, partial, blocked, or neutral;
4. scores existing sentences for outcomes, changes, verification, and attention;
5. adds a screen-detail cue for omitted code or tables;
6. applies the configured word limit.

An optional `<blair_brief>...</blair_brief>` region can supply a concise source,
but it still passes through cleaning and redaction. The composer does not invent
test results or use agent text as executable control input.

### Speech and playback

Backend selection in `auto` mode is:

1. verified Kokoro model plus installed optional `kokoro-onnx` dependencies;
2. built-in Windows SAPI;
3. a clear error if neither local backend is available.

Kokoro defaults to `bf_emma`, `en-gb`, and speed `1.03`. SAPI selects an installed
English (United Kingdom) female voice where available, otherwise its default.
Both backends write a WAV before playback. Playback runs in a child process so
`blair stop` and the stop hotkey can interrupt it.

Each playback receives a random token in `playback.json`. Stop cancels the token;
it never terminates a PID read from that file. Workers check ownership every
25 milliseconds during playback. On Windows, cancellation exits only the dedicated
sound worker itself. On macOS/Linux, the worker stops its own child audio player.
Playback startup, cancellation, and cleanup share a file lock. A finishing worker
removes the record only if it still contains that worker's token, so it cannot
erase a newer playback. The stored PID is informational.

The main service never imports the optional neural runtime. It sends one job at a
time over a private JSON-lines pipe to a persistent child process launched with
the same local Python interpreter. The child removes caller-controlled native
library/provider environment overrides, loads the verified local model once, and
atomically encodes mono PCM16 WAV files using NumPy and Python's standard `wave`
module. It contains no download or network code. If the pipe fails, BLAIR replaces
the child and retries once; synthesis errors remain local and never fail an agent
hook. Keeping the worker warm avoids reloading the 326 MB model after every turn.

Kokoro's phonemizer stack has separate license obligations and is never included
in BLAIR's Apache-2.0 core artifact. See
[third-party-licenses.md](third-party-licenses.md).

## Persistence

The default data root is `%LOCALAPPDATA%\BLAIR`:

```text
BLAIR/
├── config.json
├── sessions.json
├── playback.json              # present only around playback
├── audio/                     # rolling WAV cache
├── models/kokoro/             # optional verified model cache
├── logs/blair.log             # operational metadata/errors
└── runtime/                   # daemon metadata, locks, key, hashes
```

See [PRIVACY.md](../PRIVACY.md) for exact fields and deletion instructions.

## Integration changes

`blair install` is an explicit, reversible operation:

- Codex receives one marked top-level `notify` block. Installation refuses if an
  unrelated notify command already exists.
- Claude receives BLAIR hook groups appended to `Stop` and `StopFailure`; unrelated
  hooks and settings remain intact.
- Existing files receive timestamped backups before an atomic write.
- `blair uninstall` removes only BLAIR-managed entries and creates another backup.

Implementation details and conflict handling are in
[integrations.md](integrations.md).

## Failure model

- Provider hook: catch all errors, record a diagnostic, return zero.
- Service: reject malformed events and continue listening.
- Queue: newest completion supersedes stale speech.
- TTS: report locally; never alter the provider's completed turn.
- Installer: validate first, back up, write atomically, or make no change.
- Playback: isolate sound output in an interruptible child process.

The terminal output is always authoritative. A briefing is an attention aid, not
an approval or validation channel.
