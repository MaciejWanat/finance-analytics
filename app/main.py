"""Streamlit entry point. Start with `fa ui` (or `streamlit run app/main.py`)."""

from __future__ import annotations

import os

import streamlit as st
from ui.components import apply_global_styles

st.set_page_config(
    page_title="Finanse",
    page_icon=":material/savings:",
    layout="wide",
    initial_sidebar_state="expanded",
)

pages = {
    "Analiza": [
        st.Page("views/portfolio.py", title="Portfel", icon=":material/monitoring:", default=True),
    ],
    "Dane": [
        st.Page("views/imports.py", title="Importy", icon=":material/upload_file:"),
    ],
}
if os.environ.get("FA_DEV") == "1":
    pages["Deweloper"] = [
        st.Page("views/style_preview.py", title="Podgląd stylu", icon=":material/palette:"),
    ]

navigation = st.navigation(pages, position="sidebar")
apply_global_styles()

with st.sidebar:
    st.caption(":material/lock: Dane zostają na tym komputerze.")

navigation.run()
