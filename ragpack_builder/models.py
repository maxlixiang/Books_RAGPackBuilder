from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PageText:
    page_index: int
    text: str


@dataclass
class TocItem:
    toc_id: str
    title: str
    level: int
    order: int
    parent_toc_id: str | None = None
    page: int | None = None
    locate: dict | None = None


@dataclass
class Section:
    toc_item: TocItem
    heading_path: list[TocItem]
    text: str
    page_start: int | None = None
    page_end: int | None = None
    child_sections: list["Section"] = field(default_factory=list)
    source_metadata: dict = field(default_factory=dict)


@dataclass
class ChunkDraft:
    text: str
    heading_path: list[TocItem]
    merged_headings: list[TocItem]
    page_start: int | None
    page_end: int | None
    split_info: dict
    source_metadata: dict = field(default_factory=dict)
