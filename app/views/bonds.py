"""Treasury bonds: value with interest, current rates and an early-redemption estimate (R-008, D-026)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from ui.charts import area_total, current_mode, show
from ui.components import Kpi, empty_state, kpi_row, page_header, section, table
from ui.data import require_database
from ui.fmt import fmt_date, fmt_money, fmt_money_compact, fmt_pct, plural
from ui.glossary import G

from finance_analytics import reports
from finance_analytics.config import get_settings
from finance_analytics.portfolio import bonds as bond_math
from finance_analytics.portfolio.valuation import MODEL_VERSION, BondInputs, data_version, load_inputs
from finance_analytics.sources import bonds as bond_files
from finance_analytics.sources.sync import sync

RATE_SOURCE = {
    bond_math.RATE_FIRST: "oficjalna", bond_math.RATE_FIXED: "oficjalna", bond_math.RATE_OFFICIAL: "oficjalna",
    bond_math.RATE_CPI: "wyliczona", bond_math.RATE_REFERENCE: "wyliczona", bond_math.RATE_MARGIN_ONLY: "tylko marża",
}

page_header("Obligacje", "Obligacje skarbowe: wartość z odsetkami, bieżące oprocentowanie i kwota przy wcześniejszym "
            "wykupie.")
settings = get_settings()
require_database(settings)
csv_path = bond_files.bonds_file(settings.manual_dir)


@st.cache_data(show_spinner="Liczę wartość obligacji…")
def bond_inputs(db_path: str, version: tuple, model: int) -> BondInputs:
    return load_inputs(Path(db_path)).bonds


@st.cache_data(show_spinner=False)
def bond_history(db_path: str, version: tuple, today: date, tax_free: frozenset[str]) -> bond_math.BondValuation:
    inputs = bond_inputs(db_path, version, MODEL_VERSION)
    return bond_math.value_lots(inputs.lots, inputs.params(), inputs.market(), today, tax_free)


def run_sync(message: str) -> None:
    result = sync(settings)
    st.session_state["bonds_message"] = (message, result.errors)
    st.rerun()


def purchase_form(known: set[str], accounts: pd.DataFrame) -> None:
    """'Dodaj zakup obligacji': appends a row to data/manual/bonds.csv and rebuilds the database."""
    with st.container(border=True):
        st.markdown("#### :material/add_card: Dodaj zakup obligacji")
        st.caption(f"Zakup trafia do pliku `{csv_path}` na tym komputerze. Wartość policzy aplikacja.")
        with st.form("bond_purchase", clear_on_submit=True, border=False):
            options = dict(zip(accounts["id"], accounts["alias"], strict=True)) or {
                bond_files.DEFAULT_ACCOUNT_ID: f"{bond_files.DEFAULT_ACCOUNT_ALIAS} (nowy rachunek)"}
            left, middle, right, last = st.columns([2, 2, 2, 1])
            account = left.selectbox("Konto", list(options), format_func=options.get,
                                     help=G["bond_account"])
            series = middle.text_input("Seria", placeholder="np. EDO0736", max_chars=7, help=G["bond_series"])
            purchased = right.date_input("Data zakupu", value=date.today(), max_value=date.today(),
                                         format="DD.MM.YYYY", help=G["bond_purchase"])
            quantity = last.number_input("Liczba sztuk", min_value=1, value=10, step=1, help=G["bond_quantity"])
            note = st.text_input("Notatka (opcjonalnie)", max_chars=120)
            submitted = st.form_submit_button("Dodaj zakup", type="primary", icon=":material/add:")
        if submitted:
            code = series.strip().upper()
            problem = bond_files.check_purchase(code, purchased, known, date.today())
            if problem:
                st.error(problem[0].upper() + problem[1:], icon=":material/error:")
                return
            bond_files.append_lot(csv_path, account, code, purchased, int(quantity), note.strip())
            run_sync(f"Dodano {plural(int(quantity), 'sztukę', 'sztuki', 'sztuk')} {code}.")


if "bonds_message" in st.session_state:
    message, errors = st.session_state.pop("bonds_message")
    st.success(message, icon=":material/check_circle:")
    if errors:
        st.warning(f"Po przebudowie bazy są problemy z plikami ({len(errors)}); szczegóły na dole strony.",
                   icon=":material/warning:")

if reports.bond_series(settings.db_path).empty:
    sync(settings)  # a database synced before bonds existed: build the bond tables now (local, no network)
version = data_version(settings.db_path)
known = set(reports.bond_series(settings.db_path)["series"])
accounts = reports.bond_accounts(settings.db_path)
lots = reports.bond_lots(settings.db_path)
issues = reports.bond_issues(settings.db_path)

today = date.today()
tax_free = frozenset(accounts.loc[accounts["tax_wrapper"].isin(["IKE", "IKZE"]), "id"])
inputs = bond_inputs(str(settings.db_path), version, MODEL_VERSION)
params, market = inputs.params(), inputs.market()

statuses = []
for lot in lots.itertuples(index=False):
    p = params.get(lot.series)
    status = bond_math.lot_status(p, lot.purchase_date.date(), int(lot.quantity), today, market,
                                  tax_free=lot.account_id in tax_free) if p else None
    statuses.append(status)
held = [(lot, s) for lot, s in zip(lots.itertuples(index=False), statuses, strict=True) if s is not None]

if not held:
    empty_state(
        "Nie masz jeszcze obligacji",
        "Dodaj zakup poniżej: wystarczy seria, data zakupu i liczba sztuk. Aplikacja sama policzy odsetki, "
        "także indeksację inflacją, i doliczy obligacje do wartości portfela.",
        icon=":material/account_balance:",
        steps=["Sprawdź serię w historii rachunku w serwisie obligacji (np. EDO0736).",
               "Wpisz ją z datą zakupu i liczbą sztuk w formularzu poniżej."],
    )
    purchase_form(known, accounts)
    if not lots.empty:
        st.caption(f"Wszystkie zapisane obligacje ({len(lots)}) są już wykupione.")
    st.stop()

# ------------------------------------------------------------------------------------------- KPIs
gross = sum(float(s.gross) * s.quantity for _, s in held)
nominal = sum(100.0 * s.quantity for _, s in held)
payout = sum(float(s.payout) for _, s in held)
avg_rate = sum(float(s.period.rate) * float(s.gross) * s.quantity for _, s in held) / gross / 100
history = bond_history(str(settings.db_path), version, today, tax_free)
by_day = history.daily.groupby("date")[["value", "qty"]].sum().sort_index()
total = by_day["value"]
year_ago = pd.Timestamp(today) - pd.DateOffset(years=1)


def weekly(series: pd.Series) -> list[float]:
    """Sparkline over the last year, one point a week."""
    return series[series.index > year_ago].resample("W-FRI").last().dropna().round(0).tolist()


trend = weekly(total)
count = sum(s.quantity for _, s in held)

kpi_row(
    [
        Kpi("Wartość brutto", fmt_money_compact(gross), delta=plural(count, "obligacja", "obligacje", "obligacji"),
            delta_color="off", help=G["bond_gross"], trend=trend),
        Kpi("Odsetki naliczone", fmt_money(gross - nominal, decimals=0), delta=f"{fmt_pct((gross - nominal) / nominal)}"
            " od wartości nominalnej", delta_color="off", help=G["bond_accrued"],
            trend=weekly(by_day["value"] - 100 * by_day["qty"])),
        Kpi("Do wypłaty dziś", fmt_money_compact(payout), delta=fmt_money(payout - gross, decimals=0, signed=True)
            + " podatek i opłaty", delta_color="off", help=G["bond_payout"], trend=trend),
        Kpi("Średnie oprocentowanie", fmt_pct(avg_rate, 2, signed=False), delta="w bieżących okresach",
            delta_color="off", help=G["bond_avg_rate"], trend=trend),
    ]
)

mode = current_mode()

# -------------------------------------------------------------------------------- value over time
section("Wartość obligacji", "Wartość brutto wszystkich obligacji w PLN, dzień po dniu. Spadki to wypłacone "
        "odsetki i wykupy.", help=G["bond_flows"])
show(area_total(total, name="Obligacje", mode=mode, height=300), key="bonds_value")

# ------------------------------------------------------------------------------------ per purchase
section("Twoje obligacje", "Jeden wiersz na zakup. Wartości na dziś, po zamknięciu poprzedniego dnia.",
        help=G["bond_types"])
rows = pd.DataFrame([
    {
        "series": s.series, "type": s.type, "account": lot.account, "quantity": s.quantity,
        "purchase": fmt_date(s.purchase), "maturity": fmt_date(s.maturity), "rate": float(s.period.rate) / 100,
        "source": RATE_SOURCE[s.period.source], "period_end": fmt_date(s.period.end),
        "gross": float(s.gross) * s.quantity, "accrued": float(s.accrued) * s.quantity, "payout": float(s.payout),
        "sort": s.purchase,
    }
    for lot, s in held
]).sort_values(["series", "sort"]).drop(columns="sort")
columns = ["series", "type", "quantity", "purchase", "maturity", "rate", "source", "period_end", "gross", "accrued",
           "payout"]
if rows["account"].nunique() > 1:
    columns.insert(2, "account")
table(
    rows[columns],
    numbers={"quantity": 0, "gross": 2, "accrued": 2, "payout": 2},
    percents=["rate"],
    labels={"series": "Seria", "type": "Typ", "account": "Rachunek", "quantity": "Liczba", "purchase": "Data zakupu",
            "maturity": "Wykup", "rate": "Oprocentowanie", "source": "Stopa", "period_end": "Okres odsetkowy do",
            "gross": "Wartość brutto (zł)", "accrued": "Odsetki (zł)", "payout": "Do wypłaty (zł)"},
    helps={"series": G["bond_series"], "type": G["bond_types"], "quantity": G["bond_quantity"],
           "purchase": G["bond_purchase"], "maturity": G["bond_maturity"], "rate": G["bond_current_rate"],
           "source": G["bond_rate_source"], "period_end": G["bond_period"], "gross": G["bond_gross"],
           "accrued": G["bond_accrued"], "payout": G["bond_payout"]},
)
st.caption(
    ":material/info: Do wypłaty: szacunek przy wcześniejszym wykupie dziś, po opłacie i 19% podatku od odsetek "
    "(na IKE bez podatku). Nie jest to porada podatkowa ani inwestycyjna."
)

# --------------------------------------------------------------------------------- series rules
types_held = sorted({s.type for _, s in held})
with st.expander(":material/rule: Parametry Twoich serii"):
    known_frame = reports.bond_series(settings.db_path).set_index("series")
    series_held = sorted({s.series for _, s in held})
    table(
        pd.DataFrame([
            {"series": code, "type": known_frame.loc[code, "type"],
             "first_rate": known_frame.loc[code, "first_rate"] / 100,
             "margin": None if pd.isna(known_frame.loc[code, "margin"]) else known_frame.loc[code, "margin"] / 100,
             "early_fee": known_frame.loc[code, "early_fee"],
             "capitalised": "nie, wypłata" if bond_math.TYPES[known_frame.loc[code, "type"]].coupon else "tak"}
            for code in series_held
        ]),
        numbers={"early_fee": 2},
        percents=["first_rate", "margin"],
        labels={"series": "Seria", "type": "Typ", "first_rate": "1. okres", "margin": "Marża",
                "early_fee": "Opłata za wykup (zł/szt.)", "capitalised": "Kapitalizacja"},
        helps={"margin": G["bond_margin"], "early_fee": G["bond_early_fee"], "capitalised": G["bond_capitalization"],
               "first_rate": G["bond_current_rate"]},
    )
    if "EDO" in types_held:
        st.caption(f"EDO: {G['bond_edo']}")
    if "COI" in types_held:
        st.caption(f"COI: {G['bond_coi']}")

# ------------------------------------------------------------------------------------------ add / edit
purchase_form(known, accounts)

with st.expander(f":material/list: Zapisane zakupy ({len(lots)})"):
    st.caption(f"Plik `{csv_path}`. Usuń wiersz, jeśli wpisałeś go przez pomyłkę.")
    listing = lots.assign(purchase=lots["purchase_date"].map(fmt_date))
    table(
        listing[["row_no", "account", "series", "purchase", "quantity", "note"]],
        numbers={"row_no": 0, "quantity": 0},
        labels={"row_no": "Wiersz", "account": "Rachunek", "series": "Seria", "purchase": "Data zakupu",
                "quantity": "Liczba", "note": "Notatka"},
        helps={"series": G["bond_series"], "quantity": G["bond_quantity"]},
    )
    labels = {int(r.row_no): f"wiersz {r.row_no}: {r.series}, {plural(int(r.quantity), 'sztuka', 'sztuki', 'sztuk')}, "
              f"{fmt_date(r.purchase_date)}" for r in lots.itertuples(index=False)}
    left, right = st.columns([3, 1], vertical_alignment="bottom")
    chosen = left.selectbox("Wiersz do usunięcia", list(labels), format_func=labels.get, index=None,
                            placeholder="Wybierz wiersz")
    if right.button("Usuń", icon=":material/delete:", disabled=chosen is None):
        st.session_state["bond_delete"] = chosen
    pending = st.session_state.get("bond_delete")
    if pending is not None and pending in labels:
        st.warning(f"Usunąć {labels[pending]} z pliku bonds.csv? Tego nie da się cofnąć z poziomu aplikacji.",
                   icon=":material/warning:")
        yes, no, _ = st.columns([1, 1, 4])
        if yes.button("Tak, usuń", type="primary"):
            st.session_state.pop("bond_delete", None)
            if bond_files.delete_row(csv_path, pending):
                run_sync(f"Usunięto {labels[pending]}.")
            else:
                st.error("Nie znaleziono tego wiersza w pliku; odśwież stronę.", icon=":material/error:")
        if no.button("Anuluj"):
            st.session_state.pop("bond_delete", None)
            st.rerun()

notes = history.warnings
if notes or not issues.empty:
    with st.expander(f":material/warning: Uwagi do obligacji ({len(notes) + len(issues)})"):
        for message in issues["message"]:
            st.markdown(f"- {message}")
        for message in notes:
            st.markdown(f"- {message}")
