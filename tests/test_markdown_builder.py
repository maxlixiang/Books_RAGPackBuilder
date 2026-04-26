import json
import shutil
from pathlib import Path

from ragpack_builder.markdown_builder import build_markdown_packs, collect_markdown_jobs


def clean_workspace_tmp(name: str) -> Path:
    root = Path("output") / "__tmp_tests" / name
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    return root


def test_collect_markdown_jobs_by_profile():
    tmp = clean_workspace_tmp("collect_jobs")
    try:
        root = tmp / "markdown_files"
        (root / "journal").mkdir(parents=True)
        (root / "TechNotes" / "RAG技术学习").mkdir(parents=True)
        (root / "WebPageCollection").mkdir(parents=True)
        (root / "journal" / "2026-04-25.md").write_text("# 今日\n内容", encoding="utf-8")
        (root / "journal" / "2026-04-26.md").write_text("# 今日\n内容", encoding="utf-8")
        (root / "TechNotes" / "RAG技术学习" / "Chunking.md").write_text("# 分块\n内容", encoding="utf-8")
        (root / "WebPageCollection" / "Milvus HNSW.md").write_text("# HNSW\n内容", encoding="utf-8")

        jobs = collect_markdown_jobs(root)

        assert [(job.profile, job.output_stem, len(job.files)) for job in jobs] == [
            ("journal", "journal_2026-04", 2),
            ("tech_notes", "RAG技术学习", 1),
            ("web_page_collection", "Milvus HNSW", 1),
        ]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_build_markdown_packs_no_embedding_outputs_schema():
    tmp = clean_workspace_tmp("build_packs")
    try:
        root = tmp / "markdown_files"
        output = tmp / "markdown_output"
        (root / "journal").mkdir(parents=True)
        (root / "TechNotes" / "RAG技术学习").mkdir(parents=True)
        (root / "WebPageCollection").mkdir(parents=True)
        (root / "journal" / "2026-04-25.md").write_text("# 今日\n内容\n\n## 想法\n更多内容", encoding="utf-8")
        (root / "TechNotes" / "RAG技术学习" / "Chunking.md").write_text("# 分块\n技术内容", encoding="utf-8")
        (root / "WebPageCollection" / "Milvus HNSW.md").write_text("# HNSW\n网页内容", encoding="utf-8")

        paths = build_markdown_packs(root, output, no_embedding=True)

        assert [path.name for path in paths] == [
            "journal_2026-04_noembedding.rag.jsonl",
            "RAG技术学习_noembedding.rag.jsonl",
            "Milvus HNSW_noembedding.rag.jsonl",
        ]
        records = [json.loads(line) for line in paths[0].read_text(encoding="utf-8").splitlines()]
        manifest = records[0]
        chunks = [record for record in records if record["record_type"] == "chunk"]
        assert manifest["source"]["source_type"] == "markdown"
        assert manifest["chunking"]["profile"] == "journal"
        assert chunks
        assert chunks[0]["embedding"] == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_markdown_parent_intro_is_preserved():
    tmp = clean_workspace_tmp("parent_intro")
    try:
        root = tmp / "markdown_files"
        output = tmp / "markdown_output"
        (root / "journal").mkdir(parents=True)
        (root / "TechNotes" / "RAG技术学习").mkdir(parents=True)
        (root / "WebPageCollection").mkdir(parents=True)
        note = root / "TechNotes" / "RAG技术学习" / "Chunking.md"
        note.write_text("# 分块\n父标题下的引言。\n\n## 子标题\n子标题正文。", encoding="utf-8")

        path = build_markdown_packs(root, output, no_embedding=True)[0]
        chunks = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if json.loads(line)["record_type"] == "chunk"
        ]

        assert any("父标题下的引言" in chunk["text"] for chunk in chunks)
        assert any("子标题正文" in chunk["text"] for chunk in chunks)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_markdown_source_date_metadata_is_written_to_chunks():
    tmp = clean_workspace_tmp("date_metadata")
    try:
        root = tmp / "markdown_files"
        output = tmp / "markdown_output"
        (root / "journal").mkdir(parents=True)
        (root / "TechNotes").mkdir(parents=True)
        (root / "WebPageCollection").mkdir(parents=True)
        (root / "journal" / "2026-04-10.md").write_text("# Day\nJournal content.", encoding="utf-8")
        (root / "WebPageCollection" / "Saved Page.md").write_text(
            "---\ncreated: 2026-04-10\nsource_url: https://example.com\n---\n# Page\nSaved content.",
            encoding="utf-8",
        )

        paths = build_markdown_packs(root, output, no_embedding=True)
        journal_path = next(path for path in paths if path.name.startswith("journal_2026-04"))
        web_path = next(path for path in paths if path.name.startswith("Saved Page"))
        journal_records = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]
        web_records = [json.loads(line) for line in web_path.read_text(encoding="utf-8").splitlines()]
        journal_chunk = next(record for record in journal_records if record["record_type"] == "chunk")
        web_manifest = web_records[0]
        web_chunk = next(record for record in web_records if record["record_type"] == "chunk")

        assert journal_chunk["source"]["logical_date"] == "2026-04-10"
        assert journal_chunk["source"]["logical_month"] == "2026-04"
        assert journal_chunk["source"]["markdown_profile"] == "journal"
        assert journal_chunk["source"]["file_created_at"]
        assert journal_chunk["source"]["file_modified_at"]
        assert web_manifest["source"]["files"][0]["logical_date"] == "2026-04-10"
        assert web_chunk["source"]["front_matter_date"] == "2026-04-10"
        assert web_chunk["source"]["markdown_profile"] == "web_page_collection"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
