"""Read transcript image references without fetching remote content."""

from __future__ import annotations

import base64
import hashlib
import re
import threading
from collections import OrderedDict
from pathlib import Path
from urllib.parse import unquote, urlsplit


IMAGE_WRAPPER = re.compile(r'<image\b[^>]*\bpath=["\x27]([^"\x27]+)["\x27][^>]*>', re.I)


def clean_image_text(text: str) -> str:
    if text.lstrip().startswith("# Files mentioned by the user:"):
        marker = re.search(r'^## My request(?: for Codex)?:\s*', text, re.M)
        if marker:
            text = text[marker.end():]
    parts = re.split(r'(```.*?```)', text, flags=re.S)
    for index in range(0, len(parts), 2):
        parts[index] = re.sub(r'^[ \t]*<image\b[^>]*\bpath=["\x27][^"\x27]+["\x27][^>]*>.*?</image>\s*', '', parts[index], flags=re.M | re.S)
    return ''.join(parts).strip()


def extract_images(text: str, payload: dict) -> list[dict]:
    prose = re.sub(r'```.*?```|`[^`\n]+`', '', text, flags=re.S)
    paths = IMAGE_WRAPPER.findall(prose)
    parts = payload.get("content") or payload.get("images") or []
    sources = []
    if isinstance(parts, list):
        for part in parts:
            if isinstance(part, str):
                sources.append(part)
            elif isinstance(part, dict) and str(part.get("type", "")).lower() in {"input_image", "image", "local_image", "localimage"}:
                source = part.get("image_url") or part.get("url") or part.get("path")
                if isinstance(source, dict):
                    source = source.get("url")
                if isinstance(source, str):
                    sources.append(source)
    sources.extend(value for value in payload.get("local_images", []) if isinstance(value, str))
    images = []
    for index in range(max(len(paths), len(sources))):
        source = sources[index] if index < len(sources) else paths[index]
        path = paths[index] if index < len(paths) else ""
        name = Path(path or (source if not source.startswith("data:") else "")).name or f"Image {index + 1}"
        images.append({"source": source, "name": name})
    for match in re.finditer(r'!\[([^\]]*)\]\((?:<([^>]+)>|([^\s)]+))(?:\s+"[^"]*")?\)', prose):
        source = match[2] or match[3]
        images.append({"source": source, "name": match[1] or Path(source).name or "Image"})
    return images[:8]


def image_mime(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


class ImageStore:
    max_image_bytes = 16 * 1024 ** 2
    max_cache_bytes = 64 * 1024 ** 2

    def __init__(self):
        self.entries = OrderedDict()
        self.size = 0
        self.lock = threading.Lock()

    def render(self, reference: dict, cwd: str, budget: list[int]) -> dict:
        result = {"name": reference["name"], "status": "missing"}
        source = reference["source"]
        try:
            if source.lower().startswith("data:"):
                if not re.match(r'^data:image/(?:png|jpeg|jpg|gif|webp);base64,', source, re.I):
                    return {**result, "status": "unsupported"}
                if len(source) > self.max_image_bytes * 4 // 3 + 100:
                    return {**result, "status": "too_large"}
                data = base64.b64decode(source.split(",", 1)[1], validate=True)
            else:
                parsed = urlsplit(source)
                if parsed.scheme in {"http", "https"}:
                    return {**result, "status": "remote"}
                if parsed.scheme and parsed.scheme != "file":
                    return {**result, "status": "unsupported"}
                if parsed.scheme == "file" and parsed.netloc not in {"", "localhost"}:
                    return {**result, "status": "unsupported"}
                path = Path(unquote(parsed.path) if parsed.scheme == "file" else source).expanduser()
                if not path.is_absolute():
                    path = Path(cwd).expanduser() / path
                if path.is_symlink() or not path.is_file():
                    return result
                if path.stat().st_size > self.max_image_bytes:
                    return {**result, "status": "too_large"}
                with path.open("rb") as handle:
                    if not image_mime(handle.read(16)):
                        return {**result, "status": "unsupported"}
                    handle.seek(0)
                    data = handle.read(self.max_image_bytes + 1)
            mime = image_mime(data)
            if not mime:
                return {**result, "status": "unsupported"}
            if len(data) > min(self.max_image_bytes, budget[0]):
                return {**result, "status": "too_large"}
            budget[0] -= len(data)
            token = hashlib.sha256(data).hexdigest()
            with self.lock:
                if token not in self.entries:
                    self.entries[token] = (mime, data)
                    self.size += len(data)
                self.entries.move_to_end(token)
                while self.size > self.max_cache_bytes:
                    _, (_, expired) = self.entries.popitem(last=False)
                    self.size -= len(expired)
            return {**result, "status": "available", "url": "/api/session-image?token=" + token}
        except ValueError:
            return {**result, "status": "unsupported"}
        except OSError:
            return result

    def get(self, token: str):
        with self.lock:
            entry = self.entries.get(token)
            if entry:
                self.entries.move_to_end(token)
            return entry
