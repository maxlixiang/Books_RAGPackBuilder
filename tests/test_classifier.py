from ragpack_builder.classifier import (
    choose_profile,
    english_ratio,
    format_classification_scores,
    format_classification_signals,
)


def test_choose_profile_priority_for_clear_scores():
    assert choose_profile({"legal": 10, "paper": 0, "english": 0, "technical": 0, "textbook": 0, "social_science": 0}) == "legal"
    assert choose_profile({"legal": 0, "paper": 8, "english": 0, "technical": 0, "textbook": 0, "social_science": 0}) == "paper"
    assert choose_profile({"legal": 0, "paper": 0, "english": 8, "technical": 0, "textbook": 0, "social_science": 0}) == "english"
    assert choose_profile({"legal": 0, "paper": 0, "english": 0, "technical": 8, "textbook": 0, "social_science": 0}) == "technical"
    assert choose_profile({"legal": 0, "paper": 0, "reference": 8, "classical": 0, "english": 0, "technical": 0, "textbook": 0, "fiction": 0, "social_science": 0}) == "reference"
    assert choose_profile({"legal": 0, "paper": 0, "reference": 0, "classical": 8, "english": 0, "technical": 0, "textbook": 0, "fiction": 0, "social_science": 0}) == "classical"
    assert choose_profile({"legal": 0, "paper": 0, "reference": 0, "classical": 0, "english": 0, "technical": 0, "textbook": 0, "fiction": 8, "social_science": 0}) == "fiction"


def test_english_ratio():
    assert english_ratio("Chapter Introduction Appendix") > 0.9
    assert english_ratio("第一章 总论") < 0.1


def test_format_classification_scores_descending():
    scores = {"fiction": 4, "social_science": 10, "legal": 2, "classical": 7}

    assert format_classification_scores(scores) == "social_science=10, classical=7, fiction=4, legal=2"


def test_format_classification_signals_summarizes_winner_first():
    scores = {"social_science": 10, "fiction": 4}
    signals = [
        "fiction+2: detected chapter-only structure",
        "social_science+3: detected chapter-only structure",
        "social_science+5: detected philosophy/social-science vocabulary",
    ]

    assert format_classification_signals("social_science", scores, signals) == [
        "social_science+10: detected chapter-only structure; detected philosophy/social-science vocabulary",
        "fiction+2: detected chapter-only structure",
    ]
