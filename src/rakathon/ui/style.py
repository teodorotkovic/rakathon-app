"""Vizuální vrstva: doplňky k tématu v .streamlit/config.toml, které téma neumí.

Princip: stránka má tónovaný podklad, každý ohraničený blok (st.container(border=True), rozbalovací
panel, tabulka) je bílá karta – bloky jsou od sebe zřetelně oddělené. Vnořená karta je jemně
tónovaná, aby se odlišila od rodiče. Selektory jsou založené na data-testid Streamlitu.
"""

from __future__ import annotations

import streamlit as st

PAGE = "#E9EEEC"
CARD = "#FFFFFF"
CARD_NESTED = "#F5F8F7"
LINE = "#D5DEDB"
INK = "#1A2B29"
MUTED = "#56635F"
PRIMARY = "#0B6E66"

# Ohraničený kontejner (border=True) má atribut data-test-scroll-behavior a výšku auto;
# posuvný seznam (height=…) ho má s pevnou výškou a kartou být nemá.
_CARD_SEL = '[data-testid="stVerticalBlock"][data-test-scroll-behavior][height="auto"]'

_CSS = f"""
<style>
/* Podklad stránky a horní lišta */
[data-testid="stAppViewContainer"], [data-testid="stMain"] {{ background: {PAGE}; }}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stMainBlockContainer"] {{ padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1480px; }}

/* Karty */
{_CARD_SEL} {{
  background: {CARD};
  border-color: {LINE} !important;
  box-shadow: 0 1px 2px rgba(21, 50, 46, 0.05);
}}
{_CARD_SEL} {_CARD_SEL} {{ background: {CARD_NESTED}; box-shadow: none; }}
[data-testid="stExpander"] details {{ background: {CARD}; border-color: {LINE}; }}
{_CARD_SEL} [data-testid="stExpander"] details {{ background: {CARD_NESTED}; }}
[data-testid="stDataFrame"] {{ background: {CARD}; border-radius: 0.55rem; }}

/* Typografie */
.stMain h1 {{ letter-spacing: -0.01em; }}
.stMain h3 {{ margin-top: 0.6rem; }}
[data-testid="stCaptionContainer"] p {{ color: {MUTED}; }}
[data-testid="stMetricLabel"] p {{ color: {MUTED}; }}
[data-testid="stMetricValue"] {{ font-variant-numeric: tabular-nums; color: {INK}; }}
/* Metrika mimo kartu je sama malou kartou; uvnitř karty zůstává bez rámečku. */
.stMain [data-testid="stMetric"] {{
  background: {CARD}; border: 1px solid {LINE}; border-radius: 0.55rem; padding: 0.7rem 0.9rem;
}}
{_CARD_SEL} [data-testid="stMetric"] {{ background: transparent; border: none; padding: 0; }}

/* Záložky: zřetelné oddělení obsahu záložky od zbytku stránky */
.stMain [data-baseweb="tab-list"] {{ gap: 0.25rem; border-bottom: 1px solid {LINE}; }}
.stMain [data-baseweb="tab"] {{ padding: 0.45rem 0.9rem; border-radius: 0.45rem 0.45rem 0 0; }}
.stMain [data-baseweb="tab"][aria-selected="true"] {{ background: {CARD}; }}
.stMain [data-baseweb="tab-panel"] {{ padding-top: 1rem; }}

/* Postranní panel: navigace jako oddělená vrstva */
[data-testid="stSidebarNavLink"] [data-testid="stIconMaterial"] {{ font-size: 1.5rem !important; }}
[data-testid="stSidebarNavLink"] {{ padding-top: 0.45rem; padding-bottom: 0.45rem; gap: 0.6rem; }}
[data-testid="stSidebarNavLink"] p, [data-testid="stSidebarNavLink"] span {{ font-size: 1.05rem; }}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {{ color: #A9C2BD; }}
</style>
"""


def inject() -> None:
    st.html(_CSS)
