# Installing Robo

## Before you begin

- Use Python 3.11, 3.12, or 3.13.
- Extract Robo into a **new directory**. Do not unzip over an older copy.
- Keep secrets in `~/.robo/.env` (Windows: `%USERPROFILE%\.robo\.env`).
- The installer preserves an existing Robo home. If a `.env` exists beside the
  installer, it is copied only when the destination `.env` does not exist.

## Kali, Debian, Ubuntu, Raspberry Pi OS, macOS, WSL

```bash
git clone https://github.com/igniteenow/robo.git robo
cd robo
bash install-robo.sh
```

If `~/.local/bin` is not already on PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Make that export permanent in `~/.bashrc` or `~/.zshrc`, then run:

```bash
robo --robo-version
robo model
robo
```

Optional installer arguments:

```text
--home PATH       Use a different Robo data directory
--python PATH     Use a specific Python executable
--node PATH       Use a specific Node.js 22+ executable
--skip-node       Skip managed Node installation
```

## Windows 10/11 PowerShell

```powershell
git clone https://github.com/igniteenow/robo.git robo
cd .\robo
Set-ExecutionPolicy -Scope Process Bypass
.\install-robo.ps1
```

Open a new PowerShell window, then:

```powershell
robo --robo-version
robo model
robo
```

The PowerShell installer supports `-RoboHome`, `-Python`, `-Node`, `-BinDir`,
`-SkipNode`, and `-NoPathUpdate`.

## Configure a model

Run the interactive wizard:

```bash
robo model
```

Choose OpenAI, Anthropic/Claude, Kimi, DeepSeek, OpenRouter, Ollama, or a custom
OpenAI-compatible endpoint. Secret fields are entered through the wizard rather
than printed into the conversation. You may also edit `~/.robo/.env`.

For Ollama, install and start Ollama first, pull a model, then choose the local
or custom OpenAI-compatible provider in `robo model` and point it at Ollama's
local endpoint.

## Start the interfaces

Professional terminal UI:

```bash
robo
```

Desktop interface (first run installs/builds platform Node dependencies):

```bash
robo desktop
```

Wake word inside the TUI:

```text
/wake on
```

Robo uses the bundled `hey_roh_boh.onnx` model by default. The TFLite version
is included for compatible runtimes and hardware integrations.

## Moving an existing `.env` safely

Linux/Kali example when the backup is `/home/kali/robo.env.backup`:

```bash
mkdir -p /home/kali/.robo
chmod 700 /home/kali/.robo
cp /home/kali/robo.env.backup /home/kali/.robo/.env
chmod 600 /home/kali/.robo/.env
```

Do not delete the backup until `robo model` and a real provider response both
work. Robo does not need the `.env` inside its program directory.

## Verify

```bash
robo --robo-version
robo assets
robo status
```

The asset report should point into `.robo/assets/face` and
`.robo/assets/wake_word`. If voice setup is unavailable, the terminal and
desktop text interfaces continue to work; wake/voice dependencies are installed
separately from the core runtime.

## Updating without merge prompts

Never extract a new zip over the old directory. Extract into a new versioned
folder, run its installer, verify it, and only then remove the old program
folder. Operator state stays in `.robo`, so program upgrades do not overwrite
configuration or memory.

## Troubleshooting

**The terminal fills with numbers like `35;111;47M` whenever the mouse moves.**
A Robo session was killed or its terminal tab closed before it could switch the
terminal's mouse reporting off, so the shell now receives every mouse movement
as text. Run any Robo command, for example `robo --robo-version`; every Robo
command resets the terminal on its way in. (If Robo is not installed yet:
`printf '\033[?1003l\033[?1006l\033[?1000l'`.) Press Enter once to clear the
line that was already typed.

**Red text during installation.** pip prints its errors in red. The installer
puts the optional voice extras' output in `~/.robo/logs/install-extras.log` and
prints a one-line summary of what installed; `robo doctor` lists anything
missing with the command that fixes it. Robo itself installs even when an extra
does not.
