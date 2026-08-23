#!/usr/bin/env python3
"""Destructive lifecycle actions. Never import this module from the dashboard server."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.core import (  # noqa: E402
    default_app_dir,
    discover_database,
    load_pins,
    read_json,
    schema_fingerprint,
    session_id_from_path,
    sha256_file,
    utc_now,
    write_json,
)

DESTRUCTIVE = {"cold_archive", "quarantine", "permanent_delete"}
CONFIRM_PREFIX = {
    "cold_archive": "COLD-ARCHIVE",
    "quarantine": "QUARANTINE-14D",
    "permanent_delete": "PERMANENT-DELETE",
    "restore": "RESTORE",
    "purge": "PURGE-FOREVER",
}


class ActionBlocked(RuntimeError):
    pass


def exact_regular_file(path: Path, allowed_roots: Iterable[Path]) -> Path:
    if not path.is_absolute():
        raise ActionBlocked(f"path_not_absolute:{path}")
    if path.is_symlink():
        raise ActionBlocked(f"symlink_rejected:{path}")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or not stat.S_ISREG(resolved.stat().st_mode):
        raise ActionBlocked(f"not_regular_file:{resolved}")
    roots = [root.expanduser().resolve() for root in allowed_roots]
    if not any(root == resolved.parent or root in resolved.parents for root in roots):
        raise ActionBlocked(f"path_outside_allowed_roots:{resolved}")
    return resolved


def ensure_target_directory(path: Path, forbidden_root: Path | None = None) -> Path:
    path = path.expanduser().resolve()
    if path == Path(path.anchor) or path in {Path.home().resolve(), (Path.home() / ".codex").resolve()}:
        raise ActionBlocked("broad_target_rejected")
    if forbidden_root is not None:
        forbidden = forbidden_root.expanduser().resolve()
        if path == forbidden or forbidden in path.parents or path in forbidden.parents:
            raise ActionBlocked("target_overlaps_codex_home")
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise ActionBlocked("invalid_target_directory")
    return path


def fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def codex_processes(codex_home: Path) -> list[str]:
    if platform.system() == "Windows":
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            check=True,
            capture_output=True,
            text=True,
        )
        return [
            line.strip()
            for line in result.stdout.splitlines()
            if line.lower().startswith('"codex')
        ]
    if platform.system() == "Darwin":
        database_files: list[Path] = []
        for root in (codex_home, codex_home / "sqlite"):
            if not root.is_dir():
                continue
            for database in root.glob("state_*.sqlite"):
                if database.is_file() and not database.is_symlink():
                    database_files.extend(
                        path
                        for path in (
                            database,
                            database.with_name(f"{database.name}-wal"),
                            database.with_name(f"{database.name}-shm"),
                        )
                        if path.is_file() and not path.is_symlink()
                    )
        matches: list[str] = []
        if database_files:
            result = subprocess.run(
                ["lsof", "-nP", *map(str, database_files)],
                capture_output=True,
                text=True,
            )
            matches.extend(
                line.strip() for line in result.stdout.splitlines()[1:] if line.strip()
            )
        app_processes = subprocess.run(
            [
                "pgrep",
                "-fal",
                r"/Applications/(Codex|ChatGPT)\.app/Contents/MacOS/(Codex|ChatGPT)( |$)",
            ],
            capture_output=True,
            text=True,
        )
        matches.extend(line.strip() for line in app_processes.stdout.splitlines() if line.strip())
        return list(dict.fromkeys(matches))
    result = subprocess.run(
        ["ps", "-axo", "pid=,command="],
        check=True,
        capture_output=True,
        text=True,
    )
    markers = ("codex app-server", "/Applications/Codex.app/")
    return [line.strip() for line in result.stdout.splitlines() if any(x in line for x in markers)]


def process_gate(codex_home: Path, fixture_mode: bool, wait_seconds: int = 0) -> None:
    if fixture_mode:
        return
    deadline = time.time() + max(0, wait_seconds)
    matches = codex_processes(codex_home)
    while matches and time.time() < deadline:
        print("WAITING: Codex is still running; close the desktop app completely.", flush=True)
        time.sleep(2)
        matches = codex_processes(codex_home)
    if matches:
        raise ActionBlocked(
            "codex_desktop_still_running: close Codex completely before applying indexed actions"
        )


def connect_rw(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def select_database(codex_home: Path) -> tuple[Path, str]:
    log_ids: set[str] = set()
    for root in (codex_home / "sessions", codex_home / "archived_sessions"):
        if not root.is_dir():
            continue
        for path in root.rglob("*.jsonl"):
            thread_id = session_id_from_path(path)
            if thread_id:
                log_ids.add(thread_id)
    candidates, selected, ambiguous = discover_database(codex_home, log_ids)
    if not selected:
        raise ActionBlocked("no_compatible_database")
    if ambiguous:
        raise ActionBlocked("database_ambiguous")
    candidate = next(item for item in candidates if item.path == selected)
    return Path(selected), candidate.schema_fingerprint


def sqlite_backup(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(source)
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
        if target_conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ActionBlocked("backup_integrity_check_failed")
    finally:
        target_conn.close()
        source_conn.close()
    os.chmod(target, 0o600)
    fsync_file(target)


def immutable_write(path: Path, payload: dict[str, Any]) -> None:
    write_json(path, payload)
    digest_path = path.with_suffix(path.suffix + ".sha256")
    digest_path.write_text(f"{sha256_file(path)}  {path.name}\n", encoding="utf-8")
    os.chmod(path, 0o600)
    os.chmod(digest_path, 0o600)


def verify_immutable(path: Path) -> None:
    digest_path = path.with_suffix(path.suffix + ".sha256")
    expected = digest_path.read_text(encoding="utf-8").split()[0]
    if not expected or expected != sha256_file(path):
        raise ActionBlocked("manifest_hash_mismatch")


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")]


def snapshot_thread(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM threads WHERE id=?", (session_id,)).fetchone()
    if not row:
        raise ActionBlocked(f"thread_not_indexed:{session_id}")
    dynamic = [
        dict(item)
        for item in conn.execute(
            "SELECT * FROM thread_dynamic_tools WHERE thread_id=? ORDER BY position",
            (session_id,),
        )
    ]
    edges = [
        dict(item)
        for item in conn.execute(
            "SELECT * FROM thread_spawn_edges WHERE parent_thread_id=? OR child_thread_id=?",
            (session_id, session_id),
        )
    ]
    return {"thread": dict(row), "dynamic_tools": dynamic, "spawn_edges": edges}


def insert_row(conn: sqlite3.Connection, table: str, row: dict[str, Any]) -> None:
    available = set(table_columns(conn, table))
    if not set(row).issubset(available):
        raise ActionBlocked(f"schema_columns_changed:{table}")
    columns = list(row)
    sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})"
    conn.execute(sql, [row[name] for name in columns])


def resolve_rollout_path(row: dict[str, Any], codex_home: Path) -> Path:
    raw = Path(str(row.get("rollout_path") or "")).expanduser()
    roots = [codex_home / "sessions", codex_home / "archived_sessions"]
    try:
        return exact_regular_file(raw, roots)
    except (FileNotFoundError, ActionBlocked):
        thread_id = str(row["id"]).lower()
        matches = []
        for root in roots:
            if root.is_dir():
                matches.extend(
                    path for path in root.rglob("*.jsonl") if session_id_from_path(path) == thread_id
                )
        if len(matches) != 1:
            raise ActionBlocked(f"rollout_path_unresolved:{thread_id}")
        return exact_regular_file(matches[0], roots)


def same_volume_note(source: Path, target: Path) -> str:
    try:
        return "same_volume_no_system_disk_reclaim" if source.stat().st_dev == target.stat().st_dev else "cross_volume"
    except OSError:
        return "volume_unknown"


def prepare(args: argparse.Namespace) -> Path:
    codex_home = args.codex_home.expanduser().resolve()
    app_dir = args.app_dir.expanduser().resolve()
    app_dir.mkdir(parents=True, exist_ok=True)
    pinned, pin_status = load_pins(args.pinned_file)
    if pin_status != "snapshot":
        raise ActionBlocked("fresh_pinned_snapshot_required")
    database, fingerprint = select_database(codex_home)
    conn = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    items = []
    protected_payload = read_json(app_dir / "protected.json", {"session_ids": []})
    protected = {str(value).lower() for value in protected_payload.get("session_ids", [])}
    try:
        for session_id in sorted(set(value.lower() for value in args.session_id)):
            if session_id in pinned:
                raise ActionBlocked(f"pinned_session:{session_id}")
            if session_id in protected:
                raise ActionBlocked(f"permanent_protection:{session_id}")
            snapshot = snapshot_thread(conn, session_id)
            if snapshot["spawn_edges"]:
                raise ActionBlocked(f"unresolved_parent_child_dependency:{session_id}")
            row = snapshot["thread"]
            if not bool(row.get("archived")):
                raise ActionBlocked(f"session_must_be_archived_first:{session_id}")
            source = resolve_rollout_path(row, codex_home)
            digest = sha256_file(source)
            items.append(
                {
                    "session_id": session_id,
                    "source_path": str(source),
                    "source_size": source.stat().st_size,
                    "source_sha256": digest,
                    "source_mtime_ns": source.stat().st_mtime_ns,
                    "database_snapshot": snapshot,
                }
            )
    finally:
        conn.close()
    manifest_id = f"{int(time.time())}-{uuid.uuid4().hex[:10]}"
    if args.action == "cold_archive":
        if not args.target:
            raise ActionBlocked("cold_storage_target_required")
        target_root = ensure_target_directory(args.target, codex_home)
        if target_root == codex_home or codex_home in target_root.parents:
            raise ActionBlocked("cold_storage_must_be_outside_codex_home")
    elif args.action == "quarantine":
        if len(items) != 1:
            raise ActionBlocked("quarantine_manifest_must_contain_exactly_one_session")
        target_root = ensure_target_directory(app_dir / "quarantine")
    elif args.action == "permanent_delete":
        target_root = ensure_target_directory(app_dir / "delete-staging")
    else:
        raise ActionBlocked("unsupported_prepare_action")
    confirmation = f"{CONFIRM_PREFIX[args.action]} {manifest_id}"
    manifest = {
        "schema_version": 1,
        "manifest_id": manifest_id,
        "created_at": utc_now(),
        "action": args.action,
        "status": "prepared",
        "codex_home": str(codex_home),
        "database_path": str(database),
        "database_schema_fingerprint": fingerprint,
        "target_root": str(target_root),
        "volume_notes": [same_volume_note(Path(item["source_path"]), target_root) for item in items],
        "items": items,
        "confirmation_phrase": confirmation,
        "pin_snapshot_path": str(args.pinned_file.resolve()),
        "quarantine_days": 14 if args.action == "quarantine" else None,
        "quarantine_starts_on_apply": args.action == "quarantine",
        "expires_at": None,
        "content_retained_after_success": args.action != "permanent_delete",
    }
    manifest_path = app_dir / "manifests" / f"{manifest_id}.json"
    immutable_write(manifest_path, manifest)
    print(f"manifest: {manifest_path}")
    if args.show_confirmation:
        print(f"confirm: {confirmation}")
    return manifest_path


def package_item(
    item: dict[str, Any],
    package_dir: Path,
    compression: str,
    parent_manifest: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    source = Path(item["source_path"])
    exact_regular_file(source, [source.parent])
    if sha256_file(source) != item["source_sha256"]:
        raise ActionBlocked(f"source_hash_changed:{item['session_id']}")
    copied = package_dir / "session.jsonl"
    shutil.copyfile(source, copied)
    os.chmod(copied, 0o600)
    fsync_file(copied)
    if sha256_file(copied) != item["source_sha256"]:
        raise ActionBlocked(f"copy_hash_mismatch:{item['session_id']}")
    zstd = shutil.which("zstd")
    output = copied
    compression_used = "none"
    if compression == "zstd" and not zstd:
        raise ActionBlocked("zstd_required_but_missing")
    if compression in {"auto", "zstd"} and zstd:
        compressed = package_dir / "session.jsonl.zst"
        subprocess.run([zstd, "-q", "-T0", "-f", str(copied), "-o", str(compressed)], check=True)
        subprocess.run([zstd, "-q", "-t", str(compressed)], check=True)
        os.chmod(compressed, 0o600)
        compressed_hash = sha256_file(compressed)
        os.unlink(copied)
        output = compressed
        compression_used = "zstd"
    metadata = {
        "package_schema_version": 1,
        "session_id": item["session_id"],
        "original_path": item["source_path"],
        "original_size": item["source_size"],
        "original_sha256": item["source_sha256"],
        "stored_file": output.name,
        "stored_sha256": sha256_file(output),
        "compression": compression_used,
        "parent_manifest_id": parent_manifest["manifest_id"],
        "lifecycle_action": parent_manifest["action"],
        "expires_at": parent_manifest.get("expires_at"),
        "quarantine_started_at": parent_manifest.get("quarantine_started_at"),
        "database_snapshot": item["database_snapshot"],
        "created_at": utc_now(),
    }
    immutable_write(package_dir / "package.json", metadata)
    fsync_dir(package_dir)
    return output, metadata


def delete_index_rows(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute(
        "DELETE FROM thread_spawn_edges WHERE parent_thread_id=? OR child_thread_id=?",
        (session_id, session_id),
    )
    conn.execute("DELETE FROM thread_dynamic_tools WHERE thread_id=?", (session_id,))
    conn.execute("DELETE FROM threads WHERE id=?", (session_id,))


def append_audit(app_dir: Path, event: dict[str, Any]) -> Path:
    audit_dir = app_dir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    path = audit_dir / f"{int(time.time())}-{uuid.uuid4().hex[:8]}.json"
    immutable_write(path, event)
    return path


def clear_completed_session_plans(
    app_dir: Path,
    session_ids: list[str],
    *,
    expected_actions: set[str] | None = None,
) -> None:
    """Remove only the stale plan entries that match the completed action."""
    normalized = {str(session_id).lower() for session_id in session_ids}
    if not normalized:
        return

    plans_payload = read_json(app_dir / "plans.json", {"plans": {}})
    plans = plans_payload.get("plans")
    removed: set[str] = set()
    plans_changed = False
    if isinstance(plans, dict):
        for session_id in normalized:
            action = plans.get(session_id)
            if action is None:
                continue
            if expected_actions is not None and action not in expected_actions:
                continue
            if session_id in plans:
                plans.pop(session_id, None)
                removed.add(session_id)
                plans_changed = True
        if plans_changed:
            plans_payload["plans"] = plans
            write_json(app_dir / "plans.json", plans_payload)

    auto_payload = read_json(app_dir / "auto-plans.json", {"plans": {}})
    auto_plans = auto_payload.get("plans")
    auto_changed = False
    if isinstance(auto_plans, dict):
        for session_id in removed:
            if session_id in auto_plans:
                auto_plans.pop(session_id, None)
                auto_changed = True
        if auto_changed:
            auto_payload["plans"] = auto_plans
            write_json(app_dir / "auto-plans.json", auto_payload)


def mark_restore_verified(app_dir: Path) -> None:
    write_json(
        app_dir / "restore-verified.json",
        {
            "version": 1,
            "verified": True,
            "verified_at": utc_now(),
            "mechanism": "closed_app_restore",
        },
    )


def remove_package_files(package: dict[str, Any]) -> None:
    """Remove only files created by package_item, never a recursive path."""
    directory = Path(package["directory"])
    metadata = package["metadata"]
    candidates = [
        directory / str(metadata["stored_file"]),
        directory / "package.json",
        directory / "package.json.sha256",
    ]
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            os.unlink(candidate)
    try:
        directory.rmdir()
    except OSError as exc:
        raise ActionBlocked(f"package_contains_unexpected_files:{directory}") from exc


def apply_manifest(args: argparse.Namespace) -> None:
    manifest_path = args.manifest.expanduser().resolve()
    verify_immutable(manifest_path)
    manifest = read_json(manifest_path, {})
    if manifest.get("status") != "prepared":
        raise ActionBlocked("manifest_not_prepared")
    if args.confirm != manifest.get("confirmation_phrase"):
        raise ActionBlocked("confirmation_phrase_mismatch")
    codex_home = Path(manifest["codex_home"]).resolve()
    database = Path(manifest["database_path"]).resolve()
    process_gate(codex_home, args.fixture_mode, args.wait_for_exit_seconds)
    current_database, current_fingerprint = select_database(codex_home)
    if current_database != database or current_fingerprint != manifest["database_schema_fingerprint"]:
        raise ActionBlocked("database_or_schema_changed")
    target_root = ensure_target_directory(Path(manifest["target_root"]), codex_home)
    app_dir = args.app_dir.expanduser().resolve()
    backup_path = app_dir / "backups" / f"{manifest['manifest_id']}.sqlite"
    sqlite_backup(database, backup_path)
    compression = "none" if manifest.get("action") == "permanent_delete" else args.compression
    packages: list[dict[str, Any]] = []
    db_committed = False
    permanent_sources_removed = False
    audit_path: Path | None = None
    effective_manifest = dict(manifest)
    if manifest.get("action") == "quarantine":
        started_at = datetime.now(timezone.utc)
        effective_manifest["quarantine_started_at"] = started_at.isoformat()
        effective_manifest["expires_at"] = (
            started_at + timedelta(days=int(manifest.get("quarantine_days") or 14))
        ).isoformat()
    try:
        for item in manifest["items"]:
            source = exact_regular_file(
                Path(item["source_path"]),
                [codex_home / "sessions", codex_home / "archived_sessions"],
            )
            package_dir = target_root / f"{item['session_id']}-{manifest['manifest_id']}"
            if package_dir.exists():
                raise ActionBlocked(f"package_already_exists:{package_dir}")
            package_dir.mkdir(mode=0o700)
            _, metadata = package_item(item, package_dir, compression, effective_manifest)
            packages.append(
                {
                    "directory": str(package_dir),
                    "metadata": metadata,
                    "source": str(source),
                }
            )
        conn = connect_rw(database)
        try:
            conn.execute("BEGIN IMMEDIATE")
            if schema_fingerprint(conn) != manifest["database_schema_fingerprint"]:
                raise ActionBlocked("schema_changed_during_apply")
            for item in manifest["items"]:
                delete_index_rows(conn, item["session_id"])
            conn.commit()
            db_committed = True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        permanent_delete = manifest.get("action") == "permanent_delete"
        event = {
            "event": "permanent_delete" if permanent_delete else manifest["action"],
            "completed_at": utc_now(),
            "manifest_id": manifest["manifest_id"],
            "database_backup_retained": False,
            "session_ids": [item["session_id"] for item in manifest["items"]],
            "content_retained": not permanent_delete,
            "quarantine_started_at": effective_manifest.get("quarantine_started_at"),
            "expires_at": effective_manifest.get("expires_at"),
        }
        if permanent_delete:
            event["bytes_purged"] = sum(
                int(item["source_size"]) for item in manifest["items"]
            )
        else:
            event["packages"] = [entry["directory"] for entry in packages]
        if not permanent_delete:
            audit_path = append_audit(app_dir, event)
        for entry in packages:
            source = exact_regular_file(
                Path(entry["source"]),
                [codex_home / "sessions", codex_home / "archived_sessions"],
            )
            if sha256_file(source) != entry["metadata"]["original_sha256"]:
                raise ActionBlocked(f"source_changed_before_remove:{entry['metadata']['session_id']}")
            os.unlink(source)
        if permanent_delete:
            permanent_sources_removed = True
            for entry in packages:
                remove_package_files(entry)
            os.unlink(backup_path)
            manifest_digest = manifest_path.with_suffix(manifest_path.suffix + ".sha256")
            os.chmod(manifest_path, 0o600)
            os.chmod(manifest_digest, 0o600)
            os.unlink(manifest_path)
            os.unlink(manifest_digest)
            audit_path = append_audit(app_dir, event)
        else:
            os.unlink(backup_path)
        completed_ids = [item["session_id"] for item in manifest["items"]]
        expected_actions = {
            "cold_archive": {"cold_archive"},
            "quarantine": {"quarantine"},
            "permanent_delete": {"permanent_delete", "purge_after_quarantine"},
        }.get(str(manifest.get("action") or ""), set())
        try:
            clear_completed_session_plans(
                app_dir, completed_ids, expected_actions=expected_actions
            )
        except OSError as plan_error:
            # The indexed action is already committed at this point. A local plan-file
            # cleanup failure must not misreport the session move/delete as failed.
            event["plan_cleanup_pending"] = True
            event["plan_cleanup_error"] = type(plan_error).__name__
            try:
                append_audit(
                    app_dir,
                    {
                        "event": "plan_cleanup_pending",
                        "completed_at": utc_now(),
                        "manifest_id": manifest["manifest_id"],
                        "session_ids": completed_ids,
                        "content_retained": not permanent_delete,
                    },
                )
            except OSError:
                pass
        print(json.dumps(event, ensure_ascii=False, indent=2))
    except Exception as exc:
        if permanent_sources_removed:
            if audit_path is None:
                append_audit(
                    app_dir,
                    {
                        "event": "permanent_delete_cleanup_incomplete",
                        "completed_at": utc_now(),
                        "manifest_id": manifest["manifest_id"],
                        "session_ids": [
                            item["session_id"] for item in manifest["items"]
                        ],
                        "bytes_purged": sum(
                            int(item["source_size"]) for item in manifest["items"]
                        ),
                        "content_retained": True,
                        "cleanup_error": type(exc).__name__,
                    },
                )
            raise
        if audit_path and audit_path.exists():
            digest_path = audit_path.with_suffix(audit_path.suffix + ".sha256")
            os.chmod(audit_path, 0o600)
            os.unlink(audit_path)
            if digest_path.exists():
                os.chmod(digest_path, 0o600)
                os.unlink(digest_path)
        if db_committed and backup_path.exists():
            source_conn = sqlite3.connect(backup_path)
            target_conn = sqlite3.connect(database)
            try:
                source_conn.backup(target_conn)
            finally:
                target_conn.close()
                source_conn.close()
        for entry in packages:
            source = Path(entry["source"])
            metadata = entry["metadata"]
            directory = Path(entry["directory"])
            if not source.exists() and directory.is_dir():
                stored = directory / metadata["stored_file"]
                temp = source.with_name(f".{source.name}.{manifest['manifest_id']}.recover")
                if metadata["compression"] == "zstd":
                    zstd = shutil.which("zstd")
                    if not zstd:
                        raise ActionBlocked("zstd_required_for_rollback")
                    subprocess.run([zstd, "-q", "-d", "-f", str(stored), "-o", str(temp)], check=True)
                else:
                    shutil.copyfile(stored, temp)
                if sha256_file(temp) != metadata["original_sha256"]:
                    raise ActionBlocked("rollback_hash_mismatch")
                os.replace(temp, source)
                fsync_dir(source.parent)
        for entry in packages:
            directory = Path(entry["directory"])
            if directory.is_dir():
                for name in ("session.jsonl", "session.jsonl.zst", "package.json", "package.json.sha256"):
                    candidate = directory / name
                    if candidate.is_file() and not candidate.is_symlink():
                        os.unlink(candidate)
                try:
                    directory.rmdir()
                except OSError:
                    pass
        raise


def restore_package(args: argparse.Namespace) -> None:
    package_dir = args.package.expanduser().resolve()
    package_manifest = exact_regular_file(package_dir / "package.json", [package_dir])
    verify_immutable(package_manifest)
    metadata = read_json(package_manifest, {})
    expected = f"{CONFIRM_PREFIX['restore']} {metadata['session_id']}"
    if args.confirm != expected:
        raise ActionBlocked(f"confirmation_phrase_mismatch: expected '{expected}'")
    codex_home = args.codex_home.expanduser().resolve()
    process_gate(codex_home, args.fixture_mode, args.wait_for_exit_seconds)
    database, fingerprint = select_database(codex_home)
    target = Path(metadata["original_path"]).expanduser().resolve()
    allowed_roots = [(codex_home / "sessions").resolve(), (codex_home / "archived_sessions").resolve()]
    if not any(root == target.parent or root in target.parents for root in allowed_roots):
        raise ActionBlocked("restore_path_outside_codex_home")
    if target.exists() or target.is_symlink():
        raise ActionBlocked("restore_target_exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    stored = exact_regular_file(package_dir / metadata["stored_file"], [package_dir])
    if sha256_file(stored) != metadata["stored_sha256"]:
        raise ActionBlocked("stored_hash_mismatch")
    fd, temp_name = tempfile.mkstemp(prefix=".restore-", dir=target.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        if metadata["compression"] == "zstd":
            zstd = shutil.which("zstd")
            if not zstd:
                raise ActionBlocked("zstd_required_for_restore")
            subprocess.run([zstd, "-q", "-d", "-f", str(stored), "-o", str(temp)], check=True)
        else:
            shutil.copyfile(stored, temp)
        if sha256_file(temp) != metadata["original_sha256"]:
            raise ActionBlocked("restored_hash_mismatch")
        conn = connect_rw(database)
        target_installed = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            if schema_fingerprint(conn) != fingerprint:
                raise ActionBlocked("schema_changed_during_restore")
            snapshot = metadata["database_snapshot"]
            if conn.execute("SELECT 1 FROM threads WHERE id=?", (metadata["session_id"],)).fetchone():
                raise ActionBlocked("thread_already_indexed")
            insert_row(conn, "threads", snapshot["thread"])
            for row in snapshot.get("dynamic_tools", []):
                insert_row(conn, "thread_dynamic_tools", row)
            for edge in snapshot.get("spawn_edges", []):
                other = (
                    edge["child_thread_id"]
                    if edge["parent_thread_id"] == metadata["session_id"]
                    else edge["parent_thread_id"]
                )
                if not conn.execute("SELECT 1 FROM threads WHERE id=?", (other,)).fetchone():
                    raise ActionBlocked(f"dependency_missing:{other}")
                insert_row(conn, "thread_spawn_edges", edge)
            os.replace(temp, target)
            target_installed = True
            fsync_dir(target.parent)
            conn.commit()
        except Exception:
            conn.rollback()
            if target_installed and target.exists():
                os.unlink(target)
            raise
        finally:
            conn.close()
        package_files = [
            stored,
            package_manifest,
            exact_regular_file(package_manifest.with_suffix(".json.sha256"), [package_dir]),
        ]
        for path in package_files:
            os.unlink(path)
        package_dir.rmdir()
        append_audit(
            args.app_dir.expanduser().resolve(),
            {
                "event": "restore",
                "completed_at": utc_now(),
                "session_ids": [metadata["session_id"]],
                "restored_path": str(target),
                "content_retained": True,
            },
        )
        app_dir = args.app_dir.expanduser().resolve()
        try:
            clear_completed_session_plans(app_dir, [metadata["session_id"]])
        except OSError:
            pass
        if not args.fixture_mode:
            try:
                mark_restore_verified(app_dir)
            except OSError:
                pass
        print(target)
    finally:
        if temp.exists():
            os.unlink(temp)


def purge_package(args: argparse.Namespace) -> None:
    package_dir = args.package.expanduser().resolve()
    app_dir = args.app_dir.expanduser().resolve()
    quarantine_root = (app_dir / "quarantine").resolve()
    if quarantine_root not in package_dir.parents:
        raise ActionBlocked("purge_only_allows_quarantine_packages")
    package_manifest = exact_regular_file(package_dir / "package.json", [package_dir])
    verify_immutable(package_manifest)
    metadata = read_json(package_manifest, {})
    if args.expires_at and not args.fixture_mode:
        raise ActionBlocked("expiry_override_only_allowed_in_fixture_mode")
    expiry_raw = args.expires_at if args.fixture_mode and args.expires_at else metadata.get("expires_at")
    parent_manifest = args.parent_manifest.expanduser().resolve()
    verify_immutable(parent_manifest)
    parent = read_json(parent_manifest, {})
    if (
        parent.get("action") != "quarantine"
        or len(parent.get("items", [])) != 1
        or parent["items"][0].get("session_id") != metadata["session_id"]
    ):
        raise ActionBlocked("parent_manifest_mismatch")
    if not expiry_raw:
        expiry_raw = parent.get("expires_at")
    if not expiry_raw:
        raise ActionBlocked("quarantine_expiry_missing")
    expiry = datetime.fromisoformat(str(expiry_raw).replace("Z", "+00:00"))
    if datetime.now(timezone.utc) < expiry:
        raise ActionBlocked(f"quarantine_not_expired:{expiry.isoformat()}")
    pinned, pin_status = load_pins(args.pinned_file)
    if pin_status != "snapshot":
        raise ActionBlocked("fresh_pinned_snapshot_required")
    if metadata["session_id"] in pinned:
        raise ActionBlocked("session_is_currently_pinned")
    protected_payload = read_json(app_dir / "protected.json", {"session_ids": []})
    if metadata["session_id"] in {str(value).lower() for value in protected_payload.get("session_ids", [])}:
        raise ActionBlocked("session_is_currently_permanently_protected")
    codex_home = Path(parent["codex_home"]).resolve()
    database, _fingerprint = select_database(codex_home)
    conn = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        if conn.execute("SELECT 1 FROM threads WHERE id=?", (metadata["session_id"],)).fetchone():
            raise ActionBlocked("session_reappeared_in_codex_index")
    finally:
        conn.close()
    expected = f"{CONFIRM_PREFIX['purge']} {metadata['session_id']}"
    if args.confirm != expected:
        raise ActionBlocked(f"confirmation_phrase_mismatch: expected '{expected}'")
    raw_files = [
        exact_regular_file(package_dir / metadata["stored_file"], [package_dir]),
        package_manifest,
        exact_regular_file(package_manifest.with_suffix(".json.sha256"), [package_dir]),
    ]
    for path in raw_files:
        os.unlink(path)
    try:
        package_dir.rmdir()
    except OSError as exc:
        raise ActionBlocked(f"package_contains_unexpected_files:{exc}") from exc
    parent_digest = parent_manifest.with_suffix(parent_manifest.suffix + ".sha256")
    os.chmod(parent_manifest, 0o600)
    os.chmod(parent_digest, 0o600)
    os.unlink(parent_manifest)
    os.unlink(parent_digest)
    append_audit(
        app_dir,
        {
            "event": "purge",
            "completed_at": utc_now(),
            "session_ids": [metadata["session_id"]],
            "bytes_purged": int(metadata["original_size"]),
            "content_retained": False,
        },
    )
    try:
        clear_completed_session_plans(app_dir, [metadata["session_id"]])
    except OSError:
        pass
    print(f"purged:{metadata['session_id']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex session destructive action helper")
    parser.add_argument("--app-dir", type=Path, default=default_app_dir())
    sub = parser.add_subparsers(dest="command", required=True)

    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--action", required=True, choices=sorted(DESTRUCTIVE))
    prepare_parser.add_argument("--session-id", action="append", required=True)
    prepare_parser.add_argument("--codex-home", type=Path, default=Path.home() / ".codex")
    prepare_parser.add_argument("--pinned-file", type=Path, required=True)
    prepare_parser.add_argument("--target", type=Path)
    prepare_parser.add_argument("--show-confirmation", action="store_true")

    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("--manifest", type=Path, required=True)
    apply_parser.add_argument("--confirm", required=True)
    apply_parser.add_argument("--compression", choices=["auto", "zstd", "none"], default="auto")
    apply_parser.add_argument("--fixture-mode", action="store_true", help=argparse.SUPPRESS)
    apply_parser.add_argument("--wait-for-exit-seconds", type=int, default=900)

    restore_parser = sub.add_parser("restore")
    restore_parser.add_argument("--package", type=Path, required=True)
    restore_parser.add_argument("--confirm", required=True)
    restore_parser.add_argument("--codex-home", type=Path, default=Path.home() / ".codex")
    restore_parser.add_argument("--fixture-mode", action="store_true", help=argparse.SUPPRESS)
    restore_parser.add_argument("--wait-for-exit-seconds", type=int, default=900)

    purge_parser = sub.add_parser("purge")
    purge_parser.add_argument("--package", type=Path, required=True)
    purge_parser.add_argument("--confirm", required=True)
    purge_parser.add_argument("--expires-at")
    purge_parser.add_argument("--parent-manifest", type=Path, required=True)
    purge_parser.add_argument("--pinned-file", type=Path, required=True)
    purge_parser.add_argument("--fixture-mode", action="store_true", help=argparse.SUPPRESS)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "prepare":
            prepare(args)
        elif args.command == "apply":
            apply_manifest(args)
        elif args.command == "restore":
            restore_package(args)
        elif args.command == "purge":
            purge_package(args)
        return 0
    except (ActionBlocked, OSError, sqlite3.Error, subprocess.CalledProcessError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
