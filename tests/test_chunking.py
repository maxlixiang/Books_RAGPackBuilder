from ragpack_builder.chunking import make_chunks
from ragpack_builder.models import PageText, Section, TocItem
from ragpack_builder.toc import build_sections, infer_txt_toc


def item(order, title, level, parent=None):
    return TocItem(f"toc:{order:06d}", title, level, order, parent_toc_id=parent, page=order)


def test_short_level_three_sections_merge_within_parent():
    chapter = item(1, "第1章 成为公正的思考者", 1)
    parent = item(2, "公正性需要什么", 2, chapter.toc_id)
    a = item(3, "思维谦逊：努力发现未知", 3, parent.toc_id)
    b = item(4, "思维的勇气：挑战信念", 3, parent.toc_id)
    sections = [
        Section(a, [chapter, parent, a], "短内容" * 20, 3, 3),
        Section(b, [chapter, parent, b], "另一段" * 20, 4, 4),
    ]

    chunks = make_chunks(sections, min_chunk_chars=220, target_chars=800, max_chars=1200)

    assert len(chunks) == 1
    assert [x.title for x in chunks[0].merged_headings] == [a.title, b.title]
    assert chunks[0].heading_path == [chapter, parent]


def test_long_section_splits():
    chapter = item(1, "第1章", 1)
    text = "。".join(["这是一个很长的句子"] * 300)
    sections = [Section(chapter, [chapter], text, 1, 2)]

    chunks = make_chunks(sections, max_chars=300, overlap_chars=20)

    assert len(chunks) > 1
    assert chunks[0].split_info["reason"] == "section_exceeds_max_chars"


def test_natural_section_kept_even_when_above_max_chars():
    chapter = item(1, "第一章", 1)
    text = "这是一个完整小节。" * 90
    sections = [Section(chapter, [chapter], text, 1, 2)]

    chunks = make_chunks(sections, max_chars=300, section_split_chars=2000, overlap_chars=20)

    assert len(chunks) == 1
    assert chunks[0].text == text
    assert chunks[0].split_info["reason"] == "natural_section_within_split_threshold"


def test_section_above_split_threshold_splits():
    chapter = item(1, "第一章", 1)
    text = "这是一个很长的小节。" * 260
    sections = [Section(chapter, [chapter], text, 1, 2)]

    chunks = make_chunks(sections, max_chars=300, section_split_chars=800, overlap_chars=20)

    assert len(chunks) > 1
    assert chunks[0].split_info["reason"] == "section_exceeds_max_chars"


def test_textbook_heading_levels():
    page = PageText(
        1,
        "\n".join(
            [
                "第一章 总论",
                "第一节 基本概念",
                "一、研究对象",
                "（一）基本定义",
                "1. 主要特点",
                "这里是教材正文内容。",
            ]
        ),
    )

    toc = infer_txt_toc([page], profile="textbook")

    assert [(item.title, item.level) for item in toc] == [
        ("第一章 总论", 1),
        ("第一节 基本概念", 2),
        ("一、研究对象", 3),
        ("（一）基本定义", 4),
        ("1. 主要特点", 5),
    ]


def test_textbook_max_chunk_heading_level_keeps_deeper_headings_inside_parent():
    page = PageText(
        1,
        "\n".join(
            [
                "第一章 总论",
                "第一节 基本概念",
                "一、研究对象",
                "（一）基本定义",
                "1. 主要特点",
                "特点一的正文内容。",
                "2. 其他特点",
                "特点二的正文内容。",
            ]
        ),
    )
    toc = infer_txt_toc([page], profile="textbook")

    sections = build_sections([page], toc, max_chunk_heading_level=4)

    assert len(sections) == 1
    assert sections[0].toc_item.title == "（一）基本定义"
    assert "1. 主要特点" in sections[0].text
    assert "2. 其他特点" in sections[0].text
