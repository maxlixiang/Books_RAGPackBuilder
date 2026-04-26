from ragpack_builder.models import PageText, TocItem
from ragpack_builder.toc import augment_toc_with_body_headings, repair_toc_titles_from_text_pages


def test_repair_toc_titles_from_front_matter():
    pages = [
        PageText(
            1,
            "\n".join(
                [
                    "目录",
                    "第一篇 阅读的层次",
                    "第一章 阅读的活力与艺术",
                    "第二章 阅读的层次",
                    "第三章 阅读的第一个层次：基础阅读",
                ]
            ),
        )
    ]
    toc = [
        TocItem("toc:000001", "第一篇 阅读的层次", 1, 1, page=1),
        TocItem("toc:000002", "第一章 阅读的活力与艺术", 2, 2, "toc:000001", page=2),
        TocItem("toc:000003", "第二章 阅读的层次", 2, 3, "toc:000001", page=3),
        TocItem("toc:000004", "第乺\ue000ₖ֋ﭶ葻ⱎN⩜䉫⇿ᩗ喝䂖֋", 2, 4, "toc:000001", page=4),
    ]

    repaired = repair_toc_titles_from_text_pages(pages, toc)

    assert repaired == 1
    assert toc[3].title == "第三章 阅读的第一个层次：基础阅读"


def test_augment_toc_with_body_short_headings():
    pages = [
        PageText(
            1,
            "\n".join(
                [
                    "第一章 一本书的分类",
                    "章节导言正文。",
                    "书籍分类的重要性",
                    "这一节的正文。",
                    "从一本书的书名中你能学到什么",
                    "这一节的正文。",
                    "这不是标题，因为它有句号。",
                    "第二章 下一章",
                ]
            ),
        )
    ]
    toc = [
        TocItem("toc:000001", "第一章 一本书的分类", 1, 1, page=1),
        TocItem("toc:000002", "第二章 下一章", 1, 2, page=1),
    ]

    added = augment_toc_with_body_headings(pages, toc, "social_science")

    titles = [item.title for item in toc]
    assert added == 2
    assert "书籍分类的重要性" in titles
    assert "从一本书的书名中你能学到什么" in titles
    assert "这不是标题，因为它有句号。" not in titles
