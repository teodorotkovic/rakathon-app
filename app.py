"""Vstupní bod: konfigurace stránky, společný stav, navigace a postranní panel.

Spuštění:  python -m uv run streamlit run app.py --server.address 127.0.0.1
"""

import streamlit as st

from rakathon.ui import sidebar, state

st.set_page_config(page_title="Odchylky průběhu péče", page_icon=":material/monitor_heart:", layout="wide")
# Větší ikony a text přepínání stránek v postranním panelu.
st.html(
    """<style>
    [data-testid="stSidebarNavLink"] [data-testid="stIconMaterial"] { font-size: 1.6rem !important; }
    [data-testid="stSidebarNavLink"] { padding-top: 0.45rem; padding-bottom: 0.45rem; gap: 0.6rem; }
    [data-testid="stSidebarNavLink"] p, [data-testid="stSidebarNavLink"] span { font-size: 1.05rem; }
    </style>"""
)
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
navigation.run()
