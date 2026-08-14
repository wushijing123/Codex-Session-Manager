#!/usr/bin/env python3
"""Token-gated localhost dashboard server."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .core import (
    atomic_write,
    build_short_conversation_review_bundle,
    classification_policy,
    conversation_preview,
    load_plans,
    load_protected,
    read_json,
    scan_catalog,
    search_conversation_text,
    session_id_from_path,
    write_json,
)

VALID_ACTIONS = {
    "keep",
    "archive",
    "unarchive",
    "cold_archive",
    "quarantine",
    "permanent_delete",
    "purge_after_quarantine",
    "restore",
    "protect",
}
DESTRUCTIVE_ACTIONS = {
    "cold_archive",
    "quarantine",
    "permanent_delete",
    "purge_after_quarantine",
}
LOCAL_CONFIRMATION_PHRASE = "确认执行本次本地操作"
PLAN_BLOCK_MESSAGES = {
    "current_session": "当前活跃会话不可执行破坏性动作",
    "pinned": "当前处于置顶保护",
    "permanent_protection": "已设为永久保护",
    "state_conflict_or_missing": "状态冲突或日志缺失",
    "unindexed_log": "日志未进入 Codex 索引",
}
AUTO_ACTION_BY_RECOMMENDATION = {
    "cold_archive": "cold_archive",
    "delete_candidate": "quarantine",
}
AUTO_PRESETS = {
    "conservative": {"cold_archive"},
    "space": {"cold_archive", "quarantine"},
    "temporary": {"quarantine"},
}


def plan_block_reason(record: dict[str, Any]) -> str | None:
    """Return blockers for reversible planning, excluding stale pin snapshots."""
    if record.get("actual_state") == "active":
        return "current_session"
    if record.get("pinned"):
        return "pinned"
    if record.get("permanent_protection"):
        return "permanent_protection"
    if record.get("state_conflict") or record.get("actual_state") == "missing":
        return "state_conflict_or_missing"
    if record.get("actual_state") == "unindexed":
        return "unindexed_log"
    return None


class DashboardState:
    def __init__(
        self,
        codex_home: Path,
        app_dir: Path,
        assets_dir: Path,
        pinned_file: Path | None,
        light_log_scan: bool,
    ) -> None:
        self.codex_home = codex_home
        self.app_dir = app_dir
        self.assets_dir = assets_dir
        self.pinned_file = pinned_file
        self.light_log_scan = light_log_scan
        self.launch_token = secrets.token_urlsafe(32)
        self.cookie_value = secrets.token_urlsafe(32)
        self.csrf_token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.catalog: dict[str, Any] = {}
        self.detail_cache: dict[tuple[str, int, int, int], dict[str, Any]] = {}
        self.confirmation_sheets: dict[str, dict[str, Any]] = {}
        self.content_search_jobs: dict[str, dict[str, Any]] = {}
        self.refresh()

    def refresh(self) -> dict[str, Any]:
        with self.lock:
            self.catalog = scan_catalog(
                self.codex_home,
                self.app_dir,
                self.pinned_file,
                self.light_log_scan,
            )
            return self.catalog

    def record_for(self, session_id: str) -> dict[str, Any] | None:
        return next(
            (item for item in self.catalog.get("sessions", []) if item["id"] == session_id),
            None,
        )

    def unarchive_session(self, session_id: str) -> dict[str, Any]:
        with self.lock:
            record = self.record_for(session_id)
            if not record:
                raise ValueError("unknown_session")
            if record.get("actual_state") != "archived" or record.get("state_conflict"):
                raise PermissionError("unarchive_requires_plain_archive")

        codex = shutil.which("codex")
        if not codex:
            raise ValueError("codex_cli_unavailable")
        try:
            result = subprocess.run(
                [codex, "unarchive", session_id],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
                env={**os.environ, "CODEX_HOME": str(self.codex_home)},
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            code = (
                "official_unarchive_timeout"
                if isinstance(error, subprocess.TimeoutExpired)
                else "codex_cli_unavailable"
            )
            raise ValueError(code) from error
        catalog = self.refresh()
        refreshed = self.record_for(session_id)
        if refreshed and refreshed.get("actual_state") != "archived":
            return catalog
        if result.returncode != 0:
            raise ValueError("official_unarchive_failed")
        raise ValueError("official_unarchive_not_verified")

    def session_detail(self, session_id: str, max_messages: int = 24) -> dict[str, Any]:
        max_messages = min(200, max(4, int(max_messages)))
        with self.lock:
            record = self.record_for(session_id)
            if not record:
                raise ValueError("unknown_session")
            raw_path = str(record.get("rollout_path") or "")
            candidate = (
                self.codex_home.parent / raw_path[2:]
                if raw_path.startswith("~/")
                else Path(raw_path).expanduser()
            )
            try:
                resolved = candidate.resolve(strict=True)
            except OSError:
                resolved = None
            allowed_roots = [
                (self.codex_home / "sessions").resolve(),
                (self.codex_home / "archived_sessions").resolve(),
            ]
            if (
                not resolved
                or candidate.is_symlink()
                or not resolved.is_file()
                or session_id_from_path(resolved) != session_id
                or not any(root in resolved.parents for root in allowed_roots)
            ):
                return {
                    "session_id": session_id,
                    "available": False,
                    "summary": "当前生命周期状态没有可直接读取的原始聊天日志。",
                    "summary_source": "local_rules",
                    "messages": [],
                    "safety_note": "冷存档或隔离包需要先完成受控文件恢复，页面不会绕过生命周期边界读取。",
                }
            stat = resolved.stat()
            cache_key = (session_id, stat.st_size, stat.st_mtime_ns, max_messages)
            cached = self.detail_cache.get(cache_key)
            if cached:
                return dict(cached)
            detail = {
                "session_id": session_id,
                **conversation_preview(resolved, record, max_messages=max_messages),
            }
            self.detail_cache[cache_key] = detail
            while len(self.detail_cache) > 64:
                self.detail_cache.pop(next(iter(self.detail_cache)))
            return dict(detail)

    def search_archived_content(self, query: str, limit: int = 100) -> dict[str, Any]:
        query = " ".join(str(query).split())
        if len(query) < 2:
            raise ValueError("content_search_query_too_short")
        if len(query) > 500:
            raise ValueError("content_search_query_too_long")
        limit = min(200, max(1, int(limit)))
        with self.lock:
            records = list(self.catalog.get("sessions", []))
        return self._search_archived_content(query, limit, records)

    def _search_archived_content(
        self, query: str, limit: int, records: list[dict[str, Any]], job_id: str | None = None
    ) -> dict[str, Any]:
            matches: list[dict[str, Any]] = []
            scanned = 0
            archived_root = (self.codex_home / "archived_sessions").resolve()
            candidates = [item for item in records if item.get("actual_state") == "archived"]
            total = len(candidates)
            for record in candidates:
                raw_path = str(record.get("rollout_path") or "")
                candidate = (
                    self.codex_home.parent / raw_path[2:]
                    if raw_path.startswith("~/")
                    else Path(raw_path).expanduser()
                )
                try:
                    resolved = candidate.resolve(strict=True)
                except OSError:
                    continue
                if (
                    candidate.is_symlink()
                    or not resolved.is_file()
                    or session_id_from_path(resolved) != record["id"]
                    or archived_root not in resolved.parents
                ):
                    continue
                scanned += 1
                if job_id:
                    with self.lock:
                        job = self.content_search_jobs.get(job_id)
                        if job:
                            job.update({"scanned": scanned, "total": total, "matches": len(matches)})
                excerpts = search_conversation_text(resolved, query)
                if not excerpts:
                    continue
                matches.append(
                    {
                        "session_id": record["id"],
                        "title": record.get("title") or "(无标题)",
                        "updated_at": record.get("updated_at"),
                        "size_bytes": int(record.get("size_bytes") or 0),
                        "excerpts": excerpts,
                    }
                )
                if len(matches) >= limit:
                    break
            return {
                "query": query,
                "scanned_archived_logs": scanned,
                "matches": matches,
                "limited": len(matches) >= limit,
            }

    def start_archived_content_search(self, query: str, limit: int = 100) -> dict[str, Any]:
        query = " ".join(str(query).split())
        if len(query) < 2:
            raise ValueError("content_search_query_too_short")
        if len(query) > 500:
            raise ValueError("content_search_query_too_long")
        limit = min(200, max(1, int(limit)))
        with self.lock:
            records = list(self.catalog.get("sessions", []))
            job_id = secrets.token_urlsafe(12)
            self.content_search_jobs[job_id] = {
                "status": "running", "query": query,
                "scanned": 0,
                "total": sum(item.get("actual_state") == "archived" for item in records),
                "matches": 0, "started_at": time.monotonic(),
            }

        def run() -> None:
            try:
                result = self._search_archived_content(query, limit, records, job_id)
                with self.lock:
                    self.content_search_jobs[job_id].update({"status": "complete", "result": result})
            except Exception as error:
                with self.lock:
                    self.content_search_jobs[job_id].update({"status": "error", "error": str(error)})

        threading.Thread(target=run, name=f"content-search-{job_id}", daemon=True).start()
        return {"job_id": job_id}

    def archived_content_search_status(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            job = self.content_search_jobs.get(job_id)
            if not job:
                raise ValueError("content_search_not_found")
            payload = {key: value for key, value in job.items() if key not in {"started_at"}}
            payload["elapsed_seconds"] = round(time.monotonic() - float(job["started_at"]), 1)
            return payload

    def save_plan(self, session_id: str, action: str | None) -> dict[str, Any]:
        with self.lock:
            record = self.record_for(session_id)
            if not record:
                raise ValueError("unknown_session")
            if action is not None and action not in VALID_ACTIONS:
                raise ValueError("invalid_action")
            if action == "purge_after_quarantine" and record.get("actual_state") == "archived":
                action = "permanent_delete"
            if action in DESTRUCTIVE_ACTIONS:
                blocker = plan_block_reason(record)
                if blocker:
                    raise PermissionError(blocker)
                if action == "permanent_delete" and record.get("actual_state") != "archived":
                    raise PermissionError("incinerator_requires_plain_archive")
                if action == "purge_after_quarantine" and record.get("actual_state") != "quarantine":
                    raise PermissionError("incinerator_requires_archive_or_quarantine")
                if not self.catalog.get("selected_database") or self.catalog.get(
                    "database_ambiguous"
                ):
                    raise PermissionError("planning_gate_closed")
            plans = load_plans(self.app_dir)
            if action is None or action == "keep":
                plans.pop(session_id, None)
            else:
                plans[session_id] = action
            write_json(self.app_dir / "plans.json", {"version": 1, "plans": plans})
            auto = read_json(self.app_dir / "auto-plans.json", {"plans": {}})
            auto_plans = auto.get("plans", {})
            if session_id in auto_plans:
                auto_plans.pop(session_id, None)
                auto["plans"] = auto_plans
                write_json(self.app_dir / "auto-plans.json", auto)
            return self.refresh()

    def auto_preview(self, preset: str) -> dict[str, Any]:
        if preset not in AUTO_PRESETS:
            raise ValueError("invalid_auto_preset")
        with self.lock:
            catalog = self.refresh()
            allowed_actions = AUTO_PRESETS[preset]
            tracked = read_json(self.app_dir / "auto-plans.json", {"plans": {}}).get(
                "plans", {}
            )
            proposals: list[dict[str, Any]] = []
            for record in catalog.get("sessions", []):
                action = AUTO_ACTION_BY_RECOMMENDATION.get(record.get("recommendation"))
                if not action or action not in allowed_actions:
                    continue
                blocked_reason = None
                if record.get("actual_state") != "archived":
                    blocked_reason = "not_plain_archive"
                else:
                    blocked_reason = plan_block_reason(record)
                if blocked_reason is None and record.get("relation_count", 0):
                    blocked_reason = "group_action_required"
                current_plan = record.get("planned_action")
                tracked_action = tracked.get(record["id"], {}).get("action")
                if current_plan and current_plan != action and tracked_action != current_plan:
                    blocked_reason = "manual_plan_conflict"
                proposals.append(
                    {
                        "session_id": record["id"],
                        "title": record.get("title") or "(无标题)",
                        "action": action,
                        "size_bytes": int(record.get("size_bytes") or 0),
                        "recommendation": record.get("recommendation"),
                        "reasons": record.get("recommendation_reasons", []),
                        "blocked_reason": blocked_reason,
                        "execution_warning": (
                            "pin_snapshot_unavailable_or_stale"
                            if record.get("pin_status") != "snapshot"
                            else None
                        ),
                        "selected": blocked_reason is None,
                        "planned_action": current_plan,
                    }
                )
            proposals.sort(
                key=lambda item: (
                    item["blocked_reason"] is not None,
                    item["action"] != "quarantine",
                    -item["size_bytes"],
                    item["session_id"],
                )
            )
            archived = [
                item
                for item in catalog.get("sessions", [])
                if item.get("actual_state") == "archived"
            ]
            archived_by_recommendation: dict[str, int] = {}
            for item in archived:
                recommendation = str(item.get("recommendation") or "unknown")
                archived_by_recommendation[recommendation] = (
                    archived_by_recommendation.get(recommendation, 0) + 1
                )
            planning_allowed = bool(
                catalog.get("selected_database")
                and not catalog.get("database_ambiguous")
            )
            return {
                "preset": preset,
                "planning_allowed": planning_allowed,
                "execution_ready": catalog.get("mutation_allowed", False),
                "proposals": proposals,
                "summary": {
                    "archived_total": len(archived),
                    "archived_by_recommendation": archived_by_recommendation,
                    "strategy_candidates": len(proposals),
                    "outside_strategy": max(0, len(archived) - len(proposals)),
                    "cold_candidates": sum(
                        1
                        for item in proposals
                        if item["action"] == "cold_archive"
                        and item["blocked_reason"] is None
                    ),
                    "quarantine_candidates": sum(
                        1
                        for item in proposals
                        if item["action"] == "quarantine"
                        and item["blocked_reason"] is None
                    ),
                    "manual_review": int(
                        archived_by_recommendation.get("review_required", 0)
                    )
                    + int(archived_by_recommendation.get("unknown", 0)),
                    "candidate_bytes": sum(
                        item["size_bytes"]
                        for item in proposals
                        if item["blocked_reason"] is None
                    ),
                    "blocked": sum(
                        1 for item in proposals if item["blocked_reason"] is not None
                    ),
                },
            }

    def apply_auto_plan(self, preset: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        if preset not in AUTO_PRESETS:
            raise ValueError("invalid_auto_preset")
        if len(items) > 5000:
            raise ValueError("too_many_auto_plan_items")
        with self.lock:
            preview = self.auto_preview(preset)
            if not preview["planning_allowed"]:
                raise PermissionError("planning_gate_closed")
            eligible = {
                (item["session_id"], item["action"]): item
                for item in preview["proposals"]
                if item["blocked_reason"] is None
            }
            requested: list[tuple[str, str]] = []
            for item in items:
                session_id = str(item.get("session_id", "")).lower()
                action = str(item.get("action", ""))
                if (session_id, action) not in eligible:
                    raise PermissionError(f"auto_candidate_changed:{session_id}")
                requested.append((session_id, action))

            plans = load_plans(self.app_dir)
            auto_payload = read_json(
                self.app_dir / "auto-plans.json", {"version": 1, "plans": {}}
            )
            auto_plans = auto_payload.get("plans", {})
            for session_id, action in requested:
                existing = plans.get(session_id)
                tracked_action = auto_plans.get(session_id, {}).get("action")
                if existing and existing != action and tracked_action != existing:
                    raise PermissionError(f"manual_plan_conflict:{session_id}")
                plans[session_id] = action
                auto_plans[session_id] = {
                    "action": action,
                    "preset": preset,
                    "planned_at": datetime.now(timezone.utc).isoformat(),
                }
            write_json(self.app_dir / "plans.json", {"version": 1, "plans": plans})
            write_json(
                self.app_dir / "auto-plans.json",
                {"version": 1, "plans": auto_plans},
            )
            return {
                "applied": len(requested),
                "catalog": self.refresh(),
            }

    def clear_auto_plans(self) -> dict[str, Any]:
        with self.lock:
            plans = load_plans(self.app_dir)
            auto_payload = read_json(
                self.app_dir / "auto-plans.json", {"version": 1, "plans": {}}
            )
            auto_plans = auto_payload.get("plans", {})
            removed = 0
            for session_id, metadata in auto_plans.items():
                if plans.get(session_id) == metadata.get("action"):
                    plans.pop(session_id, None)
                    removed += 1
            write_json(self.app_dir / "plans.json", {"version": 1, "plans": plans})
            write_json(
                self.app_dir / "auto-plans.json",
                {"version": 1, "plans": {}},
            )
            return {"removed": removed, "catalog": self.refresh()}

    def set_protected(self, session_id: str, enabled: bool) -> dict[str, Any]:
        with self.lock:
            if not self.record_for(session_id):
                raise ValueError("unknown_session")
            protected = load_protected(self.app_dir)
            if enabled:
                protected.add(session_id)
            else:
                protected.discard(session_id)
            if enabled:
                plans = load_plans(self.app_dir)
                if plans.get(session_id) in DESTRUCTIVE_ACTIONS:
                    plans.pop(session_id, None)
                    write_json(
                        self.app_dir / "plans.json", {"version": 1, "plans": plans}
                    )
                auto = read_json(
                    self.app_dir / "auto-plans.json", {"version": 1, "plans": {}}
                )
                if session_id in auto.get("plans", {}):
                    auto["plans"].pop(session_id, None)
                    write_json(self.app_dir / "auto-plans.json", auto)
            write_json(
                self.app_dir / "protected.json",
                {"version": 1, "session_ids": sorted(protected)},
            )
            return self.refresh()

    def save_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "cold_storage_dir",
            "report_dir",
            "compression",
            "cleanup_age_days",
            "automation_keep_runs",
        }
        current = read_json(self.app_dir / "settings.json", {})
        for key, value in updates.items():
            if key not in allowed:
                continue
            if key == "compression" and value not in {"auto", "zstd", "none"}:
                raise ValueError("invalid_compression")
            if key == "cleanup_age_days":
                parsed = int(value)
                if parsed not in {7, 14, 30, 60, 90, 180, 365}:
                    raise ValueError("invalid_cleanup_age_days")
                current[key] = parsed
                continue
            if key == "automation_keep_runs":
                parsed = int(value)
                if parsed < 1 or parsed > 20:
                    raise ValueError("invalid_automation_keep_runs")
                current[key] = parsed
                continue
            current[key] = str(value)
        write_json(self.app_dir / "settings.json", current)
        return current

    def select_directory(self) -> dict[str, Any]:
        osascript = shutil.which("osascript")
        if sys.platform != "darwin" or not osascript:
            raise ValueError("directory_picker_unavailable")
        script = """
try
    set selectedFolder to choose folder with prompt "选择冷存档目录"
    return POSIX path of selectedFolder
on error number -128
    return ""
end try
"""
        try:
            result = subprocess.run(
                [osascript, "-e", script],
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError("directory_picker_timeout") from exc
        if result.returncode != 0:
            raise ValueError("directory_picker_failed")
        selected = result.stdout.strip()
        if not selected:
            return {"selected": False}
        try:
            target = Path(selected).expanduser().resolve(strict=True)
        except OSError as exc:
            raise ValueError("directory_picker_invalid_selection") from exc
        if not target.is_dir():
            raise ValueError("directory_picker_invalid_selection")
        filesystem_root = Path(target.anchor).resolve()
        home = Path.home().resolve()
        codex_home = self.codex_home.resolve()
        if (
            target in {filesystem_root, home, codex_home}
            or codex_home in target.parents
            or target in codex_home.parents
        ):
            raise ValueError("unsafe_storage_target")
        usage = shutil.disk_usage(target)
        return {"selected": True, "path": str(target), "free_bytes": usage.free}

    @property
    def action_script(self) -> Path:
        return self.assets_dir.parents[1] / "scripts/session_actions.py"

    @staticmethod
    def execution_action(record: dict[str, Any]) -> str | None:
        action = record.get("planned_action")
        if action == "purge_after_quarantine" and record.get("actual_state") == "archived":
            return "permanent_delete"
        if action in {"cold_archive", "quarantine", "permanent_delete"}:
            return str(action)
        return None

    def confirmation_snapshot(self, catalog: dict[str, Any]) -> dict[str, Any]:
        settings = read_json(self.app_dir / "settings.json", {})
        planned: list[dict[str, Any]] = []
        blockers: list[dict[str, str]] = []
        warnings: list[dict[str, Any]] = []
        counts = {"cold_archive": 0, "quarantine": 0, "permanent_delete": 0}
        total_bytes = 0

        if catalog.get("pin_snapshot_status") != "snapshot":
            blockers.append(
                {
                    "code": "fresh_pin_snapshot_required",
                    "message": "置顶快照已过期；请刷新置顶列表并重新扫描后再执行。",
                }
            )
        if not catalog.get("selected_database") or catalog.get("database_ambiguous"):
            blockers.append(
                {
                    "code": "database_selection_required",
                    "message": "当前数据库识别未通过，执行保持禁用。",
                }
            )

        for record in catalog.get("sessions", []):
            action = self.execution_action(record)
            if not action:
                continue
            session_id = str(record["id"])
            size_bytes = int(record.get("size_bytes") or 0)
            planned.append(
                {
                    "session_id": session_id,
                    "title": record.get("title") or "(无标题)",
                    "action": action,
                    "size_bytes": size_bytes,
                    "recommendation": record.get("recommendation") or "unknown",
                    "_review_fingerprint": {
                        "actual_state": record.get("actual_state"),
                        "updated_at": record.get("updated_at"),
                        "mtime_ns": record.get("mtime_ns"),
                        "pinned": bool(record.get("pinned")),
                        "permanent_protection": bool(
                            record.get("permanent_protection")
                        ),
                        "state_conflict": bool(record.get("state_conflict")),
                        "relation_count": int(record.get("relation_count") or 0),
                        "write_signals": int(record.get("write_signals") or 0),
                        "business_turns": int(record.get("business_turns") or 0),
                        "has_attachments": bool(record.get("has_attachments")),
                        "semantic_review": record.get("semantic_review"),
                    },
                }
            )
            counts[action] += 1
            total_bytes += size_bytes

            reason = plan_block_reason(record)
            if reason:
                blockers.append(
                    {
                        "code": reason,
                        "session_id": session_id,
                        "message": (
                            f"{record.get('title') or session_id}："
                            f"{PLAN_BLOCK_MESSAGES.get(reason, reason)}"
                        ),
                    }
                )
            if record.get("relation_count", 0):
                blockers.append(
                    {
                        "code": "group_action_required",
                        "session_id": session_id,
                        "message": f"{record.get('title') or session_id}：存在父子任务依赖，必须整组处理。",
                    }
                )
            if action != "permanent_delete":
                continue

            warning_reasons: list[str] = []
            recommendation = str(record.get("recommendation") or "unknown")
            if recommendation in {"high_value", "review_required", "protected", "unknown"}:
                warning_reasons.append(f"当前分类：{recommendation}")
            if int(record.get("write_signals") or 0) > 0:
                warning_reasons.append("检测到实际写入或工具产出")
            if bool(record.get("has_attachments")):
                warning_reasons.append("聊天中包含附件")
            if int(record.get("business_turns") or 0) > 3:
                warning_reasons.append(f"共有 {int(record['business_turns'])} 轮用户对话")
            semantic = record.get("semantic_review") or {}
            if semantic.get("label") in {"one_off_reference", "produced_artifact", "needs_review"}:
                warning_reasons.append(f"Codex 语义复核：{semantic['label']}")
            if size_bytes >= 20 * 1024 * 1024:
                warning_reasons.append("会话体积超过 20 MiB")
            if warning_reasons:
                warnings.append(
                    {
                        "session_id": session_id,
                        "title": record.get("title") or "(无标题)",
                        "reasons": warning_reasons,
                        "size_bytes": size_bytes,
                    }
                )

        if counts["cold_archive"] and not settings.get("cold_storage_dir"):
            blockers.append(
                {
                    "code": "cold_storage_target_required",
                    "message": "冷存档计划尚未设置目标目录。",
                }
            )

        fingerprint_rows = [
            {
                "session_id": item["session_id"],
                "action": item["action"],
                "size_bytes": item["size_bytes"],
                "recommendation": item["recommendation"],
                "review": item["_review_fingerprint"],
            }
            for item in sorted(planned, key=lambda value: value["session_id"])
        ]
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_rows, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        return {
            "plan_fingerprint": fingerprint,
            "counts": counts,
            "total_count": len(planned),
            "total_bytes": total_bytes,
            "plans": [
                {key: value for key, value in item.items() if not key.startswith("_")}
                for item in planned
            ],
            "warnings": warnings,
            "blockers": blockers,
            "can_execute": bool(planned) and not blockers,
        }

    def confirmation_sheet(self) -> dict[str, Any]:
        with self.lock:
            snapshot = self.confirmation_snapshot(self.refresh())
            if not snapshot["plans"]:
                raise ValueError("no_destructive_plans")
            sheet_id = secrets.token_urlsafe(18)
            sheet = {
                "sheet_id": sheet_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "expires_in_seconds": 1800,
                "confirmation_phrase": LOCAL_CONFIRMATION_PHRASE,
                **snapshot,
            }
            self.confirmation_sheets[sheet_id] = {
                **sheet,
                "created_monotonic": time.monotonic(),
            }
            while len(self.confirmation_sheets) > 16:
                self.confirmation_sheets.pop(next(iter(self.confirmation_sheets)))
            # The phrase remains an internal helper/manifest safeguard. The dashboard
            # deliberately exposes only an explicit second confirmation button.
            return {
                key: value
                for key, value in sheet.items()
                if key not in {"confirmation_phrase", "created_monotonic"}
            }

    def confirm_sheet(
        self,
        sheet_id: str,
        confirmation: str,
        warnings_acknowledged: bool,
    ) -> list[dict[str, Any]]:
        with self.lock:
            sheet = self.confirmation_sheets.get(sheet_id)
            if not sheet:
                raise PermissionError("confirmation_sheet_missing_or_expired")
            if time.monotonic() - float(sheet["created_monotonic"]) > 1800:
                self.confirmation_sheets.pop(sheet_id, None)
                raise PermissionError("confirmation_sheet_missing_or_expired")
            if not secrets.compare_digest(
                confirmation.encode("utf-8"),
                LOCAL_CONFIRMATION_PHRASE.encode("utf-8"),
            ):
                raise PermissionError("local_confirmation_phrase_mismatch")
            current = self.confirmation_snapshot(self.refresh())
            if current["plan_fingerprint"] != sheet["plan_fingerprint"]:
                raise PermissionError("planned_actions_changed_after_review")
            if current["blockers"]:
                raise PermissionError("confirmation_sheet_has_blockers")
            if current["warnings"] and not warnings_acknowledged:
                raise PermissionError("important_warnings_not_acknowledged")
            manifests = self.prepare_plans()
            self.confirmation_sheets.pop(sheet_id, None)
            return manifests

    def confirm_sheet_button(
        self,
        sheet_id: str,
        warnings_acknowledged: bool,
        second_confirmation: bool,
    ) -> list[dict[str, Any]]:
        """Dashboard-only final confirmation without asking people to type a phrase."""
        if not second_confirmation:
            raise PermissionError("second_confirmation_required")
        with self.lock:
            sheet = self.confirmation_sheets.get(sheet_id)
            if not sheet:
                raise PermissionError("confirmation_sheet_missing_or_expired")
            return self.confirm_sheet(
                sheet_id,
                str(sheet["confirmation_phrase"]),
                warnings_acknowledged,
            )

    def prepare_plans(self) -> list[dict[str, Any]]:
        with self.lock:
            catalog = self.refresh()
            if catalog.get("pin_snapshot_status") != "snapshot":
                raise PermissionError("fresh_pin_snapshot_required")
            if not catalog.get("selected_database") or catalog.get("database_ambiguous"):
                raise PermissionError("database_selection_required")
            plans = [
                item
                for item in catalog["sessions"]
                if self.execution_action(item)
            ]
            if not plans:
                raise ValueError("no_destructive_plans")
            if any(plan_block_reason(item) for item in plans):
                raise PermissionError("planned_session_became_protected")
            if any(item.get("relation_count", 0) for item in plans):
                raise PermissionError("group_action_required")
            settings = read_json(self.app_dir / "settings.json", {})
            groups: list[tuple[str, list[str]]] = []
            cold_ids = [
                item["id"] for item in plans if self.execution_action(item) == "cold_archive"
            ]
            if cold_ids:
                if not settings.get("cold_storage_dir"):
                    raise ValueError("cold_storage_target_required")
                groups.append(("cold_archive", cold_ids))
            groups.extend(
                ("quarantine", [item["id"]])
                for item in plans
                if self.execution_action(item) == "quarantine"
            )
            permanent_ids = [
                item["id"]
                for item in plans
                if self.execution_action(item) == "permanent_delete"
            ]
            if permanent_ids:
                groups.append(("permanent_delete", permanent_ids))
            prepared: list[dict[str, Any]] = []
            for action, session_ids in groups:
                command = [
                    sys.executable,
                    str(self.action_script),
                    "--app-dir",
                    str(self.app_dir),
                    "prepare",
                    "--action",
                    action,
                    "--codex-home",
                    str(self.codex_home),
                    "--pinned-file",
                    str(self.pinned_file),
                ]
                for session_id in session_ids:
                    command.extend(["--session-id", session_id])
                if action == "cold_archive":
                    command.extend(["--target", str(settings["cold_storage_dir"])])
                result = subprocess.run(command, capture_output=True, text=True, timeout=600)
                if result.returncode != 0:
                    raise PermissionError(result.stderr.strip() or "manifest_prepare_failed")
                manifest_line = next(
                    (line for line in result.stdout.splitlines() if line.startswith("manifest: ")),
                    None,
                )
                if not manifest_line:
                    raise RuntimeError("manifest_path_missing")
                manifest_path = Path(manifest_line.removeprefix("manifest: ")).resolve()
                payload = read_json(manifest_path, {})
                prepared.append(
                    {
                        "path": str(manifest_path),
                        "manifest_id": payload.get("manifest_id"),
                        "action": payload.get("action"),
                        "session_ids": [item["session_id"] for item in payload.get("items", [])],
                        "bytes": sum(int(item["source_size"]) for item in payload.get("items", [])),
                        "confirmation_phrase": payload.get("confirmation_phrase"),
                        "volume_notes": payload.get("volume_notes", []),
                    }
                )
            return prepared

    def prepare_review_bundle(self, max_turns: int) -> dict[str, Any]:
        if max_turns not in {1, 2, 3}:
            raise ValueError("invalid_max_turns")
        with self.lock:
            result = build_short_conversation_review_bundle(
                self.codex_home,
                self.app_dir,
                self.pinned_file,
                max_turns,
            )
            self.catalog = result.pop("catalog")
            result["catalog"] = self.catalog
            return result

    def purge_request(self, session_id: str) -> dict[str, Any]:
        with self.lock:
            catalog = self.refresh()
            record = next(
                (item for item in catalog["sessions"] if item["id"] == session_id),
                None,
            )
            if not record:
                raise ValueError("unknown_session")
            if record.get("planned_action") != "purge_after_quarantine":
                raise PermissionError("purge_intent_required")
            if record.get("actual_state") != "quarantine":
                raise PermissionError("session_not_in_quarantine")
            if not record.get("purge_eligible"):
                raise PermissionError("quarantine_countdown_active")
            if record.get("hard_protected") or record.get("relation_count", 0):
                raise PermissionError("purge_protection_recheck_failed")
            if catalog.get("pin_snapshot_status") != "snapshot":
                raise PermissionError("fresh_pin_snapshot_required")
            packages = [
                path
                for path in (self.app_dir / "quarantine").glob(f"{session_id}-*/package.json")
                if path.is_file() and not path.is_symlink()
            ]
            if len(packages) != 1:
                raise PermissionError("quarantine_package_not_unique")
            metadata = read_json(packages[0], {})
            manifest_id = str(metadata.get("parent_manifest_id") or "")
            parent = (self.app_dir / "manifests" / f"{manifest_id}.json").resolve()
            if not parent.is_file() or parent.is_symlink():
                raise PermissionError("parent_manifest_missing")
            return {
                "session_id": session_id,
                "package": str(packages[0].parent.resolve()),
                "parent_manifest": str(parent),
                "confirmation_phrase": f"PURGE-FOREVER {session_id}",
                "expires_at": record.get("quarantine_expires_at"),
                "bytes": int(record.get("size_bytes") or 0),
            }

    def launch_purge(self, request: dict[str, Any], confirmation: str) -> dict[str, Any]:
        expected = str(request["confirmation_phrase"])
        if confirmation != expected:
            raise PermissionError("confirmation_phrase_mismatch")
        log_dir = self.app_dir / "helper-logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"purge-{request['session_id']}.log"
        command = [
            sys.executable,
            str(self.action_script),
            "--app-dir",
            str(self.app_dir),
            "purge",
            "--package",
            str(request["package"]),
            "--confirm",
            confirmation,
            "--parent-manifest",
            str(request["parent_manifest"]),
            "--pinned-file",
            str(self.pinned_file),
        ]
        with log_path.open("ab", buffering=0) as output:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        return {"pid": process.pid, "log": str(log_path), "status": "purge_started"}

    def launch_purge_button(self, session_id: str, second_confirmation: bool) -> dict[str, Any]:
        """Use the same local two-click confirmation pattern for expired quarantine."""
        if not second_confirmation:
            raise PermissionError("second_confirmation_required")
        request = self.purge_request(session_id)
        return self.launch_purge(request, str(request["confirmation_phrase"]))

    def launch_helper(self, manifest_value: str, confirmation: str) -> dict[str, Any]:
        manifest_root = (self.app_dir / "manifests").resolve()
        manifest_path = Path(manifest_value).expanduser().resolve()
        if (
            manifest_root not in manifest_path.parents
            or manifest_path.parent != manifest_root
            or manifest_path.is_symlink()
            or not manifest_path.is_file()
        ):
            raise PermissionError("manifest_path_rejected")
        payload = read_json(manifest_path, {})
        if confirmation != payload.get("confirmation_phrase"):
            raise PermissionError("confirmation_phrase_mismatch")
        helpers = read_json(self.app_dir / "helpers.json", {"helpers": []})
        for helper in helpers.get("helpers", []):
            if helper.get("manifest_id") != payload.get("manifest_id"):
                continue
            try:
                os.kill(int(helper["pid"]), 0)
            except (KeyError, OSError, ValueError):
                continue
            raise PermissionError("helper_already_running")
        settings = read_json(self.app_dir / "settings.json", {})
        compression = settings.get("compression", "auto")
        if compression not in {"auto", "zstd", "none"}:
            compression = "auto"
        log_dir = self.app_dir / "helper-logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{payload['manifest_id']}.log"
        command = [
            sys.executable,
            str(self.action_script),
            "--app-dir",
            str(self.app_dir),
            "apply",
            "--manifest",
            str(manifest_path),
            "--confirm",
            confirmation,
            "--compression",
            compression,
            "--wait-for-exit-seconds",
            "900",
        ]
        with log_path.open("ab", buffering=0) as output:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        helpers.setdefault("helpers", []).append(
            {
                "manifest_id": payload["manifest_id"],
                "pid": process.pid,
                "log": str(log_path),
                "launched_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        write_json(self.app_dir / "helpers.json", helpers)
        return {"pid": process.pid, "log": str(log_path), "status": "waiting_for_codex_exit"}

    def launch_and_quit_codex(self, manifest_value: str, confirmation: str) -> dict[str, Any]:
        helper = self.launch_helper(manifest_value, confirmation)
        try:
            return {"helper": helper, **self.quit_codex_desktop(), "manual_exit_required": False}
        except RuntimeError as error:
            return {
                "helper": helper,
                "requested_apps": [],
                "manual_exit_required": True,
                "quit_warning": str(error),
            }

    def quit_codex_desktop(self) -> dict[str, Any]:
        """Request a normal macOS app quit after the user has started a helper."""
        requested: list[str] = []
        for app_name in ("ChatGPT", "Codex"):
            running = subprocess.run(
                ["osascript", "-e", f'application "{app_name}" is running'],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if running.returncode != 0 or running.stdout.strip().lower() != "true":
                continue
            result = subprocess.run(
                ["osascript", "-e", f'tell application "{app_name}" to quit'],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                requested.append(app_name)
        if not requested:
            raise RuntimeError("codex_desktop_quit_request_failed")
        return {"requested_apps": requested}


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "CodexSessionManager/1"

    @property
    def state(self) -> DashboardState:
        return self.server.state  # type: ignore[attr-defined]

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def log_message(self, format: str, *args: object) -> None:
        return

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
            "form-action 'self'; connect-src 'self'; img-src 'self' data:; "
            "style-src 'self'; script-src 'self'",
        )
        super().end_headers()

    def send_json(self, value: Any, status: int = 200) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def cookie_ok(self) -> bool:
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        morsel = cookie.get("csm_session")
        return bool(morsel and secrets.compare_digest(morsel.value, self.state.cookie_value))

    def authorize(self, require_csrf: bool = False) -> bool:
        if not self.cookie_ok():
            self.send_json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return False
        if require_csrf:
            origin = self.headers.get("Origin", "")
            csrf = self.headers.get("X-CSRF-Token", "")
            if origin != self.origin or not secrets.compare_digest(csrf, self.state.csrf_token):
                self.send_json({"error": "csrf_rejected"}, HTTPStatus.FORBIDDEN)
                return False
        return True

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/" and query.get("launch", [""])[0] == self.state.launch_token:
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header(
                "Set-Cookie",
                f"csm_session={self.state.cookie_value}; Path=/; HttpOnly; SameSite=Strict",
            )
            self.send_header("Location", "/")
            self.end_headers()
            return
        if not self.authorize():
            return
        if parsed.path == "/api/bootstrap":
            settings = read_json(self.state.app_dir / "settings.json", {})
            policy = classification_policy(settings)
            settings.setdefault("cleanup_age_days", policy["cleanup_age_days"])
            settings.setdefault("automation_keep_runs", policy["automation_keep_runs"])
            self.send_json(
                {
                    "csrf": self.state.csrf_token,
                    "catalog": self.state.catalog,
                    "settings": settings,
                    "capabilities": {
                        "detail_planning": True,
                        "manifest_prepare": True,
                        "official_unarchive": bool(shutil.which("codex")),
                        "native_directory_picker": sys.platform == "darwin"
                        and bool(shutil.which("osascript")),
                        "indexed_restore_to_codex": False,
                        "reason": "真实关闭应用后的恢复闭环尚未通过，因此保持禁用。",
                    },
                }
            )
            return
        if parsed.path == "/api/catalog":
            self.send_json(self.state.catalog)
            return
        if parsed.path == "/api/plans":
            self.send_json({"plans": load_plans(self.state.app_dir)})
            return
        if parsed.path == "/api/search-archived-content/status":
            self.send_json(self.state.archived_content_search_status(query.get("job", [""])[0]))
            return
        if parsed.path == "/":
            return self.send_asset("index.html")
        if parsed.path in {"/style.css", "/i18n.js", "/app.js"}:
            return self.send_asset(parsed.path.removeprefix("/"))
        if parsed.path.startswith("/assets/"):
            return self.send_asset(parsed.path.removeprefix("/assets/"))
        self.send_error(HTTPStatus.NOT_FOUND)

    def send_asset(self, relative: str) -> None:
        target = (self.state.assets_dir / relative).resolve()
        if self.state.assets_dir.resolve() not in target.parents or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        if not self.authorize(require_csrf=True):
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 256 * 1024:
                raise ValueError("body_too_large")
            payload = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/api/plan":
                result = self.state.save_plan(str(payload["session_id"]), payload.get("action"))
                self.send_json({"ok": True, "catalog": result})
                return
            if self.path == "/api/auto-preview":
                preview = self.state.auto_preview(str(payload.get("preset", "")))
                self.send_json({"ok": True, "preview": preview})
                return
            if self.path == "/api/auto-apply":
                items = payload.get("items", [])
                if not isinstance(items, list):
                    raise ValueError("invalid_auto_items")
                result = self.state.apply_auto_plan(
                    str(payload.get("preset", "")), items
                )
                self.send_json({"ok": True, **result})
                return
            if self.path == "/api/auto-clear":
                result = self.state.clear_auto_plans()
                self.send_json({"ok": True, **result})
                return
            if self.path == "/api/protect":
                result = self.state.set_protected(
                    str(payload["session_id"]), bool(payload.get("enabled"))
                )
                self.send_json({"ok": True, "catalog": result})
                return
            if self.path == "/api/unarchive":
                result = self.state.unarchive_session(str(payload["session_id"]).lower())
                self.send_json({"ok": True, "catalog": result})
                return
            if self.path == "/api/settings":
                settings = self.state.save_settings(payload)
                self.send_json(
                    {"ok": True, "settings": settings, "catalog": self.state.refresh()}
                )
                return
            if self.path == "/api/select-directory":
                self.send_json({"ok": True, **self.state.select_directory()})
                return
            if self.path == "/api/refresh":
                self.send_json({"ok": True, "catalog": self.state.refresh()})
                return
            if self.path == "/api/review-bundle":
                result = self.state.prepare_review_bundle(
                    int(payload.get("max_turns", 3))
                )
                self.send_json({"ok": True, **result})
                return
            if self.path == "/api/session-detail":
                detail = self.state.session_detail(
                    str(payload["session_id"]).lower(),
                    int(payload.get("max_messages", 24)),
                )
                self.send_json({"ok": True, "detail": detail})
                return
            if self.path == "/api/search-archived-content":
                result = self.state.start_archived_content_search(
                    str(payload.get("query", "")), int(payload.get("limit", 100))
                )
                self.send_json({"ok": True, **result})
                return
            if self.path == "/api/prepare":
                raise PermissionError("confirmation_sheet_required")
            if self.path == "/api/confirmation-sheet":
                self.send_json({"ok": True, "sheet": self.state.confirmation_sheet()})
                return
            if self.path == "/api/confirm-sheet":
                manifests = self.state.confirm_sheet_button(
                    str(payload.get("sheet_id", "")),
                    bool(payload.get("warnings_acknowledged")),
                    bool(payload.get("second_confirmation")),
                )
                self.send_json({"ok": True, "manifests": manifests})
                return
            if self.path == "/api/launch-helper":
                helper = self.state.launch_helper(
                    str(payload["manifest"]), str(payload["confirmation"])
                )
                self.send_json({"ok": True, "helper": helper})
                return
            if self.path == "/api/launch-and-quit":
                self.send_json(
                    {"ok": True, **self.state.launch_and_quit_codex(
                        str(payload["manifest"]), str(payload["confirmation"])
                    )}
                )
                return
            if self.path == "/api/quit-codex":
                self.send_json({"ok": True, **self.state.quit_codex_desktop()})
                return
            if self.path == "/api/purge-request":
                request = self.state.purge_request(str(payload["session_id"]).lower())
                self.send_json(
                    {
                        "ok": True,
                        "request": {
                            key: value
                            for key, value in request.items()
                            if key != "confirmation_phrase"
                        },
                    }
                )
                return
            if self.path == "/api/launch-purge":
                helper = self.state.launch_purge_button(
                    str(payload["session_id"]).lower(),
                    bool(payload.get("second_confirmation")),
                )
                self.send_json({"ok": True, "helper": helper})
                return
            self.send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
        except PermissionError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.CONFLICT)
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address: tuple[str, int], state: DashboardState):
        self.state = state
        super().__init__(address, DashboardHandler)
