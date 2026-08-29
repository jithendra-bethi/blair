# Windows release packaging

The `windows-core.zip` artifact is a portable **bootstrap bundle**, not a frozen
standalone executable. It contains BLAIR's pure-Python wheel, PowerShell lifecycle
scripts, the project license, and release notes. A 64-bit Python 3.11–3.13 installation
is required on the destination machine.

The core archive intentionally does not bundle `kokoro-onnx`, audio runtime wheels,
ONNX models, or third-party voice data. Choosing Kokoro in `install.ps1` authorizes pip
to install the optional dependencies and `blair setup --yes` to download and verify the
model files. Selecting `Skip` keeps installation offline after the local wheel is
available and uses Windows SAPI.

## Build and verify

From a PowerShell prompt with the project's pinned build-system requirements and the
`build` development dependency installed in the selected Python environment:

```powershell
./scripts/build-release.ps1
./scripts/test-clean-install.ps1 -WheelPath ./release/blair_briefing-0.1.0-py3-none-any.whl
```

The build emits one wheel, one source archive, the Windows core ZIP, and
`SHA256SUMS`. It uses `python -m build --no-isolation`, so release construction does not
silently download or substitute build tools. The clean-install check uses a uniquely
named temporary path containing
spaces, redirects `BLAIR_HOME`, `USERPROFILE`, and `LOCALAPPDATA`, installs both hooks
only into those sandboxed config homes, and removes the sandbox after verification.

## Install and uninstall behavior

`install.ps1` creates a virtual environment below the current user's local application
data directory and never requests elevation or modifies machine state. It does not add
itself to `PATH`; `blair.cmd` in the install directory is the stable launcher.

`uninstall.ps1` removes BLAIR-managed Codex and Claude hooks before deleting the managed
virtual environment. User state, generated audio, downloaded models, and configuration
backups are preserved by default. `-PurgeUserData` explicitly removes BLAIR's data root,
including models; `-PurgeBackups` separately removes only files matching BLAIR's backup
naming convention beside the Codex and Claude configuration files.
