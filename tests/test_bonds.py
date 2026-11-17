"""Treasury bond rules (D-026): hand-computed cases and official PKO / Ministry of Finance figures."""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from finance_analytics.portfolio import bonds as B
from finance_analytics.sources import bonds as files

D = Decimal


def params(series="EDO0335", type_=None, first="5.00", margin="2.00", fee="2.00"):
    return B.SeriesParams(series, type_ or series[:3], D(first), None if margin is None else D(margin), D(fee))


@pytest.fixture(scope="module")
def shipped():
    """Parameters and official rates exactly as shipped in src/finance_analytics/resources/."""
    table = files.load_series(config_dir=Path("does-not-exist"))
    series = {
        code: B.SeriesParams(code, e["type"], e["first_rate"], e["margin"], e["early_fee"], e["maturity_interest"])
        for code, e in table.series.items()
    }
    official = {key: rate for key, (rate, _) in table.rates.items()}
    reference = tuple(sorted((date.fromisoformat(day), rate) for day, rate in table.reference))
    return series, B.MarketData(official=official, reference=reference), table


# ---------------------------------------------------------------------------------- calendar


def test_months_are_anchored_on_the_purchase_day_and_clamped():
    assert B.add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)  # OTS bought 30.11 -> 28.02 (letter OTS0227)
    assert B.add_months(date(2026, 11, 30), 4) == date(2027, 3, 30)  # back to the 30th, not drifting
    assert B.add_months(date(2024, 2, 29), 12) == date(2025, 2, 28)
    assert B.maturity("EDO", date(2026, 7, 15)) == date(2036, 7, 15)
    assert B.series_maturity_month("EDO0736") == (2036, 7)


def test_tenth_working_day_skips_weekends_and_polish_holidays():
    # Before 1.01.2026: 31, 30, 29.12, then 24-26.12 (24.12 is a day off from 2025) and the weekend are skipped.
    assert B.working_days_before(date(2026, 1, 1), 10) == date(2025, 12, 15)
    # Before 1.07.2025: Corpus Christi on 19.06.2025 is skipped.
    assert B.working_days_before(date(2025, 7, 1), 10) == date(2025, 6, 16)


# ----------------------------------------------------------------------------- hand-computed


def test_edo_capitalises_yearly_and_indexes_to_cpi_two_months_back():
    p = params("EDO0334", first="5.00", margin="2.00")
    # Period 2 starts 15.03.2025: the CPI announced in February is the y/y figure for January 2025.
    data = B.MarketData(cpi_yoy={(2025, 1): D("104.0"), (2025, 2): D("199.9")})
    periods = B.schedule(p, date(2024, 3, 15), data)
    assert len(periods) == 10 and periods[1].rate == D("6.0") and periods[1].source == B.RATE_CPI
    # 184 days into period 1 (365 days): 100 * (1 + 5% * 184/365) = 102.5205 -> 102.52
    assert B.gross_value(p, periods, date(2024, 9, 15)) == D("102.52")
    # Period 2 on the base 105 (no rounding at capitalisation): 105 * (1 + 6% * 184/365) = 108.1759 -> 108.18
    assert B.gross_value(p, periods, date(2025, 9, 15)) == D("108.18")
    assert B.gross_value(p, periods, date(2024, 3, 14)) is None


def test_negative_inflation_counts_as_zero_and_missing_cpi_uses_margin_only():
    p = params("ROS0336", first="5.00", margin="2.00")
    deflation = B.schedule(p, date(2030, 3, 1), B.MarketData(cpi_yoy={(2031, 1): D("99.4")}), until=date(2031, 3, 1))
    assert deflation[1].rate == D("2.00") and deflation[1].source == B.RATE_CPI
    missing = B.schedule(p, date(2030, 3, 1), B.MarketData(), until=date(2031, 3, 1))
    assert missing[1].rate == D("2.00") and missing[1].source == B.RATE_MARGIN_ONLY
    assert "01.2031" in missing[1].note


def test_official_rate_wins_over_computed_cpi():
    p = params("EDO0334", first="6.80", margin="1.50")
    data = B.MarketData(official={("EDO0334", 2): D("6.80")}, cpi_yoy={(2025, 1): D("104.9")})
    # GUS later revised January 2025 to 104.9; the rate was set on the announced 105.3 (MF: 6.80%).
    assert B.schedule(p, date(2024, 3, 1), data, until=date(2025, 3, 1))[1].rate == D("6.80")


def test_coi_pays_a_yearly_coupon_net_of_tax():
    p = params("COI0627", first="7.00", margin="1.25", fee="0.70")
    data = B.MarketData(cpi_yoy={(2024, 4): D("102.4"), (2025, 4): D("104.3"), (2026, 4): D("102.0")})
    periods = B.schedule(p, date(2023, 6, 10), data)
    assert [x.rate for x in periods] == [D("7.00"), D("3.65"), D("5.55"), D("3.25")]
    paid = B.payments(p, periods)
    assert [(x.date, x.amount, x.interest) for x in paid[:2]] == [
        (date(2024, 6, 10), D("7.00"), D("7.00")), (date(2025, 6, 10), D("3.65"), D("3.65"))]
    assert paid[-1].amount == D("103.25") and paid[-1].final
    # A coupon type restarts from 100 zł every period: 100 * (1 + 3.65% * 30/365) = 100.30
    assert B.gross_value(p, periods, date(2024, 7, 10)) == D("100.30")
    assert B.tax(D("7.00"), 10, tax_free=False) == D("13.30")  # 19% of 70.00 zł
    assert B.tax(D("7.00"), 10, tax_free=True) == 0


def test_tos_is_fixed_and_capitalised():
    p = params("TOS0127", first="6.50", margin=None, fee="0.70")
    periods = B.schedule(p, date(2024, 1, 1), B.MarketData())
    assert {x.rate for x in periods} == {D("6.50")} and {x.source for x in periods} == {B.RATE_FIXED}
    (redemption,) = B.payments(p, periods)
    assert redemption.date == date(2027, 1, 1) and redemption.amount == D("120.79")  # 100 * 1.065^3 = 120.795


def test_ror_follows_the_nbp_reference_rate_fixed_ten_working_days_before_the_month():
    p = params("ROR0626", first="6.00", margin="0.00", fee="0.50")
    data = B.MarketData(reference=((date(2025, 5, 8), D("5.25")), (date(2025, 7, 3), D("5.00"))))
    periods = B.schedule(p, date(2025, 6, 20), data)
    assert len(periods) == 12
    # Period 2 (from 20.07) uses the rate in force on 16.06 (5.25%); the July cut counts from period 3.
    assert (periods[1].rate, periods[2].rate) == (D("5.25"), D("5.00"))
    # Monthly coupon 100 * 5.25% / 12 = 0.4375 -> 0.44
    assert B.payments(p, periods)[1].amount == D("0.44")
    # 15 of 30 days of period 1: 100 * (1 + 6% * 15 / (30 * 12)) = 100.25
    assert B.gross_value(p, periods, date(2025, 7, 5)) == D("100.25")


def test_ots_pays_a_quarter_of_the_rate_and_nothing_on_early_redemption():
    p = params("OTS0227", first="2.00", margin=None, fee="0")
    periods = B.schedule(p, date(2026, 11, 30), B.MarketData())
    (redemption,) = B.payments(p, periods)
    assert redemption.date == date(2027, 2, 28) and redemption.amount == D("100.50")  # letter OTS0227: 100,50 zł
    assert B.early_redemption(p, periods, date(2027, 1, 15)) == D("100")


def test_ots_interest_is_the_amount_fixed_in_the_letter(shipped):
    """List emisyjny 87/2018 (OTS0419, 1.50%): interest at maturity 0,37 zl, not 100 * 1.5% / 4 = 0,375 -> 0,38."""
    series, data, _ = shipped
    p = series["OTS0419"]
    periods = B.schedule(p, date(2019, 1, 1), data)
    assert B.payments(p, periods)[0].amount == D("100.37")
    # 45 of 90 days: 0.37 * 45/90 = 0.185, rounded half up per bond -> 100.19
    assert B.gross_value(p, periods, date(2019, 2, 15)) == D("100.19")


def test_early_redemption_fee_is_capped_by_the_rules_of_each_type():
    edo = params("EDO0335", first="5.00", margin="2.00", fee="3.00")
    periods = B.schedule(edo, date(2025, 3, 3), B.MarketData())
    assert B.early_redemption(edo, periods, date(2025, 3, 20)) == D("100")  # fee cannot exceed the interest
    coi = params("COI0329", first="5.00", margin="1.50", fee="2.00")
    periods = B.schedule(coi, date(2025, 3, 3), B.MarketData(official={("COI0329", 2): D("6.00")}))
    assert B.early_redemption(coi, periods, date(2025, 3, 20)) == D("100")  # period 1: capped
    # Period 2, 4 days in: 100 * (1 + 6% * 4/365) = 100.0658 -> 100.07 - 2.00 = 98.07 (fee in full)
    assert B.early_redemption(coi, periods, date(2026, 3, 7)) == D("98.07")


def test_pko_early_redemption_example_edo():
    """obligacjeskarbowe.pl, EDO offer page (checked 2026-11-16): EDO0524 bought 10.05.2014, 4.00% then 1.50%,
    redeemed with interest accrued to 16.06.2015 = 4.16 zł; pays 100 + 4.16 - 2.00 fee - 0.41 tax = 101.75 zł."""
    p = params("EDO0524", first="4.00", margin="1.00", fee="2.00")
    data = B.MarketData(official={("EDO0524", 2): D("1.50")})
    status = B.lot_status(p, date(2014, 5, 10), 1, date(2015, 6, 17), data)
    assert status.gross == D("104.16") and status.early == D("102.16")
    assert status.tax == D("0.41") and status.payout == D("101.75")
    assert B.lot_status(p, date(2014, 5, 10), 1, date(2015, 6, 17), data, tax_free=True).payout == D("102.16")


# -------------------------------------------------- official interest tables (obligacjeskarbowe.pl)


def test_official_interest_table_edo0129(shipped):
    """PKO 'tabela odsetkowa' EDO0129, period 8 (2026-01-01 -> 2027-01-01, 4.00%), issued 2025-12-16,
    for one bond bought on 2019-01-01. Interest per bond: 02.01.2026 66,84; 02.02.2026 67,41; 31.12.2026 73,48."""
    series, data, _ = shipped
    periods = B.schedule(series["EDO0129"], date(2019, 1, 1), data)
    assert [x.rate for x in periods[:8]] == [D(r) for r in ("2.70", "4.10", "4.50", "9.30", "19.00", "8.10", "6.20",
                                                             "4.00")]
    for day, interest in ((date(2026, 1, 2), "66.84"), (date(2026, 2, 2), "67.41"), (date(2026, 12, 31), "73.48")):
        assert B.gross_value(series["EDO0129"], periods, day) - 100 == D(interest)


def test_official_interest_table_tos0127_uses_the_unrounded_base(shipped):
    """PKO 'tabela odsetkowa' TOS0127, period 3 (6.50%), issued 2023-12-22, bond bought 2024-01-01.
    14.01.2026: 13,69 (a base rounded to 113.42 would give 13,68); 12.11.2026: 19,79; 05.06.2026: 16,55."""
    series, data, _ = shipped
    periods = B.schedule(series["TOS0127"], date(2024, 1, 1), data)
    for day, interest in ((date(2026, 1, 14), "13.69"), (date(2026, 11, 12), "19.79"), (date(2026, 6, 5), "16.55")):
        assert B.gross_value(series["TOS0127"], periods, day) - 100 == D(interest)


def test_official_interest_tables_coupon_types(shipped):
    """PKO tables: COI0328 period 3 (3.45%, issued 2026-02-17, bought 2024-03-01): 01.04.2026 0,29;
    ROR0127 period 1 (4.25%, issued 2025-12-23, bought 2026-01-01): 12.01.2026 0,13."""
    series, data, _ = shipped
    coi = B.schedule(series["COI0328"], date(2024, 3, 1), data)
    assert coi[2].rate == D("3.45") and B.gross_value(series["COI0328"], coi, date(2026, 4, 1)) == D("100.29")
    ror = B.schedule(series["ROR0127"], date(2026, 1, 1), data)
    assert ror[0].rate == D("4.25") and B.gross_value(series["ROR0127"], ror, date(2026, 1, 12)) == D("100.13")


# ------------------------------------------------------------------------------ shipped files


def test_shipped_series_are_consistent(shipped):
    series, _, table = shipped
    assert len(series) > 600
    for code, p in series.items():
        assert files.SERIES_RE.match(code), code
        kind = B.TYPES[p.type]
        assert (p.margin is None) == (kind.index is None), code
        assert p.early_fee > 0 or p.type == "OTS", code
    rows = list(csv.DictReader(io.StringIO(files.resource_bytes("bond_series.csv").decode("utf-8"))))
    for row in rows:  # a purchase on the first day of sale must mature in the month the code says
        assert files.check_purchase(row["series"], date.fromisoformat(row["sale_start"]), series) is None, row
    assert {code for code, _ in table.rates} <= set(series)


def test_shipped_ror_dor_rates_follow_the_reference_rule(shipped):
    """Every official ROR/DOR rate in the shipped file is reproduced from the shipped NBP history."""
    series, data, table = shipped
    without_official = B.MarketData(reference=data.reference)
    checked = 0
    for (code, number), (rate, _) in table.rates.items():
        if code[:3] not in ("ROR", "DOR"):
            continue
        p = series[code]
        start = B.add_months(date(2000 + int(code[5:7]), int(code[3:5]), 1), -B.TYPES[p.type].term_months)
        start = B.add_months(start, number - 1)
        computed, source, _ = B.period_rate(p, number, start, without_official)
        assert (computed, source) == (rate, B.RATE_REFERENCE), (code, number)
        checked += 1
    assert checked > 1000


def test_paid_out_lists_coupons_made_up_to_the_day():
    p = params("COI0627", first="7.00", margin="1.25", fee="0.70")
    data = B.MarketData(cpi_yoy={(2024, 4): D("102.4"), (2025, 4): D("104.3")})
    paid = B.paid_out(p, date(2023, 6, 10), data, date(2025, 6, 10))
    assert [(x.date, x.amount) for x in paid] == [(date(2024, 6, 10), D("7.00")), (date(2025, 6, 10), D("3.65"))]
    assert B.paid_out(p, date(2023, 6, 10), data, date(2024, 6, 9)) == []
