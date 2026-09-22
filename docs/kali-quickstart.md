# Robo on Kali Linux — quickstart

> Verified here: the package installs and the `robo` binary runs; `robo assets` places the face + wake models; SOUL.md/config seed correctly. The full `pytest` suite (step 4) still needs a networked machine.

Step-by-step with a checkpoint after each step. Kali is Debian-based; these
commands also work on Debian/Ubuntu.

## 0. Prerequisites (once)

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip python3-dev git unzip build-essential \
  libffi-dev libssl-dev portaudio19-dev libasound2-dev libgtk-3-0 libnss3 libxss1 \
  binutils file xxd radare2 checksec
python3 --version   # must be 3.11, 3.12 or 3.13
```

Do not install Node yourself; the installer manages a Node 22 runtime.

## 1. Unpack

```bash
cd ~ && unzip Robo-3.0.0-alpha.5-igniteenow.zip && cd Robo-3.0.0-alpha.5
```

## 2. Install

```bash
bash install-robo.sh
export PATH="$HOME/.local/bin:$PATH"
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc   # or ~/.bashrc
robo --robo-version        # → Robo 3.0.0-alpha.5
```

## 3. Assets

```bash
robo assets                                            # paths to face + wake models
sha256sum ~/.robo/assets/wake_word/hey_roh_boh.onnx    # starts ca54d3…
xdg-open ~/.robo/assets/face/cute-face.html            # keys 1–7 cycle emotions
```

## 4. Tests

```bash
source .venv/bin/activate
pip install -e ".[dev]"
pytest -x -q 2>&1 | tail -30
pytest tests/tools/test_reverse_engineering_tool.py -v   # 8 passed
```

## 5. Model + setup

```bash
robo setup      # pick a provider; writes ~/.robo/.env and ~/.robo/config.yaml
robo doctor
```

## 6. Terminal UI

```bash
robo            # header "Robo · … · ● READY", tagline "AI security engineer · by Ignitee Now"
robo tools      # lists reverse_engineer among the tools
```

## 7. Voice + wake word

```bash
pip install -e ".[voice,wake]"
robo            # then /wake, then say "Hey Roh Boh"
python -c "import sounddevice; print(sounddevice.query_devices())"   # if no mic is found
```

## 8. Desktop app with the face

```bash
robo desktop    # first run builds the Electron app (a few minutes)
```

## 9. Web dashboard (optional)

```bash
robo dashboard
```

## Troubleshooting

- Wheel build errors in step 2: `sudo apt install -y python3-dev libffi-dev libssl-dev`, rerun.
- `pyproject.toml` errors: `python3 -c "import tomllib; tomllib.load(open('pyproject.toml','rb'))"` must succeed.
- Test failures in step 4 are the place real issues surface; capture the tail of the output.
