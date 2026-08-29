# Changelog

All notable user-visible changes are recorded here. BLAIR follows Semantic
Versioning while the public interfaces stabilize.

## 0.1.0 — 2026-08-30

Initial Windows-first alpha release.

- Concise deterministic briefings with outcome, verification, blockers, and
  screen-detail cues; no summarization API or per-turn model cost.
- Local Kokoro `bf_emma` neural speech with verified model downloads and a
  persistent isolated helper, plus Microsoft Hazel/SAPI fallback.
- Per-session consent, on/off/toggle, replay, stop, and configurable global
  hotkeys.
- Fail-open Codex CLI `notify` and Claude Code `Stop`/`StopFailure` integrations,
  with reversible configuration installers and a provider-neutral JSON hook.
- Authenticated local Windows service, bounded payloads, duplicate suppression,
  latest-result-wins playback, and a rolling local WAV cache.
- No-admin Windows bootstrap bundle, Python wheel/source archive, checksums,
  clean-install verification, privacy documentation, and CI.

Known release boundaries: Windows 11 x64 is the only tested platform; the
bootstrap requires 64-bit Python 3.11–3.13; artifacts are unsigned; and BLAIR
does not provide dictation, microphone capture, streaming narration, or voice
approval of agent actions.
