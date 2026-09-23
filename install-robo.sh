#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROBO_HOME="${ROBO_HOME:-$HOME/.robo}"
PYTHON_BIN="${ROBO_PYTHON:-}"
NODE_BIN="${ROBO_NODE:-}"
SKIP_NODE=false

while [ "$#" -gt 0 ]; do
    case "$1" in
        --home)
            ROBO_HOME="$2"
            shift 2
            ;;
        --python)
            PYTHON_BIN="$2"
            shift 2
            ;;
        --node)
            NODE_BIN="$2"
            shift 2
            ;;
        --skip-node)
            SKIP_NODE=true
            shift
            ;;
        -h|--help)
            printf '%s\n' \
                'Robo installer (Linux/macOS/WSL/Termux)' \
                '' \
                'Usage: bash install-robo.sh [--home PATH] [--python PATH] [--node PATH] [--skip-node]'
            exit 0
            ;;
        *)
            printf 'Unknown option: %s\n' "$1" >&2
            exit 2
            ;;
    esac
done

if [ -z "$PYTHON_BIN" ]; then
    for candidate in python3.13 python3.12 python3.11 python3; do
        if command -v "$candidate" >/dev/null 2>&1; then
            PYTHON_BIN="$(command -v "$candidate")"
            break
        fi
    done
fi

if [ -z "$PYTHON_BIN" ] || ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] < (3,14) else 1)' 2>/dev/null; then
    printf '%s\n' 'Robo requires Python 3.11, 3.12, or 3.13.' >&2
    exit 1
fi

if [ -n "$NODE_BIN" ]; then
    if [ ! -x "$NODE_BIN" ]; then
        printf 'The supplied Node.js executable is not executable: %s\n' "$NODE_BIN" >&2
        exit 1
    fi
    NODE_VERSION="$($NODE_BIN --version 2>/dev/null || true)"
    NODE_MAJOR="${NODE_VERSION#v}"
    NODE_MAJOR="${NODE_MAJOR%%.*}"
    if ! [ "$NODE_MAJOR" -ge 22 ] 2>/dev/null; then
        printf 'Robo requires Node.js 22 or newer; found %s\n' "${NODE_VERSION:-unknown}" >&2
        exit 1
    fi
    PATH="$(dirname "$NODE_BIN"):$PATH"
    export PATH
fi

export ROBO_HOME
export ROBO_HOME="$ROBO_HOME"
mkdir -p "$ROBO_HOME"
chmod 700 "$ROBO_HOME" 2>/dev/null || true

if [ -f "$ROOT/.env" ] && [ ! -f "$ROBO_HOME/.env" ]; then
    cp "$ROOT/.env" "$ROBO_HOME/.env"
    chmod 600 "$ROBO_HOME/.env" 2>/dev/null || true
    printf 'Copied existing .env to %s\n' "$ROBO_HOME/.env"
fi

VENV="$ROOT/.venv"
if [ ! -x "$VENV/bin/python" ]; then
    printf 'Creating Robo Python environment...\n'
    "$PYTHON_BIN" -m venv "$VENV"
fi

# A .venv created by uv (developers running the test suite) ships without
# pip. Bootstrap it with ensurepip; if that interpreter cannot, rebuild the
# environment with the Python selected above instead of failing.
if ! "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
    printf 'Existing Python environment has no pip; bootstrapping it...\n'
    if ! "$VENV/bin/python" -m ensurepip --upgrade >/dev/null 2>&1; then
        printf 'Recreating the Robo Python environment...\n'
        rm -rf "$VENV"
        "$PYTHON_BIN" -m venv "$VENV"
    fi
fi

"$VENV/bin/python" -m pip install --upgrade pip setuptools wheel
"$VENV/bin/python" -m pip install --editable "$ROOT"

# The hands-free stack ("Hey Roh Boh", local transcription, spoken replies) is
# three optional extras. Each is installed on its own so one missing wheel
# cannot take the others down, pip's output goes to a log instead of the
# screen, and a one-line summary says what happened.
EXTRAS_LOG="$ROBO_HOME/logs/install-extras.log"
mkdir -p "$(dirname "$EXTRAS_LOG")"
: > "$EXTRAS_LOG"
EXTRAS_OK=""
EXTRAS_FAILED=""
for extra in voice wake edge-tts; do
    echo "Installing the $extra extra..."
    if "$VENV/bin/python" -m pip install --editable "$ROOT[$extra]" >>"$EXTRAS_LOG" 2>&1; then
        EXTRAS_OK="$EXTRAS_OK $extra"
    elif [ "$extra" = "wake" ] && "$VENV/bin/python" -m pip install \
            "openwakeword==0.6.0" "onnxruntime==1.27.0" "sounddevice==0.5.5" >>"$EXTRAS_LOG" 2>&1; then
        # sherpa-onnx (the optional any-phrase engine) had no wheel here; the
        # bundled "hey roh boh" model only needs openWakeWord + ONNX Runtime.
        EXTRAS_OK="$EXTRAS_OK wake(no sherpa-onnx)"
    else
        EXTRAS_FAILED="$EXTRAS_FAILED $extra"
    fi
done
if [ -n "$EXTRAS_OK" ]; then
    echo "Hands-free voice installed:$EXTRAS_OK"
fi
if [ -n "$EXTRAS_FAILED" ]; then
    echo "WARNING: not installed on this platform:$EXTRAS_FAILED" >&2
    echo "         Details: $EXTRAS_LOG   Check: robo doctor" >&2
fi

if [ "$SKIP_NODE" = false ]; then
    # Upstream's audited dependency helper installs a managed Node runtime
    # only when the machine does not already have a compatible one.
    bash "$ROOT/scripts/install.sh" \
        --ensure node \
        --robo-home "$ROBO_HOME" \
        --dir "$ROOT" \
        --non-interactive
fi

BIN_DIR="${ROBO_BIN_DIR:-$HOME/.local/bin}"
mkdir -p "$BIN_DIR"
WRAPPER="$BIN_DIR/robo"
printf '%s\n' \
    '#!/usr/bin/env bash' \
    "export ROBO_HOME=$(printf '%q' "$ROBO_HOME")" \
    "exec $(printf '%q' "$VENV/bin/robo") \"\$@\"" \
    > "$WRAPPER"
chmod 755 "$WRAPPER"

# Restore the terminal in case an earlier session left mouse tracking on
# (the symptom is the shell filling with numbers like "35;111;47M" whenever the
# mouse moves). `robo` does the same on every start.
if [ -t 1 ]; then
    printf '\033[?1006l\033[?1003l\033[?1002l\033[?1000l\033[?1004l\033[?2004l\033[0m\033[?25h'
fi
"$VENV/bin/robo" --robo-version
printf '\nRobo installed. Start it with:\n  robo\n\n'
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    printf 'Add this directory to PATH, then open a new terminal:\n  %s\n' "$BIN_DIR"
fi
