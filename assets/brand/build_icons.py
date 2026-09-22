#!/usr/bin/env python3
"""Regenerate every Robo icon from the master vector mark.

    python3 assets/brand/build_icons.py

One source of truth (`assets/brand/robo-mark.svg`) feeds the desktop app, the
bootstrap installer, the web dashboard and the docs site, so the
product can never drift into showing two different logos.

Requirements: Pillow (`pip install pillow`) and the `sharp` npm package for SVG
rasterisation (`npm i -g sharp`, or `npm i sharp` anywhere on NODE_PATH).

Two renderings are produced:
  * tile       rounded navy tile; used where the OS does not mask the icon
               (Windows .ico, macOS .icns, favicons, in-app images).
  * full-bleed square, fully opaque, no rounded corners; used where the OS
               applies its own mask (iOS AppIcon, apple-touch-icon). Apple
               rejects App Store icons that contain an alpha channel.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
BRAND = ROOT / "assets" / "brand"
MASTER = BRAND / "robo-mark.svg"
PLAIN = BRAND / "robo-mark-plain.svg"

# (path relative to repo root, pixel size, rendering)
PNG_TARGETS = [
    ("assets/brand/robo-icon-1024.png", 1024, "tile"),
    ("apps/desktop/assets/icon.png", 1024, "tile"),
    ("apps/desktop/public/robo-face-icon.png", 512, "tile"),
    ("apps/desktop/public/apple-touch-icon.png", 180, "bleed"),
    ("apps/bootstrap-installer/public/robo-face-icon.png", 512, "tile"),
    ("apps/bootstrap-installer/src-tauri/icons/32x32.png", 32, "tile"),
    ("apps/bootstrap-installer/src-tauri/icons/128x128.png", 128, "tile"),
    ("apps/bootstrap-installer/src-tauri/icons/128x128@2x.png", 256, "tile"),
    ("website/static/img/apple-touch-icon.png", 180, "bleed"),
    ("website/static/img/favicon-16x16.png", 16, "tile"),
    ("website/static/img/favicon-32x32.png", 32, "tile"),
    ("website/static/img/logo.png", 256, "plain"),
]
ICO_TARGETS = [
    "apps/desktop/assets/icon.ico",
    "apps/bootstrap-installer/src-tauri/icons/icon.ico",
    "web/public/favicon.ico",
    "website/static/img/favicon.ico",
]
ICNS_TARGETS = [
    "apps/desktop/assets/icon.icns",
    "apps/bootstrap-installer/src-tauri/icons/icon.icns",
]
ICO_SIZES = [16, 32, 48, 64, 128, 256]

RASTERISE_JS = r"""
const sharp = require('sharp'); const fs = require('fs');
const jobs = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
(async () => {
  for (const j of jobs) {
    // Oversample then downscale: crisper small sizes than rendering direct.
    const density = Math.max(72, Math.ceil(72 * (j.size * 2) / 512));
    await sharp(Buffer.from(j.svg), { density }).resize(j.size, j.size).png().toFile(j.out);
  }
})().catch(e => { console.error(e.message); process.exit(1); });
"""


def _variants() -> dict[str, str]:
    tile = MASTER.read_text(encoding="utf-8")
    bleed = tile.replace('<rect width="512" height="512" rx="112" fill="#0A1030"/>',
                         '<rect width="512" height="512" fill="#0A1030"/>')
    if bleed == tile:
        sys.exit("error: tile <rect> not found in robo-mark.svg; update build_icons.py")
    return {"tile": tile, "bleed": bleed, "plain": PLAIN.read_text(encoding="utf-8")}


def _rasterise(jobs: list[dict]) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        spec, script = Path(tmp) / "jobs.json", Path(tmp) / "r.js"
        spec.write_text(json.dumps(jobs), encoding="utf-8")
        script.write_text(RASTERISE_JS, encoding="utf-8")
        env = dict(os.environ)
        try:
            npm_root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
            if npm_root:
                env["NODE_PATH"] = os.pathsep.join(filter(None, [env.get("NODE_PATH"), npm_root]))
        except OSError:
            pass
        done = subprocess.run(["node", str(script), str(spec)], env=env, capture_output=True, text=True)
        if done.returncode:
            sys.exit(f"error: SVG rasterisation failed (is `sharp` installed?)\n{done.stderr}")


def main() -> None:
    svgs = _variants()
    with tempfile.TemporaryDirectory() as tmp:
        jobs = [{"svg": svgs[kind], "size": size, "out": str(ROOT / rel)} for rel, size, kind in PNG_TARGETS]
        masters = {s: str(Path(tmp) / f"tile-{s}.png") for s in sorted(set(ICO_SIZES + [512, 1024]))}
        jobs += [{"svg": svgs["tile"], "size": s, "out": p} for s, p in masters.items()]
        for j in jobs:
            Path(j["out"]).parent.mkdir(parents=True, exist_ok=True)
        _rasterise(jobs)

        # Apple: opaque, no alpha.
        for rel, _size, kind in PNG_TARGETS:
            if kind == "bleed":
                p = ROOT / rel
                Image.open(p).convert("RGB").save(p, optimize=True)

        # .ico — hand Pillow a pre-rendered image per size so 16/32 px are
        # rasterised from vector, not scaled down from 256.
        frames = [Image.open(masters[s]).convert("RGBA") for s in ICO_SIZES]
        for rel in ICO_TARGETS:
            frames[-1].save(ROOT / rel, format="ICO", sizes=[(s, s) for s in ICO_SIZES], append_images=frames[:-1])

        big = Image.open(masters[1024]).convert("RGBA")
        for rel in ICNS_TARGETS:
            big.save(ROOT / rel, format="ICNS")

    print(f"wrote {len(PNG_TARGETS)} png, {len(ICO_TARGETS)} ico, {len(ICNS_TARGETS)} icns from {MASTER.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
