from __future__ import annotations

import argparse
from pathlib import Path

from .chunking import make_chunks
from .classifier import classify_raw_entries, format_classification_scores, format_classification_signals
from .embeddings import NullEmbedder, SentenceTransformerEmbedder
from .extractors import ImageOnlyPdfError, UnsupportedSourceError, extract_document
from .profiles import DEFAULT_MODEL, PROFILE_DEFAULTS
from .toc import build_sections, infer_txt_toc, locate_toc_items
from .utils import now_iso, safe_stem, sha256_file
from .writer import build_embedding_text, make_chunk_records, toc_record, write_jsonl


def build_pack(args: argparse.Namespace) -> Path:
    apply_profile_defaults(args)
    source_path = Path(args.source).resolve()
    output_dir = Path(args.output).resolve()
    pages, toc_items, source_type = extract_document(source_path)

    if not toc_items:
        toc_items = infer_txt_toc(pages, profile=args.profile)
        toc_source = "txt_heading_rules" if toc_items else "synthetic"
    else:
        locate_toc_items(pages, toc_items, args.search_before_pages, args.search_after_pages)
        toc_source = "pdf_outline"

    sections = build_sections(pages, toc_items, max_chunk_heading_level=args.max_chunk_heading_level)
    chunks = make_chunks(
        sections,
        target_chars=args.target_chars,
        max_chars=args.max_chars,
        min_chunk_chars=args.min_chunk_chars,
        overlap_chars=args.overlap_chars,
    )

    if args.no_embedding:
        embedder = NullEmbedder()
    else:
        embedder = SentenceTransformerEmbedder(args.embedding_model, normalize=True, batch_size=args.batch_size)

    title = args.title or safe_stem(source_path)
    document_id = sha256_file(source_path)
    embedding_texts = [build_embedding_text(title, chunk) for chunk in chunks]
    embeddings = embedder.encode(embedding_texts)

    manifest = {
        "record_type": "manifest",
        "schema_version": "1.0",
        "document_id": document_id,
        "title": title,
        "created_at": now_iso(),
        "source": {
            "file_name": source_path.name,
            "source_type": source_type,
            "source_sha256": document_id,
        },
        "language": "zh",
        "parser": {
            "name": "pymupdf" if source_type == "pdf" else "plain_text",
            "preserve_layout": False,
        },
        "toc": {
            "source": toc_source,
            "item_count": len(toc_items),
        },
        "chunking": {
            "strategy": "hierarchical_semantic",
            "profile": args.profile,
            "target_chars": args.target_chars,
            "max_chars": args.max_chars,
            "overlap_chars": args.overlap_chars,
            "min_chunk_chars": args.min_chunk_chars,
            "max_chunk_heading_level": args.max_chunk_heading_level,
            "heading_detection": PROFILE_DEFAULTS[args.profile]["heading_detection"],
            "search_before_pages": args.search_before_pages,
            "search_after_pages": args.search_after_pages,
            "title_match_min_confidence": 0.82,
        },
        "embedding": {
            "provider": "local" if not args.no_embedding else "none",
            "model": embedder.model_name,
            "dimension": embedder.dimension,
            "normalize": embedder.normalize,
        },
    }

    records = make_chunk_records(document_id, title, chunks, embeddings)
    suffix = "_noembedding.rag.jsonl" if args.no_embedding else ".rag.jsonl"
    out_path = output_dir / f"{safe_stem(source_path)}{suffix}"
    write_jsonl(out_path, manifest, toc_record(document_id, toc_items, toc_source), records)
    return out_path


def apply_profile_defaults(args: argparse.Namespace) -> None:
    defaults = PROFILE_DEFAULTS[args.profile]
    for name in ("target_chars", "max_chars", "min_chunk_chars", "overlap_chars", "max_chunk_heading_level"):
        if getattr(args, name) is None:
            setattr(args, name, defaults[name])


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ragpack", description="Build one-file JSONL RAG packs.")
    sub = parser.add_subparsers(dest="command")

    build = sub.add_parser("build", help="Build a .rag.jsonl file from a PDF or TXT book.")
    build.add_argument("source", help="Input .pdf or .txt file.")
    build.add_argument("-o", "--output", default="output", help="Output directory.")
    build.add_argument("--title", default=None, help="Override document title.")
    build.add_argument(
        "--profile",
        choices=sorted(PROFILE_DEFAULTS),
        default="social_science",
        help="Chunking and heading-detection profile.",
    )
    build.add_argument("--embedding-model", default=DEFAULT_MODEL, help="SentenceTransformer model name.")
    build.add_argument("--batch-size", type=int, default=16)
    build.add_argument("--no-embedding", action="store_true", help="Write empty embedding arrays for dry runs.")
    build.add_argument("--target-chars", type=int, default=None)
    build.add_argument("--max-chars", type=int, default=None)
    build.add_argument("--min-chunk-chars", type=int, default=None)
    build.add_argument("--overlap-chars", type=int, default=None)
    build.add_argument(
        "--max-chunk-heading-level",
        type=int,
        default=None,
        help="Deepest heading level to split on. Deeper headings stay inside that parent section.",
    )
    build.add_argument("--search-before-pages", type=int, default=1)
    build.add_argument("--search-after-pages", type=int, default=2)
    build.set_defaults(func=build_pack)

    classify = sub.add_parser("classify", help="Classify PDFs placed directly under a raw_data folder.")
    classify.add_argument("--raw-dir", default="raw_data", help="Raw data directory.")
    classify.add_argument("--dry-run", action="store_true", help="Only show decisions; do not move files.")
    classify.set_defaults(func=classify_command)
    return parser


def classify_command(args: argparse.Namespace) -> None:
    results, errors = classify_raw_entries(Path(args.raw_dir), move=not args.dry_run)
    if not results and not errors:
        print(f"No unclassified PDF files found directly under {Path(args.raw_dir).resolve()}")
        return
    for result in results:
        action = "would move" if args.dry_run else "moved"
        print(f"{action}: {result.source.name} -> {result.destination}")
        print("  scores:", format_classification_scores(result.scores))
        print("  signals:")
        for signal in format_classification_signals(result.profile, result.scores, result.signals):
            print(f"    {signal}")
    for error in errors:
        print(f"skip: {error.source.name} -> {error.message}")


def main(argv: list[str] | None = None) -> None:
    parser = make_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return
    try:
        result = args.func(args)
    except (ImageOnlyPdfError, UnsupportedSourceError) as exc:
        raise SystemExit(str(exc)) from exc
    if result is not None:
        print(f"Wrote {result}")


if __name__ == "__main__":
    main()
