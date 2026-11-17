"""Market data: NBP and Yahoo clients and the incremental cache, all offline (fakes only)."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date, timedelta

import pandas as pd
import pytest
from conftest import go_online

from finance_analytics.config import Settings
from finance_analytics.db import connect, migrate
from finance_analytics.market import cache, nbp, yahoo
from finance_analytics.market.update import update_market
from finance_analytics.mock.xtb_export import write_mock_export
from finance_analytics.sources.sync import import_xtb, sync

TODAY = date(2026, 11, 16)  # a Monday


@pytest.fixture
def conn(tmp_path):
    with closing(connect(tmp_path / "m.db")) as c:
        migrate(c)
        yield c


# ---------------------------------------------------------------------- cache


def test_missing_ranges():
    d = date.fromisoformat
    assert cache.missing_ranges(None, d("2026-01-01"), d("2026-01-31")) == [(d("2026-01-01"), d("2026-01-31"))]
    covered = (d("2026-01-10"), d("2026-01-20"))
    assert cache.missing_ranges(covered, d("2026-01-01"), d("2026-01-31")) == [
        (d("2026-01-01"), d("2026-01-09")),
        (d("2026-01-21"), d("2026-01-31")),
    ]
    assert cache.missing_ranges(covered, d("2026-01-12"), d("2026-01-20")) == []
    assert cache.missing_ranges(covered, d("2026-01-12"), d("2026-01-20"), overlap_days=3) == [
        (d("2026-01-18"), d("2026-01-20"))
    ]


def test_record_extends_and_errors_do_not(conn):
    d = date.fromisoformat
    cache.record_error(conn, "nbp", "USD", "boom")
    assert cache.coverage(conn, "nbp", "USD") is None
    cache.record(conn, "nbp", "USD", d("2026-01-10"), d("2026-01-20"))
    cache.record(conn, "nbp", "USD", d("2026-01-01"), d("2026-01-15"))
    assert cache.coverage(conn, "nbp", "USD") == (d("2026-01-01"), d("2026-01-20"))
    cache.record_error(conn, "nbp", "USD", "later failure")
    assert cache.coverage(conn, "nbp", "USD") == (d("2026-01-01"), d("2026-01-20"))


# ------------------------------------------------------------------------ NBP


class FakeResponse:
    def __init__(self, status: int, payload: dict | None = None):
        self.status_code, self._payload = status, payload or {}

    def json(self):
        return self._payload


def fake_nbp_get(calls):
    """Business days get a rate of 4 + day/100; ranges without business days return 404."""

    def get(url, headers, timeout):
        assert headers["User-Agent"] == "finance-analytics"  # nothing personal in requests
        calls.append(url)
        start, end = (date.fromisoformat(part) for part in url.split("/")[-3:-1])
        days = [start + timedelta(n) for n in range((end - start).days + 1)]
        rates = [
            {"no": f"{d:%j}/A/NBP/{d:%Y}", "effectiveDate": d.isoformat(), "mid": 4 + d.day / 100}
            for d in days if d.weekday() < 5
        ]
        return FakeResponse(200, {"rates": rates}) if rates else FakeResponse(404)

    return get


def test_fetch_rates_splits_long_ranges_and_handles_404():
    calls = []
    rates = nbp.fetch_rates("USD", date(2026, 1, 1), date(2026, 6, 30), get=fake_nbp_get(calls))
    assert len(calls) == 2 and all("/rates/a/usd/" in url for url in calls)  # 181 days -> 93 + 88
    assert rates[0][0] == date(2026, 1, 1) and all(d.weekday() < 5 for d, _, _ in rates)
    weekend = []
    assert nbp.fetch_rates("EUR", date(2026, 11, 14), date(2026, 11, 15), get=fake_nbp_get(weekend)) == []


def test_fetch_rates_raises_on_server_error():
    with pytest.raises(nbp.NbpError, match="HTTP 500"):
        nbp.fetch_rates("USD", TODAY, TODAY, get=lambda *a, **k: FakeResponse(500))


def test_update_fx_is_incremental(conn):
    calls = []

    def fetch(currency, start, end):
        return nbp.fetch_rates(currency, start, end, get=fake_nbp_get(calls))

    report = nbp.update_fx(conn, {"USD": date(2026, 10, 1), "PLN": date(2026, 1, 1)}, TODAY, fetch=fetch)
    assert report.fetched["USD"] > 30 and "PLN" not in report.fetched
    assert cache.coverage(conn, "nbp", "USD")[1] == TODAY - timedelta(days=1)  # today is never final
    calls.clear()
    nbp.update_fx(conn, {"USD": date(2026, 10, 1)}, TODAY, fetch=fetch)
    assert len(calls) == 1 and calls[0].endswith(f"/{TODAY}/{TODAY}/?format=json")


# ---------------------------------------------------------------------- Yahoo


class FakePriceClient:
    def __init__(self, currency="USD", fail=None):
        self.currency, self.fail, self.calls = currency, fail or set(), []

    def history(self, ticker, start, end):
        self.calls.append((ticker, start, end))
        if ticker in self.fail:
            raise yahoo.YahooError(f"{ticker}: not found")
        days = [start + timedelta(n) for n in range((end - start).days + 1)]
        prices = [(d, 100 + d.toordinal() % 50) for d in days if d.weekday() < 5]
        return yahoo.History(prices=prices, currency=self.currency if prices else None, name=ticker)


def test_update_prices_incremental_with_refetch_window(conn):
    client = FakePriceClient()
    report = yahoo.update_prices(conn, {"NVDA": date(2026, 9, 1)}, TODAY, client=client)
    assert report.fetched["NVDA"] > 50 and report.currencies == {"NVDA": "USD"}
    client.calls.clear()
    yahoo.update_prices(conn, {"NVDA": date(2026, 9, 1)}, TODAY, client=client)
    (_, start, end), = client.calls
    assert end == TODAY and (TODAY - start).days == yahoo.REFETCH_DAYS


def test_update_prices_records_errors_and_continues(conn):
    client = FakePriceClient(fail={"BAD"})
    report = yahoo.update_prices(conn, {"BAD": date(2026, 9, 1), "GOOD": date(2026, 9, 1)}, TODAY, client=client)
    assert "BAD" in report.errors and report.fetched["GOOD"] > 0
    error = conn.execute("SELECT last_error FROM fetch_log WHERE key = 'BAD'").fetchone()[0]
    assert "not found" in error


def test_unknown_ticker_gives_polish_warning_and_is_not_asked_again(monkeypatch, conn):
    import yfinance

    calls = []

    class FakeTicker:
        history_metadata: dict = {}

        def __init__(self, ticker):
            calls.append(ticker)

        def history(self, **kwargs):
            raise RuntimeError("$COIN.DE: possibly delisted; no timezone found")

    monkeypatch.setattr(yfinance, "Ticker", FakeTicker)
    needed = {"COIN.DE": date(2026, 9, 1)}
    report = yahoo.update_prices(conn, needed, TODAY)
    assert report.errors["COIN.DE"].startswith("Brak notowań w Yahoo dla COIN.DE — ")
    assert "delisted" not in report.errors["COIN.DE"] and len(calls) == 1
    again = yahoo.update_prices(conn, needed, TODAY)  # fresh error: no new request
    assert len(calls) == 1 and again.errors["COIN.DE"] == report.errors["COIN.DE"]
    conn.execute("UPDATE fetch_log SET fetched_at = '2000-01-01T00:00:00+00:00'")  # old error: tried again
    yahoo.update_prices(conn, needed, TODAY)
    assert len(calls) == 2


def test_update_prices_stops_asking_after_a_rate_limit(conn):
    # Without this, every remaining ticker would back off again (35 s each) before failing.
    class Client(FakePriceClient):
        def history(self, ticker, start, end):
            self.calls.append((ticker, start, end))
            raise yahoo.YahooRateLimitError(f"{ticker}: Yahoo rate limit, try again later")

    client = Client()
    report = yahoo.update_prices(conn, {t: date(2026, 9, 1) for t in ("AAA", "BBB", "CCC")}, TODAY, client=client)
    assert [c[0] for c in client.calls] == ["AAA"]
    assert set(report.errors) == {"AAA", "BBB", "CCC"} and "skipped" in report.errors["CCC"]


def test_update_prices_stops_at_the_last_needed_day_of_a_closed_ticker(conn):
    client = FakePriceClient()
    sold = date(2026, 10, 9)
    yahoo.update_prices(conn, {"OLD": date(2026, 9, 1)}, TODAY, client=client, until={"OLD": sold})
    (_, _, end), = client.calls
    assert end == sold
    client.calls.clear()
    yahoo.update_prices(conn, {"OLD": date(2026, 9, 1)}, TODAY, client=client, until={"OLD": sold})
    assert client.calls == []  # fully cached: no request at all


def test_update_prices_reports_progress(conn):
    seen = []
    yahoo.update_prices(conn, {"B": date(2026, 11, 1), "A": date(2026, 11, 1)}, TODAY, client=FakePriceClient(),
                        progress=lambda *args: seen.append(args))
    assert seen == [("A", 0, 2), ("B", 1, 2)]


def test_closed_until_skips_tickers_still_held(conn):
    from finance_analytics.market.update import closed_until

    conn.execute("INSERT INTO accounts (id, alias, institution, kind, currency) "
                 "VALUES ('a', 'A', 'xtb', 'broker', 'USD')")
    conn.executemany("INSERT INTO instruments (id, xtb_symbol, asset_class, yahoo_ticker) VALUES (?, ?, 'stock', ?)",
                     [(1, "OLD.US", "OLD"), (2, "HELD.US", "HELD"), (3, "ODD.PL", None)])
    conn.executemany(
        "INSERT INTO positions (account_id, position_id, instrument_id, side, volume, open_time, open_price, "
        "close_time) VALUES ('a', ?, ?, 'BUY', 1, ?, 1, ?)",
        [("1", 1, "2025-01-02T10:00:00", "2025-06-02T10:00:00"),
         ("2", 2, "2025-01-02T10:00:00", "2025-03-02T10:00:00"),
         ("3", 2, "2025-04-02T10:00:00", None),
         ("4", 3, "2025-01-02T10:00:00", "2025-02-02T10:00:00")],
    )
    # A dividend paid after the sale extends the needed range.
    conn.execute("INSERT INTO cash_ledger (account_id, ts, type, amount, instrument_id, broker_type, source_ref) "
                 "VALUES ('a', '2025-06-20T08:00:00', 'DIVIDEND', 1, 1, 'Dividend', 'd1')")
    assert closed_until(conn) == {"OLD": date(2025, 6, 20)}


def test_yahoo_client_converts_pence_and_reads_actions(monkeypatch):
    import yfinance

    class FakeTicker:
        def __init__(self, ticker):
            self.history_metadata = {"currency": "GBp", "longName": "Fake plc", "exchangeName": "LSE"}

        def history(self, **kwargs):
            assert kwargs["auto_adjust"] is False and kwargs["actions"] is True
            index = pd.to_datetime(["2026-11-12", "2026-11-13"]).tz_localize("Europe/London")
            return pd.DataFrame(
                {"Close": [1234.5, 1250.0], "Dividends": [0.0, 12.0], "Stock Splits": [0.0, 2.0]}, index=index
            )

    monkeypatch.setattr(yfinance, "Ticker", FakeTicker)
    history = yahoo.YahooClient().history("FAKE.L", date(2026, 11, 12), date(2026, 11, 13))
    assert history.currency == "GBP"
    assert history.prices == [(date(2026, 11, 12), 12.345), (date(2026, 11, 13), 12.5)]
    assert history.dividends == [(date(2026, 11, 13), 0.12)] and history.splits == [(date(2026, 11, 13), 2.0)]


# ----------------------------------------------------------------- end to end


def test_update_market_on_imported_mock_export(tmp_path):
    settings = Settings(data_dir=tmp_path / "data")
    export = tmp_path / "export"
    write_mock_export(export)
    import_xtb(export, settings)
    sync(settings)
    go_online(settings)

    class Client(FakePriceClient):
        def history(self, ticker, start, end):
            self.currency = "USD"
            return super().history(ticker, start, end)

    steps = []
    report = update_market(
        settings, today=TODAY, price_client=Client(),
        fx_fetch=lambda c, s, e: nbp.fetch_rates(c, s, e, get=fake_nbp_get([])),
        cpi_fetch=lambda: [(2026, 1, 100.0, 103.0)],
        progress=lambda *args: steps.append(args),
    )
    assert not report.errors and not report.unresolved
    assert [s[2] for s in steps] == list(range(15)) and {s[3] for s in steps} == {15}  # 13 tickers, NBP, GUS
    assert [s[0] for s in steps[-2:]] == ["nbp", "gus"]
    assert set(report.prices.fetched) == {"NVDA", "TSLA", "AMD", "MSFT", "AAPL", "GOOGL", "AMZN", "META",
                                          "VUAA.L", "IWDA.L", "VWRA.L", "EIMI.L", "SGLN.L"}
    assert set(report.fx.fetched) == {"USD", "EUR"}  # account + price currencies, never PLN
    with closing(sqlite3.connect(settings.db_path)) as c:
        first_fx = c.execute("SELECT MIN(date) FROM fx_rates WHERE currency = 'USD'").fetchone()[0]
    assert first_fx <= "2024-11-01"  # covers the first operation

    # Market cache survives a projection rebuild.
    sync(settings, force=True)
    with closing(sqlite3.connect(settings.db_path)) as c:
        assert c.execute("SELECT COUNT(*) FROM prices").fetchone()[0] > 0


def test_bank_balance_currency_needs_nbp_rates(conn):
    # Regression (D-029): a EUR bank account with no broker operations must still get EUR rates.
    from finance_analytics.market.update import needed_currencies

    conn.execute("INSERT INTO accounts (id, alias, institution, kind, currency) "
                 "VALUES ('bank-eur', 'Konto EUR', 'bank', 'bank', 'EUR')")
    conn.execute("INSERT INTO cash_snapshots (account_id, date, balance, row_no) "
                 "VALUES ('bank-eur', '2025-03-01', 1, 1)")
    assert needed_currencies(conn, {}) == {"EUR": date(2025, 3, 1)}


def test_symbol_without_history_for_the_period_is_reported_in_polish_and_not_asked_again(conn):
    """D-046: e.g. a delisted share whose symbol now belongs to another company."""

    class Empty(FakePriceClient):
        def history(self, ticker, start, end):
            self.calls.append((ticker, start, end))
            return yahoo.History(prices=[], currency=None, name=ticker)

    client = Empty()
    sold = date(2022, 11, 10)
    needed = {"OLD": date(2022, 8, 16)}
    report = yahoo.update_prices(conn, needed, TODAY, client=client, until={"OLD": sold})
    assert report.errors["OLD"].startswith("Brak notowań w Yahoo dla OLD w okresie 09.08.2022–10.11.2022 — ")
    assert "z cen Twoich transakcji" in report.errors["OLD"]
    again = yahoo.update_prices(conn, needed, TODAY, client=client, until={"OLD": sold})
    assert len(client.calls) == 1 and again.errors["OLD"] == report.errors["OLD"]
