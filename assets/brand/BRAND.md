# Ignitee Now / Robo brand tokens

Sampled from the Ignitee Now logo. This file is the single source of truth;
every surface (CLI/TUI skin, dashboard, desktop, iOS, docs) uses these values.

| Token | Hex | Use |
|---|---|---|
| navy-900 | `#0A1030` | App background |
| navy-800 | `#0E1437` | Panels, cards |
| navy-700 | `#1E255C` | Borders, raised surfaces, circuit lines |
| indigo-500 | `#3F3E98` | Secondary accent, selection, the logo disc |
| indigo-300 | `#8E8CE0` | Secondary text on navy, links at rest |
| flame-red | `#D52734` | Gradient start, destructive/error |
| flame-mid | `#DF5A30` | Gradient middle |
| flame-orange | `#EF8A22` | **Primary accent**, focus ring, gradient end |
| ember-100 | `#FFE9D6` | Primary text on navy (warm white) |
| ash-400 | `#A9AECF` | Muted text |
| ok | `#3FBF7F` | Success |
| warn | `#F2B441` | Warning |

Signature gradient: `linear-gradient(90deg, #D52734, #DF5A30, #EF8A22)`.

Typeface: **Poppins** (SIL Open Font License 1.1, see `fonts/OFL.txt`), weights
400 / 400 italic / 500 / 700, subset to Latin. Monospace: JetBrains Mono (OFL).
The OFL lets Ignitee Now bundle, embed and ship these fonts commercially; its
only conditions are that the licence text travels with the files and the fonts
are not sold on their own.

## Logo

Robo's mark is vector; the master is `robo-mark.svg`. Variants: `robo-mark-plain.svg`
(transparent), `robo-mark-mono.svg` (one colour, `currentColor`), and
`robo-lockup-dark.svg` / `robo-lockup-light.svg` (mark + wordmark, type outlined).
Regenerate every product icon with `python3 assets/brand/build_icons.py`.

Clear space: keep at least the width of one eye free on all sides. Minimum size:
16 px for the tile, 24 px for the lockup. Do not recolour the flame, stretch the
mark, or place the plain mark on a busy photo; use the tile version there.

`igniteenow-lockup-from-site.png` is the Ignitee Now **company** logo as a
low-resolution raster (190 px). Replace it with the designer's source file
before print or store use.
