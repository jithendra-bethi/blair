# Windows morning acceptance checklist

This is the release proof for BLAIR v0.1. Record the date, Windows build, Python
version, Claude Code version, Codex version, audio device, and tester initials.

Do not mark a live adapter supported from fixture tests alone.

## Evidence already recorded on 2026-08-30

- A live Codex `agent-turn-complete` test produced exactly one WAV.
- A live Claude `Stop` test using the synchronous fail-open enqueue hook produced
  exactly one WAV. The earlier async print-mode approach was rejected as
  unreliable.

Record the exact provider versions and repeat both checks on the release artifact
before turning the corresponding checkboxes below into release claims.

## 1. Clean local test home

```powershell
$env:BLAIR_HOME = Join-Path $PWD '.acceptance-home'
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

- [ ] Installation succeeds with Python 3.11–3.13 and no administrator rights.
- [ ] `blair --version` reports 0.1.0.
- [ ] `blair doctor` identifies a writable home and Windows SAPI.
- [ ] No microphone permission dialog appears.

## 2. Automated gates

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m build
```

- [ ] The complete test suite passes.
- [ ] Ruff passes with no ignored release-blocking result.
- [ ] Wheel and source archive build successfully.
- [ ] Integration tests prove install → idempotent reinstall → uninstall against
  temporary Codex and Claude config files.
- [ ] An existing Codex notify command is never overwritten.
- [ ] Malformed hooks return success to the provider and log no response content.
- [ ] Duplicate and superseded events produce at most one current briefing.
- [ ] Success, zero-failure, partial, blocked, table, code, path, URL, long-ID, and
  synthetic-secret fixtures pass their content invariants.

## 3. Windows SAPI vertical slice

```powershell
.\.venv\Scripts\blair.exe setup --skip-models
.\.venv\Scripts\blair.exe config set backend windows
.\.venv\Scripts\blair.exe demo --wait
.\.venv\Scripts\blair.exe brief --file tests\fixtures\dense_result.md --session acceptance-sapi --provider generic --wait
```

- [ ] The demo speaks through the default Windows output device.
- [ ] Output reports backend `windows-sapi` and a selected installed voice.
- [ ] The dense fixture is under the configured word limit.
- [ ] It does not read the code block, table cells, fake token, URL, or path.
- [ ] It mentions that dense details are on screen.
- [ ] `blair replay --session acceptance-sapi` replays the same briefing.
- [ ] `blair stop` interrupts a long replay within one second.
- [ ] `off` stops current speech and the next non-explicit event remains silent.

## 4. Preferred Kokoro voice

Only run this section after approving the approximately 354 MB download:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,kokoro]"
.\.venv\Scripts\blair.exe setup
.\.venv\Scripts\blair.exe config set backend auto
.\.venv\Scripts\blair.exe doctor
.\.venv\Scripts\blair.exe demo --wait
```

- [ ] Both assets download once, match expected sizes and SHA-256 hashes, and are
  reused on the second setup.
- [ ] `doctor` reports `kokoro_package: True` and `kokoro_models: True`.
- [ ] Demo output reports backend `kokoro-onnx` and voice `bf_emma`.
- [ ] Disconnecting network after setup does not affect demo synthesis.
- [ ] Forcing `backend=windows` still provides the immediate fallback.

## 5. Session controls and hotkeys

```powershell
.\.venv\Scripts\blair.exe daemon start
.\.venv\Scripts\blair.exe daemon status
```

- [ ] A previously unseen hook session asks once and defaults silent on No/close.
- [ ] Yes persists for later turns with the same provider session ID.
- [ ] A new `blair run --briefings off` launch overrides an earlier stored On
  state once, and a later manual On remains active for that launch.
- [ ] `on`, `off`, `toggle`, `status`, and `replay` affect the requested session.
- [ ] Two fixture sessions retain independent consent and replay state.
- [ ] `Ctrl+Alt+B` mutes/unmutes all speech, regardless of which chat is active.
- [ ] Each toggle says "Blair muted" or "Blair unmuted" in the configured voice.
- [ ] Rapid toggles and Stop cancel stale confirmation audio; confirmations do
  not change session permissions or replace the last briefing in replay history.
- [ ] Global mute stops current audio and blocks completions, manual speech, and replay.
- [ ] Unmuting preserves each session's consent and works without restarting a chat.
- [ ] Global mute persists across daemon restarts and appears in `blair status`.
- [ ] `Ctrl+Alt+R` replays the most recently active session's briefing when unmuted.
- [ ] `Ctrl+Alt+S` stops speech without disabling later briefings.
- [ ] A conflicting Windows binding leaves CLI controls operational.
- [ ] New completion replaces stale queued/speaking output rather than creating an
  audio backlog.

## 6. Real Codex CLI

Use a profile whose configuration has been backed up and record the Codex version:

```powershell
.\.venv\Scripts\blair.exe install codex
.\.venv\Scripts\blair.exe doctor
.\.venv\Scripts\blair.exe run codex
```

- [ ] The installer prints a backup and preserves unrelated TOML byte-for-byte on
  round trip.
- [ ] Answering No produces no speech after a real completed turn.
- [ ] A new session answered Yes produces exactly one briefing per real
  `agent-turn-complete` event.
- [ ] A response with a table/code block receives a screen-detail cue.
- [ ] A reported failed check is spoken as failed, never complete.
- [ ] `blair off --session ID`, then a new turn, remains silent.
- [ ] `blair on --session ID`, then a new turn, speaks again.
- [ ] Agent behavior and exit status remain normal with the BLAIR service stopped
  or a malformed synthetic hook event delivered.

## 7. Real Claude Code

Use a profile whose settings have been backed up and record the Claude Code
version:

```powershell
.\.venv\Scripts\blair.exe install claude
.\.venv\Scripts\blair.exe doctor
.\.venv\Scripts\blair.exe run claude
```

- [ ] Existing hooks and settings are retained.
- [ ] No produces no speech; Yes produces one briefing for a real `Stop` event.
- [ ] A real or synthetic `StopFailure` is described as needing attention.
- [ ] Pending background work is described as partial, not complete.
- [ ] Code/table/failure and on/off/replay checks match the Codex section.
- [ ] Hook timeout or BLAIR failure never changes Claude's result.

## 8. Privacy and local-data inspection

- [ ] Routine SAPI and cached Kokoro use succeeds with network disabled.
- [ ] No process opens a microphone capture device and no microphone permission is
  requested.
- [ ] `%LOCALAPPDATA%\BLAIR` contents match [PRIVACY.md](../PRIVACY.md).
- [ ] Operational logs contain no full assistant response or briefing text.
- [ ] Audio pruning keeps no more than the configured rolling count.
- [ ] WAVs contain only the composed briefing, not raw terminal output.
- [ ] The README's removal sequence stops the service, removes only BLAIR-managed
  hooks, uninstalls the package, and leaves data until separately deleted.

## 9. Documentation smoke test

- [ ] Every command in the release-bundle quick start works when copied verbatim from a
  fresh checkout path containing spaces.
- [ ] Win+H is described only as separate Windows dictation.
- [ ] README, privacy, controls, retention, and uninstall behavior match the CLI.
- [ ] Known limitations name the exact platforms and provider versions tested.
- [ ] Apache-2.0 license and build metadata agree.

## Release decision

Release only when all automated gates, SAPI vertical slice, session safety, and
privacy checks pass. Claim an adapter as supported only after its real section
passes on the recorded version. If one live adapter cannot be tested tonight,
label it experimental instead of treating a fixture pass as end-to-end proof.

The following are explicitly deferred and must not be implied by v0.1:

- signed installer and SmartScreen reputation;
- clean-machine coverage beyond the recorded Windows system;
- Windows 10, ARM64, WSL, SSH, macOS, and Linux;
- every SAPI voice/audio device and every Claude/Codex version;
- screen-reader compatibility and real-user comprehension studies;
- long-running multi-session reliability and willingness-to-pay validation.
