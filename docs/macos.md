# BLAIR on a MacBook

This is an **experimental setup guide**, checked against the code but not yet
tested on a Mac. Windows 11 remains the tested release target. Intel and Apple
Silicon Macs both need verification, including the optional speech dependencies.

BLAIR has a local Kokoro speech backend and uses macOS's `afplay` for playback.
It has **no built-in Mac global hotkeys or Yes/No popup**. Use the launch command
and terminal controls below. BLAIR does not use your microphone.

## 1. What you need

- Git.
- Python **3.11–3.13**. These examples use Python 3.12; Python 3.14 is not supported.
- Codex CLI or Claude Code installed, signed in, and working in your terminal.
- Internet access for installation and approximately **354 MB** of voice files.

Check Python:

```bash
python3.12 --version
```

If you already use Homebrew and need Python, run `brew install python@3.12`.
Otherwise install a supported Python version using your usual method.

Your Windows installation, virtual environment, voice files, and session choices
do not transfer through GitHub. Install BLAIR separately on the Mac.

## 2. Install BLAIR

Run these commands in Terminal:

```bash
mkdir -p ~/Developer
git clone https://github.com/jithendra-bethi/blair.git ~/Developer/blair
cd ~/Developer/blair
python3.12 -m venv --copies .venv
source .venv/bin/activate
python -m pip install ".[kokoro]"
blair setup
blair config set backend kokoro
blair config set hotkeys_enabled false
```

Keep `--copies`: BLAIR resolves the Python executable's path when creating hooks.
A virtual environment whose Python is a symlink can point those hooks at the
base interpreter, where BLAIR is not installed. If you previously created a
symlink-based environment, create a fresh environment with `--copies` and reinstall
the package and hooks using that environment.

When `blair setup` asks to download voice files, type `y` and press Enter. It
verifies the downloads. Kokoro is required for this Mac setup because Windows
SAPI is unavailable; there is no native macOS `say` backend in BLAIR yet.
See [optional speech dependencies and licenses](third-party-licenses.md).

Check that the environment's Python resolves inside the environment:

```bash
python -c 'import sys; from pathlib import Path; print(Path(sys.executable).resolve())'
```

The printed path should be inside `~/Developer/blair/.venv`, expanded to your
actual home directory. Then try speech:

```bash
blair doctor
blair demo --wait
```

You should hear a spoken demo. Get that working before connecting an agent.

## 3. Connect and activate your agent

For Codex:

```bash
blair install codex
blair run codex --briefings on
```

For Claude Code:

```bash
blair install claude
blair run claude --briefings on
```

Install both integrations if you use both agents. Run the launch command from
the project directory where you want to work. The hook service starts
automatically when a supported completion arrives.

`--briefings on` grants speech permission for that launch. To choose at launch,
use `blair run codex` or `blair run claude` and type `y` at the terminal question.
Starting a new chat directly through `codex` or `claude` does not provide this
permission; on Mac, BLAIR cannot show the Windows consent popup and defaults to
silent for an unanswered session.

Hook installation makes backups and preserves unrelated settings. If Codex
already has another `notify` command, BLAIR refuses to overwrite it. See
[agent integrations](integrations.md) before resolving that conflict.

## 4. Use it in a new terminal

Activate the existing environment, then launch your agent from your project:

```bash
source ~/Developer/blair/.venv/bin/activate
blair run codex --briefings on
```

Replace `codex` with `claude` as needed. Keep the checkout and virtual environment
in place: installed hooks refer to that interpreter. If you move the installation,
recreate the environment, reinstall BLAIR, and reinstall the hooks.

## 5. Controls and hotkeys

**There is currently no BLAIR keyboard shortcut on Mac.** The Windows shortcuts
`Ctrl+Alt+B`, `Ctrl+Alt+R`, and `Ctrl+Alt+S` are not registered on macOS.

In another terminal, activate the same environment and use:

```bash
source ~/Developer/blair/.venv/bin/activate
blair mute
blair unmute
blair stop
blair replay
```

Run the command you need: `mute` silences all BLAIR speech; `unmute` restores
speech for enabled sessions; `stop` cancels current speech; `replay` reads the
most recently active session's last briefing. These commands do not require
Mac Accessibility or microphone permissions. The mute/unmute CLI commands do
not announce their state aloud.

To enable or disable an existing chat mid-session, find its ID first:

```bash
blair sessions
blair on --session SESSION_ID
blair status --session SESSION_ID
```

Replace `SESSION_ID` with the ID from `blair sessions`. Use `blair off --session
SESSION_ID` to disable that chat. If globally muted, also run `blair unmute`.
With multiple chats, always supply the session ID: commands without it target
the most recently active BLAIR session, which may differ from the window you see.

Codex recaps stay enabled in Codex. BLAIR skips identified subagents and Codex
events without a recognized main-session source, so those events cannot prompt,
speak, or interrupt a briefing. If main-session metadata is unavailable, a normal
briefing can also be skipped; BLAIR checks again on the next completion.

## 6. Get the latest version from GitHub

From a clean checkout:

```bash
cd ~/Developer/blair
source .venv/bin/activate
blair daemon stop
git pull --ff-only
python -m pip install ".[kokoro]"
```

Re-run `blair install codex` and/or `blair install claude` for the agents you use,
then run `blair daemon start`. Updating retains the local settings and downloaded
models. If Git reports local changes or diverging history, resolve them before
updating; do not discard your work just to follow this guide.

## If you do not hear anything

- **`blair: command not found`:** activate `.venv` in this terminal.
- **No speech backend or missing models:** confirm `.[kokoro]` installed
  successfully, run `blair setup`, and select `backend kokoro`.
- **Demo is silent:** check Mac volume and audio output, run `blair unmute`, then
  retry `blair demo --wait`. `blair doctor` helps distinguish missing dependencies
  from missing model files. Native dependency installation may need Mac-specific
  investigation; this setup has not been validated on either Mac architecture.
- **Demo works but chats are silent:** confirm the Python path check above,
  reinstall the relevant hooks, and use `blair run ... --briefings on`.
  Check `blair sessions`, the specific session's `blair status`, and global mute.
- **A hotkey does nothing:** Mac hotkeys are not implemented. Use the commands above.

By default, Mac settings, session state, audio, models, and logs live under
`~/.local/state/blair/`. `BLAIR_HOME` overrides that location; otherwise
`XDG_STATE_HOME`, when set, changes the base directory. Check `blair doctor` for
the actual location. The diagnostic log is `logs/blair.log` inside it.

## Remove BLAIR

Before removing the virtual environment, activate it and run:

```bash
blair daemon stop
blair uninstall codex claude
python -m pip uninstall blair-briefing
```

This removes BLAIR's managed hooks and Python package. Local settings, downloaded
models, and audio remain in the data directory until you choose to remove them.
