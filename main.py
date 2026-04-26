from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

from ragpack_builder.classifier import (
    Classification,
    ClassificationError,
    classify_raw_entries,
    format_classification_scores,
    format_classification_signals,
    is_ignored_local_file,
)
from ragpack_builder.cli import build_pack
from ragpack_builder.extractors import ImageOnlyPdfError, UnsupportedSourceError
from ragpack_builder.markdown_builder import build_markdown_packs
from ragpack_builder.profiles import DEFAULT_MODEL, PROFILE_DEFAULTS


RAW_DATA_DIR = Path("raw_data")
OUTPUT_DIR = Path("output")
BOOKS_RAW_DIR = RAW_DATA_DIR / "books"
MARKDOWN_RAW_DIR = RAW_DATA_DIR / "markdown_files"
BOOKS_OUTPUT_NAME = "books_output"
MARKDOWN_OUTPUT_NAME = "markdown_output"
SUPPORTED_SUFFIXES = {".pdf", ".txt"}
MARKDOWN_FOLDERS = ("journal", "TechNotes", "WebPageCollection")


def iter_source_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(
        path
        for path in folder.rglob("*")
        if path.is_file() and not is_ignored_local_file(path) and path.suffix.lower() in SUPPORTED_SUFFIXES
    )


def iter_unsupported_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(
        path
        for path in folder.rglob("*")
        if path.is_file() and not is_ignored_local_file(path) and path.suffix.lower() not in SUPPORTED_SUFFIXES
    )


def make_build_args(source: Path, profile: str, args: argparse.Namespace) -> SimpleNamespace:
    return SimpleNamespace(
        source=str(source),
        output=str(args.output),
        title=None,
        profile=profile,
        embedding_model=args.embedding_model,
        batch_size=args.batch_size,
        no_embedding=args.no_embedding,
        target_chars=None,
        max_chars=None,
        section_split_chars=None,
        min_chunk_chars=None,
        overlap_chars=None,
        max_chunk_heading_level=args.max_chunk_heading_level,
        search_before_pages=1,
        search_after_pages=2,
    )


def build_all(args: argparse.Namespace) -> int:
    ensure_workspace_dirs(Path(args.output))
    classify_errors = 0
    results, errors = classify_raw_entries(BOOKS_RAW_DIR, move=True)
    if results:
        print(f"Classified {len(results)} unclassified PDF file(s):")
        print_classification_results(results, base_label="raw_data/books")
    if errors:
        classify_errors = len(errors)
        print_classification_errors(errors)

    books_output_dir = Path(args.output) / BOOKS_OUTPUT_NAME
    markdown_output_dir = Path(args.output) / MARKDOWN_OUTPUT_NAME

    jobs = [(profile, BOOKS_RAW_DIR / profile) for profile in PROFILE_DEFAULTS]
    invalid_files: list[Path] = []
    sources: list[tuple[str, Path]] = []
    for profile, folder in jobs:
        invalid_files.extend(iter_unsupported_files(folder))
        sources.extend((profile, source) for source in iter_source_files(folder))

    for path in invalid_files:
        print(f"skip: {path} -> 非支持文件，请检查文件格式")

    if sources:
        print(f"Found {len(sources)} book file(s). Output: {books_output_dir.resolve()}")
    else:
        print(f"No PDF/TXT book files found under {BOOKS_RAW_DIR.resolve()}")
    failures = 0
    for index, (profile, source) in enumerate(sources, start=1):
        print(f"[{index}/{len(sources)}] {profile}: {source}")
        try:
            book_args = make_build_args(source, profile, args)
            book_args.output = str(books_output_dir)
            out_path = build_pack(book_args)
        except (ImageOnlyPdfError, UnsupportedSourceError) as exc:
            failures += 1
            print(f"  error: {exc}")
            continue
        print(f"  -> {out_path}")

    markdown_failures = 0
    try:
        markdown_outputs = build_markdown_packs(
            MARKDOWN_RAW_DIR,
            markdown_output_dir,
            embedding_model=args.embedding_model,
            batch_size=args.batch_size,
            no_embedding=args.no_embedding,
        )
    except Exception as exc:
        markdown_failures += 1
        print(f"Markdown build error: {exc}")
        markdown_outputs = []
    if markdown_outputs:
        print(f"Built {len(markdown_outputs)} markdown RAGPack file(s). Output: {markdown_output_dir.resolve()}")
        for out_path in markdown_outputs:
            print(f"  -> {out_path}")
    else:
        print(f"No Markdown files found under {MARKDOWN_RAW_DIR.resolve()}")

    return 1 if invalid_files or failures or classify_errors or markdown_failures else 0


def classify_all(args: argparse.Namespace) -> int:
    ensure_workspace_dirs(Path(getattr(args, "output", OUTPUT_DIR)))
    results, errors = classify_raw_entries(BOOKS_RAW_DIR, move=not args.dry_run)
    if not results and not errors:
        print(f"No unclassified PDF files found directly under {BOOKS_RAW_DIR.resolve()}")
        return 0
    print_classification_results(results, dry_run=args.dry_run, base_label="raw_data/books")
    print_classification_errors(errors)
    return 1 if errors else 0


def print_classification_results(
    results: list[Classification],
    dry_run: bool = False,
    base_label: str = "raw_data",
) -> None:
    for result in results:
        action = "would move" if dry_run else "moved"
        print(f"{action}: {result.source.name} -> {base_label}/{result.profile}/{result.destination.name}")
        print("  scores:", format_classification_scores(result.scores))
        print("  signals:")
        for signal in format_classification_signals(result.profile, result.scores, result.signals):
            print(f"    {signal}")


def print_classification_errors(errors: list[ClassificationError]) -> None:
    for error in errors:
        print(f"skip: {error.source.name} -> {error.message}")


def ensure_workspace_dirs(output_root: Path) -> None:
    for profile in PROFILE_DEFAULTS:
        (BOOKS_RAW_DIR / profile).mkdir(parents=True, exist_ok=True)
    for folder in MARKDOWN_FOLDERS:
        (MARKDOWN_RAW_DIR / folder).mkdir(parents=True, exist_ok=True)
    (output_root / BOOKS_OUTPUT_NAME).mkdir(parents=True, exist_ok=True)
    (output_root / MARKDOWN_OUTPUT_NAME).mkdir(parents=True, exist_ok=True)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch build RAG JSONL files from raw_data folders.")
    sub = parser.add_subparsers(dest="command")

    classify = sub.add_parser("classify", help="Classify PDFs placed directly under raw_data into profile folders.")
    classify.add_argument("--dry-run", action="store_true", help="Only show decisions; do not move files.")
    classify.set_defaults(func=classify_all)

    build = sub.add_parser("build", help="Build all classified files. This is the default command.")
    add_build_arguments(build)
    build.set_defaults(func=build_all)

    add_build_arguments(parser)
    parser.set_defaults(func=build_all)
    return parser


def add_build_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-o", "--output", default=str(OUTPUT_DIR), help="Output directory.")
    parser.add_argument("--embedding-model", default=DEFAULT_MODEL, help="SentenceTransformer model name.")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--no-embedding", action="store_true", help="Generate *_noembedding.rag.jsonl files.")
    parser.add_argument(
        "--section-split-chars",
        type=int,
        default=None,
        help="Override the natural section length threshold before secondary splitting.",
    )
    parser.add_argument(
        "--max-chunk-heading-level",
        type=int,
        default=None,
        help="Override the deepest heading level to split on for profiles that support it.",
    )


def main() -> None:
    parser = make_parser()
    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
