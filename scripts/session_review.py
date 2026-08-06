#!/usr/bin/env python3
"""Prepare and apply Codex semantic reviews for short archived conversations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.core import (  # noqa: E402
    apply_semantic_review_results,
    build_short_conversation_review_bundle,
    default_app_dir,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Short-conversation semantic review helper")
    parser.add_argument("--app-dir", type=Path, default=default_app_dir())
    sub = parser.add_subparsers(dest="command", required=True)

    export = sub.add_parser("export", help="Scan and export archived conversations up to N turns")
    export.add_argument("--codex-home", type=Path, default=Path.home() / ".codex")
    export.add_argument("--pinned-file", type=Path)
    export.add_argument("--max-turns", type=int, default=3, choices=[1, 2, 3])

    apply = sub.add_parser("apply", help="Validate and cache Codex review results")
    apply.add_argument("--bundle", type=Path, required=True)
    apply.add_argument("--results", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "export":
        result = build_short_conversation_review_bundle(
            args.codex_home,
            args.app_dir,
            args.pinned_file,
            args.max_turns,
        )
    else:
        result = apply_semantic_review_results(
            args.app_dir,
            args.bundle,
            args.results,
        )
    printable = dict(result)
    printable.pop("catalog", None)
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
