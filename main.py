from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

from ragpack_builder.classifier import classify_raw_entries, format_classification_scores, format_classification_signals
from ragpack_builder.cli import build_pack
from ragpack_builder.extractors import ImageOnlyPdfError, UnsupportedSourceError
from ragpack_builder.profiles import DEFAULT_MODEL, PROFILE_DEFAULTS


RAW_DATA_DIR = Path("raw_data")
OUTPUT_DIR = Path("output")
SUPPORTED_SUFFIXES = {".pdf", ".txt"}


def iter_source_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(
        path
        for path in folder.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )


def iter_unsupported_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(
        path
        for path in folder.rglob("*")
        if path.is_file() and path.suffix.lower() not in SUPPORTED_SUFFIXES
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
        min_chunk_chars=None,
        overlap_chars=None,
        max_chunk_heading_level=args.max_chunk_heading_level,
        search_before_pages=1,
        search_after_pages=2,
    )


def build_all(args: argparse.Namespace) -> int:
    loose_files = sorted(path for path in RAW_DATA_DIR.iterdir() if path.is_file()) if RAW_DATA_DIR.exists() else []
    if loose_files:
        print("Found unclassified file(s) directly under raw_data:")
        for path in loose_files:
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                print(f"  - {path} -> 非支持文件，请检查文件格式")
            else:
                print(f"  - {path}")
        print("Run `python main.py classify` first, or move them into a profile folder manually.")
        return 1

    jobs = [(profile, RAW_DATA_DIR / profile) for profile in PROFILE_DEFAULTS]
    invalid_files: list[Path] = []
    sources: list[tuple[str, Path]] = []
    for profile, folder in jobs:
        invalid_files.extend(iter_unsupported_files(folder))
        sources.extend((profile, source) for source in iter_source_files(folder))

    for path in invalid_files:
        print(f"skip: {path} -> 非支持文件，请检查文件格式")

    if not sources:
        print(f"No PDF/TXT files found under {RAW_DATA_DIR.resolve()}")
        return 1 if invalid_files else 0

    print(f"Found {len(sources)} file(s). Output: {Path(args.output).resolve()}")
    failures = 0
    for index, (profile, source) in enumerate(sources, start=1):
        print(f"[{index}/{len(sources)}] {profile}: {source}")
        try:
            out_path = build_pack(make_build_args(source, profile, args))
        except (ImageOnlyPdfError, UnsupportedSourceError) as exc:
            failures += 1
            print(f"  error: {exc}")
            continue
        print(f"  -> {out_path}")
    return 1 if invalid_files or failures else 0


def classify_all(args: argparse.Namespace) -> int:
    results, errors = classify_raw_entries(RAW_DATA_DIR, move=not args.dry_run)
    if not results and not errors:
        print(f"No unclassified PDF files found directly under {RAW_DATA_DIR.resolve()}")
        return 0
    for result in results:
        action = "would move" if args.dry_run else "moved"
        print(f"{action}: {result.source.name} -> raw_data/{result.profile}/{result.destination.name}")
        print("  scores:", format_classification_scores(result.scores))
        print("  signals:")
        for signal in format_classification_signals(result.profile, result.scores, result.signals):
            print(f"    {signal}")
    for error in errors:
        print(f"skip: {error.source.name} -> {error.message}")
    return 1 if errors else 0


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
