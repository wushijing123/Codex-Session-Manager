from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from demo_dashboard import ACTIVE_ID, ARCHIVED_ID, create_demo_fixture
from lib.core import conversation_preview
from lib.server import DashboardState
from lib.session_tools import native_request


class SessionToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        fixture = create_demo_fixture(self.root)
        self.state = DashboardState(fixture["codex_home"], fixture["app_dir"], ROOT / "assets/dashboard", fixture["pinned_file"], False)
        self.tools = self.state.tools
        self.tools._capabilities = {"archive": True, "delete": True, "backup": True}

    def tearDown(self):
        self.temp.cleanup()

    def test_backup_preserves_transcript_and_database_row_without_credentials(self):
        (self.state.codex_home / "auth.json").write_text('"private credential"')
        record = self.tools.record(ARCHIVED_ID)
        source = self.tools.log_path(record).read_bytes()
        result = self.tools.action(ARCHIVED_ID, "backup")
        archive = self.state.app_dir / "backups" / result["backup"]["filename"]
        with zipfile.ZipFile(archive) as bundle:
            self.assertEqual({"session.jsonl", "backup.json"}, set(bundle.namelist()))
            self.assertEqual(source, bundle.read("session.jsonl"))
            metadata = json.loads(bundle.read("backup.json"))
        self.assertEqual(hashlib.sha256(source).hexdigest(), metadata["sha256"])
        self.assertEqual(ARCHIVED_ID, metadata["database_rows"]["thread"]["id"])
        self.assertEqual(1, metadata["database_rows"]["thread"]["archived"])
        self.assertEqual(source, self.tools.log_path(record).read_bytes())
        self.assertFalse((self.state.app_dir / "manifests").exists())

    def test_delete_backs_up_before_exact_native_request_without_confirmation_sheet(self):
        def delete(codex, home, method, params):
            self.assertEqual("thread/delete", method)
            self.assertEqual({"threadId": ARCHIVED_ID}, params)
            self.assertEqual(1, len(list((self.state.app_dir / "backups").glob("*.zip"))))
            self.tools.log_path(self.tools.record(ARCHIVED_ID)).unlink()
            with contextlib.closing(sqlite3.connect(home / "state_5.sqlite")) as conn, conn:
                conn.execute("DELETE FROM threads WHERE id=?", (ARCHIVED_ID,))
            return {}
        with mock.patch("lib.session_tools.native_request", side_effect=delete), mock.patch("lib.session_tools.shutil.which", return_value="/test/codex"):
            result = self.tools.action(ARCHIVED_ID, "delete")
        self.assertTrue(result["verified"])
        self.assertIsNone(self.state.record_for(ARCHIVED_ID))
        self.assertFalse((self.state.app_dir / "manifests").exists())
        self.assertTrue(result["backup"]["download_url"].startswith("/api/backup-download?file="))

    def test_native_refusal_keeps_backup_and_original_session(self):
        original = self.tools.log_path(self.tools.record(ARCHIVED_ID)).read_bytes()
        with mock.patch("lib.session_tools.native_request", side_effect=ValueError("codex_refused: active writer")), mock.patch("lib.session_tools.shutil.which", return_value="/test/codex"):
            with self.assertRaisesRegex(ValueError, "active writer"):
                self.tools.action(ARCHIVED_ID, "delete")
        self.assertEqual(original, self.tools.log_path(self.tools.record(ARCHIVED_ID)).read_bytes())
        self.assertEqual(1, len(list((self.state.app_dir / "backups").glob("*.zip"))))

    def test_delete_never_calls_native_for_linked_or_pinned_session(self):
        with contextlib.closing(sqlite3.connect(self.state.codex_home / "state_5.sqlite")) as conn, conn:
            conn.execute("INSERT INTO thread_spawn_edges VALUES (?,?,?)", (ARCHIVED_ID, ACTIVE_ID, "done"))
        with mock.patch("lib.session_tools.native_request") as native:
            with self.assertRaisesRegex(PermissionError, "protected_or_linked"):
                self.tools.action(ARCHIVED_ID, "delete")
            native.assert_not_called()
        self.assertFalse((self.state.app_dir / "backups").exists())

    def test_unsupported_delete_fails_before_backup_or_mutation(self):
        self.tools._capabilities["delete"] = False
        with mock.patch("lib.session_tools.native_request") as native:
            with self.assertRaisesRegex(ValueError, "native_method_unavailable"):
                self.tools.action(ARCHIVED_ID, "delete")
            native.assert_not_called()
        self.assertFalse((self.state.app_dir / "backups").exists())

    def test_old_unarchived_sessions_get_archive_suggestion(self):
        record = next(row for row in self.tools.catalog()["sessions"] if row["id"].endswith("d005"))
        self.assertEqual("archive", record["suggestion"]["action"])
        self.assertEqual(45, record["suggestion"]["days"])
        self.assertEqual("codex://threads/" + record["id"], record["codex_url"])
        with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": record["id"]}):
            self.assertIsNone(self.tools.suggestion(record)["action"])
        disposable = next(row for row in self.tools.catalog()["sessions"] if row["id"].endswith("d006"))
        self.assertEqual("delete", disposable["suggestion"]["action"])

    def test_content_search_includes_unarchived_sessions_and_is_read_only(self):
        records = self.state.catalog["sessions"]
        before = self.tools.log_path(self.tools.record(ACTIVE_ID)).read_bytes()
        result = self.state._search_archived_content("海盐", 200, records, include_active=True)
        self.assertEqual(["01900000-0000-7000-8000-00000000d007"], [row["session_id"] for row in result["matches"]])
        self.assertEqual(before, self.tools.log_path(self.tools.record(ACTIVE_ID)).read_bytes())

    def test_pagination_can_reach_messages_after_200_without_gaps(self):
        log = self.root / "long.jsonl"
        log.write_text("\n".join(json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": f"message {i}"}}) for i in range(245)))
        messages, offset = [], 0
        while offset is not None:
            page = conversation_preview(log, max_messages=20, offset=offset, max_chars=240_000)
            messages.extend(item["text"] for item in page["messages"])
            offset = page["next_offset"]
        self.assertEqual([f"message {i}" for i in range(245)], messages)

    def test_backup_rejects_transcript_symlink(self):
        record = self.tools.record(ARCHIVED_ID)
        path = self.tools.log_path(record)
        outside = self.root / "outside.jsonl"
        outside.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(outside)
        with self.assertRaises(PermissionError):
            self.tools.backup(record)

    def test_native_success_without_disk_change_is_not_reported_verified(self):
        with mock.patch("lib.session_tools.native_request", return_value={}), mock.patch("lib.session_tools.shutil.which", return_value="/test/codex"):
            result = self.tools.action(ACTIVE_ID, "archive")
        self.assertFalse(result["verified"])
        self.assertEqual("active", self.state.record_for(ACTIVE_ID)["actual_state"])

    def test_demo_blocks_mutations_but_allows_backups(self):
        self.state.is_demo = True
        self.assertFalse(self.tools.capabilities()["archive"])
        with mock.patch("lib.session_tools.native_request") as native:
            with self.assertRaisesRegex(PermissionError, "demo_read_only"):
                self.tools.action(ACTIVE_ID, "archive")
            native.assert_not_called()
        self.assertIn("backup", self.tools.action(ACTIVE_ID, "backup"))

    def test_native_request_initializes_and_sends_one_exact_method(self):
        fake = self.root / "codex"
        fake.write_text("#!" + sys.executable + "\n" + '''import json, sys
for line in sys.stdin:
    message = json.loads(line)
    if message.get("method") == "initialize":
        print(json.dumps({"id": message["id"], "result": {}}), flush=True)
    elif message.get("method") == "initialized":
        continue
    else:
        print(json.dumps({"id": message["id"], "result": {"method": message["method"], "params": message["params"]}}), flush=True)
''')
        fake.chmod(0o700)
        result = native_request(str(fake), self.state.codex_home, "thread/archive", {"threadId": ARCHIVED_ID})
        self.assertEqual({"method": "thread/archive", "params": {"threadId": ARCHIVED_ID}}, result)

    def test_cancel_backup_mid_file_removes_partial_and_preserves_source(self):
        record = self.tools.record(ARCHIVED_ID)
        path = self.tools.log_path(record)
        with path.open("ab") as file:
            file.write(b"x" * (3 * 1024 * 1024))
        original = path.read_bytes()
        cancel = threading.Event()
        def progress(done, total):
            if done:
                cancel.set()
        with self.assertRaisesRegex(ValueError, "backup_cancelled"):
            self.tools.backup(record, cancel_event=cancel, progress=progress)
        self.assertEqual(original, path.read_bytes())
        self.assertEqual([], list((self.state.app_dir / "backups").iterdir()))

    def test_cancel_batch_is_responsive_and_keeps_completed_backups(self):
        with self.tools.log_path(self.tools.record(ARCHIVED_ID)).open("ab") as file:
            file.write(b"x" * (3 * 1024 * 1024))
        entered, release = threading.Event(), threading.Event()
        update = self.tools._backup_progress
        def progress(done, total):
            update(done, total)
            if done and self.tools.batch_status()["current"]["session_id"] == ARCHIVED_ID:
                entered.set()
                release.wait(3)
        with mock.patch.object(self.tools, "_backup_progress", side_effect=progress):
            job = self.tools.start_batch([ACTIVE_ID, ARCHIVED_ID,
                "01900000-0000-7000-8000-00000000d005"], "backup")
            try:
                self.assertTrue(entered.wait(3))
                started = time.monotonic()
                result = self.tools.cancel_backup(job["job"])
                self.assertLess(time.monotonic() - started, .5)
                self.assertTrue(result["cancel_requested"])
            finally:
                release.set()
            result = self.wait_batch(job["job"])
        self.assertEqual(["success", "cancelled", "cancelled"], [r["status"] for r in result["results"]])
        self.assertTrue(result["cancelled"])
        self.assertEqual(1, len(self.tools.list_backups()))
        self.assertEqual([], list((self.state.app_dir / "backups").glob("*.partial")))
        with self.assertRaisesRegex(ValueError, "unknown_batch"):
            self.tools.cancel_backup("another-job")
        self.assertFalse(self.tools.cancel_backup(job["job"])["running"])

    def test_backup_locations_persist_and_old_files_stay_readable(self):
        old = self.tools.action(ACTIVE_ID, "backup")["backup"]
        first, second = self.root / "chosen", self.root / "next"
        first.mkdir(); second.mkdir()
        location = self.tools.set_backup_location(str(first))
        self.assertTrue(location["configured"])
        unrelated = first / "other.zip"
        with zipfile.ZipFile(unrelated, "w") as archive:
            archive.writestr("private.txt", "not a session backup")
        with self.assertRaisesRegex(ValueError, "invalid_backup"):
            self.tools.backup_path(unrelated.name)
        custom = self.tools.action(ARCHIVED_ID, "backup")["backup"]
        self.assertTrue((first / custom["filename"]).is_file())
        self.tools.set_backup_location(str(second))
        self.assertTrue((self.state.app_dir / "backups" / old["filename"]).is_file())
        self.assertEqual(first.resolve() / custom["filename"], self.tools.backup_path(custom["filename"]))
        self.tools.verify_backup(custom["filename"])
        self.assertEqual(2, len(self.tools.list_backups()))
        self.assertEqual(str(second.resolve()), self.tools.backup_location()["directory"])

    def test_custom_manual_location_does_not_move_trash_recovery_copies(self):
        folder = self.root / "chosen"
        folder.mkdir()
        self.tools.set_backup_location(str(folder))
        manual = self.tools.action(ACTIVE_ID, "backup")["backup"]
        deleted = self.delete_fixture()["backup"]
        self.assertTrue((folder / manual["filename"]).is_file())
        self.assertTrue((self.state.app_dir / "backups" / deleted["filename"]).is_file())
        self.assertEqual([deleted["filename"]], [item["filename"] for item in self.tools.list_trash()])
        self.assertEqual([manual["filename"]], [item["filename"] for item in self.tools.list_backups()])

    def test_invalid_or_disconnected_backup_folder_never_falls_back(self):
        with self.assertRaisesRegex(ValueError, "invalid_backup_directory"):
            self.tools.set_backup_location(str(self.state.codex_home))
        folder = self.root / "chosen"
        folder.mkdir()
        link = self.root / "linked"
        link.symlink_to(folder)
        with self.assertRaisesRegex(ValueError, "invalid_backup_directory"):
            self.tools.set_backup_location(str(link))
        self.tools.set_backup_location(str(folder))
        folder.rmdir()
        with self.assertRaisesRegex(ValueError, "backup_directory_unavailable"):
            self.tools.action(ACTIVE_ID, "backup")
        self.assertFalse(folder.exists())
        self.assertFalse((self.state.app_dir / "backups").exists())

    def test_cancel_native_folder_picker_does_not_change_settings(self):
        with mock.patch("lib.session_tools.platform.system", return_value="Darwin"), mock.patch(
            "lib.session_tools.subprocess.run", return_value=type("Result", (), {
                "returncode": 1, "stderr": "User canceled. (-128)", "stdout": ""})()):
            self.assertEqual({"cancelled": True}, self.tools.choose_backup_directory())
        self.assertFalse(self.tools.backup_location()["configured"])

    def wait_batch(self, job):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = self.tools.batch_status(job)
            if not result["running"]:
                return result
            time.sleep(0.01)
        self.fail("Batch did not finish")

    def delete_fixture(self, session_id=ARCHIVED_ID):
        def native(codex, home, method, params):
            self.assertEqual("thread/delete", method)
            self.tools.log_path(self.tools.record(session_id)).unlink()
            with contextlib.closing(sqlite3.connect(home / "state_5.sqlite")) as conn, conn:
                conn.execute("DELETE FROM threads WHERE id=?", (session_id,))
            return {}
        with mock.patch("lib.session_tools.native_request", side_effect=native):
            return self.tools.action(session_id, "delete")

    def test_delete_enters_trash_for_30_days_and_manual_backup_stays_separate(self):
        manual = self.tools.action(ARCHIVED_ID, "backup")["backup"]
        result = self.delete_fixture()
        trash = self.tools.list_trash()
        self.assertEqual(1, len(trash))
        self.assertEqual(30, trash[0]["remaining_days"])
        self.assertEqual(30 * 86400, trash[0]["expires_at"] - trash[0]["deleted_at"])
        self.assertEqual(result["backup"]["filename"], trash[0]["filename"])
        self.assertEqual([manual["filename"]], [item["filename"] for item in self.tools.list_backups()])

    def test_unverified_or_refused_delete_does_not_enter_trash(self):
        with mock.patch("lib.session_tools.native_request", return_value={}):
            result = self.tools.action(ARCHIVED_ID, "delete")
        self.assertFalse(result["verified"])
        self.assertIsNone(result["trash"])
        self.assertEqual([], self.tools.list_trash())
        self.assertEqual(1, len(self.tools.list_backups()))
        with mock.patch("lib.session_tools.native_request", side_effect=ValueError("codex_refused")):
            with self.assertRaises(ValueError):
                self.tools.action(ARCHIVED_ID, "delete")
        self.assertEqual([], self.tools.list_trash())

    def test_backup_verification_failure_blocks_native_delete(self):
        with mock.patch.object(self.tools, "verify_backup", side_effect=ValueError("backup_hash_mismatch")), mock.patch("lib.session_tools.native_request") as native:
            with self.assertRaisesRegex(ValueError, "backup_hash_mismatch"):
                self.tools.action(ARCHIVED_ID, "delete")
            native.assert_not_called()
        self.assertTrue(self.tools.log_path(self.tools.record(ARCHIVED_ID)).exists())

    def test_expiration_cleans_only_trash_after_deadline(self):
        manual = self.tools.action(ARCHIVED_ID, "backup")["backup"]
        deleted = self.delete_fixture()
        expires_at = deleted["trash"]["expires_at"]
        with mock.patch("lib.session_tools.time.time", return_value=expires_at - 1):
            self.assertEqual(1, len(self.tools.list_trash()))
        with mock.patch("lib.session_tools.time.time", return_value=expires_at):
            self.assertEqual([], self.tools.list_trash())
        self.assertFalse((self.state.app_dir / "backups" / deleted["backup"]["filename"]).exists())
        self.assertTrue(self.tools.backup_path(manual["filename"]).exists())

    def test_bulk_purge_deletes_exact_selection_and_never_manual_backups(self):
        manual = self.tools.action(ARCHIVED_ID, "backup")["backup"]
        first = self.delete_fixture()["backup"]["filename"]
        second = self.delete_fixture("01900000-0000-7000-8000-00000000d005")["backup"]["filename"]
        result = self.tools.purge_trash([first, first, manual["filename"]])
        self.assertEqual(["success", "failed"], [row["status"] for row in result["results"]])
        self.assertEqual([second], [row["filename"] for row in result["trash"]])
        self.assertTrue(self.tools.backup_path(manual["filename"]).exists())
        self.assertEqual([], self.tools.purge_trash([second])["trash"])

    def test_purge_rejects_traversal_before_any_deletion_and_blocks_symlink(self):
        filename = self.delete_fixture()["backup"]["filename"]
        path = self.tools.backup_path(filename)
        with self.assertRaisesRegex(ValueError, "invalid_trash_selection"):
            self.tools.purge_trash([filename, "../outside.zip"])
        self.assertTrue(path.exists())
        outside = self.root / "outside.zip"
        path.rename(outside)
        path.symlink_to(outside)
        result = self.tools.purge_trash([filename])
        self.assertEqual("failed", result["results"][0]["status"])
        self.assertTrue(outside.exists())

    def test_trash_restore_failure_keeps_recovery_copy(self):
        filename = self.delete_fixture()["backup"]["filename"]
        with mock.patch.object(self.tools, "restore_backup", side_effect=ValueError("backup_hash_mismatch")):
            with self.assertRaises(ValueError):
                self.tools.restore_trash(filename)
        self.assertTrue(self.tools.backup_path(filename).exists())
        self.assertEqual(1, len(self.tools.list_trash()))

    def test_verified_trash_restore_consumes_only_its_recovery_copy(self):
        filename = self.delete_fixture()["backup"]["filename"]
        with mock.patch.object(self.tools, "restore_backup", return_value={"verified": False}):
            self.tools.restore_trash(filename)
        self.assertEqual(1, len(self.tools.list_trash()))
        with mock.patch.object(self.tools, "restore_backup", return_value={"verified": True}):
            result = self.tools.restore_trash(filename)
        self.assertEqual([], result["trash"])
        self.assertFalse((self.state.app_dir / "backups" / filename).exists())

    def test_batch_validates_every_id_before_any_action(self):
        with mock.patch.object(self.tools, "action") as action:
            for ids in ([ACTIVE_ID, "../invalid"], [ACTIVE_ID, 123], [], "not-a-list"):
                with self.assertRaises(ValueError):
                    self.tools.start_batch(ids, "delete")
            action.assert_not_called()

    def test_batch_deduplicates_and_continues_after_item_failure(self):
        def action(session_id, action, **kwargs):
            if session_id == ACTIVE_ID:
                raise ValueError("codex_refused: active writer")
            return {"verified": True, "backup": {"download_url": "/backup"}}
        with mock.patch.object(self.tools, "action", side_effect=action) as perform:
            batch = self.tools.start_batch([ACTIVE_ID, ARCHIVED_ID, ARCHIVED_ID], "delete")
            result = self.wait_batch(batch["job"])
        self.assertEqual(2, perform.call_count)
        self.assertEqual(["failed", "success"], [row["status"] for row in result["results"]])
        self.assertEqual("/backup", result["results"][1]["backup"]["download_url"])
        self.assertEqual(2, result["total"])

    def test_batch_blocks_linked_archives_and_skips_already_archived(self):
        with contextlib.closing(sqlite3.connect(self.state.codex_home / "state_5.sqlite")) as conn, conn:
            conn.execute("INSERT INTO thread_spawn_edges VALUES (?,?,?)", (ACTIVE_ID, "01900000-0000-7000-8000-00000000d005", "done"))
        with mock.patch("lib.session_tools.native_request") as native:
            job = self.tools.start_batch([ACTIVE_ID, ARCHIVED_ID], "archive")
            result = self.wait_batch(job["job"])
            native.assert_not_called()
        self.assertEqual(["session_protected_or_linked", "already_in_target_state"], [row["error"] for row in result["results"]])
        self.assertEqual(["skipped", "skipped"], [row["status"] for row in result["results"]])

    def test_batch_backup_creates_independent_restorable_files(self):
        job = self.tools.start_batch([ACTIVE_ID, ARCHIVED_ID], "backup")
        result = self.wait_batch(job["job"])
        self.assertEqual(["success", "success"], [row["status"] for row in result["results"]])
        backups = list((self.state.app_dir / "backups").glob("*.zip"))
        self.assertEqual(2, len(backups))
        for path in backups:
            with zipfile.ZipFile(path) as bundle:
                metadata = json.loads(bundle.read("backup.json"))
                self.assertEqual(metadata["sha256"], hashlib.sha256(bundle.read(metadata["stored_file"])).hexdigest())

    def test_batch_pending_is_not_reported_as_success_and_prevents_duplicate_jobs(self):
        entered, release = threading.Event(), threading.Event()
        def perform(*args, **kwargs):
            entered.set()
            release.wait(3)
            return {"verified": False}
        with mock.patch.object(self.tools, "action", side_effect=perform):
            batch = self.tools.start_batch([ACTIVE_ID], "archive")
            self.assertTrue(entered.wait(1))
            try:
                with self.assertRaisesRegex(ValueError, "batch_already_running"):
                    self.tools.start_batch([ARCHIVED_ID], "delete")
                self.assertEqual(batch["job"], self.tools.batch_status()["job"])
            finally:
                release.set()
            result = self.wait_batch(batch["job"])
        self.assertEqual("pending", result["results"][0]["status"])

    def test_apply_suggestions_mixes_archive_delete_and_skips_without_suggestion(self):
        archive_id = "01900000-0000-7000-8000-00000000d005"
        delete_id = "01900000-0000-7000-8000-00000000d006"
        def native(codex, home, method, params):
            session_id = params["threadId"]
            path = self.tools.log_path(self.tools.record(session_id))
            with contextlib.closing(sqlite3.connect(home / "state_5.sqlite")) as conn, conn:
                if method == "thread/archive":
                    destination = home / "archived_sessions" / path.name
                    path.rename(destination)
                    conn.execute("UPDATE threads SET archived=1, rollout_path=? WHERE id=?", (str(destination), session_id))
                elif method == "thread/delete":
                    self.assertTrue(list((self.state.app_dir / "backups").glob("*.zip")))
                    path.unlink()
                    conn.execute("DELETE FROM threads WHERE id=?", (session_id,))
                else:
                    self.fail("Unexpected operation: " + method)
            return {}
        with mock.patch("lib.session_tools.native_request", side_effect=native) as perform:
            batch = self.tools.start_batch([archive_id, delete_id, ACTIVE_ID], "suggested")
            result = self.wait_batch(batch["job"])
        self.assertEqual(2, perform.call_count)
        self.assertEqual(["archive", "delete", None], [row["action"] for row in result["results"]])
        self.assertEqual(["success", "success", "skipped"], [row["status"] for row in result["results"]])
        self.assertEqual("no_suggestion", result["results"][2]["error"])
        self.assertTrue(result["results"][1]["backup"]["download_url"])
        self.assertEqual("archived", self.state.record_for(archive_id)["actual_state"])
        self.assertIsNone(self.state.record_for(delete_id))
        self.assertEqual("active", self.state.record_for(ACTIVE_ID)["actual_state"])

    def test_changed_suggestion_never_escalates_archive_into_delete(self):
        archive_id = "01900000-0000-7000-8000-00000000d005"
        with mock.patch.object(self.tools, "suggestion", side_effect=[{"action": "archive"}, {"action": "delete"}]), mock.patch("lib.session_tools.native_request") as native:
            batch = self.tools.start_batch([archive_id], "suggested")
            result = self.wait_batch(batch["job"])
            native.assert_not_called()
        self.assertEqual("archive", result["results"][0]["action"])
        self.assertEqual("skipped", result["results"][0]["status"])
        self.assertEqual("suggestion_changed", result["results"][0]["error"])
        self.assertFalse((self.state.app_dir / "backups").exists())

    def test_batch_progress_reports_completed_count_and_current_session(self):
        entered, release = threading.Event(), threading.Event()
        def perform(session_id, *args, **kwargs):
            if session_id == ARCHIVED_ID:
                entered.set()
                release.wait(3)
            return {"verified": True}
        with mock.patch.object(self.tools, "action", side_effect=perform):
            batch = self.tools.start_batch([ACTIVE_ID, ARCHIVED_ID], "backup")
            self.assertTrue(entered.wait(1))
            try:
                progress = self.tools.batch_status(batch["job"])
                self.assertTrue(progress["running"])
                self.assertEqual(2, progress["total"])
                self.assertEqual(1, len(progress["results"]))
                self.assertEqual(ARCHIVED_ID, progress["current"]["session_id"])
                self.assertEqual(2, progress["current"]["index"])
                self.assertEqual("backup", progress["current"]["action"])
            finally:
                release.set()
            finished = self.wait_batch(batch["job"])
        self.assertEqual(2, len(finished["results"]))
        self.assertIsNone(finished["current"])


if __name__ == "__main__":
    unittest.main()
