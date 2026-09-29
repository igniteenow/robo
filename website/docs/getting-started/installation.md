---
sidebar_position: 2
title: "Installation"
description: "Install Robo Agent on Linux, macOS, WSL2, native Windows, or Android via Termux"
---

# Installation

Get Robo Agent up and running in under two minutes!

:::tip Platform Support
For the full platform support matrix (which OSes, distribution methods, and
platform-gated features are supported), see **[Platform Support](./platform-support.md)**.
:::

## Quick Install

You need `git` and Python 3.11, 3.12, or 3.13 (see [Prerequisites](#prerequisites)).

#### Linux / macOS / WSL2 / Android (Termux)
```bash
git clone https://github.com/igniteenow/robo robo && cd robo && bash install-robo.sh
```

#### Windows (native)

Run in PowerShell:
```powershell
git clone https://github.com/igniteenow/robo robo
cd robo
Set-ExecutionPolicy -Scope Process Bypass -Force
.\install-robo.ps1
```

The desktop app is built from the same install. After a command-line install, run
```bash
robo desktop
```

### What the Installer Does

The installer:

- creates a Python environment in `.venv` inside the folder you cloned and installs Robo into it, plus the optional voice extras where the platform has wheels for them;
- installs a Robo-managed Node.js 22 when the machine has no compatible Node (the terminal UI and browser tools need it);
- writes the `robo` launcher and, on Windows, adds it to your user PATH;
- creates the data folder and never overwrites an existing config, memory, or skills.

It does not install ripgrep or ffmpeg, and it does not configure an LLM provider: run `robo model` next, and `robo doctor` to see anything optional that is missing, with the command that installs it.

#### Install Layout

| Installer                                   | Code lives at                  | `robo` command                         | Data directory                       |
| ------------------------------------------- | ------------------------------ | -------------------------------------- | ------------------------------------ |
| `install-robo.sh` (Linux, macOS, WSL)       | the folder you cloned          | `~/.local/bin/robo`                    | `~/.robo/`                           |
| `install-robo.ps1` (Windows)                | the folder you cloned          | `%USERPROFILE%\.robo\bin\robo.cmd`     | `%USERPROFILE%\.robo\`               |
| Scripted installer (`scripts/install.sh`)   | `~/.robo/robo-engineer/`       | `~/.local/bin/robo`                    | `~/.robo/`                           |
| Scripted installer as root                  | `/usr/local/lib/robo-engineer/` | `/usr/local/bin/robo`                 | `/root/.robo/` (or `$ROBO_HOME`)     |

The root-mode **FHS layout** (`/usr/local/lib/…`, `/usr/local/bin/robo`) matches where other system-wide developer tools land on Linux. It's useful for shared-machine deployments where one system install should serve every user. Per-user config (auth, skills, sessions) still lives under each user's `~/.robo/` or explicit `ROBO_HOME`.

### After Installation

Open a new terminal and start chatting. On macOS and Linux, if `~/.local/bin` is not on your PATH yet, the installer prints the one line to add to your shell profile.

```bash
robo model       # Choose your LLM provider and model
robo             # Start chatting!
```

To reconfigure individual settings later, use the dedicated commands:

```bash
robo model          # Choose your LLM provider and model
robo tools          # Configure which tools are enabled
robo gateway setup  # Set up messaging platforms
robo config set     # Set individual config values
robo config get     # Inspect individual config values
robo setup          # Or run the full setup wizard to configure everything at once
```

:::tip Fastest path
`robo setup` walks through the provider, the model, and the tools in one pass.
:::

---

## Prerequisites

- **Git** (`git --version`).
- **Python 3.11, 3.12, or 3.13.** Python 3.14 is not supported yet.
  - Windows: `winget install -e --id Python.Python.3.13`, or the python.org installer with "Add python.exe to PATH" ticked.
  - macOS: `brew install python@3.13`.
  - Debian/Ubuntu: `sudo apt install python3 python3-venv`.
- **Linux:** `curl` and `xz-utils`, used to download Node.js (`sudo apt install curl xz-utils` on Debian/Ubuntu).
- **Desktop app on Linux:** `g++` (`build-essential` on Debian/Ubuntu) to compile native modules.

The installer sets up **Node.js 22** itself when the machine has no compatible Node. ripgrep (faster file search) and ffmpeg (audio conversion for TTS) are optional; `robo doctor` shows the command to install them.

:::info Windows Server
On Windows Server, and wherever PowerShell opens in the classic console window, run Robo in **Windows Terminal** (search "Terminal" in Start). The classic window's default font cannot draw some of Robo's symbols.
:::

:::tip Nix users
Nix is **no longer an explicitly supported install path** (best-effort only). If you already use Nix (on NixOS, macOS, or Linux), there's a dedicated setup path with a Nix flake, declarative NixOS module, and optional container mode. See the **[Nix & NixOS Setup](./nix-setup.md)** guide.
:::

---

## Manual / Developer Installation

If you want to clone the repo and install from source — for contributing, running from a specific branch, or having full control over the virtual environment — see the [Development Setup](../developer-guide/contributing.md#development-setup) section in the Contributing guide.

---

## Non-Sudo / System Service User Installs

Running Robo as a dedicated unprivileged user (e.g. a `robo` systemd service account, or any user without `sudo` access) is supported. The only thing on the install path that genuinely needs root is Playwright's `--with-deps` step, which `apt`-installs shared libraries (`libnss3`, `libxkbcommon`, etc.) used by Chromium. Robo does not need sudo for the browser itself: on first use it downloads the Chromium binary into the service user's own cache (the binary only, never `--with-deps`), so an administrator installs the system libraries separately.

**Recommended split (Debian/Ubuntu):**

1. **One time, as an admin user with sudo**, install the system libraries Chromium needs:
   ```bash
   sudo npx playwright install-deps chromium
   ```
   (You can run this from anywhere — `npx` will fetch Playwright on the fly.)

2. **As the unprivileged service user**, run the regular installer. It needs no sudo and does not install a browser; Chromium is downloaded into the user's own cache the first time a browser tool runs:
   ```bash
   git clone https://github.com/igniteenow/robo robo && cd robo && bash install-robo.sh
   ```

3. **Make `robo` available to the service user's shells.** The installer writes the launcher to `~/.local/bin/robo`. System service accounts often have a minimal PATH that doesn't include `~/.local/bin`. Either add it to the user's environment, or symlink the launcher into a system location:
   ```bash
   # Option A — add to the service user's profile
   echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

   # Option B — symlink system-wide (run as an admin; use the folder you cloned)
   sudo ln -s /home/robo/robo/.venv/bin/robo /usr/local/bin/robo
   ```

4. **Verify:** `robo doctor` should now run cleanly. If you get `ModuleNotFoundError: No module named 'dotenv'`, you're invoking the repo's source `robo` file with system Python instead of the launcher in the Python environment (`<clone>/.venv/bin/robo`) — fix step 3.

5. **Running the messaging gateway from this account?** A user-level service stops at logout and does not start at boot until you enable lingering for the service user:

   ```bash
   sudo loginctl enable-linger <service-user>
   ```

   See [Messaging Gateway](/user-guide/messaging/) for the service setup itself.

The same pattern works on Arch (the installer uses pacman with the same sudo-detection logic), Fedora/RHEL, and openSUSE — those distros don't support `--with-deps` at all, so an administrator always installs the system libraries separately. The relevant `dnf`/`zypper` commands are printed by the installer.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `robo: command not found` | Open a new terminal. On macOS/Linux, add `~/.local/bin` to your PATH (the installer prints the line) |
| `API key not set` | Run `robo model` to configure your provider, or `robo config set OPENROUTER_API_KEY your_key` |
| Missing config after update | Run `robo config check` then `robo config migrate` |

For more diagnostics, run `robo doctor` — it will tell you exactly what's missing and how to fix it.

## Install method auto-detection

Robo auto-detects whether it was installed via the git installer, Docker, or NixOS, and `robo update` prints the matching update command for that path. There's no env var to set — the detection is based on the install layout (`~/.robo/robo-engineer/` checkout, Docker image stamp, or Nix store path). `robo doctor` also surfaces the detected method under its environment summary.
