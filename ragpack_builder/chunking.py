from __future__ import annotations

import re

from .models import ChunkDraft, Section


def make_chunks(
    sections: list[Section],
    target_chars: int = 800,
    max_chars: int = 1200,
    min_chunk_chars: int = 220,
    overlap_chars: int = 100,
    section_split_chars: int | None = None,
) -> list[ChunkDraft]:
    section_split_chars = section_split_chars or max_chars
    drafts: list[ChunkDraft] = []
    grouped = group_by_parent(sections)
    for group in grouped:
        drafts.extend(
            chunk_sibling_group(
                group,
                target_chars,
                max_chars,
                min_chunk_chars,
                overlap_chars,
                section_split_chars,
            )
        )
    return drafts


def group_by_parent(sections: list[Section]) -> list[list[Section]]:
    groups: list[list[Section]] = []
    current_parent = object()
    current: list[Section] = []
    for section in sections:
        parent = section.toc_item.parent_toc_id
        if current and parent != current_parent:
            groups.append(current)
            current = []
        current_parent = parent
        current.append(section)
    if current:
        groups.append(current)
    return groups


def chunk_sibling_group(
    sections: list[Section],
    target_chars: int,
    max_chars: int,
    min_chunk_chars: int,
    overlap_chars: int,
    section_split_chars: int,
) -> list[ChunkDraft]:
    out: list[ChunkDraft] = []
    i = 0
    while i < len(sections):
        section = sections[i]
        text = section.text.strip()
        if not text:
            i += 1
            continue
        if len(text) > section_split_chars:
            out.extend(split_long_section(section, max_chars, overlap_chars))
            i += 1
            continue
        if len(text) >= min_chunk_chars:
            out.append(
                ChunkDraft(
                    text=text,
                    heading_path=section.heading_path,
                    merged_headings=[],
                    page_start=section.page_start,
                    page_end=section.page_end,
                    split_info={
                        "strategy": "toc_node",
                        "reason": "natural_section_within_split_threshold",
                        "section_split_chars": section_split_chars,
                    },
                    source_metadata=section.source_metadata,
                )
            )
            i += 1
            continue

        merged = [section]
        merged_len = len(text)
        j = i + 1
        while j < len(sections):
            candidate = sections[j]
            candidate_text = candidate.text.strip()
            if not candidate_text:
                j += 1
                continue
            if merged_len + len(candidate_text) > max_chars:
                break
            merged.append(candidate)
            merged_len += len(candidate_text)
            j += 1
            if merged_len >= target_chars or merged_len >= min_chunk_chars:
                break

        if len(merged) == 1 and out:
            previous = out[-1]
            combined_text = previous.text + "\n\n" + format_section_text(section)
            if len(combined_text) <= max_chars:
                previous.text = combined_text
                previous.merged_headings.append(section.toc_item)
                previous.page_end = section.page_end
                previous.split_info = {
                    "strategy": "toc_node_merge",
                    "reason": "merged_short_last_section_backward",
                    "merged_toc_ids": [h.toc_id for h in previous.merged_headings],
                }
                i += 1
                continue

        if len(merged) == 1:
            out.append(
                ChunkDraft(
                    text=text,
                    heading_path=section.heading_path,
                    merged_headings=[],
                    page_start=section.page_start,
                    page_end=section.page_end,
                    split_info={"strategy": "toc_node", "reason": "short_section_without_merge_target"},
                    source_metadata=section.source_metadata,
                )
            )
            i += 1
            continue

        out.append(
            ChunkDraft(
                text="\n\n".join(format_section_text(s) for s in merged),
                heading_path=common_parent_path(merged),
                merged_headings=[s.toc_item for s in merged],
                page_start=merged[0].page_start,
                page_end=merged[-1].page_end,
                split_info={
                    "strategy": "toc_node_merge",
                    "reason": "merged_short_sibling_sections",
                    "merged_toc_ids": [s.toc_item.toc_id for s in merged],
                },
                source_metadata=merge_source_metadata(merged),
            )
        )
        i += len(merged)
    return out


def split_long_section(section: Section, max_chars: int, overlap_chars: int) -> list[ChunkDraft]:
    units = split_paragraphs_and_sentences(section.text)
    parts: list[str] = []
    current = ""
    for unit in units:
        if len(unit) > max_chars:
            if current:
                parts.append(current)
                current = ""
            parts.extend(split_oversized_unit(unit, max_chars, overlap_chars))
            continue
        if not current:
            current = unit
        elif len(current) + len(unit) + 2 <= max_chars:
            current += "\n\n" + unit
        else:
            parts.append(current)
            overlap = current[-overlap_chars:] if overlap_chars > 0 else ""
            current = (overlap + "\n\n" + unit).strip()
    if current:
        parts.append(current)

    total = len(parts)
    return [
        ChunkDraft(
            text=part,
            heading_path=section.heading_path,
            merged_headings=[],
            page_start=section.page_start,
            page_end=section.page_end,
            split_info={
                "strategy": "paragraph_sentence_split",
                "reason": "section_exceeds_max_chars",
                "part_index": idx,
                "part_count": total,
            },
            source_metadata=section.source_metadata,
        )
        for idx, part in enumerate(parts, start=1)
    ]


def merge_source_metadata(sections: list[Section]) -> dict:
    if not sections:
        return {}
    first = dict(sections[0].source_metadata)
    unique_sources = []
    seen = set()
    for section in sections:
        source = section.source_metadata
        key = (source.get("file_path"), source.get("logical_date"))
        if key in seen:
            continue
        seen.add(key)
        if source:
            unique_sources.append(source)
    if len(unique_sources) > 1:
        first["merged_sources"] = unique_sources
    return first


def split_oversized_unit(unit: str, max_chars: int, overlap_chars: int) -> list[str]:
    parts: list[str] = []
    step = max(1, max_chars - max(0, overlap_chars))
    start = 0
    while start < len(unit):
        parts.append(unit[start : start + max_chars])
        if start + max_chars >= len(unit):
            break
        start += step
    return parts


def split_paragraphs_and_sentences(text: str) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    units: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= 500:
            units.append(paragraph)
            continue
        sentences = re.split(r"(?<=[。！？；;!?])", paragraph)
        units.extend(s.strip() for s in sentences if s.strip())
    return units


def format_section_text(section: Section) -> str:
    return f"【{section.toc_item.title}】\n{section.text.strip()}"


def common_parent_path(sections: list[Section]):
    if len(sections) == 1:
        return sections[0].heading_path
    first = sections[0].heading_path
    common = []
    for idx, item in enumerate(first):
        if all(len(s.heading_path) > idx and s.heading_path[idx].toc_id == item.toc_id for s in sections):
            common.append(item)
        else:
            break
    return common or first[:1]
