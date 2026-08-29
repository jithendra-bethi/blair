# Security policy

## Supported version

BLAIR 0.1.x is the currently supported line. This is an early alpha, so users
should keep the terminal response as the source of truth and avoid spoken
briefings for highly sensitive sessions.

## Report a vulnerability

Please use the repository's **Security → Report a vulnerability** flow so the
report and any synthetic reproduction remain private. Do not open a public issue
with a real agent transcript, session state, log, cached WAV, token, or local
configuration file.

Include the BLAIR version, Windows/Python/provider versions, the affected product
boundary, and a minimal synthetic reproduction. You can expect an initial
acknowledgement within seven days. No bug-bounty payment is promised.

## Security boundary

BLAIR authenticates local IPC, bounds hook payloads, verifies optional model
downloads, and treats provider text as data rather than executable control. It is
not a sandbox or a defense against an administrator, malware, or another process
already running as your Windows account. See [PRIVACY.md](PRIVACY.md) for the
complete data and threat boundary.
