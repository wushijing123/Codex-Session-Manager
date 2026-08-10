from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS))

from lib.core import (  # noqa: E402
    apply_semantic_review_results,
    build_short_conversation_review_bundle,
    classification_policy,
    classify,
    collect_log_files,
    conversation_preview,
    inspect_conversation,
    scan_catalog,
)
from lib.server import DashboardState, plan_block_reason  # noqa: E402
import session_actions  # noqa: E402

SESSION_ID = "01900000-0000-7000-8000-000000000001"


def create_db(path: Path, updated_at: int, include_thread: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
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
    if include_thread:
        log_path = path.parent / "placeholder.jsonl"
        conn.execute(
            "INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                SESSION_ID,
                str(log_path),
                updated_at - 100,
                updated_at,
                "vscode",
                "/tmp/project",
                "无业务测试任务",
                120,
                1,
                1,
                updated_at,
                "1.0.0",
                "只用于恢复测试",
                None,
                "test-model",
            ),
        )
    conn.commit()
    conn.close()


class SessionManagerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.codex = self.root / ".codex"
        self.app = self.root / "app"
        self.archive = self.codex / "archived_sessions"
        self.archive.mkdir(parents=True)
        self.log = self.archive / f"rollout-test-{SESSION_ID}.jsonl"
        self.log.write_text(
            '{"type":"session_meta","payload":{"id":"' + SESSION_ID + '"}}\n'
            '{"type":"response_item","payload":{"role":"user","content":"test"}}\n',
            encoding="utf-8",
        )
        create_db(self.codex / "state_5.sqlite", 2_000_000_000)
        create_db(self.codex / "sqlite/state_5.sqlite", 1_000_000_000, include_thread=False)
        conn = sqlite3.connect(self.codex / "state_5.sqlite")
        conn.execute("UPDATE threads SET rollout_path=?", (str(self.log),))
        conn.execute(
            "INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "01900000-0000-7000-8000-000000000099",
                str(self.codex / "sessions/anchor.jsonl"),
                1_999_999_900,
                2_000_000_001,
                "vscode",
                "/tmp/project",
                "active anchor",
                1,
                1,
                0,
                None,
                "1.0.0",
                "anchor",
                None,
                "test-model",
            ),
        )
        conn.commit()
        conn.close()
        self.pins = self.root / "pins.json"
        self.pins.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "pinned_ids": [],
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def command(self, *args: str, expect: int = 0) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "session_actions.py"),
                "--app-dir",
                str(self.app),
                *args,
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(expect, result.returncode, result.stderr + result.stdout)
        return result

    def latest_manifest(self) -> Path:
        return max((self.app / "manifests").glob("*.json"), key=lambda p: p.stat().st_mtime_ns)

    def test_database_selection_unindexed_and_pin_gate(self) -> None:
        catalog = scan_catalog(self.codex, self.app, self.pins)
        self.assertTrue(str(catalog["selected_database"]).endswith("/.codex/state_5.sqlite"))
        self.assertFalse(catalog["database_ambiguous"])
        self.assertTrue(catalog["mutation_allowed"])
        self.assertEqual(2, catalog["summary"]["indexed"])
        extra = self.archive / "rollout-extra-01900000-0000-7000-8000-000000000002.jsonl"
        extra.write_text("{}\n", encoding="utf-8")
        catalog = scan_catalog(self.codex, self.app, None)
        self.assertFalse(catalog["mutation_allowed"])
        self.assertEqual(1, catalog["summary"]["unindexed"])

    def test_equally_current_database_copies_are_ambiguous(self) -> None:
        duplicate = self.codex / "sqlite/state_6.sqlite"
        duplicate.parent.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(self.codex / "state_5.sqlite")
        target = sqlite3.connect(duplicate)
        source.backup(target)
        target.close()
        source.close()
        catalog = scan_catalog(self.codex, self.app, self.pins)
        self.assertTrue(catalog["database_ambiguous"])
        self.assertFalse(catalog["mutation_allowed"])

    def test_symlink_logs_are_never_cataloged(self) -> None:
        target = self.root / "outside.jsonl"
        target.write_text("{}\n", encoding="utf-8")
        link = self.archive / "rollout-link-01900000-0000-7000-8000-000000000003.jsonl"
        link.symlink_to(target)
        logs = collect_log_files(self.codex)
        self.assertNotIn("01900000-0000-7000-8000-000000000003", logs)

    def test_time_policy_guides_cleanup_without_turning_value_into_a_lock(self) -> None:
        now = 2_000_000_000
        policy = classification_policy(
            {"cleanup_age_days": 30, "automation_keep_runs": 3}
        )

        def record(title: str, age_days: int, **updates: object) -> dict[str, object]:
            value: dict[str, object] = {
                "title": title,
                "actual_state": "archived",
                "updated_at": now - age_days * 86400,
                "pin_status": "snapshot",
                "pinned": False,
                "permanent_protection": False,
                "state_conflict": False,
                "relation_count": 0,
                "size_bytes": 1024,
                "write_signals": 0,
            }
            value.update(updates)
            return value

        old_value = record("实现课程 Skill", 35)
        self.assertEqual("cold_archive", classify(old_value, now, policy)[0])
        old_low_value = record("普通问答", 35)
        self.assertEqual("delete_candidate", classify(old_low_value, now, policy)[0])
        old_large = record("普通问答", 35, size_bytes=21 * 1024 * 1024)
        self.assertEqual("cold_archive", classify(old_large, now, policy)[0])
        old_unscanned = record("普通问答", 65)
        self.assertEqual("delete_candidate", classify(old_unscanned, now, policy)[0])
        old_scanned_short = record(
            "普通问答",
            65,
            conversation_scanned=True,
            business_turns=2,
            has_attachments=False,
        )
        recommendation, reasons, hard = classify(old_scanned_short, now, policy)
        self.assertEqual("permanent_delete_candidate", recommendation)
        self.assertIn("inactive_60d_permanent_delete_candidate", reasons)
        self.assertFalse(hard)
        old_scanned_with_attachment = record(
            "普通问答",
            65,
            conversation_scanned=True,
            business_turns=2,
            has_attachments=True,
        )
        self.assertEqual("cold_archive", classify(old_scanned_with_attachment, now, policy)[0])
        recent_title_hint = record("查看 Skill 工作流", 3)
        self.assertEqual("review_required", classify(recent_title_hint, now, policy)[0])
        recent_write = record("完成工作", 3, write_signals=1)
        recommendation, reasons, hard = classify(recent_write, now, policy)
        self.assertEqual("high_value", recommendation)
        self.assertIn("verified_write_work", reasons)
        self.assertFalse(hard)
        automation_history = record(
            "Automation: 日更",
            10,
            automation_key="daily",
            automation_rank=4,
        )
        recommendation, reasons, hard = classify(automation_history, now, policy)
        self.assertEqual("delete_candidate", recommendation)
        self.assertIn("old_automation_history", reasons)
        self.assertFalse(hard)
        grouped = record("父任务", 35, relation_count=2)
        recommendation, reasons, hard = classify(grouped, now, policy)
        self.assertEqual("delete_candidate", recommendation)
        self.assertIn("group_action_required", reasons)
        self.assertFalse(hard)
        self.assertIsNone(plan_block_reason(grouped))

    def test_short_conversation_scan_and_codex_review_are_cached_safely(self) -> None:
        self.log.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "type": "event_msg",
                            "payload": {
                                "type": "task_started",
                                "turn_id": "turn-1",
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "type": "event_msg",
                            "payload": {
                                "type": "user_message",
                                "message": "Python 怎么查看版本？",
                                "images": [],
                                "local_images": [],
                            },
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        {
                            "type": "event_msg",
                            "payload": {
                                "type": "agent_message",
                                "phase": "final_answer",
                                "message": "运行 python3 --version。",
                            },
                        },
                        ensure_ascii=False,
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        details = inspect_conversation(self.log)
        self.assertEqual(1, details["business_turns"])
        self.assertEqual(1, details["assistant_finals"])
        self.assertEqual(0, details["tool_events"])

        old = int(__import__("time").time()) - 10 * 86400
        conn = sqlite3.connect(self.codex / "state_5.sqlite")
        conn.execute(
            "UPDATE threads SET updated_at=?, title=? WHERE id=?",
            (old, "Python 怎么查看版本？", SESSION_ID),
        )
        conn.commit()
        conn.close()
        exported = build_short_conversation_review_bundle(
            self.codex,
            self.app,
            self.pins,
            3,
        )
        self.assertEqual(1, exported["summary"]["short_conversations"])
        bundle = Path(exported["bundle_path"])
        item = json.loads(bundle.read_text(encoding="utf-8"))["items"][0]
        results = self.root / "review-results.json"
        results.write_text(
            json.dumps(
                {
                    "reviews": [
                        {
                            "session_id": item["session_id"],
                            "label": "one_off_disposable",
                            "confidence": 0.96,
                            "reason": "单次知识问答，没有工具、附件或持久产物。",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        applied = apply_semantic_review_results(self.app, bundle, results)
        self.assertEqual(1, applied["applied"])
        catalog = scan_catalog(self.codex, self.app, self.pins)
        record = next(item for item in catalog["sessions"] if item["id"] == SESSION_ID)
        self.assertEqual(1, record["business_turns"])
        self.assertEqual("one_off_disposable", record["semantic_review"]["label"])
        self.assertEqual("delete_candidate", record["recommendation"])
        self.assertIn("codex_one_off_review", record["recommendation_reasons"])

    def test_detail_preview_shows_only_real_chat_and_local_summary(self) -> None:
        self.log.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "timestamp": "2026-05-30T14:11:54Z",
                            "type": "response_item",
                            "payload": {
                                "type": "message",
                                "role": "system",
                                "content": [{"type": "input_text", "text": "do not show me"}],
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "timestamp": "2026-05-30T14:11:55Z",
                            "type": "event_msg",
                            "payload": {
                                "type": "user_message",
                                "message": (
                                    '<in-app-browser-context source="ambient-ui-state">'
                                    "automatic browser state"
                                    "</in-app-browser-context>\n"
                                    "## My request for Codex:\n"
                                    "hello token=super-secret"
                                ),
                                "images": [],
                                "local_images": [],
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "timestamp": "2026-05-30T14:11:56Z",
                            "type": "event_msg",
                            "payload": {
                                "type": "agent_message",
                                "phase": "final_answer",
                                "message": "hello，有什么要处理的？",
                            },
                        },
                        ensure_ascii=False,
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        preview = conversation_preview(self.log)
        self.assertTrue(preview["available"])
        self.assertEqual(2, preview["total_messages"])
        self.assertIn("一次性问候或测试", preview["summary"])
        visible = "\n".join(item["text"] for item in preview["messages"])
        self.assertNotIn("do not show me", visible)
        self.assertNotIn("automatic browser state", visible)
        self.assertNotIn("My request for Codex", visible)
        self.assertNotIn("super-secret", visible)
        self.assertIn("token=[REDACTED]", visible)

        dashboard = DashboardState(
            self.codex,
            self.app,
            SKILL_DIR / "assets/dashboard",
            self.pins,
            False,
        )
        detail = dashboard.session_detail(SESSION_ID, 24)
        self.assertTrue(detail["available"])
        self.assertEqual(2, detail["shown_messages"])
        self.assertIn("仅展示真实用户消息", detail["safety_note"])

    def test_detail_preview_uses_head_and_tail_for_long_conversations(self) -> None:
        events: list[str] = []
        for index in range(6):
            events.extend(
                [
                    json.dumps(
                        {
                            "type": "event_msg",
                            "payload": {
                                "type": "task_started",
                                "turn_id": f"turn-{index}",
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "type": "event_msg",
                            "payload": {
                                "type": "user_message",
                                "message": f"问题 {index}",
                            },
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        {
                            "type": "event_msg",
                            "payload": {
                                "type": "agent_message",
                                "phase": "final_answer",
                                "message": f"回答 {index}",
                            },
                        },
                        ensure_ascii=False,
                    ),
                ]
            )
        self.log.write_text("\n".join(events) + "\n", encoding="utf-8")
        preview = conversation_preview(self.log, max_messages=4)
        self.assertEqual(12, preview["total_messages"])
        self.assertEqual(4, preview["shown_messages"])
        self.assertEqual(8, preview["omitted_messages"])
        self.assertEqual("omitted", preview["messages"][2]["role"])
        self.assertEqual("回答 5", preview["messages"][-1]["text"])

    def test_archived_content_search_returns_inert_context_and_skips_active_logs(self) -> None:
        phrase = "搜国内外多平台热点，适合找选题、挖素材"
        self.log.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "type": "event_msg",
                            "payload": {"type": "user_message", "message": phrase},
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        {
                            "type": "event_msg",
                            "payload": {
                                "type": "agent_message",
                                "phase": "final_answer",
                                "message": "可以用跨平台热点作为选题素材。",
                            },
                        },
                        ensure_ascii=False,
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        dashboard = DashboardState(
            self.codex,
            self.app,
            SKILL_DIR / "assets/dashboard",
            self.pins,
            False,
        )
        result = dashboard.search_archived_content(phrase)
        self.assertEqual(1, len(result["matches"]))
        self.assertEqual(SESSION_ID, result["matches"][0]["session_id"])
        self.assertEqual("user", result["matches"][0]["excerpts"][0]["role"])
        self.assertIn("热点", result["matches"][0]["excerpts"][0]["excerpt"])
        job_id = dashboard.start_archived_content_search(phrase)["job_id"]
        for _ in range(100):
            status = dashboard.archived_content_search_status(job_id)
            if status["status"] != "running":
                break
            time.sleep(0.01)
        self.assertEqual("complete", status["status"])
        self.assertGreaterEqual(status["scanned"], 1)
        self.assertEqual(1, len(status["result"]["matches"]))
        with self.assertRaisesRegex(ValueError, "content_search_query_too_short"):
            dashboard.search_archived_content("A")

    def test_archived_content_search_allows_artifacts_but_skips_tool_arguments(self) -> None:
        phrase = "搜国内外多平台热点，适合找选题、挖素材"
        self.log.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "type": "response_item",
                            "payload": {
                                "type": "custom_tool_call",
                                "name": "unsafe_tool",
                                "input": phrase,
                            },
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        {
                            "type": "response_item",
                            "payload": {
                                "type": "custom_tool_call_output",
                                "output": [
                                    {"type": "input_text", "text": phrase},
                                ],
                            },
                        },
                        ensure_ascii=False,
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        dashboard = DashboardState(
            self.codex,
            self.app,
            SKILL_DIR / "assets/dashboard",
            self.pins,
            False,
        )
        result = dashboard.search_archived_content(phrase)
        excerpts = result["matches"][0]["excerpts"]
        self.assertEqual(["artifact"], [excerpt["role"] for excerpt in excerpts])

    def test_permanent_delete_plan_prepares_direct_delete(self) -> None:
        dashboard = DashboardState(
            self.codex,
            self.app,
            SKILL_DIR / "assets/dashboard",
            self.pins,
            False,
        )
        catalog = dashboard.save_plan(SESSION_ID, "permanent_delete")
        record = next(item for item in catalog["sessions"] if item["id"] == SESSION_ID)
        self.assertEqual("permanent_delete", record["planned_action"])
        sheet = dashboard.confirmation_sheet()
        self.assertEqual(1, sheet["counts"]["permanent_delete"])
        self.assertEqual(0, sheet["counts"]["quarantine"])
        self.assertNotIn("confirmation_phrase", sheet)
        manifests = dashboard.confirm_sheet_button(
            sheet["sheet_id"], bool(sheet["warnings"]), True
        )
        self.assertEqual(1, len(manifests))
        self.assertEqual("permanent_delete", manifests[0]["action"])

    def test_confirmation_sheet_shows_blocker_instead_of_raising(self) -> None:
        dashboard = DashboardState(
            self.codex,
            self.app,
            SKILL_DIR / "assets/dashboard",
            self.pins,
            False,
        )
        dashboard.save_plan(SESSION_ID, "permanent_delete")
        self.pins.write_text(
            json.dumps(
                {
                    "generated_at": "2000-01-01T00:00:00+00:00",
                    "pinned_ids": [],
                }
            ),
            encoding="utf-8",
        )
        sheet = dashboard.confirmation_sheet()
        self.assertFalse(sheet["can_execute"])
        self.assertIn(
            "fresh_pin_snapshot_required",
            {item["code"] for item in sheet["blockers"]},
        )

    def test_confirmation_sheet_warns_about_important_permanent_delete(self) -> None:
        dashboard = DashboardState(
            self.codex,
            self.app,
            SKILL_DIR / "assets/dashboard",
            self.pins,
            False,
        )
        dashboard.save_plan(SESSION_ID, "permanent_delete")
        catalog = deepcopy(dashboard.catalog)
        record = next(item for item in catalog["sessions"] if item["id"] == SESSION_ID)
        record.update(
            recommendation="high_value",
            write_signals=2,
            business_turns=8,
            has_attachments=True,
            semantic_review={"label": "produced_artifact", "confidence": 0.95},
        )
        with mock.patch.object(dashboard, "refresh", return_value=catalog):
            sheet = dashboard.confirmation_sheet()
            with self.assertRaisesRegex(
                PermissionError, "second_confirmation_required"
            ):
                dashboard.confirm_sheet_button(sheet["sheet_id"], True, False)
            with self.assertRaisesRegex(
                PermissionError, "important_warnings_not_acknowledged"
            ):
                dashboard.confirm_sheet_button(sheet["sheet_id"], False, True)
        warning = next(
            item for item in sheet["warnings"] if item["session_id"] == SESSION_ID
        )
        self.assertGreaterEqual(len(warning["reasons"]), 4)

    def test_dashboard_starts_with_visual_home_and_simple_navigation(self) -> None:
        html = (SKILL_DIR / "assets/dashboard/index.html").read_text(encoding="utf-8")
        javascript = (SKILL_DIR / "assets/dashboard/app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('id="view-home" class="view active"', html)
        self.assertIn('id="lifecycleDonut"', html)
        self.assertIn('id="storageStack"', html)
        self.assertIn('id="ageChart"', html)
        self.assertEqual(4, html.count('<button class="tab'))
        self.assertNotIn('id="view-board"', html)
        self.assertNotIn('id="view-scan"', html)
        self.assertIn('class="skip-link"', html)
        self.assertIn('class="panel advanced-panel"', html)
        self.assertIn('id="loadMoreAutoBtn"', html)
        self.assertIn('id="loadMoreExplorerBtn"', html)
        self.assertIn('role="dialog"', html)
        self.assertIn('id="finalConfirmDialog"', html)
        self.assertNotIn("固定本地确认短语", javascript)
        self.assertIn("confirm_sheet_button", (SKILL_DIR / "scripts/lib/server.py").read_text(encoding="utf-8"))
        self.assertIn('api("/api/refresh"', javascript)
        self.assertIn('switchView("home")', javascript)
        self.assertIn("visibleLimit: 25", javascript)
        self.assertIn("explorerVisibleLimit: 50", javascript)
        self.assertIn("清除旧计划", javascript)
        self.assertIn("条可处理", javascript)
        self.assertIn("条旧版标记（不会执行）", javascript)
        self.assertIn("currentPlans.forEach", javascript)
        self.assertNotIn("draggable", javascript)
        stylesheet = (SKILL_DIR / "assets/dashboard/style.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("@media (prefers-reduced-motion: reduce)", stylesheet)

    def test_wal_rows_are_visible_and_duplicate_titles_remain_distinct(self) -> None:
        sessions = self.codex / "sessions/2026/07/25"
        sessions.mkdir(parents=True)
        second_id = "01900000-0000-7000-8000-000000000004"
        second_log = sessions / f"rollout-wal-{second_id}.jsonl"
        second_log.write_text("{}\n", encoding="utf-8")
        conn = sqlite3.connect(self.codex / "state_5.sqlite")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                second_id,
                str(second_log),
                2_000_000_002,
                2_000_000_003,
                "vscode",
                "/tmp/project",
                "无业务测试任务",
                10,
                1,
                0,
                None,
                "1.0.0",
                "duplicate title",
                None,
                "test-model",
            ),
        )
        conn.commit()
        catalog = scan_catalog(self.codex, self.app, self.pins)
        matching = [item for item in catalog["sessions"] if item["title"] == "无业务测试任务"]
        self.assertEqual({SESSION_ID, second_id}, {item["id"] for item in matching})
        selected = next(
            item
            for item in catalog["database_candidates"]
            if item["path"] == str((self.codex / "state_5.sqlite").resolve())
        )
        self.assertGreater(selected["wal_bytes"], 0)
        conn.close()

    def test_pinned_and_parent_dependencies_block_prepare(self) -> None:
        self.pins.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "pinned_ids": [SESSION_ID],
                }
            ),
            encoding="utf-8",
        )
        self.command(
            "prepare",
            "--action",
            "cold_archive",
            "--session-id",
            SESSION_ID,
            "--codex-home",
            str(self.codex),
            "--pinned-file",
            str(self.pins),
            "--target",
            str(self.root / "cold"),
            expect=2,
        )
        self.pins.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "pinned_ids": [],
                }
            ),
            encoding="utf-8",
        )
        conn = sqlite3.connect(self.codex / "state_5.sqlite")
        conn.execute(
            "INSERT INTO thread_spawn_edges VALUES (?,?,?)",
            ("01900000-0000-7000-8000-000000000099", SESSION_ID, "completed"),
        )
        conn.commit()
        conn.close()
        self.command(
            "prepare",
            "--action",
            "cold_archive",
            "--session-id",
            SESSION_ID,
            "--codex-home",
            str(self.codex),
            "--pinned-file",
            str(self.pins),
            "--target",
            str(self.root / "cold"),
            expect=2,
        )

    def test_hash_and_schema_drift_block_apply_without_data_loss(self) -> None:
        self.command(
            "prepare",
            "--action",
            "cold_archive",
            "--session-id",
            SESSION_ID,
            "--codex-home",
            str(self.codex),
            "--pinned-file",
            str(self.pins),
            "--target",
            str(self.root / "cold"),
        )
        manifest = self.latest_manifest()
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.log.write_text(self.log.read_text(encoding="utf-8") + '{"changed":true}\n', encoding="utf-8")
        self.command(
            "apply",
            "--manifest",
            str(manifest),
            "--confirm",
            payload["confirmation_phrase"],
            "--compression",
            "none",
            "--fixture-mode",
            expect=2,
        )
        self.assertTrue(self.log.exists())
        conn = sqlite3.connect(self.codex / "state_5.sqlite")
        self.assertEqual(
            1,
            conn.execute("SELECT COUNT(*) FROM threads WHERE id=?", (SESSION_ID,)).fetchone()[0],
        )
        conn.close()

        os.chmod(manifest, 0o600)
        os.chmod(manifest.with_suffix(".json.sha256"), 0o600)
        manifest.unlink()
        manifest.with_suffix(".json.sha256").unlink()
        self.log.write_text(
            '{"type":"session_meta","payload":{"id":"' + SESSION_ID + '"}}\n',
            encoding="utf-8",
        )
        self.command(
            "prepare",
            "--action",
            "cold_archive",
            "--session-id",
            SESSION_ID,
            "--codex-home",
            str(self.codex),
            "--pinned-file",
            str(self.pins),
            "--target",
            str(self.root / "cold"),
        )
        manifest = self.latest_manifest()
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        conn = sqlite3.connect(self.codex / "state_5.sqlite")
        conn.execute("ALTER TABLE threads ADD COLUMN future_version_field TEXT")
        conn.commit()
        conn.close()
        self.command(
            "apply",
            "--manifest",
            str(manifest),
            "--confirm",
            payload["confirmation_phrase"],
            "--compression",
            "none",
            "--fixture-mode",
            expect=2,
        )
        self.assertTrue(self.log.exists())

    def test_copy_interruption_rolls_back_before_cross_volume_move(self) -> None:
        self.command(
            "prepare",
            "--action",
            "cold_archive",
            "--session-id",
            SESSION_ID,
            "--codex-home",
            str(self.codex),
            "--pinned-file",
            str(self.pins),
            "--target",
            str(self.root / "external-volume"),
        )
        manifest = self.latest_manifest()
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        args = SimpleNamespace(
            manifest=manifest,
            confirm=payload["confirmation_phrase"],
            compression="none",
            fixture_mode=True,
            wait_for_exit_seconds=0,
            app_dir=self.app,
        )
        with mock.patch.object(
            session_actions.shutil,
            "copyfile",
            side_effect=OSError("simulated cross-volume interruption"),
        ):
            with self.assertRaises(OSError):
                session_actions.apply_manifest(args)
        self.assertTrue(self.log.exists())
        conn = sqlite3.connect(self.codex / "state_5.sqlite")
        self.assertEqual(
            1,
            conn.execute("SELECT COUNT(*) FROM threads WHERE id=?", (SESSION_ID,)).fetchone()[0],
        )
        conn.close()

    def test_cold_archive_and_full_restore_round_trip(self) -> None:
        cold = self.root / "cold"
        self.command(
            "prepare",
            "--action",
            "cold_archive",
            "--session-id",
            SESSION_ID,
            "--codex-home",
            str(self.codex),
            "--pinned-file",
            str(self.pins),
            "--target",
            str(cold),
        )
        manifest = self.latest_manifest()
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.command(
            "apply",
            "--manifest",
            str(manifest),
            "--confirm",
            payload["confirmation_phrase"],
            "--compression",
            "auto",
            "--fixture-mode",
        )
        self.assertFalse(self.log.exists())
        conn = sqlite3.connect(self.codex / "state_5.sqlite")
        self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0])
        conn.close()
        package = next(cold.glob("*/package.json")).parent
        package_metadata = json.loads((package / "package.json").read_text(encoding="utf-8"))
        if __import__("shutil").which("zstd"):
            self.assertEqual("zstd", package_metadata["compression"])
            self.assertTrue((package / "session.jsonl.zst").is_file())
        (self.app / "settings.json").write_text(
            json.dumps({"cold_storage_dir": str(cold)}), encoding="utf-8"
        )
        catalog = scan_catalog(self.codex, self.app, self.pins)
        cold_record = next(item for item in catalog["sessions"] if item["id"] == SESSION_ID)
        self.assertEqual("cold", cold_record["actual_state"])
        self.command(
            "restore",
            "--package",
            str(package),
            "--confirm",
            f"RESTORE {SESSION_ID}",
            "--codex-home",
            str(self.codex),
            "--fixture-mode",
        )
        self.assertTrue(self.log.exists())
        self.assertFalse(package.exists())
        conn = sqlite3.connect(self.codex / "state_5.sqlite")
        self.assertEqual(2, conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0])
        conn.close()
        self.assertEqual(
            payload["items"][0]["source_sha256"],
            __import__("hashlib").sha256(self.log.read_bytes()).hexdigest(),
        )

    def test_direct_permanent_delete_retains_only_redacted_audit(self) -> None:
        self.command(
            "prepare",
            "--action",
            "permanent_delete",
            "--session-id",
            SESSION_ID,
            "--codex-home",
            str(self.codex),
            "--pinned-file",
            str(self.pins),
        )
        manifest = self.latest_manifest()
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertFalse(payload["content_retained_after_success"])
        self.assertIsNone(payload["expires_at"])
        self.command(
            "apply",
            "--manifest",
            str(manifest),
            "--confirm",
            payload["confirmation_phrase"],
            "--compression",
            "none",
            "--fixture-mode",
        )
        self.assertFalse(self.log.exists())
        self.assertFalse(manifest.exists())
        self.assertFalse(manifest.with_suffix(".json.sha256").exists())
        conn = sqlite3.connect(self.codex / "state_5.sqlite")
        self.assertEqual(
            0,
            conn.execute("SELECT COUNT(*) FROM threads WHERE id=?", (SESSION_ID,)).fetchone()[0],
        )
        conn.close()
        self.assertFalse(any((self.app / "delete-staging").glob("*/session.jsonl")))
        self.assertFalse((self.app / "backups" / f"{payload['manifest_id']}.sqlite").exists())
        audits = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in (self.app / "audit").glob("*.json")
        ]
        audit = next(item for item in audits if item.get("event") == "permanent_delete")
        self.assertFalse(audit["content_retained"])
        self.assertEqual(payload["items"][0]["source_size"], audit["bytes_purged"])
        self.assertNotIn("无业务测试任务", json.dumps(audit, ensure_ascii=False))
        self.assertNotIn("source_path", json.dumps(audit, ensure_ascii=False))

    def test_quarantine_blocks_early_purge_then_allows_exact_purge(self) -> None:
        self.command(
            "prepare",
            "--action",
            "quarantine",
            "--session-id",
            SESSION_ID,
            "--codex-home",
            str(self.codex),
            "--pinned-file",
            str(self.pins),
        )
        manifest = self.latest_manifest()
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertIsNone(payload["expires_at"])
        self.assertTrue(payload["quarantine_starts_on_apply"])
        self.command(
            "apply",
            "--manifest",
            str(manifest),
            "--confirm",
            payload["confirmation_phrase"],
            "--compression",
            "none",
            "--fixture-mode",
        )
        package = next((self.app / "quarantine").glob("*/package.json")).parent
        package_metadata = json.loads((package / "package.json").read_text(encoding="utf-8"))
        started = datetime.fromisoformat(package_metadata["quarantine_started_at"])
        expires = datetime.fromisoformat(package_metadata["expires_at"])
        self.assertEqual(14 * 86400, int((expires - started).total_seconds()))
        self.command(
            "purge",
            "--package",
            str(package),
            "--confirm",
            f"PURGE-FOREVER {SESSION_ID}",
            "--parent-manifest",
            str(manifest),
            "--pinned-file",
            str(self.pins),
            expect=2,
        )
        self.assertTrue(package.exists())
        self.command(
            "purge",
            "--package",
            str(package),
            "--confirm",
            f"PURGE-FOREVER {SESSION_ID}",
            "--parent-manifest",
            str(manifest),
            "--pinned-file",
            str(self.pins),
            "--expires-at",
            "2000-01-01T00:00:00+00:00",
            expect=2,
        )
        self.assertTrue(package.exists())
        self.command(
            "purge",
            "--package",
            str(package),
            "--confirm",
            f"PURGE-FOREVER {SESSION_ID}",
            "--parent-manifest",
            str(manifest),
            "--pinned-file",
            str(self.pins),
            "--expires-at",
            "2000-01-01T00:00:00+00:00",
            "--fixture-mode",
        )
        self.assertFalse(package.exists())
        self.assertFalse(manifest.exists())
        purge_audits = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in (self.app / "audit").glob("*.json")
            if json.loads(path.read_text(encoding="utf-8")).get("event") == "purge"
        ]
        self.assertEqual(False, purge_audits[-1]["content_retained"])
        self.assertNotIn("无业务测试任务", json.dumps(purge_audits[-1], ensure_ascii=False))

    def test_auto_preview_apply_and_clear_preserve_manual_plans(self) -> None:
        def record(
            session_id: str,
            recommendation: str,
            size_bytes: int,
            hard_protected: bool = False,
            pinned: bool = False,
        ) -> dict[str, object]:
            return {
                "id": session_id,
                "title": f"title-{session_id[-1]}",
                "actual_state": "archived",
                "recommendation": recommendation,
                "recommendation_reasons": [
                    "pin_snapshot_unavailable_or_stale",
                    recommendation,
                ],
                "size_bytes": size_bytes,
                "hard_protected": hard_protected,
                "pinned": pinned,
                "pin_status": "pinned" if pinned else "stale",
                "permanent_protection": False,
                "state_conflict": False,
                "relation_count": 0,
                "source": "vscode",
                "planned_action": None,
            }

        delete_id = "01900000-0000-7000-8000-000000000010"
        cold_id = "01900000-0000-7000-8000-000000000011"
        manual_id = "01900000-0000-7000-8000-000000000012"
        pinned_id = "01900000-0000-7000-8000-000000000015"
        catalog = {
            "mutation_allowed": False,
            "selected_database": "/tmp/state.sqlite",
            "database_ambiguous": False,
            "pin_snapshot_status": "stale",
            "summary": {
                "by_recommendation": {
                    "protected": 1,
                    "high_value": 1,
                    "review_required": 1,
                    "cold_archive": 1,
                    "delete_candidate": 1,
                }
            },
            "sessions": [
                record(delete_id, "delete_candidate", 100),
                record(cold_id, "cold_archive", 21 * 1024 * 1024),
                record(manual_id, "high_value", 500),
                record("01900000-0000-7000-8000-000000000013", "protected", 20, True),
                record("01900000-0000-7000-8000-000000000014", "review_required", 20),
                record(pinned_id, "delete_candidate", 40, True, pinned=True),
            ],
        }
        (self.app / "plans.json").parent.mkdir(parents=True, exist_ok=True)
        (self.app / "plans.json").write_text(
            json.dumps({"version": 1, "plans": {manual_id: "archive"}}),
            encoding="utf-8",
        )
        with mock.patch("lib.server.scan_catalog", side_effect=lambda *args: deepcopy(catalog)):
            dashboard = DashboardState(
                self.codex,
                self.app,
                SKILL_DIR / "assets/dashboard",
                self.pins,
                False,
            )
            conservative = dashboard.auto_preview("conservative")
            self.assertEqual([cold_id], [item["session_id"] for item in conservative["proposals"]])
            self.assertTrue(conservative["planning_allowed"])
            self.assertFalse(conservative["execution_ready"])
            space = dashboard.auto_preview("space")
            self.assertEqual(6, space["summary"]["archived_total"])
            self.assertEqual(3, space["summary"]["strategy_candidates"])
            self.assertEqual(
                {"cold_archive", "quarantine"},
                {item["action"] for item in space["proposals"]},
            )
            pinned_proposal = next(
                item for item in space["proposals"] if item["session_id"] == pinned_id
            )
            self.assertEqual("pinned", pinned_proposal["blocked_reason"])
            result = dashboard.apply_auto_plan(
                "space",
                [
                    {"session_id": cold_id, "action": "cold_archive"},
                    {"session_id": delete_id, "action": "quarantine"},
                ],
            )
            self.assertEqual(2, result["applied"])
            plans = json.loads((self.app / "plans.json").read_text(encoding="utf-8"))["plans"]
            self.assertEqual("archive", plans[manual_id])
            self.assertEqual("cold_archive", plans[cold_id])
            self.assertEqual("quarantine", plans[delete_id])
            dashboard.save_plan(cold_id, "cold_archive")
            cleared = dashboard.clear_auto_plans()
            self.assertEqual(1, cleared["removed"])
            plans = json.loads((self.app / "plans.json").read_text(encoding="utf-8"))["plans"]
            self.assertEqual(
                {manual_id: "archive", cold_id: "cold_archive"},
                plans,
            )

    def test_macos_process_gate_checks_all_discovered_databases(self) -> None:
        database = self.codex / "sqlite/state_7.sqlite"
        database.parent.mkdir(parents=True, exist_ok=True)
        database.touch()
        wal = database.with_name(f"{database.name}-wal")
        wal.touch()
        calls: list[list[str]] = []

        def run(command: list[str], **_: object) -> SimpleNamespace:
            calls.append(command)
            return SimpleNamespace(stdout="", returncode=1)

        with (
            mock.patch.object(session_actions.platform, "system", return_value="Darwin"),
            mock.patch.object(session_actions.subprocess, "run", side_effect=run),
        ):
            self.assertEqual([], session_actions.codex_processes(self.codex))

        lsof = next(command for command in calls if command[0] == "lsof")
        self.assertIn(str(database), lsof)
        self.assertIn(str(wal), lsof)
        self.assertTrue(any(command[0] == "pgrep" for command in calls))

    def test_launch_and_quit_reports_helper_when_quit_request_fails(self) -> None:
        dashboard = object.__new__(DashboardState)
        helper = {"pid": 4321, "status": "waiting_for_codex_exit"}
        with (
            mock.patch.object(dashboard, "launch_helper", return_value=helper),
            mock.patch.object(
                dashboard,
                "quit_codex_desktop",
                side_effect=RuntimeError("codex_desktop_quit_request_failed"),
            ),
        ):
            result = dashboard.launch_and_quit_codex("manifest", "confirmation")

        self.assertEqual(helper, result["helper"])
        self.assertTrue(result["manual_exit_required"])
        self.assertEqual([], result["requested_apps"])


if __name__ == "__main__":
    unittest.main()
