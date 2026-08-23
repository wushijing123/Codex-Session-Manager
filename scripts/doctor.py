#!/usr/bin/env python3
"""Dependency-free project and installation diagnostics."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import unquote

SKILL_NAME = "codex-session-lifecycle-manager"
LEGACY_SKILL_NAMES = ("wushijing-codex-session-manager",)
ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "SKILL.md",
    "VERSION",
    "README.md",
    "README.en.md",
    "CHANGELOG.md",
    "LICENSE",
    "CODE_OF_CONDUCT.md",
    "CODE_OF_CONDUCT.en.md",
    "CONTRIBUTING.md",
    "CONTRIBUTING.en.md",
    "ROADMAP.md",
    "ROADMAP.en.md",
    "SECURITY.md",
    "SECURITY.en.md",
    "agents/openai.yaml",
    "assets/dashboard/index.html",
    "assets/dashboard/i18n.js",
    "assets/dashboard/app.js",
    "assets/dashboard/style.css",
    "scripts/session_manager.py",
    "scripts/session_actions.py",
    "docs/INSTALLATION.md",
    "docs/INSTALLATION.en.md",
    "docs/WORKFLOWS.md",
    "docs/WORKFLOWS.en.md",
    "docs/ARCHITECTURE.md",
    "docs/ARCHITECTURE.en.md",
    "docs/VERIFICATION.md",
    "docs/VERIFICATION.en.md",
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
)
ENTRY_DIRS = (
    ".codex/skills",
    ".claude/skills",
    ".antigravity/skills",
    ".workbuddy/skills",
)


@dataclass(frozen=True)
class Check:
    level: str
    name: str
    detail: str


def add(checks: list[Check], condition: bool, name: str, detail: str) -> None:
    checks.append(Check("pass" if condition else "fail", name, detail))


def check_python(path: Path) -> tuple[bool, str]:
    try:
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
        return True, str(path.relative_to(ROOT))
    except (OSError, SyntaxError, UnicodeError) as error:
        return False, f"{path}: {error}"


def project_checks() -> list[Check]:
    checks: list[Check] = []
    for relative in REQUIRED:
        path = ROOT / relative
        add(checks, path.is_file() and path.stat().st_size > 0, f"file:{relative}", str(path))

    skill_files = [path for path in ROOT.rglob("SKILL.md") if ".git" not in path.parts]
    add(checks, skill_files == [ROOT / "SKILL.md"], "single-skill-entry", f"found {len(skill_files)}")

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    add(checks, bool(re.fullmatch(r"\d+\.\d+\.\d+", version)), "semantic-version", version)
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    add(checks, f"## [{version}]" in changelog, "changelog-version", version)
    for name in ("README.md", "README.en.md"):
        content = (ROOT / name).read_text(encoding="utf-8")
        add(checks, f"`{version}`" in content, f"readme-version:{name}", version)

    for path in sorted((ROOT / "scripts").rglob("*.py")):
        valid, detail = check_python(path)
        add(checks, valid, f"python:{path.relative_to(ROOT)}", detail)

    node = shutil.which("node")
    if node:
        for relative in ("assets/dashboard/i18n.js", "assets/dashboard/app.js"):
            result = subprocess.run(
                [node, "--check", str(ROOT / relative)],
                check=False,
                capture_output=True,
                text=True,
            )
            add(checks, result.returncode == 0, f"node:{relative}", result.stderr.strip() or "syntax ok")
    else:
        checks.append(Check("warn", "node", "Node.js not found; JavaScript syntax was not checked"))

    for path in sorted(ROOT.rglob("*.md")):
        if ".git" in path.parts:
            continue
        content = path.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", content):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            relative = unquote(target.split("#", 1)[0]).strip()
            if not relative:
                continue
            destination = (path.parent / relative).resolve()
            add(
                checks,
                destination.exists(),
                f"link:{path.relative_to(ROOT)}",
                f"{target} -> {destination}",
            )
    return checks


def installation_checks(home: Path) -> list[Check]:
    checks: list[Check] = []
    canonical = home / ".agents" / "skills" / SKILL_NAME
    add(checks, ROOT.resolve() == canonical.resolve(), "canonical-source", str(canonical))
    legacy_root = home / ".agents" / "skills"
    for legacy_name in LEGACY_SKILL_NAMES:
        legacy = legacy_root / legacy_name
        if os.path.lexists(legacy):
            checks.append(
                Check(
                    "warn",
                    "legacy-source",
                    f"{legacy}; run scripts/install_skill.py --migrate-legacy from that directory",
                )
            )

    for index, directory in enumerate(ENTRY_DIRS):
        target = home / directory / SKILL_NAME
        valid = False
        if target.is_symlink():
            try:
                valid = target.resolve(strict=True) == ROOT.resolve()
            except FileNotFoundError:
                valid = False
        required = index == 0
        if valid:
            checks.append(Check("pass", f"entry:{directory.split('/')[0]}", str(target)))
        elif not os.path.lexists(target) and not required:
            checks.append(
                Check(
                    "pass",
                    f"entry:{directory.split('/')[0]}",
                    f"optional entry not installed: {target}",
                )
            )
        else:
            checks.append(
                Check(
                    "fail" if required else "warn",
                    f"entry:{directory.split('/')[0]}",
                    str(target),
                )
            )

        entry_root = home / directory
        for legacy_name in LEGACY_SKILL_NAMES:
            legacy_target = entry_root / legacy_name
            if os.path.lexists(legacy_target):
                checks.append(
                    Check(
                        "warn",
                        f"legacy-entry:{directory.split('/')[0]}",
                        str(legacy_target),
                    )
                )
    return checks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check project integrity and Skill entry links.")
    parser.add_argument("--project-only", action="store_true", help="Skip local agent entry links.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--verbose", action="store_true", help="Print every passing check.")
    parser.add_argument("--home", type=Path, default=Path.home(), help=argparse.SUPPRESS)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    checks = project_checks()
    if not args.project_only:
        checks.extend(installation_checks(args.home.expanduser().resolve()))
    if args.json:
        print(json.dumps([asdict(check) for check in checks], ensure_ascii=False, indent=2))
    else:
        visible = checks if args.verbose else [check for check in checks if check.level != "pass"]
        for check in visible:
            print(f"{check.level.upper():5} {check.name:34} {check.detail}")
        totals = {level: sum(check.level == level for check in checks) for level in ("pass", "warn", "fail")}
        print(f"\n{totals['pass']} passed, {totals['warn']} warnings, {totals['fail']} failed")
    return 1 if any(check.level == "fail" for check in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
