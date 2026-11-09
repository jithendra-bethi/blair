# Privacy and local data

BLAIR is output-only and local-first. It does not request microphone permission,
record audio, perform speech recognition, submit prompts, or approve agent
actions.

“Local-first” does not mean “nothing is written to disk.” BLAIR stores the state
and WAV files needed for session consent and replay. This document describes that
boundary precisely.

## Data flow

1. Claude Code or Codex invokes a local BLAIR hook after a supported completion
   event.
2. The adapter reads the provider payload and selects the final assistant message,
   provider session ID, event identity, and limited completion metadata.
3. The hook sends a normalized event to the local BLAIR service through
   authenticated local IPC. The hook returns immediately and fails open if BLAIR
   is unavailable.
4. The deterministic composer classifies the result and removes or replaces code,
   tables, URLs, paths, long identifiers, and common secret patterns.
5. Kokoro ONNX or Windows SAPI synthesizes the briefing into a local WAV file.
6. Windows plays the WAV. The rolling cache enables `blair replay`.

There is no summarization API call and no BLAIR cloud service.

To suppress Codex background and unidentified events, a hook reads only the matching thread's `source`
from Codex's local SQLite index. If unavailable, it reads a bounded first-line
`session_meta` header from the matching rollout file. It does not scan conversation
messages or modify Codex files. Claude subagent identification uses hook metadata.

## Microphone and Win+H

BLAIR has no microphone capture or STT dependency. **Win+H is a separate Windows
dictation feature**. If you use it in a terminal, its data handling is governed by
Windows and your organization, not by BLAIR.

## Network activity

Routine hook handling, composition, synthesis, and replay do not require network
access.

Network access occurs only when you explicitly run Kokoro setup and approve the
approximately 354 MB download. BLAIR fetches `kokoro-v1.0.onnx` and
`voices-v1.0.bin` from the `thewh1teagle/kokoro-onnx` GitHub release, validates
their expected sizes and SHA-256 hashes, and then reuses the local cache.

Installing Python packages may contact the configured package index. Claude Code
and Codex have their own network behavior, which is outside BLAIR's boundary.

## Files stored on Windows

The default root is `%LOCALAPPDATA%\BLAIR`. `BLAIR_HOME` can override it for
development and tests.

| Path | Contents | Retention |
| --- | --- | --- |
| `config.json` | Voice, backend, length, playback, and hotkey preferences | Until deleted |
| `sessions.json` | Provider/session IDs, working directory, consent, last briefing text, and last audio path | Until deleted |
| `audio\*.wav` | Synthesized briefings used for playback and replay | Newest 10 by default |
| `models\kokoro\...` | Downloaded Kokoro model, voices, and hash manifest | Until deleted |
| `runtime\` | Daemon PID, IPC authentication key, locks, deduplication hashes, and playback metadata | Reused and cleaned opportunistically |
| `logs\blair.log` | Timestamped operational actions, provider name, hashed session/event IDs, and error diagnostics | Until deleted |

The intended operational log does not contain full agent responses or briefing
text. Error descriptions can contain a local path or other diagnostic fragment;
inspect logs before sharing them.

Change the audio cache size with:

```powershell
blair config set keep_audio_files 3
```

Lowering the value reduces the rolling cache. Existing WAVs are pruned the next
time BLAIR synthesizes a briefing; delete them manually for immediate removal.

## Consent

- `blair run codex|claude` asks in the terminal unless `--briefings on|off` is
  provided. A random launch ID makes that choice apply once to the first
  completion from that process, even when resuming a stored provider thread.
- A supported completion that arrives outside the wrapper can show a Windows
  Yes/No dialog for a previously unseen session.
- Pressing Enter at the terminal prompt, answering No, or closing the dialog keeps
  that session silent.
- The resulting state is stored against the provider session ID. A manual `on`,
  `off`, or `toggle` then persists for the rest of the launch. Use `blair off
  --session ID` to revoke it and stop current playback.
- `blair stop` interrupts one utterance without changing consent.

## Redaction and spoken privacy

BLAIR attempts to keep these details on screen instead of in speech:

- fenced code, diffs, table rows, and Markdown syntax;
- URLs, Windows/Unix paths, long identifiers, and common token formats;
- values labelled as passwords, secrets, API keys, bearer tokens, or access
  tokens.

Pattern matching cannot recognize every secret or understand every context. Do
not treat it as a data-loss-prevention system. Disable briefings for sensitive
sessions and remember that speakers can be overheard. Headphones reduce exposure
but do not change the stored WAV cache.

## Local security boundary

The service uses authenticated local IPC and a randomly generated authentication
key. Hook payload size is bounded, duplicate events are hashed, and integration
errors return success to the provider so BLAIR cannot block the agent.

This is not a defense against malware, an administrator, or another process
already able to read files and run code as your Windows account. Protect your
Windows login and `%LOCALAPPDATA%` accordingly.

BLAIR speech is output-only. Text contained in an agent response is never treated
as a BLAIR control command, shell command, or approval.

## Delete all local BLAIR data

First stop the service and inspect the resolved target. Then remove only that
explicit directory:

```powershell
blair daemon stop
$blairData = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'BLAIR'
$blairData
Remove-Item -LiteralPath $blairData -Recurse -Force
```

If you set `BLAIR_HOME`, resolve and inspect that exact directory instead. Removing
the data directory does not remove Claude/Codex hooks or the Python package; use
the uninstall sequence in [README.md](README.md#uninstall) first.

## Reporting a privacy issue

Do not attach a real transcript, cached WAV, `sessions.json`, or unredacted log to
a public issue. Provide a minimal synthetic reproduction and describe the affected
version and backend. Security-sensitive reports should be sent privately to the
maintainer when a private reporting channel is available.
