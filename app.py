"""Vstupní bod: konfigurace stránky, společný stav, navigace a postranní panel.

Spuštění:  python -m uv run streamlit run app.py --server.address 127.0.0.1
"""

import streamlit as st

from rakathon.ui import sidebar, state

st.set_page_config(page_title="Odchylky průběhu péče", page_icon=":material/monitor_heart:", layout="wide")
state.init()

if not state.has_dataset():
    sidebar.render_no_data()
    st.stop()

pages = [
    st.Page(state.PATIENTS_PAGE, title="Pacienti", icon=":material/groups:", default=True),
    st.Page(state.DEVIATIONS_PAGE, title="Analýza odchylek", icon=":material/query_stats:"),
]
navigation = st.navigation(pages)
sidebar.render()
st.sidebar.caption(
    "Výzkumný hackathonový prototyp (Rakathon 2026) – nejde o ověřené klinické skóre ani doporučení léčby."
)
navigation.run()
