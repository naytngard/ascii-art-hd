#!/usr/bin/env python3
"""ascii_hd.py - high-resolution, per-character-colour ASCII art.

Sub-commands
  image   one picture            -> still ASCII art
  frames  animated GIF / folder  -> animated ASCII art
  obj     Wavefront .obj mesh    -> rotating turntable ASCII art

Outputs (--formats): txt, ansi, html, png, json
  txt   plain text; frames separated by ===FRAME=== (ASCII Mate compatible)
  ansi  24-bit colour escape codes for a terminal
  html  self-contained page (animated when there is more than one frame)
  png   rendered preview of one frame (--png-frame)
  json  ASCII Mate .ascii.json (schema 2.0, palette of <= 62 colours)

Needs: Python 3.10+, Pillow, NumPy.   No other dependencies.
"""
from __future__ import annotations

import argparse
import copy
import html as html_lib
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageSequence

# Printable ASCII only, so every font renders it and the art survives copy/paste.
DEFAULT_CHARSET = " .'`^\",:;Il!i><~+_-?][}{1)(|/\\tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$"
FONT_CANDIDATES = [
    "consola.ttf", "CascadiaMono.ttf", "DejaVuSansMono.ttf",
    "LiberationMono-Regular.ttf", "cour.ttf", "Menlo.ttc", "Monaco.ttf",
]
PALETTE_KEYS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
# Presets for --charset. "smooth" has no letters/digits, so small cells read as shading, not as text.
CHARSET_PRESETS = {
    "smooth": " .:;+*%#$@",
    "detailed": DEFAULT_CHARSET,
}


# ----------------------------------------------------------------------------
# fonts and ink-density ramp
# ----------------------------------------------------------------------------
def load_font(size: int, path: Optional[str] = None) -> ImageFont.ImageFont:
    for cand in ([path] if path else []) + FONT_CANDIDATES:
        try:
            return ImageFont.truetype(cand, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:  # very old Pillow
        return ImageFont.load_default()


def resolve_charset(value: str) -> str:
    """'smooth' / 'detailed' (case-insensitive) -> preset; anything else is used as the literal characters."""
    return CHARSET_PRESETS.get(value.strip().lower(), value) if value.strip() else CHARSET_PRESETS["smooth"]


def build_ramp(charset: str, font_path: Optional[str] = None) -> Tuple[List[str], np.ndarray]:
    """Sort characters by how much ink they really put on a cell (measured, not guessed)."""
    charset = resolve_charset(charset)
    font = load_font(24, font_path)
    chars = list(dict.fromkeys(charset))
    if " " not in chars:
        chars.insert(0, " ")
    dens = []
    for ch in chars:
        im = Image.new("L", (32, 40), 0)
        ImageDraw.Draw(im).text((4, 4), ch, fill=255, font=font)
        dens.append(float(np.asarray(im, dtype=np.float32).mean()))
    order = np.argsort(dens, kind="stable")
    sorted_chars = [chars[i] for i in order]
    d = np.array([dens[i] for i in order], dtype=np.float32)
    peak = float(d.max())
    d = d / peak if peak > 0 else d
    return sorted_chars, d


# ----------------------------------------------------------------------------
# core: picture -> cells
# ----------------------------------------------------------------------------
@dataclass
class Cells:
    rows: List[str]          # text rows, all the same width
    colors: np.ndarray       # (rows, cols, 3) uint8


def split_rgba(img: Image.Image) -> Tuple[Image.Image, Image.Image]:
    rgba = img.convert("RGBA")
    alpha = rgba.getchannel("A")
    backdrop = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
    rgb = Image.alpha_composite(backdrop, rgba).convert("RGB")
    return rgb, alpha


def grid_size(img: Image.Image, cols: int, aspect: float) -> Tuple[int, int]:
    w, h = img.size
    return cols, max(1, int(round(h / w * cols * aspect)))


def luminance(rgb: np.ndarray) -> np.ndarray:
    return rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def lift_shadows(lum: np.ndarray, amount: float) -> np.ndarray:
    """Open up dark tones without touching highlights or pure black.

    lum + 0.6*amount*sqrt(lum)*(1-lum)^2: zero stays zero, 1 stays 1, still monotonic for amount <= 1.
    """
    if amount <= 0:
        return lum
    lum = np.clip(lum, 0.0, 1.0)
    return np.clip(lum + 0.6 * amount * np.sqrt(lum) * (1.0 - lum) ** 2, 0.0, 1.0)


def flood_background(small: np.ndarray, tolerance: float) -> np.ndarray:
    """Cells reachable from the picture border through similar-coloured neighbours (dark/coloured backdrops).

    Reference colour = median of the border cells. A cell joins when it differs from the neighbour it is reached
    from by <= tolerance and from the reference by <= 3*tolerance (RGB distance, 0..1 scale).
    """
    from collections import deque

    rows, cols = small.shape[:2]
    border = np.concatenate([small[0], small[-1], small[:, 0], small[:, -1]])
    ref = np.median(border, axis=0)
    near_ref = np.linalg.norm(small - ref, axis=2) <= 3 * tolerance
    seen = np.zeros((rows, cols), dtype=bool)
    todo: deque = deque()
    for r, c in [(r, c) for r in (0, rows - 1) for c in range(cols)] + [(r, c) for c in (0, cols - 1) for r in range(rows)]:
        if near_ref[r, c] and not seen[r, c]:
            seen[r, c] = True
            todo.append((r, c))
    while todo:
        r, c = todo.popleft()
        for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
            if 0 <= nr < rows and 0 <= nc < cols and not seen[nr, nc] and near_ref[nr, nc] \
                    and np.linalg.norm(small[nr, nc] - small[r, c]) <= tolerance:
                seen[nr, nc] = True
                todo.append((nr, nc))
    return seen


def cell_grid(img: Image.Image, args) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(small RGB 0..1, lifted luminance, live mask) for the cell grid of one picture."""
    cols, rows = grid_size(img, args.cols, args.aspect)
    rgb, alpha = split_rgba(img)
    small = np.asarray(rgb.resize((cols, rows), Image.LANCZOS), dtype=np.float32) / 255
    a = np.asarray(alpha.resize((cols, rows), Image.LANCZOS), dtype=np.float32) / 255
    lum = luminance(small)
    live = (a > 0.5) & (lum >= args.bg_threshold)   # dark background -> empty cell (judged on the raw luminance)
    if getattr(args, "bg_mode", "threshold") == "flood":
        live &= ~flood_background(small, getattr(args, "bg_tolerance", 0.12))
    return small, lift_shadows(lum, getattr(args, "shadow_lift", 0.0)), live


def parse_crop(text: str) -> Tuple[float, float, float, float]:
    try:
        x0, y0, x1, y1 = (float(p) for p in text.split(","))
    except ValueError:
        raise SystemExit(f"--crop needs four comma-separated numbers x0,y0,x1,y1 (0..1), got {text!r}")
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise SystemExit("--crop needs 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1")
    return x0, y0, x1, y1


def crop_fraction(img: Image.Image, box: Tuple[float, float, float, float]) -> Image.Image:
    w, h = img.size
    x0, y0 = int(round(box[0] * w)), int(round(box[1] * h))
    x1, y1 = max(int(round(box[2] * w)), x0 + 1), max(int(round(box[3] * h)), y0 + 1)
    return img.crop((x0, y0, min(x1, w), min(y1, h)))


def autocrop_box(images: Sequence[Image.Image], args) -> Tuple[float, float, float, float]:
    """Bounding box (fractions) of the live cells over ALL pictures, plus --autocrop-pad. Whole picture if empty."""
    x0 = y0 = 1.0
    x1 = y1 = 0.0
    fine = copy.copy(args)
    fine.cols = max(args.cols, 200)      # detect on a fine grid so a coarse --cols does not make the box sloppy
    for im in images:
        live = cell_grid(im, fine)[2]
        cols_on = np.where(live.sum(axis=0) >= 2)[0]    # >= 2 cells: ignore lone specks
        rows_on = np.where(live.sum(axis=1) >= 2)[0]
        if cols_on.size and rows_on.size:
            h, w = live.shape
            x0, x1 = min(x0, cols_on[0] / w), max(x1, (cols_on[-1] + 1) / w)
            y0, y1 = min(y0, rows_on[0] / h), max(y1, (rows_on[-1] + 1) / h)
    if x1 <= x0 or y1 <= y0:
        return 0.0, 0.0, 1.0, 1.0
    pad = max(args.autocrop_pad, 0.0)
    px, py = (x1 - x0) * pad, (y1 - y0) * pad
    return max(x0 - px, 0.0), max(y0 - py, 0.0), min(x1 + px, 1.0), min(y1 + py, 1.0)


def apply_crop(images: List[Image.Image], args) -> List[Image.Image]:
    """--crop first, then --autocrop inside it; one box for every picture so animations stay registered."""
    if getattr(args, "crop", None):
        box = parse_crop(args.crop)
        images = [crop_fraction(im, box) for im in images]
    if getattr(args, "autocrop", False):
        box = autocrop_box(images, args)
        images = [crop_fraction(im, box) for im in images]
    return images


def measure_levels(img: Image.Image, args) -> Tuple[float, float]:
    _, lum, live = cell_grid(img, args)
    vals = lum[live]
    if vals.size < 8:
        return 0.0, 1.0
    lo, hi = np.percentile(vals, [args.black_point, args.white_point])
    return float(lo), float(max(hi, lo + 1e-3))


def image_to_cells(img: Image.Image, args, ramp, dens, levels=None) -> Cells:
    small, lum, live = cell_grid(img, args)

    lo, hi = levels if levels else measure_levels(img, args)
    tone = np.clip((lum - lo) / (hi - lo), 0.0, 1.0) ** args.gamma
    if args.invert:
        tone = 1.0 - tone

    idx = np.clip(np.searchsorted(dens, tone), 0, len(ramp) - 1)
    ramp_arr = np.array(ramp)
    grid = ramp_arr[idx]

    # directional characters on strong edges: keeps outlines, armour edges, fur strands
    if args.edges > 0:
        gy, gx = np.gradient(lum)
        mag = np.hypot(gx, gy)
        peak = float(np.percentile(mag[live], 99)) if live.any() else 0.0
        if peak > 1e-6:
            strong = (mag / peak > args.edges) & live
            ang = np.arctan2(gx, -gy) % math.pi            # edge direction, image coords
            bins = np.rint(ang / (math.pi / 4)).astype(int) % 4
            edge_chars = np.array(["-", "\\", "|", "/"])
            grid = np.where(strong, edge_chars[bins], grid)

    grid = np.where(live, grid, " ")

    # colour per cell
    if args.color == "mono":
        col = np.repeat(tone[..., None], 3, axis=2)
    elif args.color.startswith("tint:"):
        tint = np.array(hex_to_rgb(args.color[5:]), dtype=np.float32) / 255
        col = tone[..., None] * tint
    else:
        gray = luminance(small)[..., None]
        col = np.clip(gray + (small - gray) * args.saturation, 0, 1)
        if getattr(args, "shadow_lift", 0.0) > 0:       # same lift as the tone, hue preserved
            col = np.clip(col * np.clip(lum[..., None] / np.maximum(gray, 1e-4), 1.0, 4.0), 0, 1)
    peak_ch = col.max(axis=2, keepdims=True)
    boost = np.maximum(peak_ch, args.min_brightness) / np.maximum(peak_ch, 1e-4)
    col = np.clip(col * boost, 0, 1)
    col8 = (col * 255).astype(np.uint8)
    q = max(1, args.quant)
    if q > 1:
        col8 = (np.minimum(col8 // q * q + q // 2, 255)).astype(np.uint8)
    col8[~live] = 0

    return Cells(rows=["".join(r) for r in grid], colors=col8)


def hex_to_rgb(s: str) -> Tuple[int, int, int]:
    s = s.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


# ----------------------------------------------------------------------------
# writers
# ----------------------------------------------------------------------------
def iter_runs(row: str, crow: Sequence[Tuple[int, int, int]]) -> Iterator[Tuple[int, str, Optional[Tuple[int, int, int]]]]:
    """Yield (start_col, text, colour) runs; spaces are colourless."""
    n, i = len(row), 0
    while i < n:
        if row[i] == " ":
            j = i
            while j < n and row[j] == " ":
                j += 1
            yield i, row[i:j], None
            i = j
            continue
        c = crow[i]
        j = i + 1
        while j < n and row[j] != " " and crow[j] == c:
            j += 1
        yield i, row[i:j], c
        i = j


def colour_rows(cells: Cells) -> List[List[Tuple[int, int, int]]]:
    return [[tuple(p) for p in row] for row in cells.colors.tolist()]


def to_txt(frames: List[Cells]) -> str:
    return "\n===FRAME===\n".join("\n".join(c.rows) for c in frames) + "\n"


def to_ansi_frame(cells: Cells) -> str:
    out = []
    for row, crow in zip(cells.rows, colour_rows(cells)):
        line = []
        for _, text, c in iter_runs(row, crow):
            line.append(text if c is None else f"\x1b[38;2;{c[0]};{c[1]};{c[2]}m{text}")
        out.append("".join(line) + "\x1b[0m")
    return "\n".join(out)


def to_html_frame(cells: Cells) -> str:
    out = []
    for row, crow in zip(cells.rows, colour_rows(cells)):
        parts = []
        for _, text, c in iter_runs(row, crow):
            esc = html_lib.escape(text, quote=False)
            parts.append(esc if c is None else f'<span style="color:#{c[0]:02x}{c[1]:02x}{c[2]:02x}">{esc}</span>')
        out.append("".join(parts))
    return "\n".join(out)


def to_html(frames: List[Cells], fps: float, title: str, bg: str, font_px: int) -> str:
    rendered = [to_html_frame(c) for c in frames]
    safe_title = html_lib.escape(title)
    data = json.dumps(rendered, ensure_ascii=True).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{safe_title}</title>
<style>
html,body{{margin:0;background:{bg};}}
body{{display:flex;min-height:100vh;align-items:center;justify-content:center;}}
pre{{margin:16px;font:{font_px}px/{font_px}px Consolas,"Cascadia Mono","DejaVu Sans Mono",monospace;letter-spacing:0;color:#ccc;}}
</style></head><body><pre id="a"></pre>
<script>
const F={data};const fps={fps:.3f};const pre=document.getElementById("a");let i=0;
function show(){{pre.innerHTML=F[i];i=(i+1)%F.length;}}
show();if(F.length>1)setInterval(show,1000/fps);
</script></body></html>
"""


def to_png(cells: Cells, path: Path, font_size: int, bg: Tuple[int, int, int], font_path: Optional[str]) -> None:
    font = load_font(font_size, font_path)
    cw = font.getlength("M")
    asc, desc = font.getmetrics()
    lh = asc + desc
    cols = len(cells.rows[0]) if cells.rows else 1
    img = Image.new("RGB", (int(math.ceil(cw * cols)) + 8, lh * len(cells.rows) + 8), bg)
    draw = ImageDraw.Draw(img)
    for r, (row, crow) in enumerate(zip(cells.rows, colour_rows(cells))):
        for start, text, c in iter_runs(row, crow):
            if c is not None:
                draw.text((4 + start * cw, 4 + r * lh), text, fill=c, font=font)
    img.save(path)


def to_ascii_mate_json(frames: List[Cells], name: str, ident: str, author: str, fps: float) -> dict:
    """ASCII Mate schema 2.0: frames + palette_map + color_frames (<= 62 colours)."""
    pixels = np.concatenate([c.colors.reshape(-1, 3)[np.array(list("".join(c.rows))) != " "] for c in frames])
    if len(pixels) == 0:
        pixels = np.zeros((1, 3), dtype=np.uint8)
    strip = Image.fromarray(pixels.reshape(-1, 1, 3).astype(np.uint8), "RGB")
    quant = strip.quantize(colors=len(PALETTE_KEYS), method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    pal = quant.getpalette() or []
    used = sorted(set(np.asarray(quant).reshape(-1).tolist()))
    key_for = {idx: PALETTE_KEYS[n] for n, idx in enumerate(used)}
    palette_map = {key_for[i]: "#{:02X}{:02X}{:02X}".format(*pal[3 * i:3 * i + 3]) for i in used}

    pal_rgb = np.array([pal[3 * i:3 * i + 3] for i in used], dtype=np.int32)
    keys = [key_for[i] for i in used]
    color_frames = []
    for c in frames:
        flat = c.colors.reshape(-1, 3).astype(np.int32)
        nearest = ((flat[:, None, :] - pal_rgb[None, :, :]) ** 2).sum(axis=2).argmin(axis=1)
        text = np.array(list("".join(c.rows)))
        chars = np.where(text == " ", " ", np.array(keys)[nearest])
        w = len(c.rows[0])
        color_frames.append("\n".join("".join(chars[i:i + w]) for i in range(0, len(chars), w)))
    return {
        "schema_version": "2.0",
        "id": ident,
        "name": name,
        "category": "Topluluk / Özel Eklenenler",
        "author": author,
        "tags": ["hd", "ascii-art-hd"],
        "default_fps": float(fps),
        "recommended_color": "auto",
        "particles": {"enabled_by_default": False, "type": "none", "toggle_label": "Parçacık Efekti",
                      "spawn_area": "bottom", "density": "medium", "chars": ["*", ".", "+"]},
        "frames": ["\n".join(c.rows) for c in frames],
        "palette_map": palette_map,
        "color_frames": color_frames,
    }


def slug(text: str) -> str:
    import re
    s = re.sub(r"[^a-z0-9_]+", "_", text.lower().translate(str.maketrans("çğıöşü", "cgiosu"))).strip("_")
    return s or "ascii_art"


def emit(frames: List[Cells], args, fps: float) -> None:
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    base = slug(args.name)
    formats = [f.strip() for f in args.formats.split(",") if f.strip()]
    bg = hex_to_rgb(args.bg)
    written = []
    if "txt" in formats:
        p = out / f"{base}.txt"
        p.write_text(to_txt(frames), encoding="utf-8")
        written.append(p)
    if "ansi" in formats:
        p = out / f"{base}.ansi.txt"
        p.write_text("\n".join(to_ansi_frame(c) for c in frames[:1]) + "\n", encoding="utf-8")
        written.append(p)
    if "html" in formats:
        p = out / f"{base}.html"
        p.write_text(to_html(frames, fps, args.name, args.bg, args.html_font_px), encoding="utf-8")
        written.append(p)
    if "png" in formats:
        p = out / f"{base}.png"
        to_png(frames[min(args.png_frame, len(frames) - 1)], p, args.png_font_size, bg, args.font)
        written.append(p)
    if "json" in formats:
        p = out / f"{base}.ascii.json"
        data = to_ascii_mate_json(frames, args.name, base, args.author, fps)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        written.append(p)
    rows, cols = len(frames[0].rows), len(frames[0].rows[0])
    print(f"{len(frames)} frame(s), {cols}x{rows} cells ({cols * rows} characters per frame)")
    for p in written:
        print(f"  wrote {p}  ({p.stat().st_size / 1024:.0f} KiB)")
    if len(frames) * cols * rows > 2_000_000:
        print("  note: large output - consider fewer --cols or --max-frames for desktop widgets", file=sys.stderr)


# ----------------------------------------------------------------------------
# OBJ turntable
# ----------------------------------------------------------------------------
def load_obj(path: Path, up: str) -> Tuple[np.ndarray, np.ndarray]:
    verts, faces = [], []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("v "):
            verts.append([float(x) for x in line.split()[1:4]])
        elif line.startswith("f "):
            idx = [int(p.split("/")[0]) for p in line.split()[1:]]
            idx = [i - 1 if i > 0 else len(verts) + i for i in idx]
            for k in range(1, len(idx) - 1):
                faces.append([idx[0], idx[k], idx[k + 1]])
    if not verts or not faces:
        raise SystemExit("OBJ has no vertices/faces")
    v = np.array(verts, dtype=np.float64)
    if up == "z":                      # Z-up models (Blender default) -> Y-up
        v = np.stack([v[:, 0], v[:, 2], -v[:, 1]], axis=1)
    centre = (v.min(axis=0) + v.max(axis=0)) / 2
    v = v - centre
    v /= max(float(np.linalg.norm(v, axis=1).max()), 1e-9)
    return v, np.array(faces, dtype=np.int64)


def vertex_normals(v: np.ndarray, f: np.ndarray) -> np.ndarray:
    fn = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    vn = np.zeros_like(v)
    for k in range(3):
        np.add.at(vn, f[:, k], fn)
    return vn / np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-12)


def rotation(yaw: float, pitch: float) -> np.ndarray:
    cy, sy, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
    return rx @ ry


KEY_LIGHT = np.array([-0.45, 0.55, 0.70]) / np.linalg.norm([-0.45, 0.55, 0.70])
FILL_LIGHT = np.array([0.6, -0.1, 0.5]) / np.linalg.norm([0.6, -0.1, 0.5])
HALF_VEC = (KEY_LIGHT + np.array([0.0, 0.0, 1.0])) / np.linalg.norm(KEY_LIGHT + np.array([0.0, 0.0, 1.0]))


def raster(v: np.ndarray, vn: np.ndarray, f: np.ndarray, W: int, H: int,
           base: np.ndarray, light: np.ndarray) -> Image.Image:
    scale = 0.46 * min(W, H)
    sx, sy, sz = v[:, 0] * scale + W / 2, -v[:, 1] * scale + H / 2, v[:, 2]
    zbuf = np.full((H, W), -np.inf, dtype=np.float32)
    rgb = np.zeros((H, W, 4), dtype=np.uint8)
    for a, b, c in f:
        x0, y0, x1, y1, x2, y2 = sx[a], sy[a], sx[b], sy[b], sx[c], sy[c]
        minx, maxx = max(int(math.floor(min(x0, x1, x2))), 0), min(int(math.ceil(max(x0, x1, x2))), W - 1)
        miny, maxy = max(int(math.floor(min(y0, y1, y2))), 0), min(int(math.ceil(max(y0, y1, y2))), H - 1)
        if minx > maxx or miny > maxy:
            continue
        den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(den) < 1e-9:
            continue
        px, py = np.meshgrid(np.arange(minx, maxx + 1) + 0.5, np.arange(miny, maxy + 1) + 0.5)
        w0 = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / den
        w1 = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / den
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-4) & (w1 >= -1e-4) & (w2 >= -1e-4)
        if not inside.any():
            continue
        z = w0 * sz[a] + w1 * sz[b] + w2 * sz[c]
        zb = zbuf[miny:maxy + 1, minx:maxx + 1]
        upd = inside & (z > zb)
        if not upd.any():
            continue
        n = w0[..., None] * vn[a] + w1[..., None] * vn[b] + w2[..., None] * vn[c]
        n /= np.maximum(np.linalg.norm(n, axis=2, keepdims=True), 1e-9)
        n = np.where((n[..., 2] < 0)[..., None], -n, n)          # two-sided shading
        # realistic studio lighting: key + soft fill + sky term + Blinn specular + gentle rim (no outlines)
        diff = np.clip(n @ light, 0.0, 1.0)
        fill = 0.18 * np.clip(n @ FILL_LIGHT, 0.0, 1.0)
        sky = 0.10 * (0.5 + 0.5 * n[..., 1])
        spec = 0.35 * np.clip(n @ HALF_VEC, 0.0, 1.0) ** 40
        rim = 0.18 * (1.0 - np.clip(n[..., 2], 0, 1)) ** 3
        shade = np.clip(0.08 + 0.82 * diff + fill + sky + rim, 0.0, 1.2)
        zb[upd] = z[upd]
        tile = rgb[miny:maxy + 1, minx:maxx + 1]
        lit = base[None, :] * shade[upd][:, None] + 255.0 * spec[upd][:, None]
        tile[upd, :3] = np.clip(lit, 0, 255).astype(np.uint8)
        tile[upd, 3] = 255
    return Image.fromarray(rgb, "RGBA")


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def common_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("size and tone")
    g.add_argument("--cols", type=int, default=160, help="characters per row (default 160; 200+ for photo detail)")
    g.add_argument("--aspect", type=float, default=0.5, help="cell width/height of the target font (default 0.5)")
    g.add_argument("--gamma", type=float, default=0.9, help="<1 brighter mid-tones, >1 darker (default 0.9)")
    g.add_argument("--black-point", type=float, default=2.0, help="percentile mapped to black (default 2)")
    g.add_argument("--white-point", type=float, default=99.0, help="percentile mapped to white (default 99)")
    g.add_argument("--bg-threshold", type=float, default=0.06,
                   help="cells darker than this stay empty/transparent (0 keeps everything; default 0.06)")
    g.add_argument("--invert", action="store_true", help="swap light/dark (for dark text on light paper)")
    g.add_argument("--edges", type=float, default=0.0,
                   help="0 = off. 0.25-0.6 draws - | / \\ along strong edges (outlines, armour, strands)")
    g.add_argument("--charset", default="smooth",
                   help="smooth (default: ' .:;+*%%#$@', reads as shading) | detailed (70 characters, can look like "
                        "text at small sizes) | or the literal characters to use (sorted by measured ink)")
    g.add_argument("--shadow-lift", type=float, default=0.0,
                   help="0..1 opens up dark tones (dark saturated clothing) without blowing highlights; 0 = off")
    g.add_argument("--bg-mode", choices=["threshold", "flood"], default="threshold",
                   help="threshold = cells darker than --bg-threshold are background (default); flood = also every "
                        "similar-coloured cell connected to the picture border")
    g.add_argument("--bg-tolerance", type=float, default=0.12,
                   help="flood mode: max colour step between neighbouring background cells, 0..1 RGB (default 0.12)")
    k = p.add_argument_group("crop")
    k.add_argument("--crop", default=None, metavar="x0,y0,x1,y1",
                   help="keep only this part of the picture, as fractions 0..1 (e.g. 0.2,0,0.8,1); same box for all frames")
    k.add_argument("--autocrop", action="store_true",
                   help="crop to the bounding box of the non-background cells (after --crop), same box for all frames")
    k.add_argument("--autocrop-pad", type=float, default=0.03,
                   help="margin added around the --autocrop box, as a fraction of its size (default 0.03)")
    c = p.add_argument_group("colour")
    c.add_argument("--color", default="source", help="source | mono | tint:#RRGGBB (default source)")
    c.add_argument("--saturation", type=float, default=1.15, help="colour saturation (default 1.15)")
    c.add_argument("--min-brightness", type=float, default=0.28, help="dim cells are lifted to this (default 0.28)")
    c.add_argument("--quant", type=int, default=8, help="colour step; larger = smaller files (default 8, 1 = off)")
    o = p.add_argument_group("output")
    o.add_argument("--out-dir", default="ascii_out")
    o.add_argument("--name", default="ascii art")
    o.add_argument("--author", default="ascii-art-hd")
    o.add_argument("--formats", default="txt,html,png", help="comma list of: txt,ansi,html,png,json")
    o.add_argument("--bg", default="#05070d", help="html/png background colour")
    o.add_argument("--fps", type=float, default=None)
    o.add_argument("--png-frame", type=int, default=0)
    o.add_argument("--png-font-size", type=int, default=9)
    o.add_argument("--html-font-px", type=int, default=6)
    o.add_argument("--font", default=None, help="path to a monospace .ttf for measuring/png")


def run_pictures(images: List[Image.Image], args, fps: float) -> None:
    images = apply_crop(images, args)
    ramp, dens = build_ramp(args.charset, args.font)
    per_frame = [measure_levels(im, args) for im in images]
    levels = (float(np.median([a for a, _ in per_frame])), float(np.median([b for _, b in per_frame])))
    frames = [image_to_cells(im, args, ramp, dens, levels) for im in images]
    emit(frames, args, fps)


def cmd_image(args) -> None:
    run_pictures([Image.open(args.input)], args, args.fps or 1.0)


def cmd_frames(args) -> None:
    src = Path(args.input)
    images: List[Image.Image] = []
    fps = args.fps
    if src.is_dir():
        files = sorted(p for p in src.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp", ".webp"))
        images = [Image.open(p).convert("RGBA") for p in files]
    else:
        gif = Image.open(src)
        durations = []
        for fr in ImageSequence.Iterator(gif):
            images.append(fr.convert("RGBA"))
            durations.append(fr.info.get("duration", 100) or 100)
        if fps is None and durations:
            fps = 1000.0 / (sum(durations) / len(durations))
    images = images[:: max(1, args.step)][: args.max_frames]
    if not images:
        raise SystemExit("no frames found")
    run_pictures(images, args, (fps or 12.0) / max(1, args.step))


def cmd_obj(args) -> None:
    v, f = load_obj(Path(args.input), args.up)
    if len(f) > 30000:
        print(f"warning: {len(f)} triangles - rendering is pure NumPy and may take minutes", file=sys.stderr)
    vn = vertex_normals(v, f)
    base = np.array(hex_to_rgb(args.mesh_color), dtype=np.float64)
    light = KEY_LIGHT
    W = args.cols * 4
    H = int(W * args.ratio)
    pitch = math.radians(args.pitch)
    images = []
    for k in range(args.frames):
        r = rotation(2 * math.pi * k / args.frames, pitch)
        images.append(raster(v @ r.T, vn @ r.T, f, W, H, base, light))
        print(f"\rrendering {k + 1}/{args.frames}", end="", file=sys.stderr)
    print(file=sys.stderr)
    if args.bg_threshold == 0.06:
        args.bg_threshold = 0.0         # mesh background is already transparent
    run_pictures(images, args, args.fps or 12.0)


def main(argv: Optional[Sequence[str]] = None) -> None:
    ap = argparse.ArgumentParser(description="High-resolution colour ASCII art from images, GIFs and OBJ meshes.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("image", help="one picture -> ASCII art")
    p.add_argument("input")
    common_args(p)
    p.set_defaults(fn=cmd_image)

    p = sub.add_parser("frames", help="animated GIF or folder of frames -> animated ASCII art")
    p.add_argument("input")
    p.add_argument("--step", type=int, default=1, help="keep every Nth frame")
    p.add_argument("--max-frames", type=int, default=120)
    common_args(p)
    p.set_defaults(fn=cmd_frames)

    p = sub.add_parser("obj", help="OBJ mesh -> rotating turntable ASCII art")
    p.add_argument("input")
    p.add_argument("--frames", type=int, default=36, help="frames per full turn (default 36)")
    p.add_argument("--pitch", type=float, default=12.0, help="camera tilt in degrees")
    p.add_argument("--up", choices=["y", "z"], default="y", help="model up axis (Blender exports are often z)")
    p.add_argument("--ratio", type=float, default=0.9, help="canvas height/width (default 0.9)")
    p.add_argument("--mesh-color", default="#cfd6e4")
    common_args(p)
    p.set_defaults(fn=cmd_obj)

    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args.fn(args)


if __name__ == "__main__":
    main()
