# Troubleshooting

Run the diagnostic first:

```powershell
blair doctor
```

It reports the platform, Python version, BLAIR home, installed agent executables,
Windows SAPI availability, Kokoro package/model readiness, selected backend,
integration status, voice, and service PID.

## The agent finishes but nothing is spoken

Check these in order:

```powershell
blair status
blair sessions
blair doctor
blair daemon status
```

Then:

1. Enable the exact provider session with `blair on --session ID`.
2. Confirm `codex_hook: True` or `claude_hooks: True` in `doctor`.
3. Install the missing integration with `blair install codex` or `blair install
   claude`.
4. Confirm `play_audio` is true with `blair config show`.
5. Start or restart the service.

```powershell
blair daemon stop
blair daemon start
```

The first supported provider event normally starts the service automatically. A
streaming delta, tool call, unsupported event, or background subagent event is not
a BLAIR completion.

## Test speech without an agent

```powershell
blair config set backend windows
blair demo --wait
```

If the demo creates a WAV but is silent, check the Windows default output device,
volume mixer, and installed speech voices. SAPI output follows Windows audio
routing; BLAIR does not select a speaker device in v0.1.

Restore automatic selection afterward:

```powershell
blair config set backend auto
```

## Kokoro is not selected

`auto` chooses Kokoro only when its Python dependencies and both verified assets
are ready:

```powershell
py -m pip install ".[kokoro]"
blair setup
blair doctor
```

Expected checks are `kokoro_package: True`, `kokoro_models: True`, and voice
`bf_emma`. A partial or hash-invalid download is deleted. Run setup again on a
stable connection. Use `blair config set backend windows` for an immediate local
fallback.

## Setup cannot download models

- Confirm you explicitly approved the download or supplied `--yes` in an
  unattended terminal.
- Check access to GitHub releases through your proxy or organization policy.
- Do not disable size or SHA-256 verification.
- Remove only `.partial` files from the reported Kokoro model directory and retry.

Routine use does not need network access once the verified cache exists.

## Replay says no briefing is available

Replay needs a successfully synthesized cached WAV for that session:

```powershell
blair sessions
blair replay --session ID
```

The cache may have been pruned, manually deleted, created under a different
`BLAIR_HOME`, or never synthesized because the session was off. A new successful
briefing refreshes it.

## A hotkey does nothing

```powershell
blair daemon status
blair config show
```

Global hotkeys exist only while the service is running and target the most
recently active session. Another application may already own the binding. Choose
a different combination and restart the service:

```powershell
blair config set hotkey_toggle ctrl+alt+shift+b
blair daemon stop
blair daemon start
```

Supported bindings use `ctrl`, `alt`, `shift`, or `win` plus one alphanumeric key
or `F1`–`F24`. CLI controls continue to work if registration fails.

## Codex installation refuses an existing notify command

This is intentional protection. BLAIR does not overwrite another notifier. See
[Agent integrations](integrations.md#existing-codex-notify-command) for the safe
choices. Do not paste two `notify` keys into TOML; that makes the configuration
invalid.

## Claude settings or Codex TOML is invalid

The installer validates before writing and should report “nothing was changed.”
Repair the provider configuration with its own tooling, then run `blair install`
again. Do not restore a BLAIR backup blindly if you changed the file afterward;
compare it first.

## The session prompt appears again

Consent is stored by provider session ID, not by folder. `blair run` asks at
process launch by default and applies that launch's choice once when the first
completion arrives, even for a resumed provider thread. Use `--briefings on|off`
when you already know the desired launch setting.

Manual changes after the first completion persist for that launch. To change an
active session explicitly, use:

```powershell
blair sessions
blair off --session ID
# or
blair on --session ID
```

## Inspect diagnostics safely

The log is `%LOCALAPPDATA%\BLAIR\logs\blair.log` unless `BLAIR_HOME` is set. It is
designed around action names, hashes, and error types rather than response text.
Error descriptions can contain local paths or diagnostic fragments, so review and
redact it before sharing.

Hook errors deliberately fail open: losing a briefing must not change the agent's
result. Include the BLAIR version, `doctor` output with personal paths removed, the
backend, and a synthetic fixture when reporting a problem.
