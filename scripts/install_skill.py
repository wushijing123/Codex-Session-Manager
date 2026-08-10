#!/usr/bin/env python3
"""Create safe shared-skill entry links without overwriting existing installs."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SKILL_NAME = "wushijing-codex-session-manager"
TARGET_DIRS = {
    "codex": ".codex/skills",
    "claude": ".claude/skills",
    "antigravity": ".antigravity/skills",
    "workbuddy": ".workbuddy/skills",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install shared entry links for the Codex session lifecycle manager."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Canonical Skill source. It must be ~/.agents/skills/wushijing-codex-session-manager.",
    )
    parser.add_argument("--home", type=Path, default=Path.home(), help=argparse.SUPPRESS)
    parser.add_argument(
        "--targets",
        nargs="+",
        choices=["all", *TARGET_DIRS],
        default=["all"],
        help="Entry points to create. Defaults to all supported agents.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing.")
    parser.add_argument("--verify", action="store_true", help="Verify links without writing.")
    return parser


def canonical_source(home: Path) -> Path:
    return home.expanduser().resolve() / ".agents" / "skills" / SKILL_NAME


def selected_targets(values: list[str]) -> list[str]:
    return list(TARGET_DIRS) if "all" in values else list(dict.fromkeys(values))


def validate_source(source: Path, home: Path) -> Path:
    source = source.expanduser().resolve()
    expected = canonical_source(home)
    if source != expected:
        raise ValueError(
            f"source_must_be_canonical: clone or move the repository to {expected}"
        )
    skill = source / "SKILL.md"
    if not skill.is_file() or not skill.stat().st_size:
        raise ValueError(f"missing_skill_entry: {skill}")
    return source


def link_status(target: Path, source: Path) -> str:
    if not os.path.lexists(target):
        return "missing"
    if not target.is_symlink():
        return "conflict"
    try:
        return "ok" if target.resolve(strict=True) == source else "conflict"
    except FileNotFoundError:
        return "conflict"


def run(args: argparse.Namespace) -> int:
    home = args.home.expanduser().resolve()
    source = validate_source(args.source, home)
    failures = 0
    for name in selected_targets(args.targets):
        target = home / TARGET_DIRS[name] / SKILL_NAME
        status = link_status(target, source)
        if status == "ok":
            print(f"OK       {name:12} {target} -> {source}")
            continue
        if status == "conflict":
            print(f"CONFLICT {name:12} {target}", file=sys.stderr)
            failures += 1
            continue
        if args.verify:
            print(f"MISSING  {name:12} {target}", file=sys.stderr)
            failures += 1
            continue
        if args.dry_run:
            print(f"CREATE   {name:12} {target} -> {source}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(source, target_is_directory=True)
        print(f"CREATED  {name:12} {target} -> {source}")
    return 1 if failures else 0


def main() -> int:
    try:
        return run(build_parser().parse_args())
    except (OSError, ValueError) as error:
        print(f"ERROR    {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
