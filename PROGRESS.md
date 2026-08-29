# BLAIR Progress Log

## 2026-08-30

- Project name fixed: **BLAIR — Briefing Layer for Agent Interaction Results**.
- Durable Codex goal created with a verifiable Windows end state.
- Workspace created at `C:\arise\blair`.
- Mark I product contract, milestones, proof commands, and acceptance gates written.
- M0/M1 complete: package, deterministic briefing engine, session controls, Windows
  SAPI synthesis/playback, and a tested generic vertical slice.
- Provider normalization complete for Codex `agent-turn-complete`, Claude `Stop`
  and `StopFailure`, and generic JSON. Payloads are bounded and hooks fail open.
- Local background service complete: authenticated named-pipe transport, event
  deduplication, latest-result-wins playback, cross-process state locking, and
  global toggle/replay/stop hotkeys.
- Safe hook installers preserve unrelated Codex TOML and Claude JSON settings,
  create backups, and round-trip cleanly in tests.
- Kokoro `bf_emma` setup uses the current `model-files-v1.1` assets with exact
  size/SHA-256 checks, a versioned cache, concurrent bootstrap lock, and explicit
  consent for the ~354 MB download. Windows speech remains the fallback.
- Real Windows evidence: SAPI and Kokoro each produced valid WAV files; both were
  played through the Windows audio path; stop/replay were exercised. The Kokoro
  artifact was mono PCM16 at 24 kHz, 7.715 seconds, RMS 0.0706.
- The optional Kokoro runtime now runs in a persistent, sanitized local helper
  process. A real daemon test measured approximately 6.6 seconds cold and 3.1
  seconds warm, with no normal-operation network path.
- Current automated gate: 98 tests passing; Ruff lint and format checks clean;
  all PowerShell release scripts parse successfully.
- Real adapter evidence: Codex CLI 0.150.1 produced exactly one WAV from a live
  `agent-turn-complete` notification; Claude Code 2.1.251 produced exactly one
  WAV from a live synchronous `Stop` hook. Claude async hooks were rejected for
  Mark I after a print-mode test returned before delivering the event; the
  shipped hook is the reliable synchronous bridge and only enqueues work.
- The final wheel passed the no-admin clean-install lifecycle from a temporary
  path containing spaces: sandboxed Codex/Claude hooks, doctor, Hazel/SAPI WAV,
  generic completion, uninstall, backup cleanup, and data cleanup.
- The same final wheel is installed at `%LOCALAPPDATA%\Programs\BLAIR` with the
  verified Kokoro models, both real hooks, and the stable `blair.cmd` launcher.
  Its production demo produced mono PCM16 at 24 kHz, 276,192 frames, 11.508
  seconds, RMS 0.0699, and 552,428 bytes.
- Final installed-provider proof: Codex 0.150.1 and Claude Code 2.1.251 each
  exited zero and produced exactly one new Kokoro WAV through the production
  hook. Playback was muted for those two overnight checks and restored afterward.
- Market/repository inspiration and cost research is recorded in
  `docs/landscape.md`; deterministic summary and local speech incur no per-turn
  API charge.
- M0–M5 implementation and release verification are complete. Personal GitHub
  publication is the remaining handoff action.
