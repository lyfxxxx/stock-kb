from stock_kb.eval_runner import retrieval_bucket


def test_explicit_bucket_wins():
    assert retrieval_bucket(
        {"bucket": "自定义", "type": "keyword", "question": "减值"}
    ) == "自定义"


def test_bucket_rules():
    assert retrieval_bucket({"type": "no_answer", "question": "火星店"}) == "无答案"
    assert retrieval_bucket({"type": "keyword", "question": "减值准备"}) == "关键词"
    assert retrieval_bucket(
        {"type": "semantic", "question": "What is same store sales"}
    ) == "跨语言"
    assert retrieval_bucket(
        {"type": "cross", "question": "operating cash flow 经营"}
    ) == "跨语言"
    assert retrieval_bucket({"type": "semantic", "question": "减值附注怎么说"}) == "附注"
    assert retrieval_bucket(
        {
            "type": "cross",
            "question": "附注说明这里中文很多很多很多 notes to the file",
        }
    ) == "附注"
    assert retrieval_bucket({"type": "semantic", "question": "现金流质量怎么样"}) == "语义"
    assert retrieval_bucket({"type": "cross", "question": "对比两年的门店效率"}) == "语义"
    for qtype in ("exact", "indicator", "route", "year_filter", "end2end"):
        assert retrieval_bucket({"type": qtype, "question": "营业收入是多少"}) is None
