"""CSV export and import of the hand-entered data: bank balances and bonds (R-011, D-027).

Everything stays on this computer: downloads are served by the local app, uploads are only read.
An uploaded file is validated and previewed first; its valid rows are appended to the existing
file, never overwriting it, and rows that fail validation are shown and skipped.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import pandas as pd
import streamlit as st

from finance_analytics import reports
from finance_analytics.config import Settings
from finance_analytics.sources import bonds as bond_files
from finance_analytics.sources import cash as cash_files
from finance_analytics.sources.manual_csv import template
from finance_analytics.sources.sync import sync
from ui.components import table
from ui.fmt import fmt_date, plural
from ui.glossary import G


@dataclass(frozen=True)
class Dataset:
    key: str
    title: str
    file_name: str
    columns: list[str]
    path_of: Callable[[Settings], object]
    merge: Callable[..., tuple[list[str], list[dict], Callable[[], None]]]


def _merge_cash(settings: Settings, text: str, name: str):
    kinds = reports.account_kinds(settings.db_path)
    path = cash_files.cash_file(settings.manual_dir)
    result, fresh = cash_files.merge_upload(path, text, name, kinds, date.today())
    rows = [{"account": s.account_id, "date": fmt_date(s.day), "balance": float(s.balance), "note": s.note}
            for s in fresh]

    def append() -> None:
        for s in fresh:
            cash_files.append_snapshot(path, s.account_id, s.day, s.balance, s.note)

    return result.errors, rows, append


def _merge_bonds(settings: Settings, text: str, name: str):
    kinds = reports.account_kinds(settings.db_path)
    known = set(reports.bond_series(settings.db_path)["series"])
    path = bond_files.bonds_file(settings.manual_dir)
    result, fresh = bond_files.merge_upload(path, text, name, known, kinds, date.today())
    rows = [{"account": lot.account_id, "series": lot.series, "date": fmt_date(lot.purchase_date),
             "quantity": lot.quantity, "note": lot.note} for lot in fresh]

    def append() -> None:
        for lot in fresh:
            bond_files.append_lot(path, lot.account_id, lot.series, lot.purchase_date, lot.quantity, lot.note)

    return result.errors, rows, append


DATASETS = [
    Dataset("cash", "Salda kont", "cash_balances.csv", cash_files.SNAPSHOT_COLUMNS,
            lambda s: cash_files.cash_file(s.manual_dir), _merge_cash),
    Dataset("bonds", "Obligacje", "bonds.csv", bond_files.LOT_COLUMNS,
            lambda s: bond_files.bonds_file(s.manual_dir), _merge_bonds),
]
PREVIEW_LABELS = {"account": "Konto", "date": "Data", "balance": "Saldo", "series": "Seria", "quantity": "Liczba",
                  "note": "Notatka"}


def _dataset(settings: Settings, dataset: Dataset) -> None:
    path = dataset.path_of(settings)
    left, right = st.columns(2)
    saved = path.read_bytes() if path.exists() else None
    left.download_button("Pobierz moje dane", data=saved or template(dataset.columns), file_name=dataset.file_name,
                         mime="text/csv", icon=":material/download:", disabled=saved is None,
                         key=f"{dataset.key}_download", width="stretch")
    right.download_button("Pobierz pusty szablon", data=template(dataset.columns),
                          file_name=f"{dataset.file_name.removesuffix('.csv')}_szablon.csv", mime="text/csv",
                          icon=":material/description:", key=f"{dataset.key}_template", width="stretch")
    st.caption(f"Kolumny: `{','.join(dataset.columns)}`. Daty RRRR-MM-DD, separator `,` albo `;`.")

    round_ = st.session_state.get(f"{dataset.key}_round", 0)
    upload = st.file_uploader(f"Wgraj plik CSV: {dataset.title.lower()}", type="csv",
                              key=f"{dataset.key}_upload_{round_}", help=G["csv_import"])
    if upload is None:
        return
    try:
        text = upload.getvalue().decode("utf-8-sig")
    except UnicodeDecodeError:
        st.error(f"{upload.name}: plik nie jest zapisany w UTF-8. Zapisz go ponownie jako CSV UTF-8.",
                 icon=":material/error:")
        return
    errors, rows, append = dataset.merge(settings, text, upload.name)
    if rows:
        st.markdown(f"**Do dopisania: {len(rows)}**. Sprawdź i zatwierdź.")
        table(pd.DataFrame(rows), numbers={"balance": 2, "quantity": 0}, labels=PREVIEW_LABELS)
    else:
        st.info("W tym pliku nie ma poprawnych wierszy do dopisania.", icon=":material/info:")
    if errors:
        with st.expander(f":material/warning: Pominięte wiersze ({len(errors)})", expanded=True):
            for message in errors:
                st.markdown(f"- {message}")
    if rows and st.button(f"Dopisz {plural(len(rows), 'wiersz', 'wiersze', 'wierszy')} do {dataset.file_name}",
                          type="primary", icon=":material/add:", key=f"{dataset.key}_append"):
        append()
        result = sync(settings)
        st.session_state[f"{dataset.key}_round"] = round_ + 1  # a fresh, empty uploader
        st.session_state["manual_message"] = (
            f"Dopisano {plural(len(rows), 'wiersz', 'wiersze', 'wierszy')} do {dataset.file_name}.", result.errors)
        st.rerun()


def manual_data_section(settings: Settings) -> None:
    """The download and upload block; call it once on a page that already checked the database exists."""
    if "manual_message" in st.session_state:
        message, errors = st.session_state.pop("manual_message")
        st.success(message, icon=":material/check_circle:")
        if errors:
            st.warning(f"Po przebudowie bazy są problemy z plikami ({len(errors)}); szczegóły na stronach "
                       "Gotówka i Obligacje.", icon=":material/warning:")
    with st.container(border=True):
        st.markdown("#### :material/table_view: Dane wpisywane ręcznie (CSV)")
        st.caption("Salda kont i zakupy obligacji to zwykłe pliki CSV w `data/manual/`. Możesz je pobrać, edytować "
                   "w arkuszu i wgrać z powrotem. Pliki zostają na tym komputerze.", help=G["csv_export"])
        tabs = st.tabs([d.title for d in DATASETS])
        for tab, dataset in zip(tabs, DATASETS, strict=True):
            with tab:
                _dataset(settings, dataset)
