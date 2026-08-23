#!/usr/bin/env python3
"""Launch the dashboard against a disposable fictional fixture."""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
import sys

sys.path.insert(0, str(SCRIPT_DIR))

from lib.core import write_json  # noqa: E402
from lib.server import DashboardServer, DashboardState  # noqa: E402

ACTIVE_ID = "01900000-0000-7000-8000-00000000d001"
ARCHIVED_ID = "01900000-0000-7000-8000-00000000d002"
COLD_ID = "01900000-0000-7000-8000-00000000d003"
QUARANTINE_ID = "01900000-0000-7000-8000-00000000d004"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch the Codex session lifecycle dashboard with fictional demo data."
    )
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--keep-fixture", action="store_true")
    return parser


def write_log(path: Path, session_id: str, title: str, user_text: str, assistant_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    events = [
        {"type": "session_meta", "payload": {"id": session_id}},
        {
            "type": "response_item",
            "payload": {"role": "user", "content": [{"type": "output_text", "text": user_text}]},
        },
        {
            "type": "response_item",
            "payload": {"role": "assistant", "content": [{"type": "output_text", "text": assistant_text}]},
        },
    ]
    path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in events) + "\n", encoding="utf-8")


def create_threads_db(database: Path, rows: list[dict[str, Any]]) -> None:
    database.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database)
    conn.executescript(
        """
        CREATE TABLE threads (
          id TEXT PRIMARY KEY, rollout_path TEXT NOT NULL, created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL, source TEXT NOT NULL, cwd TEXT NOT NULL,
          title TEXT NOT NULL, tokens_used INTEGER NOT NULL DEFAULT 0,
          has_user_event INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0,
          archived_at INTEGER, cli_version TEXT, first_user_message TEXT,
          agent_role TEXT, model TEXT
        );
        CREATE TABLE thread_spawn_edges (
          parent_thread_id TEXT NOT NULL, child_thread_id TEXT NOT NULL PRIMARY KEY,
          status TEXT NOT NULL
        );
        CREATE TABLE thread_dynamic_tools (
          thread_id TEXT NOT NULL, position INTEGER NOT NULL, name TEXT NOT NULL,
          description TEXT NOT NULL, input_schema TEXT NOT NULL,
          defer_loading INTEGER NOT NULL DEFAULT 0, namespace TEXT,
          PRIMARY KEY(thread_id, position)
        );
        """
    )
    for row in rows:
        conn.execute(
            "INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row["id"],
                row["rollout_path"],
                row["created_at"],
                row["updated_at"],
                "vscode",
                row["cwd"],
                row["title"],
                240,
                1,
                row["archived"],
                row["archived_at"],
                "1.0.0-demo",
                row["first_user_message"],
                None,
                "gpt-5",
            ),
        )
    conn.commit()
    conn.close()


def create_package(root: Path, session_id: str, title: str, cwd: str, action: str, expires_at: str | None = None) -> None:
    package_dir = root / f"{session_id}-demo"
    package_dir.mkdir(parents=True, exist_ok=True)
    stored = package_dir / "session.jsonl"
    write_log(
        stored,
        session_id,
        title,
        f"Fictional request for {title}",
        f"Fictional response for {title}",
    )
    payload = {
        "package_schema_version": 1,
        "session_id": session_id,
        "original_path": f"/demo/{session_id}.jsonl",
        "original_size": stored.stat().st_size,
        "original_sha256": "",
        "stored_file": stored.name,
        "stored_sha256": "",
        "compression": "none",
        "parent_manifest_id": f"demo-{session_id}",
        "lifecycle_action": action,
        "expires_at": expires_at,
        "quarantine_started_at": datetime.now(timezone.utc).isoformat() if action == "quarantine" else None,
        "database_snapshot": {
            "thread": {
                "id": session_id,
                "title": title,
                "cwd": cwd,
                "created_at": int(datetime.now(timezone.utc).timestamp()) - 86400,
                "updated_at": int(datetime.now(timezone.utc).timestamp()) - 3600,
                "source": "vscode",
                "tokens_used": 42,
            },
            "dynamic_tools": [],
            "spawn_edges": [],
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    import hashlib

    digest = hashlib.sha256(stored.read_bytes()).hexdigest()
    payload["original_sha256"] = digest
    payload["stored_sha256"] = digest
    write_json(package_dir / "package.json", payload)


def create_demo_fixture(root: Path) -> dict[str, Path]:
    codex_home = root / ".codex-demo"
    app_dir = root / "app-state"
    cold_root = root / "cold-storage"
    pins = root / "pins.json"
    archived_log = codex_home / "archived_sessions" / f"rollout-demo-{ARCHIVED_ID}.jsonl"
    active_log = codex_home / "sessions" / f"rollout-demo-{ACTIVE_ID}.jsonl"
    write_log(
        active_log,
        ACTIVE_ID,
        "Live product spec review",
        "Please keep refining the launch checklist.",
        "Checklist updated with owners and release notes.",
    )
    write_log(
        archived_log,
        ARCHIVED_ID,
        "Old landing page clean-up",
        "Can we archive the old launch session now?",
        "Yes. It looks inactive and safe to cold-store.",
    )
    now = int(datetime.now(timezone.utc).timestamp())
    create_threads_db(
        codex_home / "state_5.sqlite",
        [
            {
                "id": ACTIVE_ID,
                "rollout_path": str(active_log),
                "created_at": now - 5 * 86400,
                "updated_at": now - 3600,
                "cwd": "/demo/launch-workspace",
                "title": "Live product spec review",
                "first_user_message": "Please keep refining the launch checklist.",
                "archived": 0,
                "archived_at": None,
            },
            {
                "id": ARCHIVED_ID,
                "rollout_path": str(archived_log),
                "created_at": now - 60 * 86400,
                "updated_at": now - 42 * 86400,
                "cwd": "/demo/archive-workspace",
                "title": "Old landing page clean-up",
                "first_user_message": "Can we archive the old launch session now?",
                "archived": 1,
                "archived_at": now - 40 * 86400,
            },
        ],
    )
    create_package(
        cold_root,
        COLD_ID,
        "Reusable pricing notes",
        "/demo/cold-workspace",
        "cold_archive",
    )
    create_package(
        app_dir / "quarantine",
        QUARANTINE_ID,
        "Temporary smoke test thread",
        "/demo/quarantine-workspace",
        "quarantine",
        expires_at=(datetime.now(timezone.utc) + timedelta(days=9)).isoformat(),
    )
    write_json(
        app_dir / "settings.json",
        {
            "cold_storage_dir": str(cold_root),
            "cleanup_age_days": 30,
            "automation_keep_runs": 3,
            "compression": "none",
        },
    )
    write_json(
        app_dir / "plans.json",
        {"version": 1, "plans": {ARCHIVED_ID: "cold_archive"}},
    )
    write_json(
        pins,
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "pinned_ids": [],
        },
    )
    return {"codex_home": codex_home, "app_dir": app_dir, "pinned_file": pins}


def launch_demo(args: argparse.Namespace) -> int:
    temp_root: Path | None = None
    cleanup: tempfile.TemporaryDirectory[str] | None = None
    if args.keep_fixture:
        temp_root = Path(tempfile.mkdtemp(prefix="codex-session-demo-")).resolve()
    else:
        cleanup = tempfile.TemporaryDirectory(prefix="codex-session-demo-")
        temp_root = Path(cleanup.name).resolve()
    fixture = create_demo_fixture(temp_root)
    state = DashboardState(
        fixture["codex_home"],
        fixture["app_dir"],
        SCRIPT_DIR.parent / "assets/dashboard",
        fixture["pinned_file"],
        False,
    )
    server = DashboardServer(("127.0.0.1", args.port), state)
    url = f"http://127.0.0.1:{server.server_port}/?launch={state.launch_token}"
    print(url, flush=True)
    print(f"fixture: {temp_root}", flush=True)
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if cleanup is not None:
            cleanup.cleanup()
    return 0


def main() -> int:
    return launch_demo(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
