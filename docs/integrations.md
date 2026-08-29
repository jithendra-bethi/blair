# Agent integrations

BLAIR connects only to completion events. It does not wrap streaming output,
capture terminal input, or send a message back to an agent.

## Install and inspect

```powershell
blair install codex claude
blair doctor
```

Install one provider by naming only that provider. Running the same command again
is idempotent. BLAIR prints every changed path and timestamped backup.

Default paths are:

- Codex: `%USERPROFILE%\.codex\config.toml`
- Claude Code: `%USERPROFILE%\.claude\settings.json`

The installed command points to the exact Python interpreter or frozen executable
used to install BLAIR, so hooks do not depend on shell activation.

## Codex CLI

BLAIR adds a marked, top-level `notify` entry before the first TOML table:

```toml
# >>> BLAIR managed notify >>>
notify = ["<BLAIR executable>", "hook", "codex-notify"]
# <<< BLAIR managed notify <<<
```

Codex supplies its completion JSON as the final argument. BLAIR accepts only
`type = agent-turn-complete` and extracts `thread-id`, `turn-id`,
`last-assistant-message`, and optional context.

### Existing Codex notify command

Codex has one top-level notify command. If `config.toml` already contains one,
BLAIR refuses to overwrite or silently replace it. v0.1 does not ship a general
notification multiplexer because forwarding a JSON argument safely across every
Windows shell requires user-specific handling.

The safe choices are:

1. Keep the existing notifier and use BLAIR's `brief` command manually.
2. Replace the existing notifier yourself only if it is no longer needed, then run
   `blair install codex`.
3. Use a trusted multiplexer that forwards the original single JSON argument
   unchanged to both commands. Test it against
   `tests/fixtures/codex_success.json` before using it with a live agent.

Back up `config.toml` before manual composition. BLAIR cannot validate a
third-party multiplexer.

## Claude Code

BLAIR appends command-hook groups for:

- `Stop`, using the final assistant message and optional background-work metadata;
- `StopFailure`, producing an explicit failure briefing.

Existing hook groups, matchers, permissions, and unrelated settings are retained.
Claude invokes hooks through stdin JSON. Mark I deliberately uses a synchronous,
fail-open command hook: BLAIR validates the event and waits only until the local
service accepts it, then returns before synthesis and playback. This avoids the
unreliable async print-mode behavior encountered during Windows live testing. The
hook has a five-second provider timeout and catches every internal error so a
briefing failure cannot fail Claude's turn.

## Session consent

The recommended launch path is:

```powershell
blair run codex
blair run claude
```

Arguments after the provider are forwarded to the agent. Use a separator when an
agent argument could be confused with a BLAIR option:

```powershell
blair run codex --briefings on -- --model <model-name>
```

`ask` is the default and noninteractive stdin defaults to off. Every wrapper
process receives a random launch ID. The launch selection is applied exactly once
when its first completion arrives, including for a resumed provider thread. A
manual `on`, `off`, or `toggle` after that point persists for the remaining turns
in the launch rather than being overwritten on every hook event.

If an installed hook fires from a provider launched without `blair run`, an
unknown session can display one local Windows Yes/No consent dialog. Declining it
keeps future turns in that provider session silent until explicitly enabled.

## Manual and generic briefing

Use the pipeline without changing agent configuration:

```powershell
blair brief --file tests\fixtures\dense_result.md --session manual-demo --provider generic --wait
```

Exactly one input source is required: positional text, `--file`, or `--stdin`.
`--no-play` composes and synthesizes without playback; `--wait` waits for WAV
playback to finish.

The internal generic hook accepts a provider-neutral JSON object. Its stable
fields are demonstrated in `tests/fixtures/generic_success.json`.

## Remove integrations

```powershell
blair daemon stop
blair uninstall codex claude
```

Uninstall removes only the marked Codex block and BLAIR's Claude hook groups. It
creates a fresh backup before editing. Inspect the printed result and keep backups
until both agents start normally.

Uninstalling hooks does not remove the package or `%LOCALAPPDATA%\BLAIR` data. See
the complete sequence in the [README](../README.md#uninstall).
