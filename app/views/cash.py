"""Cash at banks: balances entered by hand, valued in PLN day by day (R-007, D-027)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import streamlit as st
from ui.charts import area_total, current_mode, line_chart, show
from ui.components import Kpi, empty_state, kpi_row, page_header, section, table
from ui.data import load_valuation, require_database
from ui.fmt import fmt_date, fmt_money, fmt_money_compact
from ui.glossary import G

from finance_analytics import reports
from finance_analytics.config import get_settings
from finance_analytics.sources import accounts as account_files
from finance_analytics.sources import cash as cash_files
from finance_analytics.sources.sync import sync

STALE_DAYS = 30

page_header("Gotówka", "Gotówka na kontach bankowych: salda wpisujesz sam, a aplikacja wycenia je w PLN dzień po dniu.")
settings = get_settings()
require_database(settings)
csv_path = cash_files.cash_file(settings.manual_dir)


def run_sync(message: str) -> None:
    result = sync(settings)
    st.session_state["cash_message"] = (message, result.errors)
    st.rerun()


def account_form() -> None:
    """'Dodaj konto bankowe': appends an account to data/config/accounts.yaml and rebuilds the database."""
    with st.container(border=True):
        st.markdown("#### :material/add_card: Dodaj konto bankowe")
        st.caption("Konto trafia do pliku `accounts.yaml` na tym komputerze. Saldo dodasz w następnym kroku.")
        with st.form("bank_account", clear_on_submit=True, border=False):
            left, middle, right = st.columns([3, 1, 3])
            alias = left.text_input("Nazwa konta", placeholder="np. Konto osobiste", max_chars=60,
                                    help=G["bank_account"])
            currency = middle.selectbox("Waluta", cash_files.CURRENCIES)
            institution = right.text_input("Instytucja (opcjonalnie)", placeholder="np. mBank", max_chars=60)
            submitted = st.form_submit_button("Dodaj konto", type="primary", icon=":material/add:")
        if submitted:
            try:
                account = account_files.add_bank_account(settings.accounts_file, alias, currency, institution)
            except ValueError as exc:
                st.error(str(exc)[0].upper() + str(exc)[1:], icon=":material/error:")
                return
            run_sync(f"Dodano konto {account.alias} ({account.currency}).")


def balance_form(accounts: pd.DataFrame) -> None:
    """'Zapisz saldo': appends a row to data/manual/cash_balances.csv and rebuilds the database."""
    with st.container(border=True):
        st.markdown("#### :material/edit_note: Zapisz saldo")
        st.caption(f"Saldo trafia do pliku `{csv_path}` na tym komputerze. Obowiązuje do kolejnego wpisu.")
        options = dict(zip(accounts["id"], accounts["alias"] + " (" + accounts["currency"] + ")", strict=True))
        with st.form("cash_balance", clear_on_submit=True, border=False):
            left, middle, right = st.columns([2, 2, 2])
            account = left.selectbox("Konto", list(options), format_func=options.get, help=G["bank_account"])
            day = middle.date_input("Data salda", value=date.today(), max_value=date.today(), format="DD.MM.YYYY",
                                    help=G["balance_snapshot"])
            amount = right.number_input(
                "Saldo", value=None, step=100.0, format="%.2f", placeholder="np. 12345.67 (kropka)", help=G["balance"],
            )
            note = st.text_input("Notatka (opcjonalnie)", max_chars=120)
            submitted = st.form_submit_button("Zapisz saldo", type="primary", icon=":material/add:")
        if submitted:
            kinds = reports.account_kinds(settings.db_path)
            problem = cash_files.check_snapshot(account, day, kinds, date.today())
            if amount is None:
                problem = "wpisz saldo konta"
            taken = {(s.account_id, s.day) for s in cash_files.read_snapshots(csv_path, kinds).snapshots}
            if not problem and (account, day) in taken:
                problem = f"saldo tego konta na dzień {fmt_date(day)} już jest zapisane; usuń je i wpisz ponownie"
            if problem:
                st.error(problem[0].upper() + problem[1:], icon=":material/error:")
                return
            cash_files.append_snapshot(csv_path, account, day, Decimal(str(round(amount, 2))), note.strip())
            run_sync(f"Zapisano saldo konta {options[account]} na dzień {fmt_date(day)}.")


if "cash_message" in st.session_state:
    message, errors = st.session_state.pop("cash_message")
    st.success(message, icon=":material/check_circle:")
    if errors:
        st.warning(f"Po przebudowie bazy są problemy z plikami ({len(errors)}); szczegóły na dole strony.",
                   icon=":material/warning:")

accounts = reports.bank_accounts(settings.db_path)
snapshots = reports.cash_snapshots(settings.db_path)
issues = reports.cash_issues(settings.db_path)

if accounts.empty or snapshots.empty:
    if accounts.empty:
        empty_state(
            "Nie masz jeszcze kont bankowych",
            "Dodaj konto, a potem wpisz jego saldo. Aplikacja doliczy gotówkę do wartości portfela. "
            "Nie łączy się z bankiem, więc saldo aktualizujesz sam, kiedy chcesz.",
            icon=":material/account_balance_wallet:",
            steps=["Dodaj konto w formularzu poniżej: nazwa i waluta.",
                   "Zapisz jego saldo na wybrany dzień. Kolejne salda dopisuj, gdy się zmienią."],
        )
    else:
        empty_state(
            "Nie masz jeszcze zapisanych sald",
            "Konto bez salda nie ma wartości. Wpisz jego saldo na wybrany dzień: obowiązuje do kolejnego wpisu.",
            icon=":material/edit_note:",
        )
    account_form()
    if not accounts.empty:
        balance_form(accounts)
    st.caption(":material/table_view: Salda możesz też pobrać i wgrać jako plik CSV na stronie **Importy**.")
    if not issues.empty:
        with st.expander(f":material/warning: Uwagi do sald ({len(issues)})", expanded=True):
            for text in issues["message"]:
                st.markdown(f"- {text}")
    st.stop()

# ------------------------------------------------------------------------------------------- values
v, _ = load_valuation(settings, stop_if_empty=False)
bank = v.daily[(v.daily["kind"] == "cash") & v.daily["account_id"].isin(accounts["id"])]
if bank.empty:
    st.warning("Nie da się wycenić sald: brakuje kursów NBP dla walut kont. Pobierz je na stronie Dane rynkowe "
               "(tryb online) albo wpisz saldo konta w PLN.", icon=":material/currency_exchange:")
    account_form()
    balance_form(accounts)
    st.stop()
today = pd.Timestamp(date.today())
by_account = bank.pivot_table(index="date", columns="account", values="value_pln", aggfunc="sum").sort_index()
total = by_account.sum(axis=1)
latest = bank[bank["date"] == bank["date"].max()].set_index("account_id")

last_snapshot = snapshots.groupby("account_id").tail(1).set_index("account_id")  # newest per account
age = (today - last_snapshot["date"]).dt.days
stale = age[age > STALE_DAYS]
newest = last_snapshot["date"].max()
year_ago = today - pd.DateOffset(years=1)


def weekly(series: pd.Series) -> list[float]:
    return series[series.index > year_ago].resample("W-FRI").last().dropna().round(0).tolist()


kpi_row(
    [
        Kpi("Gotówka razem", fmt_money_compact(float(total.iloc[-1])),
            delta="w PLN, po kursie NBP", delta_color="off",
            help=G["cash_total"], trend=weekly(total)),
        Kpi("Konta bankowe", str(len(accounts)), delta=", ".join(sorted(accounts["currency"].unique())),
            delta_color="off", help=G["bank_account"], trend=weekly(total)),
        Kpi("Ostatnia aktualizacja", fmt_date(newest),
            delta=f"{int((today - newest).days)} dni temu" if newest < today else "dziś", delta_color="off",
            help=G["balance_snapshot"], trend=weekly(total)),
    ]
)

mode = current_mode()

# -------------------------------------------------------------------------------- value over time
section("Gotówka w czasie", "Wartość sald w PLN, dzień po dniu. Saldo obowiązuje do kolejnego wpisu.",
        help=G["cash_flows"])
if by_account.shape[1] > 1:
    show(line_chart(by_account.round(2), mode=mode, height=320), key="cash_value")
else:
    show(area_total(total.round(2), name="Gotówka", mode=mode, height=300), key="cash_value")

# --------------------------------------------------------------------------------------- per account
section("Twoje konta", "Ostatnie zapisane saldo każdego konta i jego wartość w PLN na dziś.")
rows = []
for account_id, info in accounts.set_index("id").iterrows():
    if account_id not in last_snapshot.index:
        rows.append({"account": info["alias"], "currency": info["currency"], "balance": None, "pln": None,
                     "date": "–", "status": "brak salda"})
        continue
    snap = last_snapshot.loc[account_id]
    days = int(age[account_id])
    rows.append({
        "account": info["alias"], "currency": info["currency"], "balance": float(snap["balance"]),
        "pln": float(latest.loc[account_id, "value_pln"]) if account_id in latest.index else None,
        "date": fmt_date(snap["date"]),
        "status": f"nieaktualne: {days} dni" if days > STALE_DAYS else "aktualne",
    })
table(
    pd.DataFrame(rows),
    numbers={"balance": 2, "pln": 2},
    labels={"account": "Konto", "currency": "Waluta", "balance": "Saldo (waluta konta)", "pln": "Wartość (zł)",
            "date": "Data salda", "status": "Status"},
    helps={"account": G["bank_account"], "balance": G["balance"], "pln": G["cash_total"],
           "date": G["balance_date"], "status": G["balance_stale"]},
)
if not stale.empty:
    names = ", ".join(accounts.set_index("id").loc[stale.index, "alias"])
    st.warning(f"Saldo starsze niż {STALE_DAYS} dni: {names}. Dopisz nowe, żeby wartość portfela była aktualna.",
               icon=":material/schedule:")
st.caption(":material/info: Zmiany salda między wpisami liczą się jak wpłaty i wypłaty, więc gotówka nie pokazuje "
           "zwrotu (odsetki z konta też nie). Zmienia ją tylko kurs walut przy kontach w obcej walucie.")

# ------------------------------------------------------------------------------------------ add / edit
account_form()
balance_form(accounts)
st.caption(":material/table_view: Salda możesz też pobrać i wgrać jako plik CSV na stronie **Importy**.")

with st.expander(f":material/list: Zapisane salda ({len(snapshots)})"):
    st.caption(f"Plik `{csv_path}`. Usuń wiersz, jeśli wpisałeś go przez pomyłkę.")
    listing = snapshots.sort_values("date", ascending=False).assign(day=lambda d: d["date"].map(fmt_date))
    table(
        listing[["row_no", "account", "day", "balance", "currency", "note"]],
        numbers={"row_no": 0, "balance": 2},
        labels={"row_no": "Wiersz", "account": "Konto", "day": "Data salda", "balance": "Saldo", "currency": "Waluta",
                "note": "Notatka"},
        helps={"balance": G["balance"], "day": G["balance_snapshot"]},
    )
    labels = {int(r.row_no): f"wiersz {r.row_no}: {r.account}, {fmt_date(r.date)}, {fmt_money(r.balance, r.currency)}"
              for r in snapshots.itertuples(index=False)}
    left, right = st.columns([3, 1], vertical_alignment="bottom")
    chosen = left.selectbox("Wiersz do usunięcia", list(labels), format_func=labels.get, index=None,
                            placeholder="Wybierz wiersz")
    if right.button("Usuń", icon=":material/delete:", disabled=chosen is None):
        st.session_state["cash_delete"] = chosen
    pending = st.session_state.get("cash_delete")
    if pending is not None and pending in labels:
        st.warning(f"Usunąć {labels[pending]} z pliku cash_balances.csv? Tego nie da się cofnąć z poziomu aplikacji.",
                   icon=":material/warning:")
        yes, no, _ = st.columns([1, 1, 4])
        if yes.button("Tak, usuń", type="primary"):
            st.session_state.pop("cash_delete", None)
            if cash_files.delete_row(csv_path, pending):
                run_sync(f"Usunięto {labels[pending]}.")
            else:
                st.error("Nie znaleziono tego wiersza w pliku; odśwież stronę.", icon=":material/error:")
        if no.button("Anuluj"):
            st.session_state.pop("cash_delete", None)
            st.rerun()

notes = list(v.warnings)
if notes or not issues.empty:
    with st.expander(f":material/warning: Uwagi do gotówki ({len(notes) + len(issues)})"):
        for text in issues["message"]:
            st.markdown(f"- {text}")
        for text in notes:
            st.markdown(f"- {text}")
