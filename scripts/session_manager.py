#!/usr/bin/env python3
"""Read-only entry points: scan, report and dashboard."""

from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.core import (  # noqa: E402
    default_app_dir,
    report_html,
    report_markdown,
    scan_catalog,
    write_json,
)
from lib.server import DashboardServer, DashboardState  # noqa: E402


def common_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")))
    parser.add_argument("--app-dir", type=Path, default=default_app_dir())
    parser.add_argument("--pinned-file", type=Path)
    parser.add_argument(
        "--light-log-scan",
        action="store_true",
        help="Sample small logs for deterministic write/tool signals.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex-Session-Manager: 本地会话搜索、阅读与整理")
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="Build a read-only session catalog")
    common_parser(scan)
    scan.add_argument("--output", type=Path)
    scan.add_argument("--pretty", action="store_true")

    report = sub.add_parser("report", help="Generate JSON, Markdown and HTML reports")
    common_parser(report)
    report.add_argument("--output-dir", type=Path)
    report.add_argument(
        "--lang",
        choices=["zh-CN", "en"],
        default="zh-CN",
        help="Report language. Defaults to Chinese.",
    )

    dashboard = sub.add_parser("dashboard", help="Launch token-gated localhost dashboard")
    common_parser(dashboard)
    dashboard.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1"])
    dashboard.add_argument("--port", type=int, default=0)
    dashboard.add_argument("--no-open", action="store_true")
    return parser


def scan_from(args: argparse.Namespace) -> dict:
    return scan_catalog(
        args.codex_home,
        args.app_dir,
        args.pinned_file,
        args.light_log_scan,
    )


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "scan":
        catalog = scan_from(args)
        if args.output:
            write_json(args.output, catalog)
        else:
            print(
                json.dumps(
                    catalog if args.pretty else catalog["summary"],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return 2 if catalog["database_ambiguous"] else 0
    if args.command == "report":
        catalog = scan_from(args)
        output_dir = (args.output_dir or args.app_dir / "reports").expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        write_json(output_dir / "codex-session-audit.json", catalog)
        (output_dir / "codex-session-audit.md").write_text(
            report_markdown(catalog, args.lang), encoding="utf-8"
        )
        (output_dir / "codex-session-audit.html").write_text(
            report_html(catalog, args.lang), encoding="utf-8"
        )
        print(output_dir)
        return 2 if catalog["database_ambiguous"] else 0
    if args.command == "dashboard":
        state = DashboardState(
            args.codex_home,
            args.app_dir,
            SCRIPT_DIR.parent / "assets/dashboard",
            args.pinned_file,
            args.light_log_scan,
        )
        server = DashboardServer((args.host, args.port), state)
        url = f"http://127.0.0.1:{server.server_port}/?launch={state.launch_token}"
        print(url, flush=True)
        if not args.no_open:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
