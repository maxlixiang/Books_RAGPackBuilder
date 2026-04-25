from __future__ import annotations

from pathlib import Path

from .models import PageText, TocItem
from .utils import normalize_text


UNSUPPORTED_FILE_MESSAGE = "非支持文件，请检查文件格式"
IMAGE_ONLY_PDF_MESSAGE = "该文件不是可复制文字的pdf文件，请检查格式"


class UnsupportedSourceError(ValueError):
    pass


class ImageOnlyPdfError(ValueError):
    pass


def extract_document(path: Path) -> tuple[list[PageText], list[TocItem], str]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf(path)
    if suffix == ".txt":
        return extract_txt(path)
    raise UnsupportedSourceError(UNSUPPORTED_FILE_MESSAGE)


def extract_pdf(path: Path) -> tuple[list[PageText], list[TocItem], str]:
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "PDF support requires PyMuPDF. Install it with: pip install pymupdf"
        ) from exc

    doc = fitz.open(path)
    pages = [
        PageText(page_index=i + 1, text=normalize_text(page.get_text("text")))
        for i, page in enumerate(doc)
    ]
    if not any(page.text.strip() for page in pages):
        doc.close()
        raise ImageOnlyPdfError(IMAGE_ONLY_PDF_MESSAGE)

    raw_toc = doc.get_toc(simple=True)
    toc_items: list[TocItem] = []
    stack: list[TocItem] = []
    for idx, item in enumerate(raw_toc, start=1):
        level, title, page = item
        while stack and stack[-1].level >= level:
            stack.pop()
        parent = stack[-1].toc_id if stack else None
        toc = TocItem(
            toc_id=f"toc:{idx:06d}",
            title=normalize_text(title).replace("\n", " "),
            level=int(level),
            order=idx,
            parent_toc_id=parent,
            page=int(page) if page else None,
            locate={"method": "pdf_outline", "confidence": 0.8},
        )
        toc_items.append(toc)
        stack.append(toc)

    doc.close()
    return pages, toc_items, "pdf"


def extract_txt(path: Path) -> tuple[list[PageText], list[TocItem], str]:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("utf-8", errors="replace")

    return [PageText(page_index=1, text=normalize_text(text))], [], "txt"
