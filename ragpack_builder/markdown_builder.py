from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from os.path import commonpath
from pathlib import Path

from .chunking import make_chunks
from .embeddings import NullEmbedder, SentenceTransformerEmbedder
from .models import Section, TocItem
from .profiles import DEFAULT_MODEL, MARKDOWN_PROFILE_DEFAULTS
from .utils import json_dumps, normalize_text, now_iso, safe_stem, sha256_text
from .writer import build_embedding_text, make_chunk_records, toc_record, write_jsonl


JOURNAL_DATE_RE = re.compile(r"^(?P<year>\d{4})[-_.](?P<month>\d{2})[-_.](?P<day>\d{2})$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
FRONT_MATTER_DATE_KEYS = ("created", "date", "saved_at", "saved", "published", "updated", "modified")


@dataclass
class MarkdownPackJob:
    title: str
    profile: str
    output_stem: str
    files: list[Path]


def build_markdown_packs(
    markdown_root: Path,
    output_dir: Path,
    embedding_model: str = DEFAULT_MODEL,
    batch_size: int = 16,
    no_embedding: bool = False,
) -> list[Path]:
    jobs = collect_markdown_jobs(markdown_root)
    outputs: list[Path] = []
    for job in jobs:
        outputs.append(
            build_markdown_pack(
                job,
                output_dir=output_dir,
                embedding_model=embedding_model,
                batch_size=batch_size,
                no_embedding=no_embedding,
            )
        )
    return outputs


def collect_markdown_jobs(markdown_root: Path) -> list[MarkdownPackJob]:
    jobs: list[MarkdownPackJob] = []
    jobs.extend(collect_journal_jobs(markdown_root / "journal"))
    jobs.extend(collect_tech_note_jobs(markdown_root / "TechNotes"))
    jobs.extend(collect_web_page_jobs(markdown_root / "WebPageCollection"))
    return jobs


def collect_journal_jobs(folder: Path) -> list[MarkdownPackJob]:
    groups: dict[str, list[Path]] = {}
    for path in sorted(folder.glob("*.md")) if folder.exists() else []:
        match = JOURNAL_DATE_RE.match(path.stem)
        group_key = f"{match.group('year')}-{match.group('month')}" if match else "undated"
        groups.setdefault(group_key, []).append(path)
    return [
        MarkdownPackJob(
            title=f"日记 {month}",
            profile="journal",
            output_stem=f"journal_{month}",
            files=files,
        )
        for month, files in sorted(groups.items())
    ]


def collect_tech_note_jobs(folder: Path) -> list[MarkdownPackJob]:
    if not folder.exists():
        return []
    jobs: list[MarkdownPackJob] = []
    for child in sorted(folder.iterdir()):
        if child.is_dir():
            files = sorted(child.rglob("*.md"))
            if files:
                jobs.append(
                    MarkdownPackJob(
                        title=child.name,
                        profile="tech_notes",
                        output_stem=safe_filename(child.name),
                        files=files,
                    )
                )
        elif child.is_file() and child.suffix.lower() == ".md":
            jobs.append(
                MarkdownPackJob(
                    title=child.stem,
                    profile="tech_notes",
                    output_stem=safe_filename(child.stem),
                    files=[child],
                )
            )
    return jobs


def collect_web_page_jobs(folder: Path) -> list[MarkdownPackJob]:
    if not folder.exists():
        return []
    return [
        MarkdownPackJob(
            title=path.stem,
            profile="web_page_collection",
            output_stem=safe_filename(path.stem),
            files=[path],
        )
        for path in sorted(folder.rglob("*.md"))
    ]


def build_markdown_pack(
    job: MarkdownPackJob,
    output_dir: Path,
    embedding_model: str = DEFAULT_MODEL,
    batch_size: int = 16,
    no_embedding: bool = False,
) -> Path:
    defaults = MARKDOWN_PROFILE_DEFAULTS[job.profile]
    toc_items, sections, file_metadata = markdown_files_to_sections(job.files, job.title, job.profile)
    chunks = make_chunks(
        sections,
        target_chars=defaults["target_chars"],
        max_chars=defaults["max_chars"],
        min_chunk_chars=defaults["min_chunk_chars"],
        overlap_chars=defaults["overlap_chars"],
        section_split_chars=defaults["section_split_chars"],
    )
    embedder = NullEmbedder() if no_embedding else SentenceTransformerEmbedder(embedding_model, normalize=True, batch_size=batch_size)
    embedding_texts = [build_embedding_text(job.title, chunk) for chunk in chunks]
    embeddings = embedder.encode(embedding_texts)

    source_hash = markdown_source_hash(job.files)
    document_id = source_hash
    manifest = {
        "record_type": "manifest",
        "schema_version": "1.0",
        "document_id": document_id,
        "title": job.title,
        "created_at": now_iso(),
        "source": {
            "file_name": job.output_stem,
            "source_type": "markdown",
            "source_sha256": source_hash,
            "files": file_metadata,
        },
        "language": "zh",
        "parser": {
            "name": "markdown_heading_parser",
            "preserve_layout": True,
        },
        "toc": {
            "source": "markdown_headings",
            "item_count": len(toc_items),
        },
        "chunking": {
            "strategy": "hierarchical_semantic",
            "profile": job.profile,
            "target_chars": defaults["target_chars"],
            "max_chars": defaults["max_chars"],
            "section_split_chars": defaults["section_split_chars"],
            "overlap_chars": defaults["overlap_chars"],
            "min_chunk_chars": defaults["min_chunk_chars"],
            "max_chunk_heading_level": defaults["max_chunk_heading_level"],
            "heading_detection": defaults["heading_detection"],
        },
        "embedding": {
            "provider": "local" if not no_embedding else "none",
            "model": embedder.model_name,
            "dimension": embedder.dimension,
            "normalize": embedder.normalize,
        },
    }

    records = make_chunk_records(document_id, job.title, chunks, embeddings)
    suffix = "_noembedding.rag.jsonl" if no_embedding else ".rag.jsonl"
    out_path = output_dir / f"{job.output_stem}{suffix}"
    write_jsonl(out_path, manifest, toc_record(document_id, toc_items, "markdown_headings"), records)
    return out_path


def markdown_files_to_sections(
    files: list[Path],
    title: str,
    profile: str,
) -> tuple[list[TocItem], list[Section], list[dict]]:
    toc_items: list[TocItem] = []
    sections: list[Section] = []
    file_metadata: list[dict] = []
    relative_names = dict(zip(sorted(files), markdown_relative_names(files)))
    for path in sorted(files):
        text = read_markdown(path)
        metadata = markdown_file_metadata(path, relative_names.get(path, path.name), profile, text)
        file_metadata.append(metadata)
        file_title = markdown_file_title(path, profile)
        root = add_toc_item(toc_items, file_title, 1, None, path, metadata)
        items, raw_sections = parse_markdown_file(text, path, root, len(toc_items), metadata)
        toc_items.extend(items)
        sections.extend(raw_sections)
    if not sections:
        root = add_toc_item(toc_items, title, 1, None, None, {})
        sections.append(Section(root, [root], "", None, None))
    return toc_items, select_markdown_sections(sections, toc_items), file_metadata


def parse_markdown_file(
    text: str,
    path: Path,
    root: TocItem,
    existing_count: int,
    source_metadata: dict,
) -> tuple[list[TocItem], list[Section]]:
    _, body = parse_front_matter(text)
    lines = body.splitlines()
    heading_entries = markdown_heading_entries(lines)
    items: list[TocItem] = []
    stack = [root]
    for entry in heading_entries:
        level = min(entry["level"] + 1, 7)
        while stack and stack[-1].level >= level:
            stack.pop()
        parent = stack[-1].toc_id if stack else root.toc_id
        item = TocItem(
            toc_id=f"toc:{existing_count + len(items) + 1:06d}",
            title=entry["title"],
            level=level,
            order=existing_count + len(items) + 1,
            parent_toc_id=parent,
            page=None,
            locate={"method": "markdown_heading", "confidence": 1.0, "file": source_metadata.get("file_path")},
        )
        items.append(item)
        stack.append(item)

    all_items = [root, *items]
    item_lines = {root.toc_id: {"start": -1, "body_start": 0, "level": root.level}}
    for entry, item in zip(heading_entries, items):
        item_lines[item.toc_id] = {"start": entry["line"], "body_start": entry["line"] + 1, "level": item.level}

    sections: list[Section] = []
    by_id = {item.toc_id: item for item in all_items}
    for item in all_items:
        current = item_lines[item.toc_id]
        end = markdown_section_end(item, all_items, item_lines, len(lines))
        body = normalize_text("\n".join(lines[current["body_start"] : end]))
        sections.append(
            Section(
                toc_item=item,
                heading_path=toc_path(item, by_id),
                text=body,
                page_start=None,
                page_end=None,
                source_metadata=source_metadata,
            )
        )
    return items, sections


def markdown_section_end(
    item: TocItem,
    all_items: list[TocItem],
    item_lines: dict[str, dict],
    line_count: int,
) -> int:
    current = item_lines[item.toc_id]
    end = line_count
    for candidate in all_items:
        candidate_info = item_lines[candidate.toc_id]
        if candidate_info["start"] <= current["start"]:
            continue
        if item.level < 4:
            end = min(end, candidate_info["start"])
            continue
        if candidate_info["level"] <= current["level"]:
            end = min(end, candidate_info["start"])
    return end


def markdown_heading_entries(lines: list[str]) -> list[dict]:
    entries: list[dict] = []
    in_code_block = False
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        match = HEADING_RE.match(stripped)
        if match:
            entries.append({"line": idx, "level": len(match.group(1)), "title": match.group(2).strip()})
    return entries


def select_markdown_sections(sections: list[Section], toc_items: list[TocItem]) -> list[Section]:
    parent_ids = {item.parent_toc_id for item in toc_items if item.parent_toc_id}
    selected: list[Section] = []
    max_level = 4
    for section in sections:
        if not section.text.strip():
            continue
        if section.toc_item.toc_id in parent_ids:
            selected.append(section)
            continue
        if section.toc_item.level == max_level:
            selected.append(section)
        elif section.toc_item.level < max_level and section.toc_item.toc_id not in parent_ids:
            selected.append(section)
    return selected


def toc_path(item: TocItem, by_id: dict[str, TocItem]) -> list[TocItem]:
    path = [item]
    parent = item.parent_toc_id
    while parent and parent in by_id:
        path.append(by_id[parent])
        parent = by_id[parent].parent_toc_id
    return list(reversed(path))


def add_toc_item(
    toc_items: list[TocItem],
    title: str,
    level: int,
    parent: str | None,
    path: Path | None,
    source_metadata: dict,
) -> TocItem:
    order = len(toc_items) + 1
    item = TocItem(
        toc_id=f"toc:{order:06d}",
        title=title,
        level=level,
        order=order,
        parent_toc_id=parent,
        page=None,
        locate={"method": "markdown_file", "confidence": 1.0, "file": source_metadata.get("file_path") if path else None},
    )
    toc_items.append(item)
    return item


def read_markdown(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def strip_front_matter(text: str) -> str:
    return parse_front_matter(text)[1]


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized.startswith("---\n"):
        end = normalized.find("\n---\n", 4)
        if end != -1:
            raw = normalized[4:end]
            return parse_simple_yaml(raw), normalized[end + 5 :]
    return {}, normalized


def parse_simple_yaml(raw: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def markdown_file_title(path: Path, profile: str) -> str:
    if profile == "journal":
        return path.stem
    return path.stem


def markdown_source_hash(files: list[Path]) -> str:
    parts = []
    for name, path in zip(markdown_relative_names(files), sorted(files)):
        parts.append(name)
        parts.append(sha256_text(read_markdown(path)))
    return sha256_text(json_dumps({"files": parts}))


def markdown_file_metadata(path: Path, file_path: str, profile: str, text: str) -> dict:
    front_matter, _ = parse_front_matter(text)
    stat = path.stat()
    created_at = timestamp_iso(stat.st_ctime)
    modified_at = timestamp_iso(stat.st_mtime)
    front_matter_date = first_front_matter_date(front_matter)
    filename_date = journal_filename_date(path) if profile == "journal" else None
    logical_date = filename_date or normalize_front_matter_date(front_matter_date) or modified_at[:10]
    return {
        "source_type": "markdown",
        "markdown_profile": profile,
        "file_name": path.name,
        "file_stem": path.stem,
        "file_path": file_path,
        "file_created_at": created_at,
        "file_modified_at": modified_at,
        "front_matter_date": front_matter_date,
        "logical_date": logical_date,
        "logical_month": logical_date[:7] if logical_date else None,
    }


def first_front_matter_date(front_matter: dict[str, str]) -> str | None:
    for key in FRONT_MATTER_DATE_KEYS:
        if key in front_matter and front_matter[key]:
            return front_matter[key]
    return None


def normalize_front_matter_date(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", value)
    if not match:
        return None
    year, month, day = re.split(r"[-/.]", match.group(0))
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def journal_filename_date(path: Path) -> str | None:
    match = JOURNAL_DATE_RE.match(path.stem)
    if not match:
        return None
    return f"{match.group('year')}-{match.group('month')}-{match.group('day')}"


def timestamp_iso(value: float) -> str:
    return datetime.fromtimestamp(value).astimezone().isoformat(timespec="seconds")


def markdown_relative_names(files: list[Path]) -> list[str]:
    ordered = sorted(files)
    if not ordered:
        return []
    if len(ordered) == 1:
        return [ordered[0].name]
    common = Path(commonpath([str(path.parent) for path in ordered]))
    return [path.relative_to(common).as_posix() for path in ordered]


def safe_filename(value: str) -> str:
    return safe_stem(Path(value))
