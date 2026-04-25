from ragpack_builder.models import PageText
from ragpack_builder.toc import infer_txt_toc


def titles_and_levels(text: str, profile: str):
    toc = infer_txt_toc([PageText(1, text)], profile=profile)
    return [(item.title, item.level) for item in toc]


def test_technical_numbered_headings():
    text = "\n".join(
        [
            "1 Introduction",
            "1.1 Background",
            "1.1.1 Architecture",
            "1.1.1.1 Components",
            "Body text.",
        ]
    )

    assert titles_and_levels(text, "technical") == [
        ("1 Introduction", 1),
        ("1.1 Background", 2),
        ("1.1.1 Architecture", 3),
        ("1.1.1.1 Components", 4),
    ]


def test_paper_headings():
    text = "\n".join(
        [
            "摘要",
            "本文研究问题。",
            "关键词：阅读；理解",
            "1 引言",
            "1.1 研究背景",
            "参考文献",
        ]
    )

    assert titles_and_levels(text, "paper") == [
        ("摘要", 1),
        ("关键词：阅读；理解", 1),
        ("1 引言", 1),
        ("1.1 研究背景", 2),
        ("参考文献", 1),
    ]


def test_legal_headings():
    text = "\n".join(
        [
            "第一编 总则",
            "第一章 基本原则",
            "第一节 一般规定",
            "第一条 立法目的",
            "第二条 适用范围",
        ]
    )

    assert titles_and_levels(text, "legal") == [
        ("第一编 总则", 1),
        ("第一章 基本原则", 2),
        ("第一节 一般规定", 3),
        ("第一条 立法目的", 4),
        ("第二条 适用范围", 4),
    ]


def test_english_headings():
    text = "\n".join(
        [
            "Part I Foundations",
            "Chapter 1 Introduction",
            "1.1 Background",
            "1.1.1 Prior Work",
            "Appendix A Resources",
        ]
    )

    assert titles_and_levels(text, "english") == [
        ("Part I Foundations", 1),
        ("Chapter 1 Introduction", 2),
        ("1.1 Background", 2),
        ("1.1.1 Prior Work", 3),
        ("Appendix A Resources", 1),
    ]


def test_fiction_headings():
    text = "\n".join(
        [
            "楔子",
            "第一章 风起",
            "第二章 夜行",
            "尾声",
        ]
    )

    assert titles_and_levels(text, "fiction") == [
        ("楔子", 1),
        ("第一章 风起", 1),
        ("第二章 夜行", 1),
        ("尾声", 1),
    ]


def test_classical_headings():
    text = "\n".join(
        [
            "卷一",
            "本纪",
            "高祖纪",
            "卷二 列传",
            "陈涉传",
        ]
    )

    assert titles_and_levels(text, "classical") == [
        ("卷一", 1),
        ("本纪", 2),
        ("高祖纪", 3),
        ("卷二 列传", 1),
        ("陈涉传", 3),
    ]


def test_reference_headings():
    text = "\n".join(
        [
            "A",
            "Algorithm",
            "Anomaly Detection",
            "B",
            "Bayes Theorem",
        ]
    )

    assert titles_and_levels(text, "reference") == [
        ("A", 1),
        ("Algorithm", 2),
        ("Anomaly Detection", 2),
        ("B", 1),
        ("Bayes Theorem", 2),
    ]
