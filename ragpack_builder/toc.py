from __future__ import annotations

import difflib
import re
import unicodedata

from .models import PageText, Section, TocItem
from .utils import normalize_text, normalize_title, reflow_zh_text


CHAPTER_RE = re.compile(r"^第\s*[一二三四五六七八九十百千万\d]+\s*章[　\s]*(.+)?$")
PART_RE = re.compile(r"^第\s*[一二三四五六七八九十百千万\d]+\s*[编篇部][　\s]*(.+)?$")
SECTION_RE = re.compile(r"^第\s*[一二三四五六七八九十百千万\d]+\s*节[　\s]*(.+)?$")
ARTICLE_RE = re.compile(r"^第\s*[一二三四五六七八九十百千万\d]+\s*条[　\s]*(.+)?$")
FICTION_CHAPTER_RE = re.compile(r"^第\s*[一二三四五六七八九十百千万\d]+\s*[章节回][　\s]*(.*)$")
FICTION_SPECIAL_RE = re.compile(r"^(楔子|序章|引子|尾声|后记|番外(?:篇)?)(?:[　\s].*)?$")
VOLUME_RE = re.compile(r"^卷\s*[一二三四五六七八九十百千万\d上下]+(?:[　\s].*)?$")
CLASSICAL_SECTION_RE = re.compile(r"^(上篇|下篇|内篇|外篇|本纪|世家|列传|志|表|书|论|序)(?:[　\s].*)?$")
CLASSICAL_BIO_RE = re.compile(r"^[\u4e00-\u9fff]{1,12}(传|纪|志|论|说|赋|铭|序|跋)$")
REFERENCE_ALPHA_RE = re.compile(r"^[A-Z]$")
REFERENCE_ENTRY_RE = re.compile(r"^[A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff·・、（）() -]{1,40}$")
CN_ENUM_RE = re.compile(r"^[一二三四五六七八九十百千万]+、\S+")
CN_PAREN_ENUM_RE = re.compile(r"^（[一二三四五六七八九十百千万]+）\S+")
ARABIC_ENUM_RE = re.compile(r"^\d+[、.．]\s*\S+")
DECIMAL_ENUM_RE = re.compile(r"^\d+(?:\.\d+)+[　\s]+\S+")
TECHNICAL_TOP_RE = re.compile(r"^\d+[　\s]+[^\s].+")
PAPER_ABSTRACT_RE = re.compile(r"^(摘要|摘\s*要|Abstract)$", re.IGNORECASE)
PAPER_KEYWORDS_RE = re.compile(r"^(关键词|关键字|Keywords?)[:：]?\s*.*$", re.IGNORECASE)
PAPER_REFERENCE_RE = re.compile(r"^(参考文献|References|Bibliography)$", re.IGNORECASE)
EN_PART_RE = re.compile(r"^Part\s+[IVXLCDM\d]+[:.\s-].*$", re.IGNORECASE)
EN_CHAPTER_RE = re.compile(r"^Chapter\s+\d+[:.\s-].*$", re.IGNORECASE)
EN_APPENDIX_RE = re.compile(r"^Appendix\s+[A-Z\d]+[:.\s-]?.*$", re.IGNORECASE)
SHORT_HEADING_RE = re.compile(r"^[^\s，。！？；;,.!?]{4,40}$")
FRONT_TOC_LINE_RE = re.compile(
    r"^(译\s*序|序\s*言|前\s*言|后\s*记|第\s*[一二三四五六七八九十百千万\d]+\s*[篇章部编]\s*.+|附录[一二三四五六七八九十百千万\d]?.*)$"
)


def infer_txt_toc(pages: list[PageText], profile: str = "social_science") -> list[TocItem]:
    lines = [line.strip() for page in pages for line in page.text.splitlines()]
    toc_items: list[TocItem] = []
    stack: list[TocItem] = []
    for line in lines:
        if not is_possible_heading(line, profile):
            continue
        level = infer_heading_level(line, stack, profile)
        while stack and stack[-1].level >= level:
            stack.pop()
        parent = stack[-1].toc_id if stack else None
        order = len(toc_items) + 1
        toc = TocItem(
            toc_id=f"toc:{order:06d}",
            title=line,
            level=level,
            order=order,
            parent_toc_id=parent,
            page=1,
            locate={"method": f"{profile}_heading_rule", "confidence": 0.7 if profile == "textbook" else 0.65},
        )
        toc_items.append(toc)
        stack.append(toc)
    return toc_items


def repair_toc_titles_from_text_pages(pages: list[PageText], toc_items: list[TocItem]) -> int:
    """Replace garbled PDF outline titles with clean titles from front-matter TOC pages."""
    if not toc_items or not any(is_garbled_title(item.title) for item in toc_items):
        return 0
    candidates = extract_front_matter_toc_candidates(pages)
    if len(candidates) < max(3, int(len(toc_items) * 0.6)):
        return 0
    repaired = 0
    for item, candidate in zip(toc_items, candidates):
        if is_garbled_title(item.title) and candidate["level"] == item.level:
            item.title = candidate["title"]
            item.locate = {
                **(item.locate or {}),
                "repair": "front_matter_toc",
                "original_title_was_garbled": True,
            }
            repaired += 1
    return repaired


def extract_front_matter_toc_candidates(pages: list[PageText], max_pages: int = 8) -> list[dict]:
    candidates: list[dict] = []
    seen = set()
    for page in pages[:max_pages]:
        for raw_line in page.text.splitlines():
            line = normalize_text(raw_line)
            if not line or line == "目录":
                continue
            if not FRONT_TOC_LINE_RE.match(line):
                continue
            key = normalize_title(line)
            if key in seen:
                continue
            seen.add(key)
            candidates.append({"title": line, "level": infer_front_toc_level(line)})
    return candidates


def infer_front_toc_level(line: str) -> int:
    if re.match(r"^第\s*[一二三四五六七八九十百千万\d]+\s*章", line):
        return 2
    if re.match(r"^第\s*[一二三四五六七八九十百千万\d]+\s*[篇部编]", line):
        return 1
    if re.match(r"^附录", line):
        return 1
    return 1


def is_garbled_title(title: str) -> bool:
    if not title:
        return False
    weird = 0
    meaningful = 0
    for ch in title:
        if ch.isspace():
            continue
        code = ord(ch)
        category = unicodedata.category(ch)
        if (
            0x0590 <= code <= 0x08FF
            or 0x0D00 <= code <= 0x0D7F
            or 0x0C80 <= code <= 0x0CFF
            or 0xFB00 <= code <= 0xFEFF
        ):
            return True
        if 0xE000 <= code <= 0xF8FF or category in {"So", "Sk"} and ch not in {"·"}:
            return True
        if "\u4e00" <= ch <= "\u9fff" or ch.isalnum() or ch in "：:、，,（）()[]【】《》一二三四五六七八九十百千万章节篇部编附录译序言":
            meaningful += 1
            continue
        if 0xE000 <= code <= 0xF8FF or code < 32 or code in {0xFFFD}:
            weird += 2
        elif code > 0x2FFF:
            weird += 1
    total = meaningful + weird
    return total > 0 and weird / total >= 0.18


def augment_toc_with_body_headings(
    pages: list[PageText],
    toc_items: list[TocItem],
    profile: str = "social_science",
    max_headings_per_parent: int = 16,
) -> int:
    if not toc_items:
        return 0
    lines = flatten_page_lines(pages)
    start_indexes = locate_heading_lines(lines, toc_items)
    parent_ids = {item.parent_toc_id for item in toc_items if item.parent_toc_id}
    existing_titles = {normalize_title(item.title) for item in toc_items}
    additions: list[tuple[int, TocItem]] = []
    next_auto = 1
    for idx, parent in enumerate(toc_items):
        if parent.toc_id in parent_ids or parent.toc_id not in start_indexes:
            continue
        if parent.level > 2 or not is_augmentable_parent(parent):
            continue
        start_idx = start_indexes[parent.toc_id]
        end_idx = len(lines)
        for later in toc_items[idx + 1 :]:
            later_idx = start_indexes.get(later.toc_id)
            if later_idx is not None and later.level <= parent.level:
                end_idx = later_idx
                break
        raw_candidates: list[tuple[int, str]] = []
        for line_idx in range(start_idx + 1, end_idx):
            title = lines[line_idx]["text"].strip()
            key = normalize_title(title)
            if key in existing_titles:
                continue
            if not is_body_short_heading(title, profile):
                continue
            raw_candidates.append((line_idx, title))
        found_for_parent = 0
        for line_idx, title in filter_candidate_heading_runs(raw_candidates):
            key = normalize_title(title)
            toc = TocItem(
                toc_id=f"toc:auto:{next_auto:06d}",
                title=title,
                level=parent.level + 1,
                order=0,
                parent_toc_id=parent.toc_id,
                page=lines[line_idx]["page"],
                locate={"method": "body_short_heading", "confidence": 0.72},
            )
            additions.append((line_idx, toc))
            existing_titles.add(key)
            next_auto += 1
            found_for_parent += 1
            if found_for_parent >= max_headings_per_parent:
                break
    if not additions:
        return 0
    sort_keys = {item.toc_id: start_indexes.get(item.toc_id, len(lines) + item.order) for item in toc_items}
    all_items = [(sort_keys[item.toc_id], item) for item in toc_items] + additions
    all_items.sort(key=lambda pair: (pair[0], pair[1].level))
    toc_items[:] = [item for _, item in all_items]
    for order, item in enumerate(toc_items, start=1):
        item.order = order
    return len(additions)


def is_augmentable_parent(item: TocItem) -> bool:
    return bool(CHAPTER_RE.match(item.title) or EN_CHAPTER_RE.match(item.title))


def is_body_short_heading(line: str, profile: str = "social_science") -> bool:
    if not line or len(line) < 4 or len(line) > 30:
        return False
    if line.endswith(("。", "，", "；", "：", "！", "？", ".", ",", ";", ":", "!", "?")):
        return False
    if any(mark in line for mark in ("。", "！", "？", "；", "“", "”", '"')):
        return False
    if CHAPTER_RE.match(line) or PART_RE.match(line) or SECTION_RE.match(line):
        return False
    if "《" in line or "》" in line or "——" in line:
        return False
    if line[0] in "（([ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz":
        return False
    if line.count("（") != line.count("）") or line.count("(") != line.count(")"):
        return False
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", line))
    if cjk_count < 4:
        return False
    ascii_count = len(re.findall(r"[A-Za-z]", line))
    if ascii_count and ascii_count / max(1, len(line)) > 0.35:
        return False
    if profile == "reference":
        return False
    return True


def filter_candidate_heading_runs(candidates: list[tuple[int, str]]) -> list[tuple[int, str]]:
    if len(candidates) < 3:
        return candidates
    out: list[tuple[int, str]] = []
    indexes = [idx for idx, _ in candidates]
    for pos, candidate in enumerate(candidates):
        prev_adjacent = pos > 0 and indexes[pos] == indexes[pos - 1] + 1
        next_adjacent = pos + 1 < len(indexes) and indexes[pos + 1] == indexes[pos] + 1
        prev_prev_adjacent = pos > 1 and indexes[pos - 1] == indexes[pos - 2] + 1
        next_next_adjacent = pos + 2 < len(indexes) and indexes[pos + 2] == indexes[pos + 1] + 1
        if (prev_adjacent and next_adjacent) or (prev_adjacent and prev_prev_adjacent) or (next_adjacent and next_next_adjacent):
            continue
        out.append(candidate)
    return out


def is_possible_heading(line: str, profile: str = "social_science") -> bool:
    if not line:
        return False
    if line.startswith(("■", "•", "-", "—")):
        return False
    if len(line) > 60:
        return False
    if line.endswith(("。", "，", "；", "：", "！", "？", ".", ",", ";", ":", "!", "?")):
        return False
    if profile in {"textbook", "technical", "paper", "legal", "english", "fiction", "classical", "reference"}:
        return bool(
            PART_RE.match(line)
            or CHAPTER_RE.match(line)
            or SECTION_RE.match(line)
            or ARTICLE_RE.match(line)
            or FICTION_CHAPTER_RE.match(line)
            or FICTION_SPECIAL_RE.match(line)
            or VOLUME_RE.match(line)
            or CLASSICAL_SECTION_RE.match(line)
            or CLASSICAL_BIO_RE.match(line)
            or (profile == "reference" and (REFERENCE_ALPHA_RE.match(line) or REFERENCE_ENTRY_RE.match(line)))
            or CN_ENUM_RE.match(line)
            or CN_PAREN_ENUM_RE.match(line)
            or ARABIC_ENUM_RE.match(line)
            or DECIMAL_ENUM_RE.match(line)
            or TECHNICAL_TOP_RE.match(line)
            or PAPER_ABSTRACT_RE.match(line)
            or PAPER_KEYWORDS_RE.match(line)
            or PAPER_REFERENCE_RE.match(line)
            or EN_PART_RE.match(line)
            or EN_CHAPTER_RE.match(line)
            or EN_APPENDIX_RE.match(line)
            or SHORT_HEADING_RE.match(line)
            or "：" in line
            or ":" in line
        )
    return bool(CHAPTER_RE.match(line) or SHORT_HEADING_RE.match(line) or "：" in line or ":" in line)


def infer_heading_level(line: str, stack: list[TocItem], profile: str = "social_science") -> int:
    if CHAPTER_RE.match(line):
        if profile == "legal":
            return 2
        return 1
    if profile in {"textbook", "technical", "paper", "legal", "english", "fiction", "classical", "reference"}:
        if profile == "fiction":
            if FICTION_SPECIAL_RE.match(line):
                return 1
            if FICTION_CHAPTER_RE.match(line) or EN_CHAPTER_RE.match(line):
                return 1
        if profile == "classical":
            if VOLUME_RE.match(line):
                return 1
            if CLASSICAL_SECTION_RE.match(line):
                return 2
            if CLASSICAL_BIO_RE.match(line):
                return 3
        if profile == "reference":
            if REFERENCE_ALPHA_RE.match(line):
                return 1
            if REFERENCE_ENTRY_RE.match(line):
                return 2
        if PART_RE.match(line):
            return 1
        if profile == "legal" and ARTICLE_RE.match(line):
            return 4
        if SECTION_RE.match(line):
            if profile == "legal":
                return 3
            return 2
        if CN_ENUM_RE.match(line):
            return 3
        if CN_PAREN_ENUM_RE.match(line):
            return 4
        if profile == "textbook" and ARABIC_ENUM_RE.match(line):
            return 5
        decimal = DECIMAL_ENUM_RE.match(line)
        if profile in {"technical", "paper"} and TECHNICAL_TOP_RE.match(line):
            return 1
        if profile in {"technical", "paper", "english"} and decimal:
            prefix = line.split(maxsplit=1)[0]
            return min(1 + prefix.count("."), 6)
        if profile == "paper":
            if PAPER_ABSTRACT_RE.match(line) or PAPER_KEYWORDS_RE.match(line):
                return 1
            if PAPER_REFERENCE_RE.match(line):
                return 1
        if profile == "english":
            if EN_PART_RE.match(line):
                return 1
            if EN_CHAPTER_RE.match(line):
                return 2
            if EN_APPENDIX_RE.match(line):
                return 1
        if profile == "textbook" and decimal:
            prefix = line.split(maxsplit=1)[0]
            return min(2 + prefix.count("."), 6)
    if ("：" in line or ":" in line) and any(item.level == 2 for item in stack):
        return 3
    if stack and stack[-1].level >= 2 and ("：" in line or ":" in line):
        return 3
    return 2 if stack else 1


def locate_toc_items(pages: list[PageText], toc_items: list[TocItem], before: int = 1, after: int = 2) -> None:
    for item in toc_items:
        if item.page is None:
            item.locate = {"method": "no_page", "confidence": 0.3}
            continue
        start = max(1, item.page - before)
        end = min(len(pages), item.page + after)
        found = find_title_in_pages(item.title, pages[start - 1 : end])
        if found:
            page_index, method, confidence = found
            item.page = page_index
            item.locate = {"method": method, "confidence": confidence}
        elif item.locate is None or item.locate.get("method") == "pdf_outline":
            item.locate = {
                "method": "bookmark_page_fallback",
                "confidence": 0.5,
                "warning": "title_not_found_near_bookmark_page",
            }


def find_title_in_pages(title: str, pages: list[PageText]) -> tuple[int, str, float] | None:
    target = normalize_title(title)
    best: tuple[int, str, float] | None = None
    for page in pages:
        for line in page.text.splitlines():
            candidate = normalize_title(line)
            if not candidate:
                continue
            if candidate == target:
                return page.page_index, "exact_normalized", 1.0
            if candidate.startswith(target[: min(len(target), 18)]) or target.startswith(candidate):
                best = max_candidate(best, (page.page_index, "prefix_normalized", 0.9))
                continue
            ratio = difflib.SequenceMatcher(None, candidate, target).ratio()
            if ratio >= 0.82:
                best = max_candidate(best, (page.page_index, "fuzzy_ratio", ratio))
    return best


def max_candidate(
    current: tuple[int, str, float] | None, candidate: tuple[int, str, float]
) -> tuple[int, str, float]:
    if current is None or candidate[2] > current[2]:
        return candidate
    return current


def build_sections(
    pages: list[PageText],
    toc_items: list[TocItem],
    max_chunk_heading_level: int | None = None,
) -> list[Section]:
    if not toc_items:
        root = TocItem("toc:000001", "正文", 1, 1, page=1, locate={"method": "synthetic", "confidence": 0.4})
        return [Section(root, [root], "\n\n".join(p.text for p in pages), 1, pages[-1].page_index if pages else 1)]

    lines = flatten_page_lines(pages)
    start_indexes = locate_heading_lines(lines, toc_items)

    by_id = {item.toc_id: item for item in toc_items}
    sections: list[Section] = []
    for i, item in enumerate(toc_items):
        start_idx = start_indexes.get(item.toc_id)
        if start_idx is None:
            continue
        end_idx = len(lines)
        for later in toc_items[i + 1 :]:
            later_idx = start_indexes.get(later.toc_id)
            child_boundary = later.parent_toc_id == item.toc_id and should_stop_section_at_child(
                item, max_chunk_heading_level
            )
            if later_idx is not None and (later.level <= item.level or child_boundary):
                end_idx = later_idx
                break
        body_start = skip_wrapped_heading_lines(lines, start_idx, item.title)
        body_lines = [entry["text"] for entry in lines[body_start:end_idx]]
        text = reflow_zh_text("\n".join(body_lines))
        start_page = lines[start_idx]["page"]
        end_page = lines[end_idx - 1]["page"] if end_idx > start_idx else start_page
        path = toc_path(item, by_id)
        sections.append(Section(item, path, text, start_page, end_page))

    return leaf_or_content_sections(sections, toc_items, max_chunk_heading_level)


def skip_wrapped_heading_lines(lines: list[dict], start_idx: int, title: str) -> int:
    target = normalize_title(title)
    accumulated = lines[start_idx]["normalized"]
    idx = start_idx + 1
    while idx < len(lines) and len(accumulated) < len(target):
        combined = accumulated + lines[idx]["normalized"]
        if target.startswith(combined):
            accumulated = combined
            idx += 1
            continue
        break
    return idx


def flatten_page_lines(pages: list[PageText]) -> list[dict]:
    lines: list[dict] = []
    for page in pages:
        for line in page.text.splitlines():
            text = line.strip()
            if text:
                lines.append({"page": page.page_index, "text": text, "normalized": normalize_title(text)})
    return lines


def locate_heading_lines(lines: list[dict], toc_items: list[TocItem]) -> dict[str, int]:
    positions: dict[str, int] = {}
    cursor = 0
    for item in toc_items:
        target = normalize_title(item.title)
        found = find_heading_line_near_page(lines, target, item.page)
        if found is None:
            found = find_heading_line_after_cursor(lines, target, cursor)
        if found is None:
            found = first_line_at_or_after_page(lines, item.page)
        if found is not None:
            positions[item.toc_id] = found
            cursor = max(cursor, found + 1)
    return positions


def find_heading_line_near_page(lines: list[dict], target: str, page: int | None) -> int | None:
    if page is None:
        return None
    candidates = [
        idx
        for idx, line in enumerate(lines)
        if page - 1 <= int(line["page"]) <= page + 2
    ]
    return best_heading_match(lines, target, candidates)


def find_heading_line_after_cursor(lines: list[dict], target: str, cursor: int) -> int | None:
    return best_heading_match(lines, target, range(cursor, len(lines)))


def first_line_at_or_after_page(lines: list[dict], page: int | None) -> int | None:
    if page is None:
        return None
    for idx, line in enumerate(lines):
        if int(line["page"]) >= page:
            return idx
    return None


def best_heading_match(lines: list[dict], target: str, indexes) -> int | None:
    best_idx = None
    best_score = 0.0
    for idx in indexes:
            candidate = lines[idx]["normalized"]
            if candidate == target or candidate.startswith(target[: min(len(target), 18)]):
                return idx
            ratio = difflib.SequenceMatcher(None, candidate, target).ratio()
            if ratio >= 0.9 and ratio > best_score:
                best_idx = idx
                best_score = ratio
    return best_idx


def toc_path(item: TocItem, by_id: dict[str, TocItem]) -> list[TocItem]:
    path = [item]
    parent = item.parent_toc_id
    while parent and parent in by_id:
        path.append(by_id[parent])
        parent = by_id[parent].parent_toc_id
    return list(reversed(path))


def remove_heading_prefix(text: str, title: str) -> str:
    lines = text.splitlines()
    target = normalize_title(title)
    for idx, line in enumerate(lines[:20]):
        candidate = normalize_title(line)
        if candidate == target or candidate.startswith(target[: min(len(target), 18)]):
            return "\n".join(lines[idx + 1 :])
    return text


def leaf_or_content_sections(
    sections: list[Section],
    toc_items: list[TocItem],
    max_chunk_heading_level: int | None = None,
) -> list[Section]:
    parent_ids = {item.parent_toc_id for item in toc_items if item.parent_toc_id}
    selected: list[Section] = []
    for section in sections:
        if not section.text.strip():
            continue
        if max_chunk_heading_level is not None:
            if section.toc_item.toc_id in parent_ids and section.toc_item.level < max_chunk_heading_level:
                selected.append(section)
                continue
            if section.toc_item.level == max_chunk_heading_level:
                selected.append(section)
            elif section.toc_item.level < max_chunk_heading_level and section.toc_item.toc_id not in parent_ids:
                selected.append(section)
            continue
        if section.toc_item.toc_id in parent_ids:
            selected.append(section)
            continue
        if section.toc_item.toc_id not in parent_ids:
            selected.append(section)
    return selected


def should_stop_section_at_child(item: TocItem, max_chunk_heading_level: int | None) -> bool:
    return max_chunk_heading_level is None or item.level < max_chunk_heading_level
