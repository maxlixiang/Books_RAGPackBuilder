from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .extractors import IMAGE_ONLY_PDF_MESSAGE, UNSUPPORTED_FILE_MESSAGE, ImageOnlyPdfError, UnsupportedSourceError
from .profiles import PROFILE_DEFAULTS


PROFILE_DIRS = tuple(PROFILE_DEFAULTS.keys())


@dataclass
class Classification:
    source: Path
    profile: str
    destination: Path
    scores: dict[str, int]
    signals: list[str]


@dataclass
class ClassificationError:
    source: Path
    message: str


def format_classification_scores(scores: dict[str, int]) -> str:
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return ", ".join(f"{profile}={score}" for profile, score in ordered)


def format_classification_signals(profile: str, scores: dict[str, int], signals: list[str]) -> list[str]:
    winning_reasons: list[str] = []
    other_signals: list[str] = []
    signal_pattern = re.compile(r"^(?P<profile>[^+]+)\+(?P<points>\d+): (?P<reason>.+)$")

    for signal in signals:
        match = signal_pattern.match(signal)
        if match and match.group("profile") == profile:
            winning_reasons.append(match.group("reason"))
        else:
            other_signals.append(signal)

    winning_score = scores.get(profile, 0)
    if winning_reasons:
        summary = "; ".join(winning_reasons)
    else:
        summary = "selected by highest total score"

    return [f"{profile}+{winning_score}: {summary}", *other_signals]


def classify_pdf(path: Path) -> tuple[str, dict[str, int], list[str]]:
    text, toc_titles = inspect_pdf(path)
    sample = "\n".join(toc_titles + [text])
    scores = {profile: 0 for profile in PROFILE_DIRS}
    signals: list[str] = []

    def add(profile: str, points: int, reason: str) -> None:
        scores[profile] += points
        signals.append(f"{profile}+{points}: {reason}")

    if re.search(r"\b(Part\s+[IVXLCDM\d]+|Chapter\s+\d+|Appendix\s+[A-Z\d]+)\b", sample, re.I):
        add("english", 8, "detected Part/Chapter/Appendix headings")
    if english_ratio(sample) > 0.55:
        add("english", 6, "mostly English text")

    if re.search(r"^\s*\d+\s+\S+", sample, re.M) and re.search(r"^\s*\d+\.\d+", sample, re.M):
        add("technical", 7, "detected 1 / 1.1 numeric hierarchy")
    if len(re.findall(r"^\s*\d+(?:\.\d+){2,}\s+\S+", sample, re.M)) >= 2:
        add("technical", 4, "detected deep numeric hierarchy")
    if re.search(r"\b(API|SDK|HTTP|JSON|Python|JavaScript|架构|部署|接口|配置|模块)\b", sample, re.I):
        add("technical", 2, "detected technical vocabulary")

    if re.search(r"^\s*(摘要|摘\s*要|Abstract)\s*$", sample, re.M | re.I):
        add("paper", 5, "detected abstract")
    if re.search(r"^\s*(关键词|关键字|Keywords?)[:：]?", sample, re.M | re.I):
        add("paper", 4, "detected keywords")
    if re.search(r"^\s*(参考文献|References|Bibliography)\s*$", sample, re.M | re.I):
        add("paper", 4, "detected references")

    if re.search(r"第\s*[一二三四五六七八九十百千万\d]+\s*编", sample):
        add("legal", 5, "detected 编 structure")
    article_count = len(re.findall(r"第\s*[一二三四五六七八九十百千万\d]+\s*条", sample))
    if article_count:
        add("legal", min(10, 2 + article_count), "detected 条 structure")
    if re.search(r"(条例|办法|规定|法律|规章|标准|规范|实施细则)", sample):
        add("legal", 2, "detected legal/policy vocabulary")

    fiction_count = len(re.findall(r"第\s*[一二三四五六七八九十百千万\d]+\s*[章节回]", sample))
    fiction_marker = re.search(r"(楔子|序章|尾声|番外|第\s*[一二三四五六七八九十百千万\d]+\s*回|Chapter\s+\d+)", sample, re.I)
    if fiction_count >= 5 and not re.search(r"第\s*[一二三四五六七八九十百千万\d]+\s*节", sample):
        add("fiction", 2, "detected chapter-only structure")
    if fiction_marker:
        add("fiction", 5, "detected strong fiction chapter markers")
    if fiction_marker and fiction_count:
        add("fiction", 2, "detected fiction markers with chapter sequence")
    if re.search(r"(小说|长篇|故事|主人公|叙事|人物对白|尾声|番外)", sample):
        add("fiction", 2, "detected fiction vocabulary")

    if re.search(r"卷\s*[一二三四五六七八九十百千万\d上下]+", sample):
        add("classical", 5, "detected 卷 structure")
    if re.search(r"(本纪|世家|列传|志|表|内篇|外篇|上篇|下篇)", sample):
        add("classical", 4, "detected classical section names")
    if len(re.findall(r"[\u4e00-\u9fff]{1,12}(传|纪|志|论|说|赋|铭|序|跋)", sample)) >= 3:
        add("classical", 3, "detected classical text headings")

    if re.search(r"(词典|辞典|百科|索引|术语表|Glossary|Dictionary|Encyclopedia)", sample, re.I):
        add("reference", 6, "detected reference-work vocabulary")
    short_entry_lines = len(re.findall(r"^[A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff·・、（）() -]{1,24}$", sample, re.M))
    if short_entry_lines >= 20:
        add("reference", 4, "detected many short entry-like headings")
    if len(re.findall(r"^[A-Z]$", sample, re.M)) >= 3:
        add("reference", 3, "detected alphabetical index headings")

    section_count = len(re.findall(r"第\s*[一二三四五六七八九十百千万\d]+\s*节", sample))
    chapter_count = len(re.findall(r"第\s*[一二三四五六七八九十百千万\d]+\s*章", sample))
    if chapter_count and section_count:
        add("textbook", 6, "detected 章/节 structure")
    if re.search(r"^[一二三四五六七八九十]+、", sample, re.M) or re.search(r"^（[一二三四五六七八九十]+）", sample, re.M):
        add("textbook", 4, "detected Chinese outline enumerators")

    if chapter_count and not section_count:
        add("social_science", 3, "detected chapter-only structure")
    if re.search(r"(译序|序言|前言|导论|绪论|后记)", sample):
        add("social_science", 2, "detected narrative book front/back matter")
    if re.search(r"(哲学|思想|理性|伦理|人生|幸福|智慧|认识|自由|意志|道德|审美|精神|社会|心理)", sample):
        add("social_science", 5, "detected philosophy/social-science vocabulary")
    if max(scores.values()) == 0:
        add("social_science", 1, "fallback default")

    profile = choose_profile(scores)
    return profile, scores, signals


def inspect_pdf(path: Path, max_pages: int = 20) -> tuple[str, list[str]]:
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise RuntimeError("PDF classification requires PyMuPDF. Install it with: pip install pymupdf") from exc

    doc = fitz.open(path)
    toc_titles = [item[1] for item in doc.get_toc(simple=True)]
    page_texts = []
    scan_pages = min(max_pages, doc.page_count)
    for i in range(scan_pages):
        page_texts.append(doc[i].get_text("text"))
    if not "".join(page_texts).strip():
        for i in range(scan_pages, doc.page_count):
            page_texts.append(doc[i].get_text("text"))
            if page_texts[-1].strip():
                break
    doc.close()
    text = "\n".join(page_texts)
    if not text.strip():
        raise ImageOnlyPdfError(IMAGE_ONLY_PDF_MESSAGE)
    return text, toc_titles[:200]


def english_ratio(text: str) -> float:
    letters = len(re.findall(r"[A-Za-z]", text))
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    total = letters + cjk
    return letters / total if total else 0.0


def choose_profile(scores: dict[str, int]) -> str:
    priority = [
        "legal",
        "paper",
        "reference",
        "classical",
        "english",
        "technical",
        "textbook",
        "fiction",
        "social_science",
    ]
    return max(priority, key=lambda profile: (scores.get(profile, 0), -priority.index(profile)))


def classify_raw_pdfs(raw_dir: Path, move: bool = True) -> list[Classification]:
    results, _ = classify_raw_entries(raw_dir, move=move)
    return results


def classify_raw_entries(raw_dir: Path, move: bool = True) -> tuple[list[Classification], list[ClassificationError]]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    results: list[Classification] = []
    errors: list[ClassificationError] = []
    for source in sorted(path for path in raw_dir.iterdir() if path.is_file()):
        suffix = source.suffix.lower()
        if suffix == ".txt":
            errors.append(ClassificationError(source, "TXT 文件不需要自动分类，请放入对应分类文件夹后再构建"))
            continue
        if suffix != ".pdf":
            errors.append(ClassificationError(source, UNSUPPORTED_FILE_MESSAGE))
            continue
        try:
            profile, scores, signals = classify_pdf(source)
        except (ImageOnlyPdfError, UnsupportedSourceError) as exc:
            errors.append(ClassificationError(source, str(exc)))
            continue
        destination = unique_destination(raw_dir / profile / source.name)
        if move:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
        results.append(Classification(source, profile, destination, scores, signals))
    return results, errors


def unique_destination(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1
