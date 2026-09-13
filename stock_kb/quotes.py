"""Latest listing quotes and FX. Not stored in stock_kb.db.

yfinance is tried first (HK symbols without a leading zero: 6862.HK).
akshare is fallback. akshare Hong Kong daily prices are in HKD.
Quote failure must fail the whole scan report.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

DEFAULT_LISTINGS: dict[str, dict[str, str]] = {
    "海底捞": {
        "yfinance": "6862.HK",
        "akshare_hk": "06862",
        "listing_currency": "HKD",
        "report_currency": "CNY",
    },
    "百胜中国": {
        "yfinance": "YUMC",
        "akshare_us": "YUMC",
        "listing_currency": "USD",
        "report_currency": "USD",
    },
}


class QuoteError(RuntimeError):
    """Raised when price, market cap, or FX cannot be obtained."""


def _listings(cfg: dict[str, Any] | None, company: str) -> dict[str, str]:
    extra = (cfg or {}).get("listings") or {}
    row = extra.get(company) or DEFAULT_LISTINGS.get(company)
    if not row:
        raise QuoteError(f"未配置上市代码: {company}")
    return {k: str(v) for k, v in row.items() if v}


def _yf_fast(symbol: str) -> dict[str, Any] | None:
    try:
        import yfinance as yf
    except ImportError:
        return None
    tk = yf.Ticker(symbol)
    try:
        fi = tk.fast_info
        price = getattr(fi, "last_price", None)
        currency = getattr(fi, "currency", None)
        mcap = getattr(fi, "market_cap", None)
        if price is None:
            hist = tk.history(period="5d")
            if hist is None or hist.empty:
                return None
            price = float(hist["Close"].iloc[-1])
            as_of = hist.index[-1].date().isoformat()
        else:
            price = float(price)
            hist = tk.history(period="5d")
            as_of = (
                hist.index[-1].date().isoformat()
                if hist is not None and not hist.empty
                else date.today().isoformat()
            )
        if mcap is None:
            return None
        return {
            "source": "yfinance",
            "symbol": symbol,
            "price": float(price),
            "currency": str(currency or "").upper() or None,
            "market_cap": float(mcap),
            "as_of": as_of,
        }
    except Exception:
        return None


def _ak_hk(symbol: str) -> dict[str, Any] | None:
    try:
        import akshare as ak
    except ImportError:
        return None
    try:
        df = ak.stock_hk_daily(symbol=symbol, adjust="")
        if df is None or df.empty:
            return None
        last = df.iloc[-1]
        as_of = str(last.get("date") or last.get("日期") or "")[:10]
        close = last.get("close")
        if close is None:
            close = last.get("收盘")
        if close is None:
            return None
        return {
            "source": "akshare",
            "symbol": symbol,
            "price": float(close),
            "currency": "HKD",
            "market_cap": None,
            "as_of": as_of,
        }
    except Exception:
        return None


def _ak_us(symbol: str) -> dict[str, Any] | None:
    try:
        import akshare as ak
    except ImportError:
        return None
    try:
        df = ak.stock_us_daily(symbol=symbol, adjust="")
        if df is None or df.empty:
            return None
        last = df.iloc[-1]
        as_of = str(last.get("date") or "")[:10]
        close = last.get("close")
        if close is None:
            return None
        return {
            "source": "akshare",
            "symbol": symbol,
            "price": float(close),
            "currency": "USD",
            "market_cap": None,
            "as_of": as_of,
        }
    except Exception:
        return None


def _yf_fx(pair: str) -> float | None:
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        hist = yf.Ticker(pair).history(period="5d")
        if hist is None or hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


def _ak_fx(pair: str) -> float | None:
    """pair like USD/CNY or HKD/CNY: units of CNY per 1 foreign."""
    try:
        import akshare as ak
    except ImportError:
        return None
    try:
        df = ak.fx_spot_quote()
        row = df[df["货币对"] == pair]
        if row.empty:
            return None
        bid = float(row.iloc[0]["买报价"])
        ask = float(row.iloc[0]["卖报价"])
        return (bid + ask) / 2.0
    except Exception:
        return None


def fx_to_cny(listing_currency: str) -> tuple[float, str]:
    ccy = listing_currency.upper()
    if ccy in {"CNY", "RMB"}:
        return 1.0, "identity"
    yf_map = {"HKD": "HKDCNY=X", "USD": "USDCNY=X"}
    ak_map = {"HKD": "HKD/CNY", "USD": "USD/CNY"}
    if ccy in yf_map:
        rate = _yf_fx(yf_map[ccy])
        if rate is not None and rate > 0:
            return rate, f"yfinance:{yf_map[ccy]}"
    if ccy in ak_map:
        rate = _ak_fx(ak_map[ccy])
        if rate is not None and rate > 0:
            return rate, f"akshare:{ak_map[ccy]}"
    raise QuoteError(f"无法取得 {ccy}/CNY 实时汇率")


def fetch_quote(company: str, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    spec = _listings(cfg, company)
    listing_ccy = spec.get("listing_currency") or ""
    yf_sym = spec.get("yfinance")
    quote = _yf_fast(yf_sym) if yf_sym else None
    if quote is None and spec.get("akshare_hk"):
        quote = _ak_hk(spec["akshare_hk"])
    if quote is None and spec.get("akshare_us"):
        quote = _ak_us(spec["akshare_us"])
    if quote is None or quote.get("price") is None:
        raise QuoteError(f"无法取得 {company} 最新收盘价")
    if quote.get("market_cap") is None:
        raise QuoteError(
            f"无法取得 {company} 最新市值（akshare 日线无市值；yfinance 未返回 market_cap）"
        )
    ccy = (quote.get("currency") or listing_ccy or "").upper()
    if not ccy:
        raise QuoteError(f"{company} 行情未标明币种")
    if spec.get("akshare_hk") and quote["source"] == "akshare":
        ccy = "HKD"
    fx, fx_src = fx_to_cny(ccy)
    price = float(quote["price"])
    mcap = float(quote["market_cap"])
    return {
        "ok": True,
        "company": company,
        "source": quote["source"],
        "symbol": quote["symbol"],
        "price": price,
        "currency": ccy,
        "market_cap": mcap,
        "as_of": quote["as_of"],
        "fx_to_cny": fx,
        "fx_source": fx_src,
        "price_cny": price * fx,
        "market_cap_cny": mcap * fx,
        "report_currency": spec.get("report_currency") or ccy,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "akshare_hk_note": "akshare 港股日线为港元 HKD",
    }


def scale_to_units(value: float, unit: str | None) -> float:
    """Convert a statement/indicator amount to currency units (元/美元)."""
    u = (unit or "").replace(" ", "").lower()
    if not u or u in {"元", "港元", "美元", "人民币元"}:
        return value
    if "千亿" in u:
        return value * 1e11
    if "百亿" in u:
        return value * 1e10
    if "十亿" in u or u in {"billion", "bn"}:
        return value * 1e9
    if "亿" in u:
        return value * 1e8
    if "百万" in u or "million" in u or u in {"mn", "m"}:
        return value * 1e6
    if "万" in u:
        return value * 1e4
    if "千" in u or "thousand" in u or u in {"k", "'000", "000"}:
        return value * 1e3
    return value


def ttm_net_profit(
    conn,
    company: str,
) -> dict[str, Any]:
    """Latest complete-year net_profit, or H1_t + (FY_{t-1} - H1_{t-1})."""
    rows = conn.execute(
        """
        SELECT i.year, i.period_type, i.value, i.unit, i.currency, i.page_no,
               i.report_id, r.title
        FROM indicators i
        LEFT JOIN reports r ON r.id = i.report_id
        WHERE i.company=? AND i.name='net_profit' AND i.value IS NOT NULL
        ORDER BY i.year DESC
        """,
        (company,),
    ).fetchall()
    if not rows:
        raise QuoteError(f"{company} 无 net_profit 指标，无法算 TTM")
    by: dict[tuple[int, str], dict[str, Any]] = {}
    for r in rows:
        item = dict(r)
        pt = (item.get("period_type") or "annual").lower()
        if pt in {"annual", "year", "fy"}:
            pt = "annual"
        elif pt in {"interim", "h1", "semi", "semiannual", "semi-annual"}:
            pt = "interim"
        else:
            continue
        item["period_type"] = pt
        key = (int(item["year"]), pt)
        if key not in by:
            by[key] = item
    years = sorted({y for y, _ in by}, reverse=True)
    if not years:
        raise QuoteError(f"{company} 无可用年报/中报净利")
    y = years[0]
    loc = None

    def _amt(item: dict[str, Any]) -> float:
        return scale_to_units(float(item["value"]), item.get("unit"))

    def _loc(item: dict[str, Any]) -> str:
        title = (item.get("title") or "").strip()
        page = item.get("page_no")
        if title and page is not None:
            return f"《{title}》第{int(page)}页"
        return ""

    if (y, "interim") in by and (y - 1, "annual") in by and (y - 1, "interim") in by:
        a, fy, b = by[(y, "interim")], by[(y - 1, "annual")], by[(y - 1, "interim")]
        ttm = _amt(a) + _amt(fy) - _amt(b)
        method = "interim_plus_stub"
        locators = [_loc(a), _loc(fy), _loc(b)]
        currency = a.get("currency") or fy.get("currency")
        unit = "元"
    elif (y, "annual") in by:
        fy = by[(y, "annual")]
        ttm = _amt(fy)
        method = "latest_annual"
        locators = [_loc(fy)]
        currency = fy.get("currency")
        unit = "元"
        y = int(fy["year"])
    else:
        raise QuoteError(f"{company} 无法由年报/中报拼出 TTM 归母净利")
    return {
        "company": company,
        "ttm_profit": ttm,
        "currency": (currency or "CNY").upper().replace("RMB", "CNY"),
        "unit": unit,
        "method": method,
        "as_of_year": y,
        "locators": [x for x in locators if x],
    }


def pe_ttm(
    quote: dict[str, Any],
    ttm_profit: float,
    ttm_profit_currency: str,
) -> dict[str, Any]:
    """PE = 最新市值 / TTM 归母净利，统一到人民币后再相除。"""
    if ttm_profit is None:
        raise QuoteError("缺少 TTM 归母净利")
    profit = float(ttm_profit)
    if profit == 0:
        raise QuoteError("TTM 归母净利为 0，无法计算 PE")
    p_ccy = (ttm_profit_currency or quote.get("report_currency") or "").upper()
    if p_ccy in {"RMB"}:
        p_ccy = "CNY"
    if p_ccy in {"CNY"}:
        profit_cny = profit
        profit_fx, profit_fx_src = 1.0, "identity"
    else:
        profit_fx, profit_fx_src = fx_to_cny(p_ccy)
        profit_cny = profit * profit_fx
    mcap_cny = float(quote["market_cap_cny"])
    pe = mcap_cny / profit_cny
    return {
        "ttm_profit": profit,
        "ttm_profit_currency": p_ccy,
        "ttm_profit_cny": profit_cny,
        "ttm_profit_fx_to_cny": profit_fx,
        "ttm_profit_fx_source": profit_fx_src,
        "pe_ttm": pe,
        "market_cap_cny": mcap_cny,
        "price_cny": quote["price_cny"],
    }
