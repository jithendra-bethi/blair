# Tested environment and evidence

Evidence below was collected on 2026-08-30. It describes one development machine,
not a universal compatibility claim.

| Component | Tested value |
| --- | --- |
| Windows | Windows 11 Pro x64, version 10.0.26200, build 26200 |
| CPU | 11th Gen Intel Core i7-1165G7 |
| Python | CPython 3.13.5 x64 |
| Codex CLI | 0.150.1 |
| Claude Code | 2.1.251 |
| Windows voice | Microsoft Hazel Desktop, en-GB, female |
| Neural voice | Kokoro ONNX 0.6.1, `bf_emma`, `model-files-v1.1` FP32 |
| Audio | Realtek High Definition Audio (SST) reported healthy |

## Verified outcomes

- Windows SAPI synthesized a non-empty WAV and completed physical-speaker
  playback.
- Kokoro synthesized the release test phrase as mono PCM16, 24 kHz, 185,168
  frames, 7.715 seconds, RMS 0.0706, and 370,380 bytes. Replay started through
  the Windows audio path and `blair stop` interrupted it.
- A live Codex `agent-turn-complete` event produced exactly one BLAIR WAV and the
  Codex command exited zero.
- A live Claude Code synchronous `Stop` hook produced exactly one BLAIR WAV and
  the Claude command exited zero. An async print-mode experiment delivered no
  event after the CLI exited, so async Claude hooks are not shipped.
- The daemon transport, global hotkey registration, session state, SAPI fallback,
  and preferred Kokoro cold/warm paths were exercised on this machine.

The release checklist records automated and clean-install results separately so
fixture coverage is not confused with live provider or physical-audio proof.
