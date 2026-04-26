from __future__ import annotations

import json
import re
from html import escape
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median
from typing import Any

from .classifier import classify_pdf, format_classification_scores, format_classification_signals
from .extractors import extract_pdf
from .profiles import PROFILE_DEFAULTS
from .toc import is_body_short_heading, is_garbled_title
from .utils import normalize_text, sha256_file


@dataclass
class InspectMessage:
    status: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


def inspect_book_pack(pdf_path: Path, jsonl_path: Path, write_report: bool = True) -> dict[str, Any]:
    pdf_path = pdf_path.resolve()
    jsonl_path = jsonl_path.resolve()
    records = read_jsonl_records(jsonl_path)
    manifest, toc, chunks = split_records(records)
    pages, _, _ = extract_pdf(pdf_path)

    messages: list[InspectMessage] = []
    messages.extend(check_file_match(pdf_path, manifest))
    messages.extend(check_schema(manifest, toc, chunks))
    messages.extend(check_profile(manifest))

    length_stats, length_messages = check_chunk_lengths(manifest, chunks)
    messages.extend(length_messages)

    heading_stats, heading_messages = check_heading_paths(chunks)
    messages.extend(heading_messages)

    garbled_stats, garbled_messages = check_garbled_text(toc, chunks)
    messages.extend(garbled_messages)

    coverage_stats, coverage_messages = check_pdf_coverage(pages, chunks)
    messages.extend(coverage_messages)

    recommendations = build_local_recommendations(pdf_path, pages, manifest, toc, chunks, length_stats, heading_stats)
    samples = build_pdf_comparison_samples(pages, chunks)

    score = score_messages(messages)
    result = result_from_score_and_messages(score, messages)
    recommendation = make_recommendation(result, messages, manifest)

    report = {
        "result": result,
        "score": score,
        "pdf": str(pdf_path),
        "ragpack": str(jsonl_path),
        "title": manifest.get("title"),
        "summary": {
            "chunks": len(chunks),
            "toc_items": len(toc.get("items", [])) if isinstance(toc, dict) else 0,
            "toc_source": (manifest.get("toc") or {}).get("source") or toc.get("source"),
            "profile": (manifest.get("chunking") or {}).get("profile"),
            "embedding_provider": (manifest.get("embedding") or {}).get("provider"),
            "embedding_dimension": (manifest.get("embedding") or {}).get("dimension"),
        },
        "stats": {
            "length": length_stats,
            "heading": heading_stats,
            "garbled": garbled_stats,
            "coverage": coverage_stats,
        },
        "recommendations": recommendations,
        "samples": samples,
        "checks": [
            {"status": item.status, "message": item.message, "detail": item.detail}
            for item in messages
        ],
        "recommendation": recommendation,
    }
    if write_report:
        report_path = jsonl_path.with_suffix(".inspect.json")
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["report_path"] = str(report_path)
        html_path = jsonl_path.with_suffix(".inspect.html")
        html_path.write_text(render_html_report(report), encoding="utf-8")
        report["html_report_path"] = str(html_path)
    return report


def read_jsonl_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSONL 第 {lineno} 行不是合法 JSON: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"JSONL 第 {lineno} 行不是对象记录")
            records.append(record)
    return records


def split_records(records: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    manifest = next((r for r in records if r.get("record_type") == "manifest"), None)
    toc = next((r for r in records if r.get("record_type") == "toc"), None)
    chunks = [r for r in records if r.get("record_type") == "chunk"]
    if manifest is None:
        manifest = {}
    if toc is None:
        toc = {}
    return manifest, toc, chunks


def check_file_match(pdf_path: Path, manifest: dict[str, Any]) -> list[InspectMessage]:
    messages: list[InspectMessage] = []
    source = manifest.get("source") or {}
    expected_hash = source.get("source_sha256") or manifest.get("document_id")
    actual_hash = sha256_file(pdf_path)
    if expected_hash and expected_hash != actual_hash:
        messages.append(
            InspectMessage(
                "FAIL",
                "PDF 文件 hash 与 RAGPack manifest 不一致，可能拿错了 PDF 或 JSONL。",
                {"expected": expected_hash, "actual": actual_hash},
            )
        )
    else:
        messages.append(InspectMessage("PASS", "PDF 文件 hash 与 RAGPack manifest 匹配。"))

    source_name = source.get("file_name")
    if source_name and Path(str(source_name)).name != pdf_path.name:
        messages.append(
            InspectMessage(
                "WARN",
                "manifest 中记录的源文件名与当前 PDF 文件名不同。",
                {"manifest_file_name": source_name, "pdf_file_name": pdf_path.name},
            )
        )
    return messages


def check_schema(manifest: dict[str, Any], toc: dict[str, Any], chunks: list[dict[str, Any]]) -> list[InspectMessage]:
    messages: list[InspectMessage] = []
    required_manifest = ("record_type", "schema_version", "document_id", "title", "source", "toc", "chunking", "embedding")
    missing_manifest = [name for name in required_manifest if name not in manifest]
    if missing_manifest:
        messages.append(InspectMessage("FAIL", "manifest 缺少必要字段。", {"missing": missing_manifest}))
    else:
        messages.append(InspectMessage("PASS", "manifest 必要字段完整。"))

    if toc.get("record_type") != "toc" or not isinstance(toc.get("items"), list):
        messages.append(InspectMessage("FAIL", "toc 记录缺失或结构不合法。"))
    else:
        messages.append(InspectMessage("PASS", "toc 记录结构正常。", {"toc_items": len(toc.get("items", []))}))

    if not chunks:
        messages.append(InspectMessage("FAIL", "没有找到任何 chunk 记录。"))
        return messages

    required_chunk = (
        "chunk_id",
        "chunk_index",
        "text",
        "embedding_text",
        "heading_path",
        "source",
        "prev_chunk_id",
        "next_chunk_id",
        "stats",
        "split_info",
        "embedding",
    )
    bad_chunks = []
    for chunk in chunks:
        missing = [name for name in required_chunk if name not in chunk]
        if missing:
            bad_chunks.append({"chunk_index": chunk.get("chunk_index"), "missing": missing})
        if not isinstance(chunk.get("heading_path"), list):
            bad_chunks.append({"chunk_index": chunk.get("chunk_index"), "error": "heading_path is not list"})
        if not isinstance(chunk.get("embedding"), list):
            bad_chunks.append({"chunk_index": chunk.get("chunk_index"), "error": "embedding is not list"})
    if bad_chunks:
        messages.append(InspectMessage("FAIL", "部分 chunk 缺少必要字段或字段类型不正确。", {"examples": bad_chunks[:10]}))
    else:
        messages.append(InspectMessage("PASS", "chunk 记录必要字段完整。", {"chunks": len(chunks)}))

    indices = [chunk.get("chunk_index") for chunk in chunks]
    if indices != list(range(1, len(chunks) + 1)):
        messages.append(InspectMessage("WARN", "chunk_index 不是连续递增序列。", {"first_indices": indices[:10]}))

    empty_chunks = [chunk.get("chunk_index") for chunk in chunks if not str(chunk.get("text") or "").strip()]
    if empty_chunks:
        messages.append(InspectMessage("FAIL", "存在空 chunk。", {"chunk_indices": empty_chunks[:20]}))
    return messages


def check_profile(manifest: dict[str, Any]) -> list[InspectMessage]:
    messages: list[InspectMessage] = []
    chunking = manifest.get("chunking") or {}
    profile = chunking.get("profile")
    if profile not in PROFILE_DEFAULTS:
        messages.append(InspectMessage("WARN", "manifest 中的 profile 不是已知书籍 profile。", {"profile": profile}))
        return messages

    defaults = PROFILE_DEFAULTS[profile]
    mismatches = {}
    for key in ("target_chars", "max_chars", "section_split_chars", "min_chunk_chars", "overlap_chars"):
        if key in chunking and chunking[key] != defaults.get(key):
            mismatches[key] = {"manifest": chunking[key], "profile_default": defaults.get(key)}
    if mismatches:
        messages.append(InspectMessage("WARN", "manifest 中部分 chunking 参数与当前 profile 默认值不同。", mismatches))
    else:
        messages.append(InspectMessage("PASS", "profile 与 chunking 默认参数一致。", {"profile": profile}))

    embedding = manifest.get("embedding") or {}
    if embedding.get("provider") != "none":
        messages.append(InspectMessage("WARN", "该文件看起来不是 no-embedding 调试文件。", {"provider": embedding.get("provider")}))
    elif embedding.get("dimension") not in (0, None):
        messages.append(InspectMessage("WARN", "no-embedding 文件的 embedding dimension 应为 0。", {"dimension": embedding.get("dimension")}))
    else:
        messages.append(InspectMessage("PASS", "确认是 no-embedding 文件。"))
    return messages


def check_chunk_lengths(manifest: dict[str, Any], chunks: list[dict[str, Any]]) -> tuple[dict[str, Any], list[InspectMessage]]:
    messages: list[InspectMessage] = []
    lengths = [len(str(chunk.get("text") or "")) for chunk in chunks]
    if not lengths:
        return {}, []
    chunking = manifest.get("chunking") or {}
    section_split = int(chunking.get("section_split_chars") or 2000)
    very_long_limit = max(section_split * 2, 3500)
    buckets = {
        "very_short_lt_100": sum(1 for x in lengths if x < 100),
        "short_100_300": sum(1 for x in lengths if 100 <= x < 300),
        "normal_300_to_section_split": sum(1 for x in lengths if 300 <= x <= section_split),
        "long_section_split_to_very_long": sum(1 for x in lengths if section_split < x <= very_long_limit),
        "very_long": sum(1 for x in lengths if x > very_long_limit),
    }
    stats = {
        "min": min(lengths),
        "median": median(lengths),
        "average": round(mean(lengths), 1),
        "max": max(lengths),
        "section_split_chars": section_split,
        "buckets": buckets,
    }
    total = len(lengths)
    if buckets["very_long"]:
        messages.append(
            InspectMessage(
                "WARN",
                "存在特别长的 chunk，可能需要更细的标题识别或降低 section_split_chars。",
                {"count": buckets["very_long"], "limit": very_long_limit},
            )
        )
    if buckets["very_short_lt_100"] / total > 0.12:
        messages.append(
            InspectMessage(
                "WARN",
                "过短 chunk 比例偏高，可能切得太碎或存在目录/残页内容。",
                {"ratio": round(buckets["very_short_lt_100"] / total, 3)},
            )
        )
    if buckets["normal_300_to_section_split"] / total >= 0.65:
        messages.append(InspectMessage("PASS", "chunk 长度分布健康。", stats))
    else:
        messages.append(InspectMessage("WARN", "chunk 长度分布需要人工抽查。", stats))
    return stats, messages


def check_heading_paths(chunks: list[dict[str, Any]]) -> tuple[dict[str, Any], list[InspectMessage]]:
    messages: list[InspectMessage] = []
    if not chunks:
        return {}, []
    depths = [len(chunk.get("heading_path") or []) for chunk in chunks]
    empty = sum(1 for depth in depths if depth == 0)
    shallow = sum(1 for depth in depths if depth <= 1)
    path_counter = Counter(" > ".join(chunk.get("heading_path") or []) for chunk in chunks)
    most_common_path, most_common_count = path_counter.most_common(1)[0]
    body_augmented = sum(
        1
        for chunk in chunks
        for item in chunk.get("toc_path") or []
        if isinstance(item, dict) and str(item.get("toc_id", "")).startswith("body:")
    )
    stats = {
        "empty_heading_path_count": empty,
        "shallow_heading_path_count": shallow,
        "average_depth": round(mean(depths), 2),
        "max_depth": max(depths),
        "most_common_path": most_common_path,
        "most_common_path_count": most_common_count,
        "body_heading_chunk_count": body_augmented,
    }
    if empty:
        messages.append(InspectMessage("WARN", "存在 heading_path 为空的 chunk。", {"count": empty}))
    if shallow / len(chunks) > 0.65 and len(chunks) >= 20:
        messages.append(
            InspectMessage(
                "WARN",
                "多数 chunk 的标题路径较浅，可能需要正文短标题增强或更合适的 profile。",
                {"shallow_ratio": round(shallow / len(chunks), 3)},
            )
        )
    if most_common_count / len(chunks) > 0.35 and len(chunks) >= 20:
        messages.append(
            InspectMessage(
                "WARN",
                "大量 chunk 集中在同一个标题路径下，可能说明目录层级偏粗。",
                {"path": most_common_path, "ratio": round(most_common_count / len(chunks), 3)},
            )
        )
    if not any(msg.status == "WARN" and "标题" in msg.message for msg in messages):
        messages.append(InspectMessage("PASS", "heading_path 分布正常。", stats))
    return stats, messages


def check_garbled_text(toc: dict[str, Any], chunks: list[dict[str, Any]]) -> tuple[dict[str, Any], list[InspectMessage]]:
    messages: list[InspectMessage] = []
    toc_titles = [str(item.get("title") or "") for item in toc.get("items", []) if isinstance(item, dict)]
    heading_titles = [
        str(title)
        for chunk in chunks
        for title in (chunk.get("heading_path") or [])
    ]
    sample_texts = [str(chunk.get("text") or "")[:600] for chunk in chunks[:80]]

    garbled_toc = [title for title in toc_titles if looks_garbled(title)]
    garbled_heading = [title for title in heading_titles if looks_garbled(title)]
    garbled_chunk_count = sum(1 for text in sample_texts if garbled_ratio(text) > 0.04)
    stats = {
        "garbled_toc_title_count": len(garbled_toc),
        "garbled_heading_title_count": len(garbled_heading),
        "garbled_sample_chunk_count": garbled_chunk_count,
        "garbled_toc_examples": garbled_toc[:5],
        "garbled_heading_examples": garbled_heading[:5],
    }
    if garbled_toc or garbled_heading:
        messages.append(InspectMessage("WARN", "目录或 heading_path 中仍存在疑似乱码标题。", stats))
    if garbled_chunk_count:
        messages.append(
            InspectMessage(
                "WARN",
                "部分 chunk 正文存在疑似乱码字符，建议抽查 PDF 文本复制质量。",
                {"sample_chunk_count": garbled_chunk_count},
            )
        )
    if not garbled_toc and not garbled_heading and not garbled_chunk_count:
        messages.append(InspectMessage("PASS", "未发现明显目录或正文乱码。", stats))
    return stats, messages


def check_pdf_coverage(pages: list[Any], chunks: list[dict[str, Any]]) -> tuple[dict[str, Any], list[InspectMessage]]:
    messages: list[InspectMessage] = []
    pdf_text = compact_text("\n".join(page.text for page in pages))
    chunk_text = compact_text("\n".join(str(chunk.get("text") or "") for chunk in chunks))
    if not pdf_text or not chunk_text:
        return {"pdf_chars": len(pdf_text), "chunk_chars": len(chunk_text)}, [
            InspectMessage("FAIL", "PDF 或 chunk 文本为空，无法估计覆盖率。")
        ]
    char_ratio = min(1.0, len(chunk_text) / len(pdf_text))
    pdf_sample_rate = sample_match_rate(pdf_text, chunk_text, window=80, max_samples=120)
    chunk_sample_rate = sample_match_rate(chunk_text, pdf_text, window=80, max_samples=120)
    coverage = round((char_ratio * 0.35) + (pdf_sample_rate * 0.35) + (chunk_sample_rate * 0.30), 3)
    stats = {
        "pdf_chars_compact": len(pdf_text),
        "chunk_chars_compact": len(chunk_text),
        "chunk_to_pdf_char_ratio": round(char_ratio, 3),
        "pdf_sample_match_rate": pdf_sample_rate,
        "chunk_sample_match_rate": chunk_sample_rate,
        "estimated_coverage": coverage,
    }
    if coverage < 0.45 or chunk_sample_rate < 0.55:
        messages.append(InspectMessage("FAIL", "chunk 文本与 PDF 文本覆盖关系异常，可能解析错书或漏内容严重。", stats))
    elif coverage < 0.65:
        messages.append(InspectMessage("WARN", "PDF 文本覆盖率估计偏低，建议抽查是否漏掉前言、附录或章节。", stats))
    else:
        messages.append(InspectMessage("PASS", "PDF 文本覆盖率估计正常。", stats))
    return stats, messages


def build_local_recommendations(
    pdf_path: Path,
    pages: list[Any],
    manifest: dict[str, Any],
    toc: dict[str, Any],
    chunks: list[dict[str, Any]],
    length_stats: dict[str, Any],
    heading_stats: dict[str, Any],
) -> dict[str, Any]:
    profile_rec = recommend_profile(pdf_path, manifest)
    heading_level_rec = recommend_heading_level(manifest, toc, chunks, length_stats)
    body_heading_rec = recommend_body_heading_augmentation(pages, manifest, toc, chunks, length_stats, heading_stats)
    return {
        "profile": profile_rec,
        "max_chunk_heading_level": heading_level_rec,
        "body_heading_augmentation": body_heading_rec,
    }


def recommend_profile(pdf_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    current = (manifest.get("chunking") or {}).get("profile")
    try:
        recommended, scores, signals = classify_pdf(pdf_path)
    except Exception as exc:
        return {
            "current": current,
            "recommended": current,
            "confidence": "unknown",
            "action": "keep",
            "reason": f"无法重新分类 PDF：{exc}",
        }
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    top_score = ordered[0][1] if ordered else 0
    second_score = ordered[1][1] if len(ordered) > 1 else 0
    gap = top_score - second_score
    confidence = "high" if top_score >= 6 and gap >= 4 else "medium" if top_score >= 4 and gap >= 2 else "low"
    action = "keep" if recommended == current or confidence == "low" else "consider_change"
    effective_recommended = current if confidence == "low" else recommended
    return {
        "current": current,
        "recommended": effective_recommended,
        "confidence": confidence,
        "action": action,
        "classifier_top": recommended,
        "scores": format_classification_scores(scores),
        "signals": format_classification_signals(recommended, scores, signals),
        "reason": (
            "离线分类信号较弱，建议保持当前 profile。"
            if confidence == "low"
            else "当前 profile 与离线分类推荐一致。"
            if recommended == current
            else f"离线分类器更倾向 {recommended}，建议确认是否应改用 --profile {recommended}。"
        ),
    }


def recommend_heading_level(
    manifest: dict[str, Any],
    toc: dict[str, Any],
    chunks: list[dict[str, Any]],
    length_stats: dict[str, Any],
) -> dict[str, Any]:
    current = (manifest.get("chunking") or {}).get("max_chunk_heading_level")
    profile = (manifest.get("chunking") or {}).get("profile")
    toc_levels = [int(item.get("level") or 0) for item in toc.get("items", []) if isinstance(item, dict)]
    max_toc_level = max(toc_levels) if toc_levels else None
    level_counts = dict(sorted(Counter(toc_levels).items()))
    buckets = (length_stats or {}).get("buckets") or {}
    long_count = buckets.get("long_section_split_to_very_long", 0) + buckets.get("very_long", 0)
    short_count = buckets.get("very_short_lt_100", 0) + buckets.get("short_100_300", 0)
    total = max(1, len(chunks))
    current_num = current if isinstance(current, int) else None

    if profile in {"fiction", "reference"}:
        return {
            "current": current,
            "recommended": current,
            "action": "keep",
            "confidence": "medium",
            "reason": f"{profile} 类资料通常不需要追求很深的标题层级。",
            "toc_level_counts": level_counts,
        }
    if max_toc_level and current_num and max_toc_level > current_num and long_count / total > 0.18:
        recommended = min(max_toc_level, current_num + 1)
        return {
            "current": current,
            "recommended": recommended,
            "action": "consider_increase",
            "confidence": "medium",
            "reason": f"存在较多长 chunk，且 TOC 还有更深层级，可尝试 --max-chunk-heading-level {recommended}。",
            "toc_level_counts": level_counts,
        }
    if current_num and short_count / total > 0.35:
        recommended = max(1, current_num - 1)
        return {
            "current": current,
            "recommended": recommended,
            "action": "consider_decrease",
            "confidence": "low",
            "reason": f"短 chunk 比例偏高，可人工评估是否降低到 --max-chunk-heading-level {recommended}。",
            "toc_level_counts": level_counts,
        }
    return {
        "current": current,
        "recommended": current,
        "action": "keep",
        "confidence": "medium",
        "reason": "当前最细分块层级与 chunk 长度分布基本匹配。",
        "toc_level_counts": level_counts,
    }


def recommend_body_heading_augmentation(
    pages: list[Any],
    manifest: dict[str, Any],
    toc: dict[str, Any],
    chunks: list[dict[str, Any]],
    length_stats: dict[str, Any],
    heading_stats: dict[str, Any],
) -> dict[str, Any]:
    toc_source = (manifest.get("toc") or {}).get("source") or toc.get("source") or ""
    enabled = "body_heading_augmentation" in toc_source
    profile = (manifest.get("chunking") or {}).get("profile")
    candidate_count = count_body_heading_candidates(pages, profile=profile or "social_science")
    buckets = (length_stats or {}).get("buckets") or {}
    total = max(1, len(chunks))
    long_ratio = (buckets.get("long_section_split_to_very_long", 0) + buckets.get("very_long", 0)) / total
    shallow_ratio = (heading_stats.get("shallow_heading_path_count", 0) / total) if heading_stats else 0
    body_heading_chunks = heading_stats.get("body_heading_chunk_count", 0) if heading_stats else 0

    if enabled:
        return {
            "current": "enabled",
            "recommended": "enabled",
            "action": "keep",
            "confidence": "high" if body_heading_chunks else "medium",
            "candidate_count": candidate_count,
            "reason": "当前 RAGPack 已使用正文短标题增强，适合书签较浅但正文标题清晰的书。",
        }
    if profile in {"reference", "fiction", "legal"}:
        return {
            "current": "disabled",
            "recommended": "disabled",
            "action": "keep",
            "confidence": "medium",
            "candidate_count": candidate_count,
            "reason": f"{profile} 类资料通常不优先使用正文短标题增强。",
        }
    if candidate_count >= 12 and (long_ratio > 0.12 or shallow_ratio > 0.45):
        return {
            "current": "disabled",
            "recommended": "enabled",
            "action": "consider_enable",
            "confidence": "medium",
            "candidate_count": candidate_count,
            "reason": "PDF 书签可能偏浅，正文中检测到较多短标题候选；如 chunk 仍偏长，可考虑启用/加强正文短标题增强。",
        }
    return {
        "current": "disabled",
        "recommended": "disabled",
        "action": "keep",
        "confidence": "medium",
        "candidate_count": candidate_count,
        "reason": "未发现足够强的正文短标题增强需求。",
    }


def count_body_heading_candidates(pages: list[Any], profile: str = "social_science") -> int:
    count = 0
    for page in pages:
        for line in page.text.splitlines():
            if is_body_short_heading(line.strip(), profile=profile):
                count += 1
    return count


def build_pdf_comparison_samples(pages: list[Any], chunks: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    selected = select_sample_chunks(chunks, limit=limit)
    samples: list[dict[str, Any]] = []
    for chunk in selected:
        source = chunk.get("source") or {}
        page_start = source.get("pdf_page_start")
        page_end = source.get("pdf_page_end") or page_start
        pdf_text = pages_text_range(pages, page_start, page_end)
        chunk_text = str(chunk.get("text") or "")
        samples.append(
            {
                "chunk_index": chunk.get("chunk_index"),
                "chunk_id": chunk.get("chunk_id"),
                "heading_path": " > ".join(chunk.get("heading_path") or []),
                "page_start": page_start,
                "page_end": page_end,
                "char_count": len(chunk_text),
                "match_rate": sample_match_rate(compact_text(chunk_text), compact_text(pdf_text), window=40, max_samples=30),
                "chunk_preview": preview_text(chunk_text, 500),
                "pdf_preview": best_pdf_preview_for_chunk(pdf_text, chunk_text, 500),
            }
        )
    return samples


def select_sample_chunks(chunks: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    if not chunks:
        return []
    candidates = [
        chunks[0],
        chunks[len(chunks) // 2],
        chunks[-1],
        max(chunks, key=lambda chunk: len(str(chunk.get("text") or ""))),
        min(chunks, key=lambda chunk: len(str(chunk.get("text") or ""))),
    ]
    seen = set()
    out = []
    for chunk in candidates:
        chunk_id = chunk.get("chunk_id")
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        out.append(chunk)
        if len(out) >= limit:
            break
    return out


def pages_text_range(pages: list[Any], page_start: Any, page_end: Any) -> str:
    try:
        start = int(page_start)
        end = int(page_end)
    except (TypeError, ValueError):
        return ""
    selected = [page.text for page in pages if start <= int(page.page_index) <= end]
    return "\n\n".join(selected)


def best_pdf_preview_for_chunk(pdf_text: str, chunk_text: str, max_chars: int) -> str:
    if not pdf_text:
        return ""
    compact_chunk = compact_text(chunk_text)
    compact_pdf = compact_text(pdf_text)
    if compact_chunk:
        probe = compact_chunk[: min(40, len(compact_chunk))]
        pos = compact_pdf.find(probe)
        if pos >= 0:
            raw_pos = max(0, min(len(pdf_text), pos))
            return preview_text(pdf_text[raw_pos:], max_chars)
    return preview_text(pdf_text, max_chars)


def preview_text(text: str, max_chars: int = 500) -> str:
    text = normalize_text(text)
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def looks_garbled(text: str) -> bool:
    if not text.strip():
        return False
    if is_garbled_title(text):
        return True
    return garbled_ratio(text) > 0.12


def garbled_ratio(text: str) -> float:
    meaningful = [ch for ch in text if not ch.isspace()]
    if not meaningful:
        return 0.0
    suspicious = [ch for ch in meaningful if ch in "�□■◆◇�" or ord(ch) < 32]
    suspicious.extend(ch for ch in meaningful if "\ue000" <= ch <= "\uf8ff")
    weird_pairs = len(re.findall(r"[A-Za-z][\u4e00-\u9fff][A-Za-z]|[\u4e00-\u9fff][A-Za-z]{2,}[\u4e00-\u9fff]", text))
    return min(1.0, (len(suspicious) + weird_pairs) / max(1, len(meaningful)))


def compact_text(text: str) -> str:
    text = normalize_text(text)
    return re.sub(r"\s+", "", text)


def sample_match_rate(source: str, target: str, window: int = 80, max_samples: int = 120) -> float:
    if not source or not target:
        return 0.0
    if len(source) <= window:
        return 1.0 if source in target else 0.0
    step = max(window, len(source) // max_samples)
    samples = []
    for start in range(0, max(1, len(source) - window + 1), step):
        sample = source[start : start + window]
        if len(sample) >= window:
            samples.append(sample)
    if not samples:
        return 0.0
    matched = sum(1 for sample in samples if sample in target)
    return round(matched / len(samples), 3)


def score_messages(messages: list[InspectMessage]) -> int:
    score = 100
    for message in messages:
        if message.status == "FAIL":
            score -= 35
        elif message.status == "WARN":
            score -= 8
    return max(0, min(100, score))


def result_from_score_and_messages(score: int, messages: list[InspectMessage]) -> str:
    if any(message.status == "FAIL" for message in messages):
        return "FAIL"
    if score < 75 or any(message.status == "WARN" for message in messages):
        return "WARN"
    return "PASS"


def make_recommendation(result: str, messages: list[InspectMessage], manifest: dict[str, Any]) -> str:
    title = manifest.get("title") or "这本书"
    if result == "PASS":
        return f"{title} 的 no-embedding 自检通过，可以继续生成 embedding。"
    if result == "WARN":
        return f"{title} 基本可用，但建议先抽查 warnings 中提到的 chunk 或标题路径，再决定是否生成 embedding。"
    fail_reasons = [message.message for message in messages if message.status == "FAIL"]
    return f"{title} 不建议继续生成 embedding。请先处理失败项：{'；'.join(fail_reasons[:3])}"


def format_inspection_report(report: dict[str, Any]) -> str:
    lines = [
        f"{report['result']}: {report.get('title') or Path(report['ragpack']).name}",
        "",
        f"score: {report['score']}/100",
        "",
        "summary:",
    ]
    for key, value in report["summary"].items():
        lines.append(f"  {key}: {value}")
    lines.extend(["", "stats:"])
    length = report["stats"].get("length") or {}
    if length:
        lines.append(
            "  length: "
            f"min={length.get('min')}, median={length.get('median')}, "
            f"avg={length.get('average')}, max={length.get('max')}"
        )
    coverage = report["stats"].get("coverage") or {}
    if coverage:
        lines.append(
            "  coverage: "
            f"estimated={coverage.get('estimated_coverage')}, "
            f"pdf_sample={coverage.get('pdf_sample_match_rate')}, "
            f"chunk_sample={coverage.get('chunk_sample_match_rate')}"
        )
    recommendations = report.get("recommendations") or {}
    if recommendations:
        lines.extend(["", "local recommendations:"])
        profile = recommendations.get("profile") or {}
        level = recommendations.get("max_chunk_heading_level") or {}
        body = recommendations.get("body_heading_augmentation") or {}
        lines.append(
            f"  profile: {profile.get('current')} -> {profile.get('recommended')} "
            f"({profile.get('action')}, {profile.get('confidence')})"
        )
        lines.append(
            f"  max_chunk_heading_level: {level.get('current')} -> {level.get('recommended')} "
            f"({level.get('action')}, {level.get('confidence')})"
        )
        lines.append(
            f"  body_heading_augmentation: {body.get('current')} -> {body.get('recommended')} "
            f"({body.get('action')}, {body.get('confidence')})"
        )
    lines.extend(["", "checks:"])
    for check in report["checks"]:
        lines.append(f"  [{check['status']}] {check['message']}")
    lines.extend(["", "recommendation:", f"  {report['recommendation']}"])
    if report.get("report_path"):
        lines.extend(["", f"report: {report['report_path']}"])
    if report.get("html_report_path"):
        lines.append(f"html_report: {report['html_report_path']}")
    return "\n".join(lines)


def render_html_report(report: dict[str, Any]) -> str:
    title = escape(str(report.get("title") or Path(report.get("ragpack", "RAGPack")).name))
    checks = "\n".join(
        "<tr>"
        f"<td class='{escape(str(check.get('status', '')).lower())}'>{escape(str(check.get('status')))}</td>"
        f"<td>{escape(str(check.get('message')))}</td>"
        f"<td><code>{escape(json.dumps(check.get('detail') or {}, ensure_ascii=False))}</code></td>"
        "</tr>"
        for check in report.get("checks", [])
    )
    rec_cards = render_recommendation_cards(report.get("recommendations") or {})
    sample_cards = "\n".join(render_sample_card(sample) for sample in report.get("samples", []))
    summary_items = "\n".join(
        f"<li><strong>{escape(str(key))}</strong>: {escape(str(value))}</li>"
        for key, value in (report.get("summary") or {}).items()
    )
    stats_json = escape(json.dumps(report.get("stats") or {}, ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{title} RAGPack 自检报告</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #202124; }}
    h1, h2 {{ margin-top: 28px; }}
    .badge {{ display: inline-block; padding: 4px 10px; border-radius: 6px; font-weight: 700; }}
    .pass {{ color: #137333; background: #e6f4ea; }}
    .warn {{ color: #b06000; background: #fef7e0; }}
    .fail {{ color: #a50e0e; background: #fce8e6; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }}
    .card {{ border: 1px solid #dadce0; border-radius: 8px; padding: 14px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #dadce0; padding: 8px; vertical-align: top; }}
    th {{ background: #f8fafd; text-align: left; }}
    pre {{ white-space: pre-wrap; word-break: break-word; background: #f8fafd; padding: 12px; border-radius: 6px; }}
    code {{ white-space: pre-wrap; word-break: break-word; }}
  </style>
</head>
<body>
  <h1>{title}</h1>
  <p><span class="badge {escape(str(report.get('result', '')).lower())}">{escape(str(report.get('result')))}</span>
  score: {escape(str(report.get('score')))} / 100</p>
  <p>{escape(str(report.get('recommendation') or ''))}</p>
  <h2>摘要</h2>
  <ul>{summary_items}</ul>
  <h2>本地建议</h2>
  <div class="grid">{rec_cards}</div>
  <h2>统计</h2>
  <pre>{stats_json}</pre>
  <h2>检查项</h2>
  <table><thead><tr><th>状态</th><th>说明</th><th>详情</th></tr></thead><tbody>{checks}</tbody></table>
  <h2>PDF 抽样对照</h2>
  {sample_cards}
</body>
</html>
"""


def render_recommendation_cards(recommendations: dict[str, Any]) -> str:
    cards = []
    labels = {
        "profile": "Profile 推荐",
        "max_chunk_heading_level": "标题层级推荐",
        "body_heading_augmentation": "正文短标题增强",
    }
    for key, label in labels.items():
        item = recommendations.get(key) or {}
        cards.append(
            "<div class='card'>"
            f"<h3>{escape(label)}</h3>"
            f"<p><strong>当前</strong>: {escape(str(item.get('current')))}</p>"
            f"<p><strong>建议</strong>: {escape(str(item.get('recommended')))}</p>"
            f"<p><strong>动作</strong>: {escape(str(item.get('action')))} / {escape(str(item.get('confidence')))}</p>"
            f"<p>{escape(str(item.get('reason') or ''))}</p>"
            "</div>"
        )
    return "\n".join(cards)


def render_sample_card(sample: dict[str, Any]) -> str:
    return (
        "<div class='card'>"
        f"<h3>chunk #{escape(str(sample.get('chunk_index')))} "
        f"pages {escape(str(sample.get('page_start')))}-{escape(str(sample.get('page_end')))}</h3>"
        f"<p><strong>章节路径</strong>: {escape(str(sample.get('heading_path') or ''))}</p>"
        f"<p><strong>字符数</strong>: {escape(str(sample.get('char_count')))}；"
        f"<strong>匹配率</strong>: {escape(str(sample.get('match_rate')))}</p>"
        "<div class='grid'>"
        f"<div><h4>Chunk</h4><pre>{escape(str(sample.get('chunk_preview') or ''))}</pre></div>"
        f"<div><h4>PDF</h4><pre>{escape(str(sample.get('pdf_preview') or ''))}</pre></div>"
        "</div></div>"
    )
