# BLAIR

**BLAIR — Briefing Layer for Agent Interaction Results** gives Claude Code and
Codex CLI a concise, local voice for completed work.

When an agent finishes a turn, BLAIR extracts the outcome, important changes,
verification, blockers, and required action into a short spoken report. Code,
logs, Markdown tables, and the full response stay on screen.

> BLAIR is an early Windows-first release. It does not listen to you, transcribe
> speech, submit prompts, or approve agent actions.

## What it sounds like

> The task is complete. The authentication flow was updated and all 18 tests
> passed. Please check the screen for the code and full details.

> The work is partly complete. One source could not be verified. I compiled a
> table for you, sir. Please check the screen for details.

BLAIR uses deterministic extraction rather than another model call. The terminal
remains the source of truth.

## Release-bundle quick start

`BLAIR-0.1.0-windows-core.zip` is a bootstrap archive, not a standalone portable
executable. It needs Python 3.11–3.13 and installs the bundled BLAIR wheel into a
user-local environment.

Extract the ZIP, open PowerShell in the extracted directory, and run:

```powershell
.\scripts\install.ps1 -Kokoro Skip
$blair = Join-Path $env:LOCALAPPDATA 'Programs\BLAIR\blair.cmd'
& $blair doctor
& $blair demo --wait
```

`-Kokoro Skip` uses Windows SAPI and makes no model download. If local script
execution is blocked, relax policy only for the current PowerShell process and
retry:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install.ps1 -Kokoro Skip
```

Connect the installed launcher to an agent:

```powershell
& $blair install codex claude
& $blair run codex
# Or:
& $blair run claude
```

Use `-Kokoro Install` instead only when you explicitly want the optional Python
dependencies and verified model downloads described in
[Optional TTS licenses](docs/third-party-licenses.md).

## Source-checkout quick start

Requirements: Windows 11, Python 3.11–3.13, and PowerShell. From a checkout:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\blair.exe setup --skip-models
.\.venv\Scripts\blair.exe demo --wait
```

This path uses a locally installed Windows SAPI voice and downloads no speech
model. If you hear the demo, connect one or both agents:

```powershell
.\.venv\Scripts\blair.exe install codex claude
.\.venv\Scripts\blair.exe run codex
# Or:
.\.venv\Scripts\blair.exe run claude
```

At launch, BLAIR asks:

```text
BLAIR: Speak concise completion briefings for this codex session? [y/N]
```

Each `blair run` gets a unique launch ID. Its answer is applied once when that
process delivers its first completion, including when the provider thread was
resumed from an earlier process. Manual `on`, `off`, or `toggle` changes then
persist for the rest of that launch. Press Enter or answer `n` to start silent;
use `--briefings on` or `--briefings off` to skip the question.

The installers make timestamped backups and preserve unrelated configuration.
Codex installation refuses to overwrite an existing `notify` command. See
[Agent integrations](docs/integrations.md) before resolving a conflict manually.

## Better local voice with Kokoro

The preferred voice is Kokoro `bf_emma`, a British-English female voice. It is
optional because its local ONNX model and voice data total about 354 MB.

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[kokoro]"
.\.venv\Scripts\blair.exe setup
```

`setup` asks before downloading and verifies both files with SHA-256. For an
unattended, explicitly approved setup, use `blair setup --yes`. With backend
`auto`, BLAIR prefers a ready Kokoro installation and falls back to Windows SAPI.

Kokoro is an optional dependency stack and is not bundled into BLAIR's
Apache-2.0 core distribution. Some transitive components use GPL-family licenses;
review [Optional TTS licenses](docs/third-party-licenses.md) before redistributing
a build that bundles the Kokoro stack or model assets.

## Controls

Commands without `--session` operate on the most recently active BLAIR session.
Use `blair sessions` to find provider session IDs when several agents are open.

| Command | Effect |
| --- | --- |
| `blair on [--session ID]` | Enable future briefings for a session |
| `blair off [--session ID]` | Disable the session and stop current speech |
| `blair toggle [--session ID]` | Toggle the session and stop speech when turning off |
| `blair status [--session ID]` | Show session consent state |
| `blair sessions` | List locally known sessions |
| `blair replay [--session ID]` | Replay that session's last cached briefing |
| `blair stop` | Stop the currently playing WAV without disabling briefings |
| `blair daemon start\|stop\|status` | Manage the local hook and hotkey service |
| `blair doctor` | Inspect agents, hooks, backends, models, and service status |

The Windows background service registers these global hotkeys by default:

| Hotkey | Effect |
| --- | --- |
| `Ctrl+Alt+B` | Toggle the most recently active session |
| `Ctrl+Alt+R` | Replay its last briefing |
| `Ctrl+Alt+S` | Stop speech |

The service starts when a hook first delivers an event. Start it explicitly with
`blair daemon start` if you want the hotkeys registered before the first result.
Bindings and hotkeys can be changed in configuration.

## Dictation is deliberately separate

BLAIR has no microphone or speech-to-text code. To dictate a prompt on Windows,
focus the agent terminal and press **Win+H**. Windows handles that input; BLAIR
only handles completed agent output. There is no wake word or always-listening
mode.

## How briefings are composed

BLAIR aims for a short human-style report rather than reading the response aloud:

- outcome first: complete, partial, blocked, failed, or awaiting input;
- material changes and explicitly reported validation;
- failures, uncertainty, and required decisions are retained;
- code blocks, diffs, table cells, URLs, paths, long identifiers, and likely
  secrets are replaced or omitted;
- dense artifacts receive a “check the screen” cue;
- output is capped by `max_words`, which defaults to 58.

The redaction layer is defensive, not a guarantee. Leave Briefing Protocol off
for highly sensitive output or when people nearby should not hear it.

## Configuration

```powershell
blair config show
blair config set backend auto
blair config set honorific ""
blair config set max_words 58
```

Supported backends are `auto`, `kokoro`, `windows`, and `none`. Configuration is
stored in `%LOCALAPPDATA%\BLAIR\config.json`. See
[Configuration](docs/configuration.md) for every key and its behavior.

## Local data and network use

Normal completion handling, briefing composition, synthesis, and playback are
local. BLAIR contacts GitHub only when you approve Kokoro model setup. Replay is
implemented with a rolling local WAV cache; it is not memory-only.

See [Privacy and local data](PRIVACY.md) for the exact data flow, stored files,
retention controls, threat boundary, and removal commands.

## Troubleshooting

Start here:

```powershell
blair doctor
blair status
blair daemon status
```

Then see [Troubleshooting](docs/troubleshooting.md). Common causes are an agent
hook that is not installed, a session that was declined, unavailable hotkey
bindings, or Kokoro dependencies installed without its model files.

## Limitations in v0.1

- Windows 11 x64 is the tested target; Windows 10, ARM64, WSL, SSH, macOS, and
  Linux are not release claims.
- Only Claude Code `Stop`/`StopFailure` and Codex `agent-turn-complete` events are
  supported. Live proof used Claude Code 2.1.251 and Codex CLI 0.150.1; other
  versions are not yet release claims. Streaming tokens and background subagent
  narration are excluded.
- Each `blair run` launch applies its selected consent once. Subsequent manual
  toggles affect that launch; directly launched hooked sessions retain their
  stored provider-session setting.
- Hotkeys target the most recently active session. Use explicit session IDs when
  several sessions are running.
- The deterministic composer can omit nuance. Always inspect the terminal before
  acting on important, destructive, financial, legal, or security-sensitive work.
- Windows SAPI voice quality depends on voices installed on the machine.
- The release is a Python bootstrap bundle, not a standalone executable. Code
  signing, SmartScreen reputation, and automatic updates are out of scope for
  v0.1.

## Uninstall

For a release-bundle installation, run the managed uninstaller. It removes hooks
before the private Python environment and preserves local data by default:

```powershell
$uninstaller = Join-Path $env:LOCALAPPDATA 'Programs\BLAIR\uninstall.ps1'
& $uninstaller
```

For a source or manually installed environment, stop BLAIR, remove its hooks,
then uninstall `blair-briefing` with that environment's Python.

This intentionally keeps configuration, models, cached audio, logs, and session
state under `%LOCALAPPDATA%\BLAIR`. Follow the verified data-removal instructions
in [PRIVACY.md](PRIVACY.md#delete-all-local-blair-data) if you also want those
files removed.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md), the
[architecture and data flow](docs/architecture.md), and the
[morning acceptance checklist](docs/acceptance-checklist.md). Exact live-test
evidence is recorded in [Tested environment](docs/tested-environment.md). The
[landscape and cost study](docs/landscape.md) records comparable projects,
observable demand signals, and transcription/summary/TTS cost estimates.

Licensed under the [Apache License 2.0](LICENSE).
