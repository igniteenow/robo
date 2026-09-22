"""Create Robo's isolated runtime home without overwriting operator data."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Mapping

from .version import ROBO_VERSION


RESOURCE_ROOT = Path(__file__).resolve().parent / "resources"


def resolve_robo_home(
    environ: Mapping[str, str] | None = None,
    *,
    user_home: Path | None = None,
) -> Path:
    """Resolve the Robo data directory with a cross-platform default."""

    env = os.environ if environ is None else environ
    configured = str(env.get("ROBO_HOME", "")).strip()
    if configured:
        return Path(os.path.expandvars(os.path.expanduser(configured))).resolve()
    base = Path.home() if user_home is None else Path(user_home)
    return (base / ".robo").resolve()


def _write_new_file(path: Path, content: str) -> bool:
    """Atomically create a UTF-8 text file, returning False if it exists."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return False
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.chmod(temp_path, 0o600)
        except OSError:
            pass
        try:
            os.link(temp_path, path)
        except FileExistsError:
            return False
        except OSError:
            # Windows commonly rejects a hard-link depending on the volume.
            # Re-check immediately before the atomic replace so an existing
            # operator file is never silently replaced.
            if path.exists():
                return False
            os.replace(temp_path, path)
            temp_path = Path()
        return True
    finally:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def _copy_new_file(source: Path, destination: Path) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return False
    with source.open("rb") as incoming:
        payload = incoming.read()
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=str(destination.parent)
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as outgoing:
            outgoing.write(payload)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        if destination.exists():
            return False
        os.replace(temp_path, destination)
        temp_path = Path()
        return True
    finally:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def _yaml_path(path: Path) -> str:
    # YAML accepts forward slashes on every supported OS. Double-quoting a
    # native Windows path would turn sequences such as \t into escapes.
    return path.as_posix()


def _default_config(home: Path) -> str:
    model_path = home / "assets" / "wake_word" / "hey_roh_boh.onnx"
    return f"""# Robo runtime configuration
# This file belongs to the operator. Robo upgrades never overwrite it.
model: ""
toolsets:
  - robo-core

model_catalog:
  enabled: false

agent:
  max_turns: 500
  gateway_timeout: 0
  restart_after_turn_timeout: 21600
  api_max_retries: 4
  tool_use_enforcement: true
  intent_ack_continuation: true
  task_completion_guidance: true
  task_focus_guidance: true
  verification_guidance: true
  claim_verification: false
  parallel_tool_call_guidance: true
  environment_probe: true
  verify_on_stop: true
  gateway_notify_interval: 180
  clarify_timeout: 3600

terminal:
  backend: local
  cwd: .
  timeout: 21600
  home_mode: auto

display:
  interface: tui
  skin: robo
  busy_input_mode: steer
  busy_steer_ack_enabled: true
  show_reasoning: true
  show_commentary: true
  interim_assistant_messages: true
  persistent_output: true
  persistent_output_max_lines: 500
  turn_summary: true
  spinner_token_flow: true
  tool_progress_grouping: accumulate
  bell_on_complete: true
  pet:
    enabled: false

approvals:
  mode: smart
  timeout: 0
  cron_mode: deny
  denial_breaker_threshold: 3
  mcp_reload_confirm: true
  destructive_slash_confirm: true

security:
  allow_private_urls: true
  redact_secrets: true
  tirith_enabled: true
  tirith_fail_open: true
  allow_lazy_installs: true

privacy:
  redact_pii: false

memory:
  memory_enabled: true
  user_profile_enabled: true
  write_approval: false
  memory_char_limit: 4400
  user_char_limit: 2750

compression:
  enabled: true
  threshold: 0.5
  target_ratio: 0.2
  protect_last_n: 30
  max_attempts: 3
  in_place: true

sessions:
  auto_prune: false
  auto_archive: false
  retention_days: 3650
  write_json_snapshots: true

skills:
  template_vars: true
  inline_shell: true
  inline_shell_timeout: 60
  guard_agent_created: true
  write_approval: false

curator:
  enabled: true
  interval_hours: 168
  min_idle_hours: 2
  backup:
    enabled: true
    keep: 10

delegation:
  inherit_mcp_toolsets: true
  max_iterations: 100
  max_summary_chars: 48000
  child_timeout_seconds: 0
  max_concurrent_children: 3
  max_spawn_depth: 2
  orchestrator_enabled: true

voice:
  record_key: ctrl+b
  max_recording_seconds: 300
  auto_tts: false
  beep_enabled: true
  thinking_sound: true
  barge_in: true
  stop_phrases:
    - stop
    - wait robo

stt:
  enabled: true
  echo_transcripts: true
  provider: local
  language: en

tts:
  provider: edge
  edge:
    voice: en-US-AriaNeural

wake_word:
  enabled: false
  surface: auto
  capture: auto
  provider: openwakeword
  phrase: hey roh boh
  sensitivity: 0.6
  confirmation_frames: 3
  start_new_session: true
  profile_routing: true
  openwakeword:
    model: {_yaml_path(model_path)}
    inference_framework: ""

checkpoints:
  enabled: true
  max_snapshots: 50
  max_total_size_mb: 2048
  auto_prune: true
  retention_days: 30
  min_interval_hours: 1

desktop:
  auto_continue:
    enabled: true
    freshness_minutes: 360
    max_attempts: 5

hooks_auto_accept: false
"""


def bootstrap_robo_home(home: Path | None = None) -> Path:
    """Seed Robo defaults and assets, preserving every existing user file."""

    target = resolve_robo_home() if home is None else Path(home).resolve()
    target.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(target, 0o700)
    except OSError:
        pass

    copies = {
        RESOURCE_ROOT / "SOUL.md": target / "SOUL.md",
        RESOURCE_ROOT / "skins" / "robo.yaml": target / "skins" / "robo.yaml",
        RESOURCE_ROOT / ".env.example": target / ".env.example",
        RESOURCE_ROOT / "face" / "cute-face.html": target / "assets" / "face" / "cute-face.html",
        RESOURCE_ROOT / "face" / "three.r128.min.js": target / "assets" / "face" / "three.r128.min.js",
        RESOURCE_ROOT / "face" / "THREE-LICENSE.txt": target / "assets" / "face" / "THREE-LICENSE.txt",
        RESOURCE_ROOT / "wake_word" / "hey_roh_boh.onnx": target / "assets" / "wake_word" / "hey_roh_boh.onnx",
        RESOURCE_ROOT / "wake_word" / "hey_roh_boh.tflite": target / "assets" / "wake_word" / "hey_roh_boh.tflite",
    }
    for source, destination in copies.items():
        if source.exists():
            _copy_new_file(source, destination)

    _write_new_file(target / "config.yaml", _default_config(target))
    _write_new_file(target / ".robo-version", f"{ROBO_VERSION}\n")
    return target


def activate_robo_home(home: Path | None = None) -> Path:
    """Set the isolated environment before Robo's compatibility core loads."""

    target = bootstrap_robo_home(home)
    os.environ["ROBO_HOME"] = str(target)
    os.environ["ROBO_HOME"] = str(target)
    os.environ.setdefault("ROBO_TUI", "1")
    return target
