from pathlib import Path

from ragpack_builder.inspector import (
    build_pdf_comparison_samples,
    check_chunk_lengths,
    check_file_match,
    check_garbled_text,
    check_heading_paths,
    check_profile,
    check_schema,
    format_inspection_report,
    recommend_heading_level,
    render_html_report,
    result_from_score_and_messages,
    score_messages,
)
from ragpack_builder.models import PageText
from ragpack_builder.utils import sha256_file


def sample_manifest(source: Path | None = None):
    source_hash = sha256_file(source) if source else "sha256:test"
    return {
        "record_type": "manifest",
        "schema_version": "1.0",
        "document_id": source_hash,
        "title": "样书",
        "source": {"file_name": source.name if source else "样书.pdf", "source_sha256": source_hash},
        "toc": {"source": "pdf_outline", "item_count": 2},
        "chunking": {
            "profile": "social_science",
            "target_chars": 800,
            "max_chars": 1200,
            "section_split_chars": 2000,
            "min_chunk_chars": 220,
            "overlap_chars": 100,
        },
        "embedding": {"provider": "none", "dimension": 0},
    }


def sample_toc():
    return {
        "record_type": "toc",
        "items": [
            {"toc_id": "toc:000001", "title": "第一章", "level": 1},
            {"toc_id": "toc:000002", "title": "主题一", "level": 2},
        ],
    }


def sample_chunks(count=4):
    return [
        {
            "record_type": "chunk",
            "document_id": "sha256:test",
            "chunk_id": f"sha256:test:chunk:{idx:06d}",
            "chunk_index": idx,
            "text": "这是一个围绕同一主题展开的自然小节。" * 40,
            "embedding_text": "书名：样书\n章节路径：第一章 > 主题一\n\n正文",
            "heading_path": ["第一章", "主题一"],
            "toc_path": [
                {"toc_id": "toc:000001", "level": 1, "title": "第一章"},
                {"toc_id": "toc:000002", "level": 2, "title": "主题一"},
            ],
            "source": {"pdf_page_start": 1, "pdf_page_end": 2},
            "prev_chunk_id": None if idx == 1 else f"sha256:test:chunk:{idx - 1:06d}",
            "next_chunk_id": None if idx == count else f"sha256:test:chunk:{idx + 1:06d}",
            "stats": {"char_count": 640, "embedding_char_count": 680},
            "split_info": {"reason": "natural_section_within_split_threshold"},
            "embedding": [],
        }
        for idx in range(1, count + 1)
    ]


def test_inspector_schema_and_profile_pass():
    manifest = sample_manifest()
    chunks = sample_chunks()

    messages = []
    messages.extend(check_schema(manifest, sample_toc(), chunks))
    messages.extend(check_profile(manifest))

    assert all(message.status == "PASS" for message in messages)


def test_file_match_detects_wrong_pdf():
    tmp = Path("output") / "__tmp_tests" / "inspector"
    tmp.mkdir(parents=True, exist_ok=True)
    pdf = tmp / "a.pdf"
    pdf.write_text("fake pdf", encoding="utf-8")
    manifest = sample_manifest()

    messages = check_file_match(pdf, manifest)

    assert any(message.status == "FAIL" for message in messages)


def test_length_and_heading_checks_warn_on_poor_chunking():
    manifest = sample_manifest()
    chunks = sample_chunks(30)
    for chunk in chunks:
        chunk["text"] = "短"
        chunk["heading_path"] = ["第一章"]

    _, length_messages = check_chunk_lengths(manifest, chunks)
    _, heading_messages = check_heading_paths(chunks)

    assert any(message.status == "WARN" for message in length_messages)
    assert any(message.status == "WARN" for message in heading_messages)


def test_garbled_check_warns_for_bad_titles():
    toc = {"record_type": "toc", "items": [{"title": "第二匝□N§m?", "level": 1}]}

    _, messages = check_garbled_text(toc, sample_chunks())

    assert any(message.status == "WARN" for message in messages)


def test_report_result_and_formatting():
    messages = check_schema(sample_manifest(), sample_toc(), sample_chunks())
    score = score_messages(messages)
    result = result_from_score_and_messages(score, messages)
    report = {
        "result": result,
        "score": score,
        "title": "样书",
        "ragpack": "样书_noembedding.rag.jsonl",
        "summary": {"chunks": 4, "toc_items": 2, "profile": "social_science"},
        "stats": {"length": {"min": 100, "median": 200, "average": 180, "max": 300}, "coverage": {}},
        "recommendations": {
            "profile": {"current": "social_science", "recommended": "social_science", "action": "keep", "confidence": "medium"},
            "max_chunk_heading_level": {"current": None, "recommended": None, "action": "keep", "confidence": "medium"},
            "body_heading_augmentation": {"current": "disabled", "recommended": "disabled", "action": "keep", "confidence": "medium"},
        },
        "samples": [],
        "checks": [{"status": item.status, "message": item.message} for item in messages],
        "recommendation": "可以继续生成 embedding。",
    }

    text = format_inspection_report(report)

    assert result == "PASS"
    assert "PASS: 样书" in text
    assert "local recommendations:" in text
    assert "recommendation:" in text


def test_recommend_heading_level_can_suggest_increase():
    manifest = sample_manifest()
    manifest["chunking"]["max_chunk_heading_level"] = 4
    toc = {
        "record_type": "toc",
        "items": [
            {"level": 1},
            {"level": 2},
            {"level": 3},
            {"level": 4},
            {"level": 5},
        ],
    }
    chunks = sample_chunks(10)
    length_stats = {
        "buckets": {
            "very_short_lt_100": 0,
            "short_100_300": 0,
            "long_section_split_to_very_long": 3,
            "very_long": 0,
        }
    }

    rec = recommend_heading_level(manifest, toc, chunks, length_stats)

    assert rec["action"] == "consider_increase"
    assert rec["recommended"] == 5


def test_pdf_comparison_samples_and_html_render():
    chunks = sample_chunks(3)
    pages = [PageText(1, chunks[0]["text"] + "\n其他 PDF 文本")]

    samples = build_pdf_comparison_samples(pages, chunks, limit=2)
    html = render_html_report(
        {
            "result": "PASS",
            "score": 100,
            "title": "样书",
            "summary": {"chunks": 3},
            "stats": {},
            "recommendations": {},
            "checks": [],
            "samples": samples,
            "recommendation": "可以继续生成 embedding。",
        }
    )

    assert samples
    assert samples[0]["match_rate"] > 0
    assert "<html" in html
    assert "PDF 抽样对照" in html
