from __future__ import annotations

import re
from pathlib import Path


ANNUAL_KEYS = ("年报", "年度报告", "年報", "annual report", "10-k")
INTERIM_KEYS = ("中报", "中期报告", "中期報告", "interim report")
Q3_KEYS = ("三季报", "第三季度")
PROSPECTUS_KEYS = ("招股", "prospectus", "ipo", "全球发售")
RESEARCH_KEYS = ("研报", "证券", "研究", "点评")


def classify_report(path: str | Path) -> dict:
    p = Path(path)
    name = p.stem.lower()
    parent = p.parent.name.lower()
    name_norm = name.replace("_", " ").replace("-", " ")
    parent_norm = parent.replace("_", " ").replace("-", " ")

    if any(k in name_norm for k in PROSPECTUS_KEYS) or any(k in parent_norm for k in PROSPECTUS_KEYS):
        report_type = "prospectus"
    elif any(k in name_norm for k in ANNUAL_KEYS) or any(k in parent_norm for k in ANNUAL_KEYS):
        report_type = "annual"
    elif any(k in name_norm for k in INTERIM_KEYS) or any(k in parent_norm for k in INTERIM_KEYS):
        report_type = "interim"
    elif any(k in name_norm for k in Q3_KEYS):
        report_type = "q3"
    elif any(k in name_norm for k in RESEARCH_KEYS) or any(k in parent_norm for k in RESEARCH_KEYS):
        report_type = "research"
    else:
        report_type = "other"

    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", name))
    language = "zh" if has_cjk else "en"

    year_match = re.search(r"(19|20)\d{2}", name)
    year = int(year_match.group(0)) if year_match else None

    if report_type == "annual":
        period_type = "annual"
    elif report_type == "interim":
        period_type = "interim"
    elif report_type == "q3":
        period_type = "q3"
    else:
        period_type = "other"

    return {
        "report_type": report_type,
        "language": language,
        "year": year,
        "period_type": period_type,
        "title": p.stem,
    }
