# Synthetic provider fixtures

These files exercise adapter normalization and briefing safety without using a
real transcript or account.

| File | Purpose |
| --- | --- |
| `codex_success.json` | Supported Codex `agent-turn-complete` payload |
| `claude_success.json` | Supported Claude `Stop` payload with no background work |
| `claude_failure.json` | Supported Claude `StopFailure` payload |
| `claude_background.json` | Claude completion that still has background work |
| `generic_success.json` | Provider-neutral completion contract |
| `generic_failed.json` | Provider-neutral explicit failure |
| `dense_result.md` | Table, code, URL, path, identifier, and fake-secret speech filter |
| `briefing_cases.json` | Expected classification and content invariants |

IDs, paths, repositories, URLs, and tokens are deliberately fake. Keep new
fixtures synthetic and deterministic.

Quick manual composition check:

```powershell
blair brief --file tests\fixtures\dense_result.md --session fixture-demo --provider generic --no-play
```

The `hook` command is an internal adapter surface. Tests should call adapter
functions directly unless they specifically need process and fail-open coverage.
