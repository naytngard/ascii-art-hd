---
name: ascii-art-hd
description: Turn a picture, animated GIF, frame folder or 3D .obj mesh into high-resolution, per-character-colour ASCII art (still or animated/rotating), with HTML, PNG, ANSI, plain-text and ASCII Mate .ascii.json output. Use when the user wants detailed ASCII art of a subject (knight, horse, animal, logo, portrait, 3D model), a rotating ASCII turntable, a colour ASCII version of an image, or asks why their hand-built low-resolution ASCII/3D art is unrecognisable.
---

# ascii-art-hd

Detailed ASCII art comes from **high resolution plus a real source**, not from clever character choice. Recognisable subjects (a horse's mane, armour, fur) need roughly 160–260 columns, per-character colour and a real picture or mesh underneath. A 50×24 hand-assembled blob of ellipsoids will never read as an animal; do not try to fix that with more shading characters.

`scripts/ascii_hd.py` does the conversion. It needs only Python 3.10+, Pillow and NumPy (`pip install pillow numpy`).

## Workflow

1. **Find out what the source is.** The script converts; it cannot invent a picture.
   - User supplied an image/GIF/frames/OBJ → use it.
   - No source → ask for one, or generate one (draw it with Pillow/NumPy, build a parametric mesh and write an `.obj`, or use an image-generation tool if the session has one). Say clearly which route you took.
   - Copyright: do not convert someone else's artwork into something the user will publish unless they own it or it is CC0/permissively licensed. For public repos prefer own/CC0 sources.
2. **Pick the command.**
   - `image` – one still picture.
   - `frames` – animated GIF or a folder of numbered frames.
   - `obj` – rotating turntable of a mesh (`--up z` for Blender exports, `--pitch` for camera tilt, `--frames` per full turn).
3. **Start with a preview, not the final run.** Default to the *realistic* look: smooth light-and-shadow shading
   only, no outline characters (`--edges 0`, the default). Outlines (`- | / \` along edges) make subjects look like
   cartoons/comics; use `--edges` only when the user explicitly wants line art.
   ```
   python scripts/ascii_hd.py image input.png --cols 200 --formats png,txt --out-dir out
   ```
   For animation, smoothness comes from more frames per loop (36–48) and constant contrast across frames, not from
   a higher FPS.
   Then **look at the PNG** (view the image file). Do not judge the result from the text alone; text dumps lie about proportions and colour.
4. **Tune, then re-render.** See the table below. Change one thing at a time.
5. **Deliver** the formats the user needs and report what was produced, its size and the character count per frame.

## Tuning guide

| Symptom | Change |
|---|---|
| Subject mushy / details lost | raise `--cols` (200–260), lower `--gamma` slightly, `--black-point 4` for more contrast |
| Looks like a cartoon / comic outline | `--edges 0` (default); keep shading only |
| User wants line art | `--edges 0.3`–`0.6` |
| Too noisy / busy | lower `--cols`, raise `--quant` |
| Letters/digits make small cells look like text | `--charset smooth` (default, ` .:;+*%#$@`); `--charset detailed` is the old 70-character set; or pass your own characters |
| Person/portrait photo, subject small in frame | `--autocrop` (or `--crop x0,y0,x1,y1` as 0..1 fractions) - same box for every GIF frame |
| Dark, saturated clothing stays sparse | `--shadow-lift 0.5`–`1` (opens dark tones, highlights untouched; 0 = off) |
| Dark/coloured backdrop (not black) shows up | `--bg-mode flood` (removes similar-coloured cells connected to the border; `--bg-tolerance` 0.08–0.2) |
| Dark subject disappears | lower `--bg-threshold` (e.g. 0.02), raise `--min-brightness` |
| Background shows up as characters | raise `--bg-threshold` (0.08–0.15) |
| Washed out | `--black-point 5 --white-point 98`, `--gamma 1.1` |
| Colours dull | `--saturation 1.4` |
| Looks stretched | `--aspect` must match the font (default 0.5 fits Consolas/Cascadia) |
| Dark text on light paper | `--invert --bg "#ffffff"` |
| Rotating mesh looks flat | `--pitch 20–40`, make sure normals are sane; model Z-up → `--up z` |

**Person / portrait photo** (dark scene, coloured light) - recommended start:
```
python scripts/ascii_hd.py image person.jpg --cols 200 --autocrop --shadow-lift 0.6 --gamma 0.7 --min-brightness 0.45 --bg-threshold 0.10 --formats png,html,txt --out-dir out
```
Add `--bg-mode flood` if a coloured backdrop remains. Keep `--edges 0` (realistic shading, no outline).

Tone mapping uses **measured ink density** of the chosen font, so brightness steps stay even. OBJ turntables are lit like a studio shot (key light, soft fill, sky term, specular highlight, gentle rim) so the form reads in 3D without outlines. Contrast levels are computed once across all frames, so animations do not flicker.

## Output formats (`--formats a,b,c`)

- `txt` – plain text, frames separated by `===FRAME===`.
- `ansi` – first frame with 24-bit terminal colour codes.
- `html` – self-contained page; animated if there are several frames.
- `png` – preview of one frame (`--png-frame N`).
- `json` – ASCII Mate `.ascii.json` (schema 2.0: `frames`, `palette_map`, `color_frames`). Colours are reduced to 62 palette entries, so photos lose some colour fidelity there; use html/png for the best look.

## Using the result in ASCII Mate

Drop the `.ascii.json` onto a running widget, or copy it to `assets/animations/community/`. Keep it modest: 100–140 columns and ≤ 36 frames keeps the widget light. Larger "HD" assets need the HD mode of ASCII Mate (separate feature) to stay cheap on the CPU.

## Limits to state honestly

- Quality is bounded by the source. A blurry or low-contrast image gives blurry ASCII.
- The OBJ rasteriser is pure NumPy: fine up to ~10k triangles; slower above 30k. It uses one flat colour (`--mesh-color`), no textures or MTL.
- No tool here judges aesthetics for you; always inspect the PNG before saying it looks good.
