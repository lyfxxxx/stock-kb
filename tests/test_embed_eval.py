from stock_kb.embed_eval import (
    bucket,
    is_embedding_question,
    pair_compare,
    _ci_overlap,
)


def test_bucket_edges():
    assert bucket(1) == "top5"
    assert bucket(5) == "top5"
    assert bucket(6) == "mid"
    assert bucket(50) == "mid"
    assert bucket(51) == "miss"
    assert bucket(None) == "miss"


def test_is_embedding_question_filters():
    long_q = {
        "type": "semantic",
        "question": "客人来得勤不勤、一桌坐得转不转？",
        "expected": {"sources": [{"file": "x", "page": 1, "required": True}]},
    }
    assert is_embedding_question(long_q) is True
    keyword = {
        "type": "keyword",
        "question": "海底捞 翻台率",
        "expected": {"sources": [{"file": "x", "page": 1}]},
    }
    assert is_embedding_question(keyword) is False
    structured = {
        "type": "cross",
        "question": "Yum China 2025 operating profit is a long enough query",
        "statement": {"type": "income", "year": 2025},
        "expected": {"sources": [{"file": "x", "page": 1}]},
    }
    assert is_embedding_question(structured) is False
    short = {
        "type": "semantic",
        "question": "短",
        "expected": {"sources": [{"file": "x", "page": 1}]},
    }
    assert is_embedding_question(short) is False


def test_ci_overlap():
    assert _ci_overlap((0.05, 0.36), (0.10, 0.40)) is True
    assert _ci_overlap((0.0, 0.1), (0.2, 0.4)) is False


def _run(model: str, ranks: list[int | None]) -> dict:
    items = []
    for i, rk in enumerate(ranks):
        b = bucket(rk)
        items.append(
            {
                "id": f"q-{i}",
                "type": "semantic",
                "split": "freeze",
                "vector_rank": rk,
                "vector_bucket": b,
                "hybrid_hit": False,
                "hybrid_fused": True,
            }
        )
    n = len(items)
    top5 = sum(1 for x in items if x["vector_bucket"] == "top5")
    mid = sum(1 for x in items if x["vector_bucket"] == "mid")
    miss = sum(1 for x in items if x["vector_bucket"] == "miss")
    r50 = top5 + mid
    from stock_kb.eval_stats import wilson_ci

    return {
        "meta": {"model": model},
        "summary": {
            "n": n,
            "recall_at_5": top5 / n,
            "recall_at_5_ci": list(wilson_ci(top5, n)),
            "recall_at_50": r50 / n,
            "recall_at_50_ci": list(wilson_ci(r50, n)),
            "n_top5": top5,
            "n_mid": mid,
            "n_miss": miss,
        },
        "results": items,
    }


def test_verdict_indistinguishable_when_one_question_moves():
    base = _run("base", [1, None, None, None, None, None, None, None, None, None] * 2)
    chal = _run("chal", [1, 3, None, None, None, None, None, None, None, None] * 2)
    # 20 items, one extra top5 in first 10 duplicated... actually 2 extra top5
    # Use equal almost: 3/20 vs 4/20 overlaps
    base = _run("base", [1, 2, 3] + [None] * 17)
    chal = _run("chal", [1, 2, 3, 4] + [None] * 16)
    c = pair_compare(base, chal)
    assert c["label"] in {"indistinguishable", "lean_better", "better_at_5_only"}
    assert c["recommend_switch"] is False


def test_verdict_better_when_ci_separates():
    # 20/20 vs 2/20 on @50 should separate Wilson
    base = _run("base", [None] * 18 + [1, 2])
    chal = _run("chal", list(range(1, 21)))
    c = pair_compare(base, chal)
    assert c["label"] == "better"
    assert c["recommend_switch"] is True
