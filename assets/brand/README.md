# Ignitee Now brand assets

Robo's visual identity is **sampled from igniteenow.com** and defined once for
every surface. Tokens:

| Token | Value | Role |
|---|---|---|
| Navy | `#0A1030` / deep `#070B24` | page/app background |
| Surface | `#141C4A` / elevated `#232960` | cards, panels |
| Indigo | `#3F3E98` (logo disc, structure) / `#8E8CE0` (on-dark secondary text) | structure, selection |
| Ember | `#EF8A22` (accent) with flame gradient `#D52734` → `#DF5A30` → `#EF8A22` | primary accent, focus rings, buttons. Full token list: `BRAND.md` |
| Flame | `#F07A2A` (with `#E03C2E` → `#F5A623` gradient in the logo) | brand spark: prompt sigil, antenna tip, warnings |
| Snow | `#F2F4FF` | text on navy |
| Muted | `#9AA0C7` (dark) / `#5A5F8A` (light) | secondary text |

Sources of truth (edit these to retune the whole product):
- `ui-tui/src/theme.ts` → `DARK_SEEDS` / `LIGHT_SEEDS`
- `apps/desktop/src/themes/presets.ts` → `igniteenowTheme`, `IGNITEENOW_INDIGO`, `IGNITEENOW_CYAN`, `IGNITEENOW_FLAME`
- `apps/desktop/src/styles.css` → `:root` static seeds (first paint before theme hydrates)
- `apps/bootstrap-installer/src/styles.css` → `:root.dark` seeds
- `web/src/themes/presets.ts` → `defaultTheme`, `igniteenowLightTheme`; `web/src/index.css` → `:root` seeds
- `robo_runtime/resources/face/cute-face.html` (mirrored at `apps/desktop/public/robo-face/`, shown in the desktop's voice chat view; everywhere else the desktop shows the mark itself, `apps/desktop/public/robo-face-icon.png`)

## Files in this folder

- `robo-icon-1024.png` — the Robo product mark (original design, in the site's
  robot language: silver shell, cyan eyes, flame antenna, navy backdrop). This
  is the app icon on every platform.
- `igniteenow-mark-from-site.png`, `igniteenow-wordmark-from-site.png`,
  `igniteenow-lockup-from-site.png` — the official logo **cropped from a
  screenshot of igniteenow.com at ~120 px**. Crisp for the docs navbar and
  favicon-size uses; **not** sharp enough for the 1024 px app icon. Replace
  with the vector/hi-res export from the WordPress Media Library when you have
  it (drop it in as `igniteenow-logo-1024.png` and run the script below).

## Replacing the icon with the official Ignitee Now logo

The current app icon is the supplied Robo face on the Ignitee palette. To use
the official Ignitee Now logo instead, export a **1024×1024 PNG with
transparent or charcoal background** and overwrite these files (the desktop
build regenerates `.ico`/`.icns` from `icon.png` on most toolchains; the
Tauri installer wants the exact sizes listed):

```
apps/desktop/assets/icon.png                     1024×1024
apps/desktop/assets/icon.ico / icon.icns         (regenerate from icon.png)
apps/desktop/public/robo-face-icon.png           512×512
apps/desktop/public/apple-touch-icon.png         180×180
apps/bootstrap-installer/public/robo-face-icon.png   512×512
apps/bootstrap-installer/src-tauri/icons/32x32.png   32×32
apps/bootstrap-installer/src-tauri/icons/128x128.png 128×128
apps/bootstrap-installer/src-tauri/icons/128x128@2x.png 256×256
apps/bootstrap-installer/src-tauri/icons/icon.ico / icon.icns
web/public/favicon.ico
website/static/img/logo.png                      512×512
website/static/img/favicon*.png, favicon.ico, apple-touch-icon.png
```

One-liner (from the repo root, with Pillow installed):

```bash
python3 - <<'PY'
from PIL import Image
src = Image.open("assets/brand/igniteenow-logo-1024.png")  # or robo-icon-1024.png.convert("RGBA")
out = {"apps/desktop/assets/icon.png":1024,"apps/desktop/public/robo-face-icon.png":512,
       "apps/desktop/public/apple-touch-icon.png":180,"apps/bootstrap-installer/public/robo-face-icon.png":512,
       "apps/bootstrap-installer/src-tauri/icons/32x32.png":32,"apps/bootstrap-installer/src-tauri/icons/128x128.png":128,
       "apps/bootstrap-installer/src-tauri/icons/128x128@2x.png":256,"website/static/img/logo.png":512,
       "website/static/img/favicon-32x32.png":32,"website/static/img/favicon-16x16.png":16,
       "website/static/img/apple-touch-icon.png":180}
for p,s in out.items(): src.resize((s,s), Image.LANCZOS).save(p)
sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)]
for p in ["apps/desktop/assets/icon.ico","apps/bootstrap-installer/src-tauri/icons/icon.ico","web/public/favicon.ico","website/static/img/favicon.ico"]:
    src.save(p, format="ICO", sizes=sizes)
for p in ["apps/desktop/assets/icon.icns","apps/bootstrap-installer/src-tauri/icons/icon.icns"]:
    src.save(p, format="ICNS")
PY
```

Drop the official file at `assets/brand/igniteenow-logo-1024.png` and run it.
