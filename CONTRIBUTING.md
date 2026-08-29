# Contributing to BLAIR

BLAIR welcomes focused fixes, adapter fixtures, accessibility feedback, briefing
quality cases, and Windows compatibility reports.

## Product invariants

Changes must preserve these boundaries:

- output only: no microphone, speech recognition, wake word, or prompt submission;
- opt-in per provider session; unknown or declined sessions stay silent;
- local composition and speech during normal operation;
- provider hooks always fail open and never delay an agent for synthesis;
- existing Codex and Claude configuration is preserved or the installer refuses;
- failures, uncertainty, and required user action are never rewritten as success;
- code, logs, tables, URLs, paths, identifiers, and likely secrets stay on screen;
- the full terminal response remains the source of truth.

## Development setup

Requirements are Python 3.11–3.13 and Git. Windows 11 is required for real SAPI,
global-hotkey, and agent-hook acceptance tests.

```powershell
git clone https://github.com/jithendra-bethi/blair.git
Set-Location blair
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

The Apache core development environment deliberately excludes the optional
Kokoro dependency stack. If voice work needs it, review
[Optional TTS licenses](docs/third-party-licenses.md), install `.[kokoro]`, and run
`blair setup` only when you want to approve the separate 354 MB model download.
Most unit tests use fakes and need neither packages nor models.

Keep development state out of the real profile:

```powershell
$env:BLAIR_HOME = Join-Path $PWD '.test-home-local'
.\.venv\Scripts\blair.exe setup --skip-models
.\.venv\Scripts\blair.exe demo --no-play
```

Remove the environment override from that PowerShell process when finished:

```powershell
Remove-Item Env:BLAIR_HOME
```

## Checks

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m build
```

Run focused tests while iterating, then run the complete suite before opening a
pull request. The [morning acceptance checklist](docs/acceptance-checklist.md)
covers the manual Windows proof that unit tests cannot provide.

## Fixtures

Provider payloads and briefing-quality samples belong in `tests/fixtures/` and
must be synthetic:

- never commit a real transcript, username, home path, repository secret, token,
  customer name, or session identifier;
- retain the provider's actual field names and event shape;
- use fixed IDs so failures are reproducible;
- include expected status and must-include/must-exclude assertions when adding a
  briefing case;
- add malformed and oversized cases only when a test consumes them.

See [tests/fixtures/README.md](tests/fixtures/README.md) for the current samples.

## Agent integration safety

Automated integration tests must pass temporary config paths into the installer.
Do not invoke `blair install` or `blair uninstall` against your real profile from
the test suite.

Manual testing changes `%USERPROFILE%\.codex\config.toml` and
`%USERPROFILE%\.claude\settings.json`. Inspect the timestamped backup paths printed
by BLAIR and run `blair uninstall` before deleting the development environment.

Hook tests must assert that malformed payloads return success to the provider and
record content-free failure diagnostics. Avoid assertions that depend on a live
cloud agent when a recorded synthetic fixture proves the same boundary.

## Briefing changes

Briefing rules are safety-sensitive. Every classifier or redaction change should
include cases for:

- success without false failure detection, such as “zero failures”;
- failed, blocked, partial, unverified, and user-decision responses;
- Markdown tables, fenced code, diffs, stack traces, and long prose;
- Windows and POSIX paths, URLs, hashes, and synthetic credentials;
- strict word caps and the final screen-detail cue.

Prefer deterministic, inspectable behavior. Introducing a network model or
telemetry is a product-boundary change and requires prior design discussion plus
updated privacy documentation.

## Pull requests

Keep each pull request narrow and include:

- the problem and user-visible behavior;
- automated proof and any manual Windows proof;
- privacy, persistence, configuration, or accessibility impact;
- documentation updates for changed CLI behavior;
- the exact Claude Code/Codex versions used for live integration testing.

Do not commit generated WAVs, model files, virtual environments, local BLAIR
homes, caches, or user configuration backups.

By contributing, you agree that your contribution is licensed under the
[Apache License 2.0](LICENSE).
