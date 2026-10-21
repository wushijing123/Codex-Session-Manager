"""Streaming plain/Zstandard rollout readers and Codex event compatibility."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path


class _TrackedReader(io.BufferedReader):
    finished = False

    def read(self, size=-1):
        data = super().read(size)
        self.finished = size < 0 or not data
        return data

    def read1(self, size=-1):
        data = super().read1(size)
        if not data:
            self.finished = True
        return data

    def readline(self, size=-1):
        data = super().readline(size)
        if not data:
            self.finished = True
        return data


@contextmanager
def open_log(path: Path, mode="r"):
    if not path.name.endswith(".jsonl.zst"):
        with path.open(mode, **({"encoding": "utf-8", "errors": "replace"} if mode == "r" else {})) as handle:
            yield handle
        return
    try:
        from compression import zstd
    except ImportError:
        zstd = None
    if zstd:
        with zstd.open(path, "rb") as binary:
            if mode == "rb":
                yield binary
            else:
                with io.TextIOWrapper(binary, encoding="utf-8", errors="replace") as text:
                    yield text
        return
    try:
        import zstandard
    except ImportError:
        zstandard = None
    if zstandard:
        with path.open("rb") as source, zstandard.ZstdDecompressor().stream_reader(source) as binary:
            if mode == "rb":
                yield binary
            else:
                with io.TextIOWrapper(binary, encoding="utf-8", errors="replace") as text:
                    yield text
        return
    executable = shutil.which("zstd")
    if not executable:
        raise OSError("zstd_decoder_unavailable")
    process = subprocess.Popen([executable, "-q", "-dc", "--", str(path)],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    binary = _TrackedReader(process.stdout)
    text = io.TextIOWrapper(binary, encoding="utf-8", errors="replace") if mode == "r" else None
    try:
        yield text or binary
    finally:
        finished = binary.finished
        if not finished and process.poll() is None:
            process.terminate()
        try:
            code = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            code = -1
        (text or binary).close()
        if finished and code != 0:
            raise OSError("compressed_log_invalid")


def normalize_event(event: dict) -> dict:
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return event
    if event.get("type") != "event_msg" or payload.get("type") != "item_completed":
        return event
    item = payload.get("item") or {}
    if not isinstance(item, dict):
        return event
    kind = item.get("type")
    if kind in {"UserMessage", "AgentMessage", "userMessage", "agentMessage"}:
        content = item.get("content") or []
        text = content if isinstance(content, str) else "\n".join(
            str(part.get("text") or "") for part in content if isinstance(part, dict))
        user = kind in {"UserMessage", "userMessage"}
        return {**event, "payload": {
            "type": "user_message" if user else "agent_message", "message": text,
            "phase": item.get("phase"), "turn_id": payload.get("turn_id"),
            "images": [part for part in content if isinstance(part, dict)
                       and str(part.get("type", "")).lower() in {"image", "localimage", "local_image"}]
                      if isinstance(content, list) else [],
        }}
    if kind in {"FileChange", "CommandExecution", "McpToolCall"}:
        return {**event, "type": "response_item", "payload": {
            "type": "function_call", "name": "apply_patch" if kind == "FileChange" else "exec_command",
            "arguments": str(item.get("command") or ""),
        }}
    return event


def iter_log_events(path: Path, query: str | None = None):
    needle = query.casefold() if query else None
    with open_log(path) as handle:
        for line in handle:
            if needle and needle not in line.casefold() and "\\u" not in line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                yield normalize_event(event)
