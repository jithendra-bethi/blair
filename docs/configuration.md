# Configuration

Show the saved configuration with:

```powershell
blair config show
```

Change one key with `blair config set KEY VALUE`. Values are saved to
`%LOCALAPPDATA%\BLAIR\config.json`, or to `BLAIR_HOME\config.json` when that
environment variable is set.

The running service reloads speech and briefing settings before each new briefing.
This includes backend, voice, language, speed, length, honorific, prompting,
automatic playback, and audio retention. A briefing already being generated or
played keeps its original settings. Changing the backend also clears the service's
cached backend selection. Invalid settings cause that briefing to be skipped and
logged; the service checks the file again for the next event.

Hotkey bindings and `hotkeys_enabled` still require a service restart, as described
below. The settings command tells you when this is needed.

## Defaults

| Key | Default | Meaning |
| --- | --- | --- |
| `backend` | `auto` | Prefer ready Kokoro, then fall back to Windows SAPI |
| `voice` | `bf_emma` | Kokoro voice ID |
| `language` | `en-gb` | Kokoro language tag |
| `speed` | `1.03` | Kokoro speed, accepted range 0.5–2.0 |
| `honorific` | `sir` | Added to the table-detail cue; set to an empty string to omit |
| `max_words` | `58` | Briefing cap, accepted range 20–120 |
| `prompt_new_sessions` | `true` | Ask once when an unknown session first reports |
| `play_audio` | `true` | Play newly synthesized hook briefings |
| `keep_audio_files` | `10` | Rolling WAV count, accepted range 1–100 |
| `hotkeys_enabled` | `true` | Register global controls in the service |
| `hotkey_toggle` | `ctrl+alt+b` | Mute/unmute all BLAIR speech, preserving session permissions |
| `hotkey_replay` | `ctrl+alt+r` | Replay the active session |
| `hotkey_stop` | `ctrl+alt+s` | Stop playback |

## Speech backend

```powershell
blair config set backend auto
blair config set backend kokoro
blair config set backend windows
blair config set backend none
```

- `auto` is recommended. It uses Kokoro only when both dependencies and both
  verified model assets are ready.
- `kokoro` fails clearly instead of silently falling back. Use it when voice
  consistency matters.
- `windows` uses local SAPI and needs no model download.
- `none` still composes and records briefing text but does not synthesize speech.

`voice`, `language`, and `speed` currently apply to Kokoro. Windows SAPI chooses
the first enabled en-GB female voice where available, otherwise the system's
default SAPI voice.

Kokoro runs in a persistent local child process and writes PCM16 WAV audio without
calling a cloud service. The child is reused by the BLAIR background service so
the model is loaded only once during a listening session.

Install and initialize Kokoro with:

```powershell
py -m pip install ".[kokoro]"
blair setup
```

## Briefing style

```powershell
blair config set honorific ""
blair config set max_words 45
```

The composer is deterministic. These options change length and phrasing but do
not enable a model or persona engine.

## Playback and retention

```powershell
blair config set play_audio false
blair config set keep_audio_files 3
```

`play_audio=false` keeps synthesis and the last replayable WAV but suppresses
automatic hook playback. Explicit `blair replay`, `blair demo`, and `blair brief`
commands can still request playback.

Lowering `keep_audio_files` takes effect after the next successful synthesis.
Delete existing files manually for immediate removal; see
[PRIVACY.md](../PRIVACY.md#delete-all-local-blair-data).

## Hotkeys

Bindings accept one or more of `ctrl`, `alt`, `shift`, and `win`, followed by one
letter, digit, or `F1`–`F24`:

```powershell
blair config set hotkey_toggle ctrl+alt+shift+b
blair config set hotkey_replay ctrl+alt+shift+r
blair config set hotkey_stop ctrl+alt+shift+s
blair daemon stop
blair daemon start
```

Restart the service after changing bindings or `hotkeys_enabled`. If Windows or
another application already owns a binding, BLAIR logs it as unavailable and the
CLI controls remain usable.

## Development override

Use a separate state root when testing:

```powershell
$env:BLAIR_HOME = Join-Path $PWD '.test-home-local'
blair doctor
```

This override affects BLAIR data, models, logs, and runtime files. It does not
redirect the real Claude and Codex configuration paths used by `blair install`.
