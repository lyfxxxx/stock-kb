from stock_kb.eval_regression import (
    diff_question_hits,
    extract_question_hits,
    primary_ok,
)


def test_extract_and_primary_ok_by_type():
    result = {
        "results": [
            {
                "id": "keyword-001",
                "type": "keyword",
                "retrieval": {"hit": True, "top_hits": [{}]},
            },
            {
                "id": "exact-001",
                "type": "exact",
                "structured": {"hit": True, "parse_hit": True},
                "retrieval": {"hit": False},
            },
            {
                "id": "indicator-001",
                "type": "indicator",
                "indicator": {"hit": True},
            },
            {
                "id": "noans-001",
                "type": "no_answer",
                "retrieval": {"hit": False, "top_hits": []},
            },
            {
                "id": "end2end-001",
                "type": "end2end",
                "generation": {"pending_manual": False},
            },
            {
                "id": "route-001",
                "type": "route",
                "route": {"hit": True, "predicted": "get_indicators"},
            },
        ]
    }
    hits = extract_question_hits(result)
    assert hits["keyword-001"] == {"type": "keyword", "hit": True}
    assert hits["exact-001"]["structured_hit"] is True
    assert "hit" not in hits["exact-001"]
    assert hits["noans-001"]["empty"] is True
    assert hits["end2end-001"]["material_complete"] is True
    assert hits["route-001"]["route_hit"] is True
    assert primary_ok(hits["keyword-001"]) is True
    assert primary_ok(hits["exact-001"]) is True
    assert primary_ok(hits["route-001"]) is True


def test_diff_lost_gained_added_removed():
    baseline = {
        "keyword-001": {"type": "keyword", "hit": True},
        "keyword-002": {"type": "keyword", "hit": False},
        "keyword-003": {"type": "keyword", "hit": True},
    }
    current = {
        "keyword-001": {"type": "keyword", "hit": False},
        "keyword-002": {"type": "keyword", "hit": True},
        "keyword-004": {"type": "keyword", "hit": True},
    }
    diff = diff_question_hits(baseline, current)
    assert diff["lost"] == ["keyword-001"]
    assert diff["gained"] == ["keyword-002"]
    assert diff["added"] == ["keyword-004"]
    assert diff["removed"] == ["keyword-003"]


def test_diff_none_when_stable():
    recs = {"k": {"type": "keyword", "hit": True}}
    assert diff_question_hits(recs, recs) == {
        "lost": [],
        "gained": [],
        "added": [],
        "removed": [],
    }
