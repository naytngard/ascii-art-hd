"""Rebuild ascii-art-hd.skill (a zip of the ascii-art-hd/ folder) so the packaged skill matches the sources.

    python build_skill.py
"""
from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "ascii-art-hd"
FILES = ["SKILL.md", "scripts/ascii_hd.py"]


def build(out: Path = ROOT / "ascii-art-hd.skill") -> Path:
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in FILES:
            info = zipfile.ZipInfo(f"ascii-art-hd/{rel}", date_time=(2026, 1, 1, 0, 0, 0))  # reproducible
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, (SRC / rel).read_bytes())
    return out


if __name__ == "__main__":
    print(f"wrote {build()}")
