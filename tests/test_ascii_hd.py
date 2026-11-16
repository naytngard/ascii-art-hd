"""Tests for ascii-art-hd/scripts/ascii_hd.py (image, frames, obj; every output format)."""
from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ascii-art-hd" / "scripts" / "ascii_hd.py"

spec = importlib.util.spec_from_file_location("ascii_hd", SCRIPT)
ah = importlib.util.module_from_spec(spec)
sys.modules["ascii_hd"] = ah  # dataclasses need the module to be registered
spec.loader.exec_module(ah)


# ---------------------------------------------------------------- fixtures
@pytest.fixture()
def sphere_png(tmp_path: Path) -> Path:
    H = W = 240
    y, x = np.mgrid[0:H, 0:W]
    r = 90
    d2 = (x - 120) ** 2 + (y - 120) ** 2
    nz = np.sqrt(np.clip(1 - d2 / r ** 2, 0, 1))
    light = np.clip(-0.5 * (x - 120) / r - 0.6 * (y - 120) / r + 0.65 * nz, 0, 1)
    img = np.zeros((H, W, 3), np.float32)
    m = d2 < r * r
    img[m] = np.stack([0.9 * light, 0.7 * light, 0.4 * light], -1)[m]
    p = tmp_path / "sphere.png"
    Image.fromarray((img * 255).astype(np.uint8)).save(p)
    return p


@pytest.fixture()
def ball_gif(tmp_path: Path) -> Path:
    frames = []
    for k in range(6):
        im = np.zeros((80, 120, 3), np.uint8)
        yy, xx = np.mgrid[0:80, 0:120]
        im[(xx - (20 + 15 * k)) ** 2 + (yy - 40) ** 2 < 18 ** 2] = [60, 200, 120]
        frames.append(Image.fromarray(im))
    p = tmp_path / "ball.gif"
    frames[0].save(p, save_all=True, append_images=frames[1:], duration=100, loop=0)
    return p


@pytest.fixture()
def torus_obj(tmp_path: Path) -> Path:
    n, m = 24, 12
    lines = []
    for i in range(n):
        for j in range(m):
            u, v = 2 * math.pi * i / n, 2 * math.pi * j / m
            lines.append("v %f %f %f" % ((1 + 0.35 * math.cos(v)) * math.cos(u), 0.35 * math.sin(v),
                                         (1 + 0.35 * math.cos(v)) * math.sin(u)))
    for i in range(n):
        for j in range(m):
            a, b = i * m + j, ((i + 1) % n) * m + j
            c, d = ((i + 1) % n) * m + (j + 1) % m, i * m + (j + 1) % m
            lines.append("f %d %d %d %d" % (a + 1, b + 1, c + 1, d + 1))
    p = tmp_path / "torus.obj"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def run(*argv: str) -> None:
    ah.main([str(a) for a in argv])


# ---------------------------------------------------------------- unit
def test_ramp_is_sorted_by_measured_ink():
    chars, dens = ah.build_ramp(ah.DEFAULT_CHARSET)
    assert chars[0] == " " and dens[0] == 0.0
    assert np.all(np.diff(dens) >= 0) and math.isclose(float(dens[-1]), 1.0)


def test_hex_to_rgb_and_slug():
    assert ah.hex_to_rgb("#fff") == (255, 255, 255)
    assert ah.hex_to_rgb("102030") == (16, 32, 48)
    assert ah.slug("Şövalye Atı!") == "sovalye_ati"
    assert ah.slug("***") == "ascii_art"


def test_iter_runs_merges_same_colour_and_skips_spaces():
    runs = list(ah.iter_runs("ab  c", [(1, 1, 1), (1, 1, 1), (0, 0, 0), (0, 0, 0), (2, 2, 2)]))
    assert runs == [(0, "ab", (1, 1, 1)), (2, "  ", None), (4, "c", (2, 2, 2))]


def test_image_to_cells_dark_background_stays_empty(sphere_png):
    ns = ah.argparse.Namespace(cols=40, aspect=0.5, gamma=0.9, black_point=2.0, white_point=99.0, bg_threshold=0.06,
                               invert=False, edges=0.0, color="source", saturation=1.15, min_brightness=0.28, quant=8)
    ramp, dens = ah.build_ramp(ah.DEFAULT_CHARSET)
    cells = ah.image_to_cells(Image.open(sphere_png), ns, ramp, dens)
    assert len(cells.rows) == 20 and all(len(r) == 40 for r in cells.rows)
    assert cells.rows[0].strip() == "" and cells.rows[10].strip() != ""  # corner empty, centre drawn
    assert cells.colors[0, 0].tolist() == [0, 0, 0]
    assert all(32 <= ord(ch) < 127 for r in cells.rows for ch in r)  # printable ASCII only


# ---------------------------------------------------------------- CLI end to end
def test_image_all_formats(tmp_path, sphere_png):
    out = tmp_path / "out"
    run("image", sphere_png, "--cols", 60, "--formats", "txt,ansi,html,png,json", "--out-dir", out, "--name", "Ball")
    for suffix in (".txt", ".ansi.txt", ".html", ".png", ".ascii.json"):
        assert (out / f"ball{suffix}").stat().st_size > 0
    data = json.loads((out / "ball.ascii.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == "2.0" and data["id"] == "ball"
    frame, cframe = data["frames"][0].split("\n"), data["color_frames"][0].split("\n")
    assert len(frame) == len(cframe) and all(len(a) == len(b) for a, b in zip(frame, cframe))
    for a, b in zip(frame, cframe):  # every drawn cell has a palette colour, every blank cell none
        for ch, key in zip(a, b):
            assert (ch == " ") == (key == " ")
            assert key == " " or key in data["palette_map"]
    assert len(data["palette_map"]) <= len(ah.PALETTE_KEYS)
    html = (out / "ball.html").read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>") and "<\\/" not in html.split("const F=")[0]


def test_frames_gif_keeps_frame_count_and_fps(tmp_path, ball_gif):
    out = tmp_path / "out"
    run("frames", ball_gif, "--cols", 40, "--formats", "txt,json", "--out-dir", out, "--name", "ball")
    txt = (out / "ball.txt").read_text(encoding="utf-8")
    assert txt.count("===FRAME===") == 5
    data = json.loads((out / "ball.ascii.json").read_text(encoding="utf-8"))
    assert len(data["frames"]) == 6 and math.isclose(data["default_fps"], 10.0)


def test_frames_step_and_max(tmp_path, ball_gif):
    out = tmp_path / "out"
    run("frames", ball_gif, "--cols", 30, "--step", 2, "--max-frames", 2, "--formats", "json", "--out-dir", out)
    data = json.loads((out / "ascii_art.ascii.json").read_text(encoding="utf-8"))
    assert len(data["frames"]) == 2


def test_obj_turntable_is_shaded_not_flat(tmp_path, torus_obj):
    out = tmp_path / "out"
    run("obj", torus_obj, "--cols", 48, "--frames", 3, "--formats", "txt,json", "--out-dir", out, "--name", "t")
    data = json.loads((out / "t.ascii.json").read_text(encoding="utf-8"))
    assert len(data["frames"]) == 3
    drawn = set(data["frames"][0]) - {" ", "\n"}
    assert len(drawn) >= 6  # smooth shading uses many density levels, not a flat fill


def test_obj_render_has_highlight_and_shadow(torus_obj):
    v, f = ah.load_obj(torus_obj, "y")
    img = np.asarray(ah.raster(v, ah.vertex_normals(v, f), f, 160, 120, np.array([200.0, 200.0, 200.0]), ah.KEY_LIGHT))
    lit = img[..., 3] > 0
    lum = img[..., :3].mean(axis=2)[lit]
    assert lit.mean() > 0.15
    assert lum.max() > 220 and lum.min() < 60  # specular highlight and a real shadow side


# ---------------------------------------------------------------- charset presets, crop, shadow lift, flood bg
def cell_args(**over):
    base = dict(cols=60, aspect=0.5, gamma=0.9, black_point=2.0, white_point=99.0, bg_threshold=0.06,
                invert=False, edges=0.0, color="source", saturation=1.15, min_brightness=0.28, quant=8)
    base.update(over)
    return ah.argparse.Namespace(**base)


def sphere_image() -> Image.Image:
    H = W = 240
    y, x = np.mgrid[0:H, 0:W]
    r = 90
    d2 = (x - 120) ** 2 + (y - 120) ** 2
    nz = np.sqrt(np.clip(1 - d2 / r ** 2, 0, 1))
    light = np.clip(-0.5 * (x - 120) / r - 0.6 * (y - 120) / r + 0.65 * nz, 0, 1)
    img = np.zeros((H, W, 3), np.float32)
    m = d2 < r * r
    img[m] = np.stack([0.9 * light, 0.7 * light, 0.4 * light], -1)[m]
    return Image.fromarray((img * 255).astype(np.uint8))


def test_legacy_behaviour_is_unchanged_with_new_options_off():
    """Golden hashes recorded from the code before --shadow-lift/--crop/--bg-mode existed (fixed ramp, no fonts)."""
    import hashlib

    ramp, dens = list(" .:-=+*#%@"), np.linspace(0, 1, 10).astype(np.float32)
    for extra in ({}, dict(shadow_lift=0.0, bg_mode="threshold", crop=None, autocrop=False)):
        cells = ah.image_to_cells(sphere_image(), cell_args(**extra), ramp, dens)
        assert hashlib.sha256("\n".join(cells.rows).encode()).hexdigest() == \
            "7899bac1c3b120f332f8011ae2dafeac8da8d240be5e4993a60ff883f02477f3"
        assert hashlib.sha256(cells.colors.tobytes()).hexdigest() == \
            "65de0a27b16fd6f235e7228184a4a4eb6fd1677797d1b6c6bc04447a9f05eee5"


def test_charset_presets():
    assert ah.resolve_charset("smooth") == " .:;+*%#$@" and ah.resolve_charset("DETAILED") == ah.DEFAULT_CHARSET
    assert ah.resolve_charset("ab ") == "ab " and ah.resolve_charset("") == " .:;+*%#$@"
    chars, _ = ah.build_ramp("smooth")
    assert set(chars) == set(" .:;+*%#$@") and chars[0] == " "
    chars, _ = ah.build_ramp("detailed")
    assert set(chars) == set(ah.DEFAULT_CHARSET)


def test_cli_default_charset_is_smooth_and_detailed_is_selectable(tmp_path, sphere_png):
    out = tmp_path / "o"
    run("image", sphere_png, "--cols", 80, "--formats", "txt", "--out-dir", out, "--name", "d")
    default_txt = (out / "d.txt").read_text(encoding="utf-8")
    assert set(default_txt) <= set(" .:;+*%#$@\n")          # no letters or digits -> no "text soup"
    run("image", sphere_png, "--cols", 80, "--formats", "txt", "--out-dir", out, "--name", "s", "--charset", "smooth")
    assert (out / "s.txt").read_text(encoding="utf-8") == default_txt
    run("image", sphere_png, "--cols", 80, "--formats", "txt", "--out-dir", out, "--name", "det", "--charset", "detailed")
    run("image", sphere_png, "--cols", 80, "--formats", "txt", "--out-dir", out, "--name", "lit",
        "--charset", ah.DEFAULT_CHARSET, "--shadow-lift", 0)
    detailed = (out / "det.txt").read_text(encoding="utf-8")
    assert detailed == (out / "lit.txt").read_text(encoding="utf-8")   # preset == literal, lift 0 == off
    assert detailed != default_txt and len(set(detailed)) > 20


def test_parse_crop_validation():
    assert ah.parse_crop("0.1,0,0.9,0.5") == (0.1, 0.0, 0.9, 0.5)
    for bad in ("1,2,3", "a,b,c,d", "0.5,0,0.2,1", "0,0,1.5,1", "0,0.6,1,0.6"):
        with pytest.raises(SystemExit):
            ah.parse_crop(bad)


def test_crop_matches_manually_cropped_input(tmp_path, sphere_png):
    out = tmp_path / "o"
    run("image", sphere_png, "--cols", 40, "--crop", "0.25,0,0.75,1", "--formats", "txt", "--out-dir", out, "--name", "c")
    manual = tmp_path / "manual.png"
    Image.open(sphere_png).crop((60, 0, 180, 240)).save(manual)
    run("image", manual, "--cols", 40, "--formats", "txt", "--out-dir", out, "--name", "m")
    got = (out / "c.txt").read_text(encoding="utf-8")
    assert got == (out / "m.txt").read_text(encoding="utf-8")
    assert len(got.splitlines()) == 40 and all(len(r) == 40 for r in got.splitlines())   # 120x240 px at --cols 40


def blob_image(x0, y0, x1, y1, size=(200, 100)) -> Image.Image:
    a = np.zeros((size[1], size[0], 3), np.uint8)
    a[y0:y1, x0:x1] = (200, 160, 120)
    return Image.fromarray(a)


def test_autocrop_box_and_cli(tmp_path):
    img = blob_image(80, 20, 120, 80)            # fractions x .4-.6, y .2-.8
    box = ah.autocrop_box([img], ah.argparse.Namespace(**vars(cell_args(cols=100)), autocrop_pad=0.0))
    assert abs(box[0] - 0.4) < 0.03 and abs(box[2] - 0.6) < 0.03 and abs(box[1] - 0.2) < 0.06 and abs(box[3] - 0.8) < 0.06
    p = tmp_path / "b.png"
    img.save(p)
    out = tmp_path / "o"
    run("image", p, "--cols", 30, "--autocrop", "--autocrop-pad", 0.05, "--formats", "txt", "--out-dir", out, "--name", "a")
    rows = (out / "a.txt").read_text(encoding="utf-8").splitlines()
    filled = [r for r in rows if r.strip()]
    assert len(filled) >= len(rows) - 3                   # the blank border is gone (only the small pad remains)
    run("image", p, "--cols", 30, "--formats", "txt", "--out-dir", out, "--name", "n")
    plain = (out / "n.txt").read_text(encoding="utf-8").splitlines()

    def fill(lines):
        return sum(ch != " " for r in lines for ch in r) / sum(len(r) for r in lines)

    assert fill(rows) > 0.7 and fill(plain) < 0.3         # without autocrop most of the canvas is empty


def test_autocrop_blank_picture_keeps_everything():
    blank = Image.new("RGB", (50, 50), (0, 0, 0))
    assert ah.autocrop_box([blank], ah.argparse.Namespace(**vars(cell_args()), autocrop_pad=0.03)) == (0.0, 0.0, 1.0, 1.0)


def test_frames_use_one_crop_box_covering_every_frame(tmp_path, ball_gif):
    frames = [f.convert("RGBA") for f in ah.ImageSequence.Iterator(Image.open(ball_gif))]
    args = ah.argparse.Namespace(**vars(cell_args(cols=120)), autocrop=True, crop=None, autocrop_pad=0.0)
    cropped = ah.apply_crop(frames, args)
    assert len({im.size for im in cropped}) == 1                       # same box -> same size
    box = ah.autocrop_box(frames, args)
    assert box[0] < 20 / 120 + 0.02 and box[2] > (20 + 75 + 18) / 120 - 0.02   # first and last ball position inside
    out = tmp_path / "o"
    run("frames", ball_gif, "--cols", 40, "--autocrop", "--formats", "txt", "--out-dir", out, "--name", "f")
    frames_txt = (out / "f.txt").read_text(encoding="utf-8").split("\n===FRAME===\n")
    assert len(frames_txt) == 6 and len({len(f.strip("\n").splitlines()) for f in frames_txt}) == 1


def test_shadow_lift_curve():
    x = np.linspace(0, 1, 101, dtype=np.float32)
    assert np.array_equal(ah.lift_shadows(x, 0.0), x)
    y = ah.lift_shadows(x, 1.0)
    assert y[0] == 0.0 and math.isclose(float(y[-1]), 1.0, abs_tol=1e-6) and np.all(np.diff(y) >= 0)
    assert y[5] > x[5] + 0.08                      # dark tones open up
    assert y[90] - x[90] < 0.02                    # highlights stay put


def test_shadow_lift_fills_dark_saturated_cloth():
    a = np.zeros((100, 100, 3), np.uint8)
    a[:, 30:] = (70, 8, 12)                        # dark red cloth, luminance ~0.08 (above the bg threshold)
    a[:, :30] = (230, 220, 200)                    # bright strip so the levels are realistic
    img = Image.fromarray(a)
    ramp, dens = list(" .:-=+*#%@"), np.linspace(0, 1, 10).astype(np.float32)

    def ink(lift):
        c = ah.image_to_cells(img, cell_args(cols=40, shadow_lift=lift, min_brightness=0.0, quant=1), ramp, dens, levels=(0.0, 1.0))
        cloth = [ramp.index(ch) for row in c.rows for ch in row[20:]]
        return float(np.mean(cloth)), float(c.colors[:, 20:].mean())

    ink0, col0 = ink(0.0)
    ink1, col1 = ink(1.0)
    assert ink1 > ink0 + 0.5 and col1 > col0       # denser characters and brighter colour


def test_flood_background_removes_coloured_backdrop_only():
    H, W = 120, 160
    y, x = np.mgrid[0:H, 0:W]
    img = np.zeros((H, W, 3), np.float32)
    img[...] = np.stack([0.16 + 0.12 * x / W, 0.06 + 0 * x, 0.30 + 0.1 * y / H], -1)   # purple gradient backdrop
    ring = ((x - 80) ** 2 + (y - 60) ** 2 < 45 ** 2)
    img[ring] = (0.85, 0.75, 0.6)                                                     # bright subject
    hole = ((x - 80) ** 2 + (y - 60) ** 2 < 14 ** 2)
    img[hole] = (0.18, 0.06, 0.32)                                                    # backdrop-coloured, enclosed
    im = Image.fromarray((img * 255).astype(np.uint8))
    ramp, dens = list(" .:-=+*#%@"), np.linspace(0, 1, 10).astype(np.float32)
    thr = ah.image_to_cells(im, cell_args(cols=80, bg_threshold=0.0), ramp, dens)
    fl = ah.image_to_cells(im, cell_args(cols=80, bg_threshold=0.0, bg_mode="flood"), ramp, dens)
    assert all(ch != " " for ch in thr.rows[0])                      # threshold mode keeps the whole backdrop
    assert all(ch == " " for ch in fl.rows[0]) and all(ch == " " for ch in fl.rows[-1])
    assert fl.rows[len(fl.rows) // 2][40] != " "                      # subject survives
    assert fl.rows[len(fl.rows) // 2][len(fl.rows[0]) // 2] != " "     # enclosed backdrop-coloured hole is not reachable


def stage_scene(W=282, H=500) -> Image.Image:
    """Black floor, bright person (35% of the width), dim blue-green panel touching the left edge, dim bags below."""
    a = np.zeros((H, W, 3), np.float32)
    px0, px1, py0, py1 = int(0.325 * W), int(0.675 * W), int(0.15 * H), int(0.85 * H)
    ramp_x = np.linspace(0.85, 0.70, px1 - px0)[None, :, None]
    a[py0:py1, px0:px1] = np.array([0.8, 0.5, 0.9])[None, None, :] * ramp_x          # lum ~0.5-0.6, with a gradient
    a[int(0.2 * H):int(0.6 * H), 0:int(0.22 * W)] = (0.06, 0.20, 0.24)                # lum ~0.17
    for cx in (0.3, 0.5, 0.7):
        a[int(0.9 * H):int(0.96 * H), int((cx - 0.06) * W):int((cx + 0.06) * W)] = (0.12, 0.12, 0.14)
    return Image.fromarray((a * 255).astype(np.uint8))


def test_autocrop_picks_the_prominent_subject_not_the_dim_set():
    img = stage_scene()
    args = cell_args(cols=100, autocrop="subject", autocrop_pad=0.03)
    box = ah.autocrop_box([img], args)
    assert box[0] < 0.325 and box[2] > 0.675 and box[1] < 0.15 and box[3] > 0.85       # covers the whole person
    assert box[2] - box[0] < 0.55                                                      # panel mostly outside
    assert box[0] > 0.22                                                               # ...in fact entirely left of it
    wide = ah.autocrop_box([img], cell_args(cols=100, autocrop="all", autocrop_pad=0.03))
    assert wide[0] == 0.0 and wide[2] - wide[0] > 0.7 and wide[3] > 0.95             # old behaviour = everything
    cropped = ah.apply_crop([img], cell_args(cols=100, autocrop=True, autocrop_pad=0.03, crop=None))[0]
    assert cropped.size[0] < 0.55 * img.size[0]


def test_autocrop_subject_includes_close_blobs_and_ignores_specks():
    a = np.zeros((100, 200, 3), np.uint8)
    a[10:90, 80:120] = (200, 200, 200)       # main
    a[30:60, 125:140] = (90, 90, 90)         # close, dim neighbour (gap 5 px = 2.5% of the width)
    a[2:4, 5:7] = (255, 255, 255)            # far speck
    box = ah.autocrop_box([Image.fromarray(a)], cell_args(cols=200, autocrop="subject", autocrop_pad=0.0))
    assert box[0] > 0.35 and box[2] > 0.69                                            # neighbour included
    assert box[1] > 0.08                                                              # speck ignored


def test_flood_removes_dim_edge_panel_and_keeps_the_person():
    img = stage_scene()
    ramp, dens = list(" .:-=+*#%@"), np.linspace(0, 1, 10).astype(np.float32)
    args = cell_args(cols=80, bg_mode="flood")
    cells = ah.image_to_cells(img, args, ramp, dens)
    lit = cells.colors.any(axis=2)                       # live cells carry colour, background cells are (0,0,0)
    rows, cols = lit.shape

    def region(x0, x1, y0, y1):
        return lit[int(y0 * rows):int(y1 * rows), int(x0 * cols):int(x1 * cols)]

    panel = region(0.0, 0.22, 0.2, 0.6)
    person = region(0.325, 0.675, 0.15, 0.85)
    assert panel.mean() <= 0.10, f"panel still {panel.mean():.0%} drawn"
    assert person.mean() >= 0.98, f"person only {person.mean():.0%} drawn"
    threshold = ah.image_to_cells(img, cell_args(cols=80), ramp, dens).colors.any(axis=2)
    assert threshold[int(0.2 * rows):int(0.6 * rows), 0:int(0.22 * cols)].mean() > 0.9    # without flood the panel stays


def test_flood_ceiling_stops_leak_into_bright_subject():
    a = np.full((60, 60, 3), 0.1, np.float32)
    a[20:40, 20:40] = 0.5                                   # bright block, touching nothing dim by a sharp step
    a[28:32, 28:32] = 0.1                                   # enclosed dim hole
    fill = ah.flood_background(a, tolerance=0.5, lum_max=0.35)    # tolerance huge on purpose: only the ceiling guards
    assert fill[0, 0] and not fill[30, 30] and not fill[25, 25]


def test_new_options_end_to_end(tmp_path, sphere_png):
    out = tmp_path / "o"
    run("image", sphere_png, "--cols", 50, "--shadow-lift", 0.7, "--bg-mode", "flood", "--autocrop", "--crop", "0,0,1,1",
        "--formats", "txt,png,json", "--out-dir", out, "--name", "all")
    assert (out / "all.png").stat().st_size > 0


def test_bad_obj_is_rejected(tmp_path):
    p = tmp_path / "empty.obj"
    p.write_text("# nothing\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        run("obj", p, "--out-dir", tmp_path)


def test_packaged_skill_matches_sources():
    import zipfile

    with zipfile.ZipFile(ROOT / "ascii-art-hd.skill") as z:
        for rel in ("SKILL.md", "scripts/ascii_hd.py"):
            def norm(b: bytes) -> bytes:  # Windows checkouts may use CRLF
                return b.replace(b"\r\n", b"\n")

            assert norm(z.read(f"ascii-art-hd/{rel}")) == norm((ROOT / "ascii-art-hd" / rel).read_bytes()), \
                f"{rel} is stale in ascii-art-hd.skill - run python build_skill.py"


def test_skill_md_frontmatter():
    text = (ROOT / "ascii-art-hd" / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: ascii-art-hd\n")
    head = text.split("---")[1]
    assert "description:" in head and len(head) < 1100
