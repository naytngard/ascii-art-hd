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


def test_bad_obj_is_rejected(tmp_path):
    p = tmp_path / "empty.obj"
    p.write_text("# nothing\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        run("obj", p, "--out-dir", tmp_path)


def test_packaged_skill_matches_sources():
    import zipfile

    with zipfile.ZipFile(ROOT / "ascii-art-hd.skill") as z:
        for rel in ("SKILL.md", "scripts/ascii_hd.py"):
            assert z.read(f"ascii-art-hd/{rel}") == (ROOT / "ascii-art-hd" / rel).read_bytes(), \
                f"{rel} is stale in ascii-art-hd.skill - run python build_skill.py"


def test_skill_md_frontmatter():
    text = (ROOT / "ascii-art-hd" / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: ascii-art-hd\n")
    head = text.split("---")[1]
    assert "description:" in head and len(head) < 1100
