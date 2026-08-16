from __future__ import annotations

import re
from typing import Any

from stock_kb import db


# 每个指标绑定报表类型；positive 按优先级排列（越靠前越优先），
# negative 命中则直接排除。避免再用宽泛的 "sales" 把 Company sales 当成总收入。
METRIC_RULES = {
    "revenue": {
        "statement_type": "income",
        "positive": ["totalrevenues", "营业收入", "收入", "revenue"],
        "negative": [
            "companysales",
            "otherrevenues",
            "franchise",
            "intersegment",
            "otherincome",
            "revenuesfromtransactions",
        ],
    },
    "net_profit": {
        "statement_type": "income",
        "positive": [
            "netincomeyumchinaholdings",
            "profitfortheyear",
            "净利润",
            "netprofit",
            "netincome",
            "年内溢利",
        ],
        "negative": [
            "noncontrolling",
            "othercomprehensive",
            "beforeincometaxes",
            "beforetax",
            "incometax",
            "comprehensiveincome",
        ],
    },
    "total_assets": {
        "statement_type": "balance",
        "positive": ["totalassets", "资产合计", "资产总计"],
        "negative": ["current", "noncurrent", "deferred", "tax", "其他资产", "其他"],
    },
    "total_equity": {
        "statement_type": "balance",
        "positive": [
            "totalshareholdersequity",
            "totalequity",
            "equityattributable",
            "权益合计",
            "股东权益合计",
        ],
        "negative": ["noncontrolling", "current", "deferred"],
    },
    "operating_cashflow": {
        "statement_type": "cashflow",
        "positive": [
            "netcashprovidedbyoperatingactivities",
            "netcashfromoperatingactivities",
            "经营活动所得现金净额",
            "经营活动产生的现金流量净额",
            "经营活动所得现金",
        ],
        "negative": ["investing", "financing", "beforemovements", "noncashoperating"],
    },
    "gross_profit": {
        "statement_type": "income",
        "positive": ["grossprofit", "毛利"],
        "negative": ["margin", "毛利率"],
    },
}


def _normalize_name(value: Any) -> str:
    text = str(value or "").casefold()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def _candidate_score(line_name: Any, rule: dict[str, Any]) -> int | None:
    name = _normalize_name(line_name)
    if not name:
        return None
    for negative in rule["negative"]:
        if _normalize_name(negative) in name:
            return None
    for idx, positive in enumerate(rule["positive"]):
        if _normalize_name(positive) in name:
            return 100 - idx
    return None


def compute_indicators(cfg: dict[str, Any]) -> dict[str, int]:
    conn = db.connect(cfg["db_path"])
    rows = conn.execute(
        """
        SELECT r.company, r.id AS report_id, r.title, r.period_type,
               s.statement_type, s.year, s.line_name_norm, s.value,
               s.unit, s.currency, s.page_no
        FROM statements s JOIN reports r ON r.id = s.report_id
        WHERE s.year IS NOT NULL AND s.value IS NOT NULL
        """
    ).fetchall()

    # key: (company, year, metric) -> 得分最高的候选行
    best: dict[tuple[str, int, str], dict[str, Any]] = {}
    for row in rows:
        rule = None
        for metric, candidate_rule in METRIC_RULES.items():
            if row["statement_type"] != candidate_rule["statement_type"]:
                continue
            if _candidate_score(row["line_name_norm"], candidate_rule) is not None:
                rule = (metric, candidate_rule)
                break
        if rule is None:
            continue
        metric, metric_rule = rule
        base_score = _candidate_score(row["line_name_norm"], metric_rule) or 0
        period_score = {"annual": 30, "interim": 20, "q3": 15}.get(
            row["period_type"] or "", 0
        )
        score = base_score + period_score
        key = (row["company"], row["year"], metric)
        current = best.get(key)
        if current is None or score > current["_score"]:
            best[key] = {
                "_score": score,
                "company": row["company"],
                "year": row["year"],
                "period_type": row["period_type"] or "annual",
                "name": metric,
                "value": row["value"],
                "unit": row["unit"],
                "currency": row["currency"],
                "report_id": row["report_id"],
                "page_no": row["page_no"],
                "line_name": row["line_name_norm"],
            }

    output: list[dict[str, Any]] = []
    for (company, year, metric), base in sorted(best.items()):
        item = {k: v for k, v in base.items() if not k.startswith("_")}
        output.append(item)

    revenue_by_key = {
        (b["company"], b["year"]): b["value"] for b in output if b["name"] == "revenue"
    }
    net_profit_by_key = {
        (b["company"], b["year"]): b["value"]
        for b in output
        if b["name"] == "net_profit"
    }
    equity_by_key = {
        (b["company"], b["year"]): b["value"]
        for b in output
        if b["name"] == "total_equity"
    }
    gross_profit_by_key = {
        (b["company"], b["year"]): b["value"]
        for b in output
        if b["name"] == "gross_profit"
    }

    for (company, year), revenue in revenue_by_key.items():
        if revenue is None or revenue == 0:
            continue
        period_type = next(
            (
                b["period_type"]
                for b in output
                if b["company"] == company and b["year"] == year and b["name"] == "revenue"
            ),
            "annual",
        )
        gross_profit = gross_profit_by_key.get((company, year))
        net_profit = net_profit_by_key.get((company, year))
        equity = equity_by_key.get((company, year))
        if gross_profit is not None:
            output.append(
                _derived(company, year, period_type, "gross_margin", gross_profit / revenue)
            )
        if net_profit is not None:
            output.append(
                _derived(company, year, period_type, "net_margin", net_profit / revenue)
            )
        if equity is not None and equity != 0 and net_profit is not None:
            output.append(_derived(company, year, period_type, "roe", net_profit / equity))

    deleted = conn.execute("DELETE FROM indicators").rowcount
    source_ids = {
        (row["report_id"], row["page_no"]): row["id"]
        for row in conn.execute(
            "SELECT id, report_id, page_no FROM sources WHERE table_index=0"
        ).fetchall()
    }
    inserted = 0
    for item in output:
        source_id = source_ids.get((item.get("report_id"), item.get("page_no")))
        conn.execute(
            """
            INSERT INTO indicators(company, year, period_type, name, value, unit,
                                   currency, report_id, page_no, line_name, source_id)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                item["company"],
                item["year"],
                item["period_type"],
                item["name"],
                item["value"],
                item.get("unit"),
                item.get("currency"),
                item.get("report_id"),
                item.get("page_no"),
                item.get("line_name"),
                source_id,
            ),
        )
        inserted += 1
    conn.commit()
    conn.close()
    return {"indicators": inserted, "deleted": deleted}


def _derived(
    company: str, year: int, period_type: str, name: str, value: float
) -> dict[str, Any]:
    return {
        "company": company,
        "year": year,
        "period_type": period_type,
        "name": name,
        "value": value,
        "unit": "ratio",
        "currency": None,
        "report_id": None,
        "page_no": None,
        "line_name": None,
    }
