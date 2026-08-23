#!/usr/bin/env python3
"""Build a deterministic, runtime-only Skill release archive."""

from __future__ import annotations

import argparse
import stat
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_NAME = "codex-session-lifecycle-manager"
INCLUDE = (
    "SKILL.md",
    "VERSION",
    "LICENSE",
    "README.md",
    "README.en.md",
    "SECURITY.md",
    "SECURITY.en.md",
    "agents",
    "assets",
    "docs",
    "references",
    "scripts",
)
EXCLUDED_NAMES = {"__pycache__", ".DS_Store"}


def included_files() -> list[Path]:
    files: list[Path] = []
    for name in INCLUDE:
        path = ROOT / name
        candidates = [path] if path.is_file() else path.rglob("*")
        files.extend(
            candidate
            for candidate in candidates
            if candidate.is_file()
            and not any(part in EXCLUDED_NAMES for part in candidate.parts)
            and candidate.suffix != ".pyc"
        )
    return sorted(set(files), key=lambda path: path.as_posix())


def build_archive(output_dir: Path) -> Path:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"{SKILL_NAME}-v{version}.zip"
    files = included_files()
    if [path for path in files if path.name == "SKILL.md"] != [ROOT / "SKILL.md"]:
        raise RuntimeError("release package must contain exactly one root SKILL.md")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in files:
            relative = path.relative_to(ROOT)
            info = zipfile.ZipInfo(f"{SKILL_NAME}/{relative.as_posix()}")
            info.date_time = (1980, 1, 1, 0, 0, 0)
            mode = path.stat().st_mode
            permissions = 0o755 if mode & stat.S_IXUSR else 0o644
            info.external_attr = permissions << 16
            bundle.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the installable Skill release archive.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    archive = build_archive(args.output_dir.expanduser().resolve())
    print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
