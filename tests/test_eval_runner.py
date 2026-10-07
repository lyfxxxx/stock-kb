from __future__ import annotations

from stock_kb.eval_runner import (
    classify_retrieval_errors,
    fact_phrase_hit,
    primary_query,
    promote_fact_match,
    _retrieval_result,
    _summarize,
    _value_within,
)
from stock_kb.eval_stats import bootstrap_ci, wilson_ci


def test_wilson_ci_bounds_and_n20():
    lo, hi = wilson_ci(15, 20)
    assert 0.0 <= lo < 0.75 < hi <= 1.0
    assert lo < 0.56 and hi > 0.88
    assert wilson_ci(0, 0) == (0.0, 0.0)


def test_bootstrap_ci_mean():
    lo, hi = bootstrap_ci([1.0, 1.0, 1.0, 0.0], n_resample=2000, seed=1)
    assert 0.0 <= lo <= hi <= 1.0
    assert lo < 0.75 < hi


def test_fact_phrase_accepts_same_number_on_another_page():
    assert fact_phrase_hit("净增 336 家，另有 1,336 家在建", ["336"]) is True
    assert fact_phrase_hit("只有 1336 家", ["336"]) is False
    assert fact_phrase_hit("已付股息 (6,071,486)", ["已付股息(6071486)"]) is True
    assert fact_phrase_hit("翻台率为3.9次╱天", ["翻台率为3.9次"]) is True
    retrieval = {"hit": False, "rank": None, "mrr": 0.0}
    hits = [
        {"page_id": 1, "title": "旧研报", "page_no": 22},
        {"page_id": 2, "title": "新年报", "page_no": 8},
    ]
    promote_fact_match(
        hits,
        retrieval,
        ["1383家"],
        {1: "门店净增讨论", 2: "餐厅总数为 1,383 家"},
    )
    assert retrieval["hit"] is True
    assert retrieval["rank"] == 2
    assert retrieval["fact_match"] is True


def test_primary_query_strips_company_for_keyword():
    assert (
        primary_query(
            {
                "type": "keyword",
                "company": "海底捞",
                "question": "海底捞 翻台率",
            }
        )
        == "翻台率"
    )
    assert (
        primary_query(
            {
                "type": "semantic",
                "company": "海底捞",
                "question": "海底捞的现金流质量怎么样？",
            }
        )
        == "海底捞的现金流质量怎么样？"
    )
    assert (
        primary_query(
            {
                "type": "cross",
                "question": "Yum China same-store sales trend",
                "keywords": ["same-store sales", "同店"],
            }
        )
        == "Yum China same-store sales trend"
    )


def test_classify_year_mismatch_and_near_miss_and_neg1():
    norm = {
        "sources": [
            {"file": "2024年报", "page": 151, "required": True, "relevance": 1}
        ],
        "negatives": [
            {"file": "2025中报", "page": 41, "required": False, "relevance": 1}
        ],
    }
    hits = [
        {
            "title": "2025中报",
            "page_no": 41,
            "year": 2025,
            "language": "zh",
            "snippet": "股息",
        },
        {
            "title": "2024年报",
            "page_no": 148,
            "year": 2024,
            "language": "zh",
            "snippet": "股息政策",
        },
    ]
    tags = classify_retrieval_errors(
        query="股息", qtype="keyword", hits=hits, norm=norm
    )
    assert "negative_at_1" in tags
    assert "page_near_miss" in tags
    assert "year_mismatch" in tags


def test_classify_lexical_overlap_on_semantic():
    norm = {
        "sources": [
            {"file": "研报-国信", "page": 41, "required": True, "relevance": 1}
        ],
        "negatives": [],
    }
    hits = [
        {
            "title": "研报-国信",
            "page_no": 40,
            "year": 2021,
            "language": "zh",
            "snippet": "经营现金流质量改善，自由现金流转正",
        }
    ]
    tags = classify_retrieval_errors(
        query="海底捞的现金流质量怎么样？",
        qtype="semantic",
        hits=hits,
        norm=norm,
    )
    assert "lexical_overlap" in tags


def test_retrieval_any_required_source_and_annual_hit():
    norm = {
        "sources": [
            {
                "file": "国信研报",
                "page": 19,
                "required": True,
                "relevance": 3,
                "authority": "research",
            },
            {
                "file": "2025中报",
                "page": 11,
                "required": True,
                "relevance": 3,
                "authority": "interim",
            },
        ],
        "negatives": [],
    }
    hits = [
        {"title": "2025中报", "page_no": 11},
        {"title": "其它年报", "page_no": 3},
    ]
    result = _retrieval_result(hits, norm, top_k=5)
    assert result["hit"] is True
    assert result["rank"] == 1
    assert result["annual_eligible"] is True
    assert result["annual_hit"] is True
    assert result["annual_rank"] == 1

    miss_filing = _retrieval_result(
        [{"title": "国信研报", "page_no": 19}], norm, top_k=5
    )
    assert miss_filing["hit"] is True
    assert miss_filing["annual_hit"] is False
    assert miss_filing["annual_rank"] is None


def test_value_within_tight_tolerance_separates_owners_vs_total():
    assert _value_within(4700278, 4708084, 0.0001) is False
    assert _value_within(4708084, 4708084, 0.0001) is True
    assert _value_within(4700278, 4708084, 0.02) is True


def test_summarize_splits_diag_and_no_answer():
    results = [
        {
            "type": "keyword",
            "split": "freeze",
            "retrieval": {
                "hit": True,
                "rank": 1,
                "ndcg": 1.0,
                "precision_at_k": 0.2,
                "negative_hit_at_k": False,
                "negative_hit_at_1": False,
                "hybrid_fused": False,
                "error_tags": [],
                "expected_sources": [{"file": "a", "page": 1}],
                "top_hits": [{}],
            },
        },
        {
            "type": "semantic",
            "split": "diag",
            "retrieval": {
                "hit": False,
                "rank": None,
                "ndcg": 0.0,
                "precision_at_k": 0.0,
                "negative_hit_at_k": True,
                "negative_hit_at_1": False,
                "hybrid_fused": True,
                "error_tags": [],
                "expected_sources": [{"file": "b", "page": 2}],
                "top_hits": [{}],
            },
        },
        {
            "type": "no_answer",
            "split": "diag",
            "retrieval": {
                "hit": False,
                "expected_sources": [],
                "top_hits": [],
            },
        },
    ]
    summary = _summarize(results)
    assert summary["retrieval"]["keyword"]["n"] == 1
    assert summary["retrieval"]["keyword"]["recall_at_k"] == 1.0
    assert "semantic" not in summary["retrieval"]
    assert summary["retrieval_diag"]["semantic"]["n"] == 1
    assert summary["no_answer"]["n"] == 1
    assert summary["no_answer"]["empty"] == 1
