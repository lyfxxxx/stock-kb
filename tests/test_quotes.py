import json
from pathlib import Path

import pytest

from stock_kb.quotes import QuoteError, fetch_quote, pe_ttm, scale_to_units


def test_scale_to_units():
    assert scale_to_units(4708.084, "千元") == pytest.approx(4_708_084)
    assert scale_to_units(4.7, "亿元") == pytest.approx(470_000_000)
    assert scale_to_units(10, None) == 10


def test_pe_ttm_converts_to_cny(monkeypatch):
    quote = {
        "price": 10.0,
        "currency": "HKD",
        "market_cap": 10_000_000_000,
        "market_cap_cny": 8_500_000_000,
        "price_cny": 8.5,
        "report_currency": "CNY",
    }
    out = pe_ttm(quote, ttm_profit=850_000_000, ttm_profit_currency="CNY")
    assert out["pe_ttm"] == pytest.approx(10.0)
    assert out["ttm_profit_cny"] == pytest.approx(850_000_000)


def test_fetch_quote_uses_yfinance_and_fx(monkeypatch):
    from stock_kb import quotes as q

    monkeypatch.setattr(
        q,
        "_yf_fast",
        lambda symbol: {
            "source": "yfinance",
            "symbol": symbol,
            "price": 11.57,
            "currency": "HKD",
            "market_cap": 62_000_000_000,
            "as_of": "2026-09-04",
        },
    )
    monkeypatch.setattr(q, "_yf_fx", lambda pair: 0.856)
    monkeypatch.setattr(q, "_ak_fx", lambda pair: None)
    got = fetch_quote("海底捞")
    assert got["ok"] is True
    assert got["currency"] == "HKD"
    assert got["price_cny"] == pytest.approx(11.57 * 0.856)
    assert got["market_cap_cny"] == pytest.approx(62_000_000_000 * 0.856)


def test_fetch_quote_fails_without_price(monkeypatch):
    from stock_kb import quotes as q

    monkeypatch.setattr(q, "_yf_fast", lambda symbol: None)
    monkeypatch.setattr(q, "_ak_hk", lambda symbol: None)
    monkeypatch.setattr(q, "_ak_us", lambda symbol: None)
    with pytest.raises(QuoteError):
        fetch_quote("海底捞")


def test_quote_cli_returns_nonzero_on_quote_error(monkeypatch, capsys):
    from stock_kb import cli
    from stock_kb import quotes as q

    monkeypatch.setattr(
        q,
        "fetch_quote",
        lambda *args, **kwargs: (_ for _ in ()).throw(q.QuoteError("无法取得 市值")),
    )
    rc = cli.main(["quote", "--company", "海底捞", "--json"])
    assert rc == 1
    out = capsys.readouterr().out
    payload = json.loads(out[out.find("{") :])
    assert payload["ok"] is False
    assert "市值" in payload["error"]


def test_module_entrypoint_exits_with_main_code():
    text = Path(__file__).resolve().parents[1].joinpath("stock_kb", "__main__.py").read_text(
        encoding="utf-8"
    )
    assert "SystemExit(main())" in text or "sys.exit(main())" in text


def test_fetch_quote_fails_without_market_cap(monkeypatch):
    from stock_kb import quotes as q

    monkeypatch.setattr(
        q,
        "_yf_fast",
        lambda symbol: None,
    )
    monkeypatch.setattr(
        q,
        "_ak_hk",
        lambda symbol: {
            "source": "akshare",
            "symbol": symbol,
            "price": 11.57,
            "currency": "HKD",
            "market_cap": None,
            "as_of": "2026-09-04",
        },
    )
    monkeypatch.setattr(q, "_ak_us", lambda symbol: None)
    with pytest.raises(QuoteError, match="市值"):
        fetch_quote("海底捞")
