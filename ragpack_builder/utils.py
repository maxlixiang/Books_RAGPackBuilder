from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return "sha256:" + h.hexdigest()


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def json_dumps(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"))


def normalize_title(value: str) -> str:
    text = unicodedata.normalize("NFKC", value)
    text = text.replace("：", ":")
    text = re.sub(r"\s+", "", text)
    return text.strip()


def normalize_text(text: str) -> str:
    text = text.replace("\u3000", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def reflow_zh_text(text: str) -> str:
    """Join PDF hard line breaks while keeping paragraph/list boundaries."""
    paragraphs = re.split(r"\n\s*\n", normalize_text(text))
    return "\n\n".join(reflow_paragraph(p) for p in paragraphs if p.strip()).strip()


def reflow_paragraph(paragraph: str) -> str:
    lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
    if not lines:
        return ""
    out = [lines[0]]
    for line in lines[1:]:
        prev = out[-1]
        if should_keep_line_break(prev, line):
            out.append(line)
        else:
            out[-1] = join_wrapped_lines(prev, line)
    return "\n".join(out)


def should_keep_line_break(prev: str, current: str) -> bool:
    if current.startswith(("■", "●", "•", "-", "—")):
        return True
    if re.match(r"^[（(]?\d+[）)、.．]", current):
        return True
    if re.match(r"^图\s*\d|^表\s*\d|^策略\s*\d+", current):
        return True
    if len(prev) <= 18 and prev.endswith(("：", ":", "？", "?", "。", "！", "!")):
        return True
    if prev.endswith(("。", "！", "？", "；", ";")) and len(current) <= 40:
        return True
    return False


def join_wrapped_lines(prev: str, current: str) -> str:
    if re.search(r"[A-Za-z0-9]$", prev) and re.match(r"^[A-Za-z0-9]", current):
        return prev + " " + current
    return prev + current


def safe_stem(path: Path) -> str:
    stem = re.sub(r'[<>:"/\\|?*]+', "_", path.stem).strip()
    return stem or "document"
