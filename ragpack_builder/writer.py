from __future__ import annotations

from pathlib import Path

from .models import ChunkDraft, TocItem
from .utils import json_dumps, sha256_text


def build_embedding_text(title: str, chunk: ChunkDraft) -> str:
    heading_path = " > ".join(item.title for item in chunk.heading_path)
    lines = [f"书名：{title}"]
    if heading_path:
        lines.append(f"章节路径：{heading_path}")
    if chunk.merged_headings:
        lines.append("包含小节：" + "；".join(item.title for item in chunk.merged_headings))
    lines.append("")
    lines.append(chunk.text)
    return "\n".join(lines)


def toc_record(document_id: str, toc_items: list[TocItem], source: str) -> dict:
    return {
        "record_type": "toc",
        "document_id": document_id,
        "source": source,
        "items": [
            {
                "toc_id": item.toc_id,
                "title": item.title,
                "level": item.level,
                "order": item.order,
                "parent_toc_id": item.parent_toc_id,
                "page": item.page,
                "locate": item.locate,
            }
            for item in toc_items
        ],
    }


def write_jsonl(path: Path, manifest: dict, toc: dict, chunk_records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(json_dumps(manifest) + "\n")
        f.write(json_dumps(toc) + "\n")
        for record in chunk_records:
            f.write(json_dumps(record) + "\n")


def make_chunk_records(
    document_id: str,
    title: str,
    chunks: list[ChunkDraft],
    embeddings: list[list[float]],
) -> list[dict]:
    records: list[dict] = []
    chunk_ids = [f"{document_id}:chunk:{idx:06d}" for idx in range(1, len(chunks) + 1)]
    for idx, chunk in enumerate(chunks, start=1):
        embedding_text = build_embedding_text(title, chunk)
        record = {
            "record_type": "chunk",
            "document_id": document_id,
            "chunk_id": chunk_ids[idx - 1],
            "chunk_index": idx,
            "text": chunk.text,
            "embedding_text": embedding_text,
            "heading_path": [item.title for item in chunk.heading_path],
            "toc_path": [
                {"toc_id": item.toc_id, "level": item.level, "title": item.title}
                for item in chunk.heading_path
            ],
            "merged_headings": [
                {"toc_id": item.toc_id, "level": item.level, "title": item.title}
                for item in chunk.merged_headings
            ],
            "content_type": "body",
            "source": {
                "pdf_page_start": chunk.page_start,
                "pdf_page_end": chunk.page_end,
            },
            "prev_chunk_id": chunk_ids[idx - 2] if idx > 1 else None,
            "next_chunk_id": chunk_ids[idx] if idx < len(chunks) else None,
            "stats": {
                "char_count": len(chunk.text),
                "embedding_char_count": len(embedding_text),
            },
            "content_hash": sha256_text(chunk.text),
            "split_info": chunk.split_info,
            "embedding": embeddings[idx - 1],
        }
        records.append(record)
    return records

