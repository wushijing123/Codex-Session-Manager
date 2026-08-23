#!/usr/bin/env python3
"""Create safe shared-skill entry links without overwriting existing installs."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SKILL_NAME = "codex-session-lifecycle-manager"
LEGACY_SKILL_NAMES = ("wushijing-codex-session-manager",)
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
        help="Canonical Skill source. It must be ~/.agents/skills/codex-session-lifecycle-manager.",
    )
    parser.add_argument("--home", type=Path, default=Path.home(), help=argparse.SUPPRESS)
    parser.add_argument(
        "--targets",
        nargs="+",
        choices=["all", *TARGET_DIRS],
        default=["codex"],
        help="Entry points to create. Defaults to Codex; use --targets all for every agent.",
    )
    parser.add_argument(
        "--migrate-legacy",
        action="store_true",
        help=(
            "Safely rename the legacy ~/.agents/skills/wushijing-codex-session-manager "
            "source and its matching entry links. Existing directories are never overwritten."
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing.")
    parser.add_argument("--verify", action="store_true", help="Verify links without writing.")
    return parser


def canonical_source(home: Path) -> Path:
    return home.expanduser().resolve() / ".agents" / "skills" / SKILL_NAME


def legacy_sources(home: Path) -> tuple[Path, ...]:
    root = home.expanduser().resolve() / ".agents" / "skills"
    return tuple(root / name for name in LEGACY_SKILL_NAMES)


def selected_targets(values: list[str]) -> list[str]:
    return list(TARGET_DIRS) if "all" in values else list(dict.fromkeys(values))


def absolute_without_resolving(path: Path) -> Path:
    absolute = Path(os.path.abspath(os.fspath(path.expanduser())))
    return Path(os.path.realpath(absolute.parent)) / absolute.name


def symlink_destination(target: Path) -> Path | None:
    if not target.is_symlink():
        return None
    raw = Path(os.readlink(target))
    if not raw.is_absolute():
        raw = target.parent / raw
    return absolute_without_resolving(raw)


def matching_symlink(target: Path, source: Path) -> bool:
    destination = symlink_destination(target)
    if destination is None:
        return False
    if destination == absolute_without_resolving(source):
        return True
    try:
        return target.resolve(strict=True) == source.resolve(strict=True)
    except FileNotFoundError:
        return False


def migrate_legacy_source(source: Path, home: Path, *, dry_run: bool = False) -> Path:
    """Move a legacy canonical source and only its installer-owned entry links."""

    source = absolute_without_resolving(source)
    expected = canonical_source(home)
    if source not in legacy_sources(home):
        raise ValueError(f"not_a_legacy_source: {source}")
    skill = source / "SKILL.md"
    if not skill.is_file() or not skill.stat().st_size:
        raise ValueError(f"missing_skill_entry: {skill}")
    if os.path.lexists(expected):
        raise ValueError(
            f"migration_target_exists: {expected}; the legacy source was preserved at {source}"
        )

    migrations: list[tuple[Path, Path]] = []
    for directory in TARGET_DIRS.values():
        entry_root = home / directory
        for legacy_name in LEGACY_SKILL_NAMES:
            legacy_target = entry_root / legacy_name
            if not matching_symlink(legacy_target, source):
                continue
            new_target = entry_root / SKILL_NAME
            if os.path.lexists(new_target) and not (
                matching_symlink(new_target, source)
                or symlink_destination(new_target) == expected
            ):
                raise ValueError(
                    f"migration_entry_conflict: {new_target}; no files were changed"
                )
            migrations.append((legacy_target, new_target))

    if dry_run:
        return expected

    created: list[Path] = []
    replaced: list[tuple[Path, str]] = []
    try:
        for _legacy_target, new_target in migrations:
            if new_target.is_symlink():
                replaced.append((new_target, os.readlink(new_target)))
                new_target.unlink()
            elif not os.path.lexists(new_target):
                created.append(new_target)
            new_target.parent.mkdir(parents=True, exist_ok=True)
            new_target.symlink_to(expected, target_is_directory=True)
        source.rename(expected)
    except OSError:
        for target in reversed(created):
            if target.is_symlink():
                target.unlink()
        for target, destination in reversed(replaced):
            if target.is_symlink():
                target.unlink()
            target.symlink_to(destination, target_is_directory=True)
        raise

    for legacy_target, _new_target in migrations:
        if legacy_target.is_symlink():
            legacy_target.unlink()
    return expected


def validate_source(source: Path, home: Path) -> Path:
    source = absolute_without_resolving(source)
    expected = canonical_source(home)
    if source != expected:
        if source in legacy_sources(home):
            raise ValueError(
                "legacy_source_detected: rerun with --migrate-legacy; "
                f"the installer will move it to {expected} without overwriting existing paths"
            )
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
    requested_source = absolute_without_resolving(args.source)
    if getattr(args, "migrate_legacy", False) and requested_source in legacy_sources(home):
        if args.verify:
            raise ValueError("migrate_legacy_cannot_be_combined_with_verify")
        source = migrate_legacy_source(requested_source, home, dry_run=args.dry_run)
        verb = "MIGRATE" if args.dry_run else "MIGRATED"
        print(f"{verb} legacy source {requested_source} -> {source}")
    else:
        source = validate_source(requested_source, home)
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
