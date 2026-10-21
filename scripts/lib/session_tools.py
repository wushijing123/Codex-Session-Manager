"""Direct session operations for the simplified local reader."""

from __future__ import annotations

import hashlib
import json
import math
import os
import queue
import platform
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core import connect_readonly, normalize_epoch, read_json, session_id_from_path, write_json
from .transcript_io import iter_log_events, open_log


def native_request(codex: str, codex_home: Path, method: str, params: dict) -> dict:
    """One initialized stdio connection; never resume or start a conversation."""
    process = subprocess.Popen(
        [codex, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
        env={**os.environ, "CODEX_HOME": str(codex_home)},
    )
    responses: queue.Queue = queue.Queue()

    def read() -> None:
        for line in process.stdout:
            try:
                responses.put(json.loads(line))
            except json.JSONDecodeError:
                continue
        responses.put(None)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()

    def send(payload: dict) -> None:
        process.stdin.write(json.dumps(payload) + "\n")
        process.stdin.flush()

    def receive(request_id: int) -> dict:
        deadline = time.monotonic() + 30
        while True:
            try:
                response = responses.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty as error:
                raise ValueError("codex_request_timeout") from error
            if response is None:
                raise ValueError("codex_connection_closed")
            if response.get("id") != request_id:
                continue
            if "error" in response:
                error = response["error"]
                if error.get("code") == -32601:
                    raise ValueError("native_method_unavailable")
                # Surface native refusal (e.g. an active writer), never force it.
                raise ValueError("codex_refused: " + str(error.get("message", ""))[:500])
            return response.get("result", {})

    try:
        send({"id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "codex_session_manager", "version": "0.7.0"},
        }})
        receive(1)
        send({"method": "initialized", "params": {}})
        send({"id": 2, "method": method, "params": params})
        return receive(2)
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        reader.join(timeout=1)
        process.stdin.close()
        process.stdout.close()


class SessionTools:
    def __init__(self, state: Any) -> None:
        self.state = state
        self._capabilities: dict | None = None
        self._batch_lock = threading.Lock()
        self._batch: dict = {}
        self._backup_cancel = threading.Event()
        self.cleanup_trash()

    def backup_location(self) -> dict:
        settings = read_json(self.state.app_dir / "settings.json", {})
        return {"directory": settings.get("backup_directory") or str(self.state.app_dir / "backups"),
                "configured": bool(settings.get("backup_directory")),
                "recovery_directory": str(self.state.app_dir / "backups")}

    def set_backup_location(self, directory: str) -> dict:
        if not isinstance(directory, str) or not directory.strip():
            raise ValueError("invalid_backup_directory")
        folder = Path(directory.strip()).expanduser()
        if folder == self.state.app_dir / "backups" and not folder.is_symlink():
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not folder.is_absolute() or folder.is_symlink() or not folder.is_dir():
            raise ValueError("invalid_backup_directory")
        folder = folder.resolve()
        if folder == self.state.codex_home.resolve() or self.state.codex_home.resolve() in folder.parents:
            raise ValueError("invalid_backup_directory")
        with self._batch_lock:
            if self._batch.get("running"):
                raise ValueError("batch_already_running")
            with self.state.lock:
                with tempfile.TemporaryFile(dir=folder) as probe:
                    probe.write(b"backup-directory-check")
                path = self.state.app_dir / "settings.json"
                settings = read_json(path, {})
                directories = settings.get("backup_directories", [])
                settings["backup_directories"] = list(dict.fromkeys([*directories, str(folder)]))
                settings["backup_directory"] = str(folder)
                write_json(path, settings)
        return self.backup_location()

    def choose_backup_directory(self) -> dict:
        if platform.system() != "Darwin":
            raise ValueError("folder_picker_unavailable")
        result = subprocess.run(["osascript", "-e",
            'POSIX path of (choose folder with prompt "选择 Codex 会话备份保存位置")'],
            capture_output=True, text=True, timeout=300)
        if result.returncode:
            if "-128" in result.stderr:
                return {"cancelled": True}
            raise ValueError("folder_picker_unavailable")
        return {"directory": result.stdout.strip()}

    def backup_directories(self) -> list[Path]:
        settings = read_json(self.state.app_dir / "settings.json", {})
        values = [str(self.state.app_dir / "backups"),
                  *settings.get("backup_directories", []), settings.get("backup_directory")]
        return list(dict.fromkeys(Path(value) for value in values if isinstance(value, str) and value))

    def capabilities(self) -> dict:
        if getattr(self.state, "is_demo", False):
            return {"archive": False, "delete": False, "backup": True, "demo": True}
        if self._capabilities is not None:
            return self._capabilities
        codex = shutil.which("codex")
        capabilities = {"archive": False, "delete": False, "backup": True}
        if codex:
            try:
                with tempfile.TemporaryDirectory(prefix="csm-schema-") as temp:
                    result = subprocess.run(
                        [codex, "app-server", "generate-json-schema", "--out", temp],
                        capture_output=True, timeout=30,
                        env={**os.environ, "CODEX_HOME": str(self.state.codex_home)},
                    )
                    if result.returncode == 0:
                        names = {path.name for path in Path(temp).rglob("*.json")}
                        capabilities["archive"] = "ThreadArchiveParams.json" in names
                        capabilities["delete"] = "ThreadDeleteParams.json" in names
            except (OSError, subprocess.TimeoutExpired):
                pass
        self._capabilities = capabilities
        return capabilities

    def record(self, session_id: str) -> dict:
        try:
            if str(uuid.UUID(session_id)) != session_id:
                raise ValueError()
        except (ValueError, AttributeError) as error:
            raise ValueError("invalid_session_id") from error
        record = self.state.record_for(session_id)
        if not record:
            raise ValueError("unknown_session")
        return record

    def log_path(self, record: dict) -> Path:
        raw = str(record.get("rollout_path") or "")
        candidate = self.state.codex_home.parent / raw[2:] if raw.startswith("~/") else Path(raw).expanduser()
        path = candidate.resolve(strict=True)
        roots = [self.state.codex_home / "sessions", self.state.codex_home / "archived_sessions"]
        if (candidate.is_symlink() or not path.is_file()
                or session_id_from_path(path) != record["id"]
                or not any(root.resolve() in path.parents for root in roots)):
            raise PermissionError("session_file_unavailable")
        return path

    def suggestion(self, record: dict) -> dict:
        if (record.get("pinned") or record.get("permanent_protection")
                or record.get("id") == os.environ.get("CODEX_THREAD_ID")
                or record.get("relation_count") or record.get("state_conflict")
                or record.get("actual_state") not in {"active", "archived"}):
            return {"action": None, "reason": ""}
        days = int(record.get("age_days") or 0)
        category = record.get("recommendation")
        if record.get("actual_state") == "archived" and category in {"delete_candidate", "permanent_delete_candidate"}:
            return {"action": "delete", "reason": "old_low_value", "days": days}
        if record.get("actual_state") == "active" and days >= 30:
            return {"action": "archive", "reason": "inactive", "days": days}
        return {"action": None, "reason": ""}

    def catalog(self) -> dict:
        return {**self.state.catalog, "sessions": [
            {**record, "suggestion": self.suggestion(record),
             "codex_url": "codex://threads/" + record["id"]}
            for record in self.state.catalog.get("sessions", [])
        ]}

    def backup(self, record: dict, *, directory: Path | None = None,
               cancel_event: threading.Event | None = None, progress=None) -> dict:
        def check_cancelled():
            if cancel_event is not None and cancel_event.is_set():
                raise ValueError("backup_cancelled")
        check_cancelled()
        path = self.log_path(record)
        before = path.stat()
        rows: dict[str, Any] = {}
        database = self.state.catalog.get("selected_database")
        rows["thread"] = {key: record.get(key) for key in ("id", "title", "cwd", "created_at", "updated_at", "archived")}
        conn = None
        if database and not self.state.catalog.get("database_ambiguous"):
            database_path = self.state.codex_home.parent / database[2:] if database.startswith("~/") else Path(database)
            conn = connect_readonly(database_path)
        try:
            if conn:
                conn.execute("BEGIN")
                row = conn.execute("SELECT * FROM threads WHERE id=?", (record["id"],)).fetchone()
                if row:
                    rows["thread"] = dict(row)
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table, where, values in (
                    ("thread_dynamic_tools", "thread_id=?", (record["id"],)),
                    ("thread_spawn_edges", "parent_thread_id=? OR child_thread_id=?", (record["id"], record["id"])),
                ):
                    if table in tables:
                        rows[table] = [dict(row) for row in conn.execute(f"SELECT * FROM {table} WHERE {where}", values)]
            folder = directory or Path(self.backup_location()["directory"])
            if folder.is_symlink() or (folder != self.state.app_dir / "backups" and not folder.is_dir()):
                raise ValueError("backup_directory_unavailable")
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            target = folder / f"{record['id']}-{uuid.uuid4().hex}.zip"
            temporary = target.with_suffix(".zip.partial")
            digest = hashlib.sha256()
            stored_file = "session.jsonl.zst" if path.name.endswith(".zst") else "session.jsonl"
            done = 0
            if progress:
                progress(0, before.st_size)
            with zipfile.ZipFile(temporary, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
                with path.open("rb") as source, bundle.open(stored_file, "w") as output:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        check_cancelled()
                        digest.update(chunk)
                        output.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, before.st_size)
                check_cancelled()
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError("session_changed_retry")
                metadata = {
                    "version": 2, "session_id": record["id"], "title": record.get("title"),
                    "stored_file": stored_file,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "sha256": digest.hexdigest(), "original_path": str(path),
                    "database_rows": rows,
                }
                bundle.writestr("backup.json", json.dumps(metadata, ensure_ascii=False, indent=2))
            check_cancelled()
            temporary.chmod(0o600)
            temporary.rename(target)
            return {"filename": target.name, "sha256": digest.hexdigest(),
                    "directory": str(folder),
                    "download_url": "/api/backup-download?file=" + target.name}
        except Exception:
            if "temporary" in locals():
                temporary.unlink(missing_ok=True)
            raise
        finally:
            if conn:
                conn.close()

    def backup_path(self, filename: str) -> Path:
        if not filename or Path(filename).name != filename or not filename.endswith(".zip"):
            raise ValueError("invalid_backup")
        for folder in self.backup_directories():
            path = folder / filename
            if folder.is_symlink() or path.is_symlink():
                raise ValueError("invalid_backup")
            if path.is_file():
                try:
                    with zipfile.ZipFile(path) as bundle:
                        self.backup_metadata(bundle)
                except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
                    raise ValueError("invalid_backup") from error
                return path
        raise ValueError("invalid_backup")

    def trash_metadata(self, filename: str) -> dict | None:
        if Path(filename).name != filename or not filename.endswith(".zip"):
            return None
        marker = (self.state.app_dir / "backups" / filename).with_suffix(".trash.json")
        try:
            if marker.parent.is_symlink() or marker.is_symlink() or marker.stat().st_size > 16_384:
                return None
            entry = json.loads(marker.read_text(encoding="utf-8"))
            if (entry.get("version") != 1 or entry.get("filename") != filename
                    or not isinstance(entry.get("deleted_at"), int)
                    or entry.get("expires_at") != entry["deleted_at"] + 30 * 86400):
                return None
            return entry
        except (OSError, ValueError, AttributeError, KeyError):
            return None

    def verify_backup(self, filename: str) -> None:
        with zipfile.ZipFile(self.backup_path(filename)) as bundle:
            metadata = self.backup_metadata(bundle)
            stored = metadata.get("stored_file", "session.jsonl")
            if bundle.getinfo(stored).file_size > 2 * 1024 ** 3:
                raise ValueError("backup_too_large")
            digest = hashlib.sha256()
            with bundle.open(stored) as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != metadata["sha256"]:
                raise ValueError("backup_hash_mismatch")

    def _purge_trash(self, filename: str) -> None:
        if not self.trash_metadata(filename):
            raise ValueError("not_in_trash")
        path = self.state.app_dir / "backups" / filename
        if path.parent.is_symlink() or path.is_symlink() or not path.is_file():
            raise ValueError("invalid_backup")
        path.unlink()
        path.with_suffix(".trash.json").unlink(missing_ok=True)

    def cleanup_trash(self) -> None:
        if getattr(self.state, "is_demo", False):
            return
        with self.state.lock:
            for marker in (self.state.app_dir / "backups").glob("*.trash.json"):
                filename = marker.name.removesuffix(".trash.json") + ".zip"
                entry = self.trash_metadata(filename)
                if entry and entry["expires_at"] <= time.time():
                    try:
                        self._purge_trash(filename)
                    except (OSError, ValueError):
                        # Retain an inaccessible copy for a later retry.
                        continue

    def list_trash(self) -> list[dict]:
        with self.state.lock:
            self.cleanup_trash()
            rows = []
            for backup in self.list_backups(include_trash=True):
                if backup["directory"] != str(self.state.app_dir / "backups"):
                    continue
                entry = self.trash_metadata(backup["filename"])
                if entry:
                    rows.append({**backup, **entry,
                                 "remaining_days": max(0, math.ceil((entry["expires_at"] - time.time()) / 86400))})
            return sorted(rows, key=lambda row: row["deleted_at"], reverse=True)

    def purge_trash(self, filenames: list) -> dict:
        if getattr(self.state, "is_demo", False):
            raise PermissionError("demo_read_only")
        if not isinstance(filenames, list) or not 1 <= len(filenames) <= 2000:
            raise ValueError("invalid_trash_selection")
        if any(not isinstance(name, str) or Path(name).name != name or not name.endswith(".zip") for name in filenames):
            raise ValueError("invalid_trash_selection")
        results = []
        with self.state.lock:
            for filename in dict.fromkeys(filenames):
                try:
                    self._purge_trash(filename)
                    results.append({"filename": filename, "status": "success"})
                except (OSError, ValueError):
                    results.append({"filename": filename, "status": "failed", "error": "trash_purge_failed"})
            return {"ok": True, "results": results, "trash": self.list_trash()}

    def restore_trash(self, filename: str) -> dict:
        with self.state.lock:
            self.cleanup_trash()
            if not self.trash_metadata(filename):
                raise ValueError("not_in_trash")
            if not (self.state.app_dir / "backups" / filename).is_file():
                raise ValueError("invalid_backup")
            result = self.restore_backup(filename)
            if result.get("verified"):
                self._purge_trash(filename)
            return {**result, "trash": self.list_trash()}

    @staticmethod
    def backup_metadata(bundle: zipfile.ZipFile) -> dict:
        if bundle.getinfo("backup.json").file_size > 2 * 1024 * 1024:
            raise ValueError("invalid_backup")
        metadata = json.loads(bundle.read("backup.json"))
        session_id = metadata.get("session_id", "")
        if str(uuid.UUID(session_id)) != session_id or metadata.get("version") not in {1, 2}:
            raise ValueError("invalid_backup")
        stored = metadata.get("stored_file", "session.jsonl")
        if stored not in {"session.jsonl", "session.jsonl.zst"}:
            raise ValueError("invalid_backup")
        if len(str(metadata.get("sha256", ""))) != 64:
            raise ValueError("invalid_backup")
        return metadata

    def list_backups(self, *, include_trash: bool = False) -> list[dict]:
        backups = []
        seen = set()
        paths = (path for folder in self.backup_directories() if not folder.is_symlink()
                 for path in folder.glob("*.zip"))
        for path in paths:
            if path.name in seen:
                continue
            seen.add(path.name)
            if path.is_symlink():
                continue
            if not include_trash and path.parent == self.state.app_dir / "backups" and self.trash_metadata(path.name):
                continue
            try:
                with zipfile.ZipFile(path) as bundle:
                    metadata = self.backup_metadata(bundle)
                existing = self.state.record_for(metadata["session_id"])
                backups.append({
                    "filename": path.name, "session_id": metadata["session_id"],
                    "title": metadata.get("title") or metadata["session_id"],
                    "created_at": metadata.get("created_at"), "size_bytes": path.stat().st_size,
                    "directory": str(path.parent),
                    "can_restore": not existing or existing.get("actual_state") == "missing",
                    "download_url": "/api/backup-download?file=" + path.name,
                })
            except (OSError, ValueError, KeyError, zipfile.BadZipFile):
                continue
        return sorted(backups, key=lambda row: str(row.get("created_at") or ""), reverse=True)

    def restore_backup(self, filename: str) -> dict:
        if getattr(self.state, "is_demo", False):
            raise PermissionError("demo_read_only")
        codex = shutil.which("codex")
        if not codex:
            raise ValueError("codex_cli_unavailable")
        with self.state.lock:
            self.state.refresh()
            path = self.backup_path(filename)
            with zipfile.ZipFile(path) as bundle:
                metadata = self.backup_metadata(bundle)
                session_id = metadata["session_id"]
                existing = self.state.record_for(session_id)
                if existing and existing.get("actual_state") != "missing":
                    raise PermissionError("restore_session_exists")
                snapshot = metadata.get("database_rows", {}).get("thread", {})
                created = normalize_epoch(snapshot.get("created_at")) or int(time.time())
                date = datetime.fromtimestamp(created, timezone.utc)
                archived = bool(snapshot.get("archived"))
                root = self.state.codex_home / "sessions"
                directory = root / date.strftime("%Y/%m/%d")
                directory.mkdir(parents=True, exist_ok=True)
                if root.resolve() != directory.resolve() and root.resolve() not in directory.resolve().parents:
                    raise PermissionError("invalid_backup")
                stored = metadata.get("stored_file", "session.jsonl")
                suffix = ".jsonl.zst" if stored.endswith(".zst") else ".jsonl"
                target = directory / f"rollout-{date.strftime('%Y-%m-%dT%H-%M-%S')}-{session_id}.jsonl"
                if target.exists() or target.is_symlink():
                    raise PermissionError("restore_session_exists")
                info = bundle.getinfo(stored)
                if info.file_size > 2 * 1024 ** 3:
                    raise ValueError("backup_too_large")
                descriptor, temporary = tempfile.mkstemp(prefix=".restore-", suffix=suffix, dir=directory)
                try:
                    digest = hashlib.sha256()
                    with os.fdopen(descriptor, "wb") as output, bundle.open(stored) as source:
                        for chunk in iter(lambda: source.read(1024 * 1024), b""):
                            digest.update(chunk)
                            output.write(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                    if digest.hexdigest() != metadata["sha256"]:
                        raise ValueError("backup_hash_mismatch")
                    events = iter_log_events(Path(temporary))
                    try:
                        first = next(events, {})
                        if first.get("type") != "session_meta" or first.get("payload", {}).get("id") != session_id:
                            raise ValueError("backup_session_mismatch")
                    finally:
                        events.close()
                    # Publish a plain rollout so native indexing/name updates work
                    # across Codex versions; the backup keeps original compressed bytes.
                    published = Path(temporary)
                    decoded = None
                    try:
                        if stored.endswith(".zst"):
                            fd, decoded = tempfile.mkstemp(prefix=".decoded-", suffix=".jsonl", dir=directory)
                            with os.fdopen(fd, "wb") as output, open_log(Path(temporary), "rb") as source:
                                total = 0
                                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                                    total += len(chunk)
                                    if total > 2 * 1024 ** 3:
                                        raise ValueError("backup_too_large")
                                    output.write(chunk)
                                output.flush()
                                os.fsync(output.fileno())
                            published = Path(decoded)
                        os.link(published, target)
                    finally:
                        if decoded:
                            Path(decoded).unlink(missing_ok=True)
                finally:
                    Path(temporary).unlink(missing_ok=True)
            try:
                restored = native_request(codex, self.state.codex_home, "thread/read", {"threadId": session_id})
                if restored.get("thread", {}).get("id") != session_id:
                    raise ValueError("restore_not_verified")
                title = snapshot.get("name") or metadata.get("title")
                if title:
                    native_request(codex, self.state.codex_home, "thread/name/set", {"threadId": session_id, "name": str(title)})
                if archived:
                    native_request(codex, self.state.codex_home, "thread/archive", {"threadId": session_id})
            except (OSError, ValueError) as error:
                # Keep the verified transcript and original backup for retry.
                self.state.refresh()
                raise ValueError("restore_file_saved_index_pending") from error
            self.state.refresh()
            record = self.state.record_for(session_id)
            return {"ok": True, "session_id": session_id, "catalog": self.catalog(),
                    "verified": bool(record and record.get("actual_state") in {"active", "archived"})}

    def start_batch(self, session_ids: list, action: str) -> dict:
        if action not in {"archive", "unarchive", "delete", "backup", "suggested"}:
            raise ValueError("invalid_action")
        if not isinstance(session_ids, list) or not 1 <= len(session_ids) <= 2000:
            raise ValueError("invalid_batch_selection")
        # Validate the entire selection before starting any operation.
        for session_id in session_ids:
            try:
                if not isinstance(session_id, str) or str(uuid.UUID(session_id)) != session_id:
                    raise ValueError()
            except (ValueError, AttributeError) as error:
                raise ValueError("invalid_session_id") from error
        ids = list(dict.fromkeys(session_ids))
        with self._batch_lock:
            if self._batch.get("running"):
                raise ValueError("batch_already_running")
            suggestions = {}
            if action == "suggested":
                with self.state.lock:
                    self.state.refresh()
                    suggestions = {session_id: self.suggestion(self.state.record_for(session_id) or {}).get("action")
                                   for session_id in ids}
            self._batch = {"job": uuid.uuid4().hex, "action": action, "running": True,
                           "total": len(ids), "results": [], "current": None,
                           "cancel_requested": False, "cancelled": False}
            self._backup_cancel = threading.Event()
            if action == "backup":
                self._batch["directory"] = self.backup_location()["directory"]
            snapshot = {**self._batch, "results": []}
        threading.Thread(target=self._run_batch, args=(ids, action, suggestions), daemon=True).start()
        return snapshot

    def batch_status(self, job: str = "") -> dict:
        with self._batch_lock:
            if not job and not self._batch:
                return {}
            if not self._batch or (job and self._batch["job"] != job):
                raise ValueError("unknown_batch")
            return {**self._batch, "results": list(self._batch["results"])}

    def cancel_backup(self, job: str) -> dict:
        with self._batch_lock:
            if not job or self._batch.get("job") != job:
                raise ValueError("unknown_batch")
            if self._batch.get("action") != "backup":
                raise ValueError("backup_not_cancellable")
            if self._batch.get("running"):
                self._batch["cancel_requested"] = True
                self._backup_cancel.set()
            return {**self._batch, "results": list(self._batch["results"])}

    def _backup_progress(self, done: int, total: int) -> None:
        with self._batch_lock:
            if self._batch.get("current"):
                self._batch["current"].update(bytes_done=done, bytes_total=total)

    def _run_batch(self, session_ids: list[str], action: str, suggestions: dict) -> None:
        for index, session_id in enumerate(session_ids, 1):
            record = self.state.record_for(session_id) or {}
            item_action = suggestions.get(session_id) if action == "suggested" else action
            result = {"session_id": session_id, "title": record.get("title") or session_id,
                      "action": item_action}
            with self._batch_lock:
                if action == "backup" and self._backup_cancel.is_set():
                    self._batch["results"].extend({"session_id": sid, "title":
                        (self.state.record_for(sid) or {}).get("title") or sid,
                        "action": "backup", "status": "cancelled"}
                        for sid in session_ids[index - 1:])
                    break
                self._batch["current"] = {**result, "index": index}
            try:
                if action == "suggested" and not item_action:
                    outcome = {"skipped": True, "reason": "no_suggestion"}
                elif action == "suggested":
                    outcome = self.action(session_id, item_action, include_catalog=False, expected_suggestion=True)
                elif action == "backup":
                    outcome = self.action(session_id, action, include_catalog=False,
                        cancel_event=self._backup_cancel, backup_directory=Path(self._batch["directory"]),
                        progress=self._backup_progress)
                else:
                    outcome = self.action(session_id, item_action, include_catalog=False)
                result.update(status="skipped" if outcome.get("skipped") else
                              "pending" if outcome.get("verified") is False else "success",
                              backup=outcome.get("backup"), error=outcome.get("reason", ""))
            except (PermissionError, ValueError, OSError, subprocess.SubprocessError) as error:
                reason = str(error) if isinstance(error, (PermissionError, ValueError)) else "local_operation_failed"
                skipped = reason in {"session_protected_or_linked", "session_file_unavailable", "unknown_session", "demo_read_only"}
                result.update(status="cancelled" if reason == "backup_cancelled" else
                              "pending" if reason in {"codex_request_timeout", "codex_connection_closed"}
                              else "skipped" if skipped else "failed", error=reason)
            with self._batch_lock:
                self._batch["results"].append(result)
                self._batch["current"] = None
        with self._batch_lock:
            self._batch["current"] = None
            self._batch["cancelled"] = any(row["status"] == "cancelled" for row in self._batch["results"])
            self._batch["running"] = False

    def action(self, session_id: str, action: str, *, include_catalog: bool = True,
               expected_suggestion: bool = False, cancel_event: threading.Event | None = None,
               backup_directory: Path | None = None, progress=None) -> dict:
        if action not in {"archive", "unarchive", "delete", "backup"}:
            raise ValueError("invalid_action")
        if getattr(self.state, "is_demo", False) and action != "backup":
            raise PermissionError("demo_read_only")
        with self.state.lock:
            self.state.refresh()
            record = self.record(session_id)
            if expected_suggestion and self.suggestion(record).get("action") != action:
                return {"skipped": True, "reason": "suggestion_changed"}
            if action == "backup":
                backup = self.backup(record, directory=backup_directory, cancel_event=cancel_event, progress=progress)
                return {"backup": backup, **({"catalog": self.catalog()} if include_catalog else {})}
            if action in {"archive", "unarchive", "delete"} and (record.get("pinned") or record.get("permanent_protection")
                    or record.get("relation_count") or session_id == os.environ.get("CODEX_THREAD_ID")):
                raise PermissionError("session_protected_or_linked")
            if record.get("state_conflict") or record.get("actual_state") not in {"active", "archived"}:
                raise PermissionError("session_file_unavailable")
            capability = "archive" if action == "unarchive" else action
            if not self.capabilities().get(capability):
                raise ValueError("native_method_unavailable")
            expected = "archived" if action == "archive" else "active"
            if action != "delete" and record.get("actual_state") == expected:
                return {"skipped": True, "reason": "already_in_target_state", "verified": True,
                        **({"catalog": self.catalog()} if include_catalog else {})}
            self.log_path(record)
            backup = self.backup(record, directory=self.state.app_dir / "backups") if action == "delete" else None
            if backup:
                self.verify_backup(backup["filename"])
            codex = shutil.which("codex")
            native_request(codex, self.state.codex_home, "thread/" + action, {"threadId": session_id})
            self.state.refresh()
            refreshed = self.state.record_for(session_id)
            verified = refreshed is None if action == "delete" else bool(refreshed and refreshed.get("actual_state") == expected)
            trash = None
            if action == "delete" and verified:
                deleted_at = int(time.time())
                trash = {"version": 1, "filename": backup["filename"], "deleted_at": deleted_at,
                         "expires_at": deleted_at + 30 * 86400}
                write_json(self.backup_path(backup["filename"]).with_suffix(".trash.json"), trash)
            return {**({"catalog": self.catalog()} if include_catalog else {}), "backup": backup,
                    "verified": verified, "action": action, "trash": trash}
