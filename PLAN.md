# BLAIR Mark I Plan

BLAIR is the **Briefing Layer for Agent Interaction Results**: a local, output-only
voice companion for terminal AI agents. It turns a completed agent response into a
short spoken report while leaving the terminal output as the source of truth.

## Product contract

- Windows-first for Mark I; architecture must remain portable to macOS.
- Codex CLI and Claude Code are first-class adapters; a generic stdin/CLI adapter
  makes the core usable with any agent.
- BLAIR never opens a microphone. Dictation remains an operating-system feature
  (`Win+H` on Windows).
- Briefing Protocol is opt-in per session. A new session asks once where the host
  integration permits, remembers the answer, and exposes explicit on/off controls.
- The user can toggle briefings, replay the last briefing, stop speech, inspect
  status, and run a demo without entering an agent session.
- The default voice is a free, local British-English female voice. Mark I uses
  Kokoro `bf_emma`, with a built-in Windows voice as an immediate fallback.
- No API key is required. Text, summaries, state, and generated audio stay local.
- Spoken output is concise: outcome, important changes, verification, blockers,
  and required user action. Code, logs, Markdown syntax, and table contents are not
  read line by line. BLAIR points the user back to the screen for dense detail.

## Architecture

1. **Adapters** normalize provider completion payloads into one `AgentResult`.
2. **Session store** records consent and the most recently active session locally.
3. **Briefing engine** extracts or deterministically composes a short result report.
4. **Speech layer** synthesizes locally, caches the last WAV, and plays/stops it.
5. **CLI and Windows host** provide commands, first-session consent, and hotkeys.

The core must remain independent of Codex/Claude config formats and of a specific
speech backend. Provider adapters and TTS engines are replaceable boundaries.

## Milestones and proof

### M0 — Repository and contract

- Python package, Apache-2.0 license, contributor-friendly layout.
- Product contract, threat/privacy notes, architecture, and acceptance matrix.
- Reproducible development and test commands.

Proof: package metadata validates and the test runner starts on Windows.

### M1 — Vertical slice

- Generic `blair brief` command accepts a realistic agent response.
- Per-session on/off/status state works.
- Briefing engine removes code/noise, reports verification and blockers, and adds
  a screen-detail cue for tables/diffs.
- Windows fallback TTS synthesizes and plays immediately.

Proof: an integration test produces a WAV and records the expected briefing text.

### M2 — Local Kokoro voice

- Idempotent model bootstrap with checksum-aware cache handling.
- Kokoro `bf_emma` is the preferred backend and Windows speech remains fallback.
- Helpful diagnostics for missing runtime/model/audio device.

Proof: real Kokoro synthesis creates a non-empty, valid WAV; playback is invoked.

### M3 — Windows session experience

- New-session consent is asked once and persisted only for that session.
- Commands: `on`, `off`, `toggle`, `status`, `replay`, `stop`, `demo`, `doctor`.
- Safe configurable global hotkeys operate on the active session.

Proof: subprocess/E2E tests cover consent, toggle, replay, stop, and state isolation.

### M4 — Agent adapters

- Codex completion notification adapter.
- Claude Code completion hook adapter.
- Generic JSON/stdin adapter and documented integration contract.
- Idempotent installers preserve unrelated user configuration and support uninstall.

Proof: recorded provider payload fixtures traverse the same end-to-end pipeline;
installer tests operate against temporary config homes and round-trip cleanly.

### M5 — Ship and morning handoff

- One-command Windows install/bootstrap and a simple launcher/demo.
- Wheel/source archive plus Windows release archive and checksums.
- README, quickstart, troubleshooting, privacy, architecture, contributing, and
  third-party notices.
- Clean-environment installation test and complete automated suite.

Proof: from a clean temporary installation, run the demo and a simulated provider
completion, synthesize audio, exercise playback, and leave an exact test checklist.

## Acceptance gates

- All unit and integration tests pass.
- No network request occurs during normal briefing after initial model setup.
- No microphone API or permission exists in the dependency/runtime path.
- A disabled or unknown session never speaks without consent.
- Adapter installation never destroys existing settings and can be undone.
- Dense terminal content is summarized and referenced, not narrated verbatim.
- BLAIR remains useful when Kokoro is unavailable through a clear local fallback.
- Release artifacts are reproducible and the morning quickstart is verified.

## Explicit non-goals for Mark I

- Speech recognition, wake words, or always-listening audio.
- Voice-only approval of shell commands or destructive agent actions.
- Actor/character voice imitation.
- Reading every token while the agent streams.
- A cloud account, hosted backend, or paid summarization dependency.

## Working loop

Implement the smallest end-to-end slice first. At each checkpoint: run focused
tests, update `PROGRESS.md`, then widen coverage. Stop only when the acceptance
gates are met or an objective external limitation is documented with a tested
fallback.
