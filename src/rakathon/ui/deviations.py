"""Stránka Analýza odchylek – jedna souvislá stránka pro lékaře.

Pořadí odpovídá otázkám lékaře: kolik je neobvyklých pacientů → kde leží a kdo to je →
proč je konkrétní pacient neobvyklý → co mají neobvyklí pacienti společného → další nástroje.

Lokální konfigurace (ukazatele, škála, hranice, reference) mění jen tuto analýzu. Globální
očekávání se zde nepřepočítává. Tlačítka mají odlišné role:
- klik na bod / „Vysvětlit“ → vybraní pacienti (nic nepřepočítává),
- „Použít jako referenci“ (Další nástroje) → lokální reference kalibrace detektoru,
- „Výchozí reference“ → všichni hodnotitelní pacienti.
"""

from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pandas as pd
import streamlit as st

from rakathon.analysis.detectors import robust_scale
from rakathon.analysis.explanations import explain_flag
from rakathon.configuration import default_analysis_config
from rakathon.domain import (
    FEATURE_SCHEMA_VERSION,
    METHOD_VERSION,
    AnalysisConfig,
    AnalysisResult,
    BaselineConfig,
    ReviewStatus,
    canonical_json,
    review_label,
)
from rakathon.features.catalog import descriptor_columns
from rakathon.formatting import fmt_num, fmt_pct
from rakathon.pipeline import GlobalResults
from rakathon.storage.csv_store import now_iso
from rakathon.ui import charts, components, state
from rakathon.ui.patients import _export_button

WIDGET_KEYS = ["dv_metrics", "dv_scale", "dv_threshold", "dv_limited", "dv_cluster_dist", "dv_cluster_min"]
K_LAST_CHART = "dv_last_chart_selection"

# Krátké názvy ukazatelů pro věty („Typický pobyt: 21 dní místo 5“).
PLAIN_METRIC = {"median_los_dx": "Typický pobyt", "max_los_dx": "Nejdelší pobyt"}
BAND_BADGE = {
    "výrazná odchylka": ("Výrazná odchylka", "orange"),
    "hraniční odchylka": ("Hraniční odchylka", "orange"),
    "těsně pod prahem": ("Těsně pod hranicí", "gray"),
}


def _bind(key: str, value) -> None:
    if key not in st.session_state:
        st.session_state[key] = value


def _reset_widgets() -> None:
    for k in WIDGET_KEYS:
        st.session_state.pop(k, None)
    state.bump_nonce()


def _days(x) -> str:
    if x is None or pd.isna(x):
        return "–"
    n = float(x)
    if n != int(n):
        word = "dne"  # desetinné číslo: 7,2 dne
    else:
        word = "den" if abs(n) == 1 else ("dny" if 2 <= abs(n) <= 4 else "dní")
    return f"{fmt_num(n)} {word}"


def _n_phrase(n: int, one: str, few: str, many: str) -> str:
    return f"{n} {one if n == 1 else few if 2 <= n <= 4 else many}"


# ---------------------------------------------------------------------------
# Stránka
# ---------------------------------------------------------------------------


def render() -> None:
    st.title("Analýza odchylek")
    st.caption(
        "Celá kohorta najednou: kteří pacienti mají pobyty neobvykle delší nebo kratší než podobní pacienti, "
        "proč a co mají společného. Očekávání pacientů se zde nemění."
    )
    state.show_flash()
    g = state.global_results()
    with st.container(border=True):
        _controls(g)
    a = state.local_analysis()

    mode = st.session_state.get("dv_chart_mode", "z")
    chart_key = f"dv_chart_{mode}_{state.nonce()}"
    xy_key = f"dv_xy_chart_{state.nonce()}"
    chart_sel = _chart_selection(chart_key)
    _apply_chart_selection(chart_key, chart_sel)
    _apply_chart_selection(xy_key, _chart_selection(xy_key))

    _summary(g, a)

    left, right = st.columns([1.55, 1], gap="large")
    with left:
        _distribution(g, a, chart_key)
    with right:
        _outlier_list(g, a)

    _focus(g, a)
    _groups(g, a)
    _two_values(g, a, xy_key)
    listed_ids = _tools(g, a, chart_sel)

    st.divider()
    _export_button(
        g,
        a,
        listed_ids,
        f"Analýza odchylek ({a.analysis_id})",
        {"seznam": "Další nástroje → vlastní výběr", "n": len(listed_ids)},
        key="dl_analysis",
    )
    components.context_caption(g, f"lokální pohled `{a.analysis_id}`")

    dialog = st.session_state.get(state.K_DIALOG) or ""
    if dialog.startswith("review:"):
        components.review_dialog(
            dialog.split(":", 1)[1], a.analysis_id, f"Analýza odchylek (hranice {fmt_num(a.config.threshold)})"
        )


# ---------------------------------------------------------------------------
# Nastavení
# ---------------------------------------------------------------------------


def _controls(g: GlobalResults) -> None:
    cfg = state.analysis_config()
    outcomes = list(g.baseline.config.outcomes)
    _bind("dv_metrics", [m for m in cfg.metrics if m in outcomes] or outcomes[:1])
    _bind("dv_scale", cfg.scale)
    _bind("dv_threshold", float(cfg.threshold))
    _bind("dv_limited", cfg.include_limited_reference)
    _bind("dv_cluster_dist", float(cfg.cluster_distance_threshold))
    _bind("dv_cluster_min", int(cfg.cluster_min_outliers))

    c1, c2, c3 = st.columns([2.2, 2, 1.3], vertical_alignment="bottom", gap="medium")
    threshold = c1.slider(
        "Hranice neobvyklosti",
        1.5,
        5.0,
        step=0.1,
        key="dv_threshold",
        help="Jak velký rozdíl oproti ostatním pacientům už považujeme za neobvyklý. Nižší hranice = citlivější "
        "(víc pacientů), vyšší = přísnější. Jde o pracovní heuristiku, ne o pravděpodobnost.",
    )
    metrics = c2.pills(
        "Co porovnávat",
        outcomes,
        selection_mode="multi",
        key="dv_metrics",
        format_func=lambda m: PLAIN_METRIC.get(m, g.metric_labels[m]),
        help="Typický pobyt = medián délky pobytů pacienta. Nejdelší pobyt = jeho nejdelší hospitalizace. "
        "Při obou rozhoduje ten, kde je odchylka větší (oba ukazatele spolu souvisejí).",
    )
    if c3.button("Výchozí pohled", key="dv_reset", icon=":material/restart_alt:", width="stretch"):
        state.set_analysis_config(default_analysis_config(state.settings()))
        st.session_state[state.K_INVESTIGATED] = []
        st.session_state[state.K_FOCUS] = None
        st.session_state.pop(K_LAST_CHART, None)
        _reset_widgets()
        st.rerun()
    with st.expander("Pokročilé nastavení"):
        d1, d2 = st.columns(2)
        scale = d1.segmented_control(
            "Jak měřit rozdíl",
            ["log", "raw"],
            key="dv_scale",
            required=True,
            format_func=lambda s: "poměrem (doporučeno)" if s == "log" else "ve dnech",
            help="Poměrem: 10 dní místo 5 je podobně neobvyklé jako 40 místo 20. Ve dnech: rozhoduje "
            "absolutní počet dní, takže víc vyniknou dlouhé pobyty.",
        )
        limited = d2.toggle(
            "Hodnotit i pacienty s malou srovnávací skupinou",
            key="dv_limited",
            help="Pacienti, jejichž očekávání vychází jen ze 4–7 podobných pacientů. Výsledek je označen jako "
            "méně spolehlivý.",
        )
        d3, d4 = st.columns(2)
        dist = d3.slider(
            "Jak podobní musí být pacienti ve skupině",
            0.5,
            5.0,
            step=0.25,
            key="dv_cluster_dist",
            help="Větší hodnota = méně a větších skupin (volnější podobnost).",
        )
        cmin = d4.number_input(
            "Nejméně neobvyklých pacientů pro hledání skupin", 2, 20, step=1, key="dv_cluster_min"
        )

    if not metrics:
        st.warning("Vyberte alespoň jeden ukazatel – ponechán předchozí výběr.")
        metrics = list(cfg.metrics)
    new = replace(
        cfg,
        metrics=tuple(m for m in outcomes if m in metrics),
        scale=scale or cfg.scale,
        threshold=float(threshold),
        include_limited_reference=bool(limited),
        cluster_distance_threshold=float(dist),
        cluster_min_outliers=int(cmin),
    )
    if new != cfg:
        state.set_analysis_config(new)


def _set_threshold(value: float) -> None:
    st.session_state["dv_threshold"] = float(value)


def _threshold_for(a: AnalysisResult, n: int) -> float | None:
    """Nejpřísnější hranice (krok 0,1, ≥ 1,5), při které bude neobvyklých alespoň n pacientů."""
    s = a.scores.loc[a.scores["scored"], "score"].sort_values(ascending=False).to_numpy()
    if len(s) < n:
        return None
    t = float(np.floor(s[n - 1] * 10) / 10)
    return t if 1.5 <= t < a.config.threshold else None


# ---------------------------------------------------------------------------
# Souhrn slovy
# ---------------------------------------------------------------------------


def _summary(g: GlobalResults, a: AnalysisResult) -> None:
    s = a.scores
    n_total = len(s)
    scored = s[s["scored"]]
    out = scored[scored["outlier"]]
    n_out, n_scored = len(out), len(scored)
    n_long = int((out["direction"] == "longer").sum())
    n_short = int((out["direction"] == "shorter").sum())
    n_strong = int((out["band"] == "výrazná odchylka").sum())
    n_near = int((scored["band"] == "těsně pod prahem").sum())
    n_weak = int((out["support_level"] == "omezená opora").sum())
    thr = a.config.threshold

    with st.container(border=True):
        if n_out:
            st.markdown(
                f"### {_n_phrase(n_out, 'neobvyklý pacient', 'neobvyklí pacienti', 'neobvyklých pacientů')} "
                f"z {n_scored} porovnatelných"
            )
        else:
            st.markdown(f"### Žádný neobvyklý pacient z {n_scored} porovnatelných")
        parts = []
        if n_out:
            dirs = []
            if n_long:
                dirs.append(f"**delší** než obvykle u {n_long}")
            if n_short:
                dirs.append(f"**kratší** u {n_short}")
            parts.append(
                f"Při hranici {fmt_num(thr)} jsou pobyty ve srovnání s podobnými pacienty {' a '.join(dirs)} "
                "z nich."
            )
            if n_strong:
                parts.append(f"Výrazně se odchyluje {n_strong}, ostatní jsou hraniční.")
            if n_weak:
                parts.append(
                    f"U {n_weak} z nich stojí srovnání na malém počtu pacientů nebo pobytů – berte je opatrně."
                )
        else:
            parts.append(
                f"Při hranici {fmt_num(thr)} nikdo nepřekračuje obvyklé rozdíly. I to je platný výsledek; pro "
                "průzkum můžete hranici snížit."
            )
        if n_near:
            parts.append(
                f"Další {n_near} jsou těsně pod hranicí." if n_near <= 4 else f"Dalších {n_near} je těsně pod hranicí."
            )
        if n_total > n_scored:
            n_not = n_total - n_scored
            parts.append(
                f"{_n_phrase(n_not, 'pacienta', 'pacienty', 'pacientů')} nelze porovnat (chybí započitatelné "
                "pobyty nebo podobní pacienti)."
            )
        st.markdown(" ".join(parts))

        # Jak výsledek závisí na hranici – skóre na hranici nezávisí, jen se jinak „řízne“.
        steps = [t for t in (2.0, 2.5, 3.0, 3.5) if abs(t - thr) > 1e-9]
        counts = [f"{fmt_num(t)} → {int((scored['score'] >= t).sum())}" for t in steps]
        st.caption("Kolik by bylo neobvyklých při jiné hranici: " + ", ".join(counts) + ".")

        info = a.cluster_info
        if info.get("status") == "clustered" and info.get("n_groups", 0):
            st.markdown(
                f"Mezi neobvyklými pacienty jsme našli **{_n_phrase(info['n_groups'], 'skupinu', 'skupiny', 'skupin')}** "
                "s podobným průběhem – viz Co mají společného níže."
            )
        elif info.get("status") == "too_few":
            need = a.config.cluster_min_outliers
            sugg = _threshold_for(a, need)
            st.markdown(
                f"Na hledání společných rysů je neobvyklých pacientů málo (potřeba alespoň {need})."
            )
            if sugg is not None:
                st.button(
                    f"Zmírnit hranici na {fmt_num(sugg)} a hledat společné rysy",
                    key="dv_relax",
                    icon=":material/tune:",
                    on_click=_set_threshold,
                    args=(sugg,),
                )


# ---------------------------------------------------------------------------
# Graf
# ---------------------------------------------------------------------------


def _apply_chart_selection(chart_key: str, chart_sel: list[str]) -> None:
    """Klik / výběr v grafu → vybraní pacienti (jen při nové volbě, aby šlo vybírat i jinak)."""
    last = st.session_state.setdefault(K_LAST_CHART, {})
    if chart_sel and chart_sel != last.get(chart_key):
        last[chart_key] = chart_sel
        st.session_state[state.K_INVESTIGATED] = list(chart_sel)
        st.session_state[state.K_FOCUS] = chart_sel[0]


def _distribution(g: GlobalResults, a: AnalysisResult, chart_key: str) -> None:
    st.markdown("#### Kde leží pacienti")
    w = _dims_wide(g, a)
    if w.empty:
        st.info("V aktuálním nastavení nelze porovnat žádného pacienta.")
        return
    highlight = set(st.session_state.get(state.K_INVESTIGATED, []))
    metrics = list(a.config.metrics)
    mode = st.segmented_control(
        "Zobrazení",
        ["z", "days"],
        key="dv_chart_mode",
        default="z",
        required=True,
        format_func=lambda m: "Míra odchylky" if m == "z" else "Skutečnost vs. očekávání (dny)",
        label_visibility="collapsed",
    )
    m0 = metrics[0]
    if mode == "days":
        df = w.rename(
            columns={f"obs__{m0}": "observed", f"exp__{m0}": "expected", f"res__{m0}": "residual"}
        )
        fig = charts.observed_vs_expected(df, highlight, PLAIN_METRIC.get(m0, g.metric_labels[m0]))
        st.plotly_chart(
            fig, key=chart_key, on_select="rerun", selection_mode=("points", "box", "lasso"), width="stretch"
        )
        st.caption(
            "Každý bod je jeden pacient. Na čárkované úhlopříčce by skutečnost přesně odpovídala očekávání; "
            "nad ní jsou pobyty delší, pod ní kratší. Barevně jsou pacienti nad hranicí. Kliknutím na bod "
            "zobrazíte vysvětlení."
        )
    elif len(metrics) == 1:
        df = w.rename(
            columns={f"z__{m0}": "z", f"obs__{m0}": "observed", f"exp__{m0}": "expected", f"res__{m0}": "residual"}
        )
        fig = charts.residual_strip(
            df, a.config.threshold, highlight, "míra odchylky (← kratší než obvykle · delší než obvykle →)"
        )
        st.plotly_chart(
            fig, key=chart_key, on_select="rerun", selection_mode=("points", "box", "lasso"), width="stretch"
        )
        st.caption(
            "Každý bod je jeden pacient, řádky jsou skupiny diagnóz. Čím dál od středu, tím neobvyklejší rozdíl "
            "oproti podobným pacientům; za čárkovanými čarami jsou neobvyklí pacienti. Kliknutím na bod "
            "zobrazíte vysvětlení, tažením vyberete víc pacientů."
        )
    else:
        mx, my = metrics[0], metrics[1]
        df = w.assign(zx=w[f"z__{mx}"], zy=w[f"z__{my}"])
        df["info"] = [
            f"{PLAIN_METRIC.get(mx, mx)}: {_days(r[f'obs__{mx}'])} místo {_days(r[f'exp__{mx}'])}"
            f"<br>{PLAIN_METRIC.get(my, my)}: {_days(r[f'obs__{my}'])} místo {_days(r[f'exp__{my}'])}"
            for _, r in df.iterrows()
        ]
        fig = charts.z_scatter(
            df,
            f"míra odchylky – {PLAIN_METRIC.get(mx, mx).lower()}",
            f"míra odchylky – {PLAIN_METRIC.get(my, my).lower()}",
            a.config.threshold,
            highlight,
        )
        st.plotly_chart(
            fig, key=chart_key, on_select="rerun", selection_mode=("points", "box", "lasso"), width="stretch"
        )
        st.caption(
            "Každý bod je jeden pacient. Uvnitř čárkovaného čtverce jsou běžné rozdíly, mimo něj neobvyklí "
            "pacienti. Oba ukazatele spolu souvisejí, takže shoda v obou není nezávislým potvrzením."
        )
    n_not = int((~a.scores["scored"]).sum())
    if n_not:
        st.caption(f"{n_not} pacientů, které nelze porovnat, v grafu není.")


# ---------------------------------------------------------------------------
# Seznam neobvyklých pacientů (karty)
# ---------------------------------------------------------------------------


def _patient_sentence(dim: pd.Series, metric_id: str, g: GlobalResults) -> str:
    """„Typický pobyt **21 dní** místo obvyklých **5 dní** – o 16 dní déle (4,2×).“"""
    obs, exp, res = dim["observed"], dim["expected"], dim["residual"]
    label = PLAIN_METRIC.get(metric_id, g.metric_labels.get(metric_id, metric_id))
    if pd.isna(obs) or pd.isna(exp):
        return f"{label}: údaj chybí."
    if res > 0:
        tail = f"o {_days(abs(res))} déle"
        if exp >= 1 and obs / exp >= 1.5:
            tail += f" ({fmt_num(obs / exp)}×)"
    elif res < 0:
        tail = f"o {_days(abs(res))} kratší"
        if obs >= 1 and exp / obs >= 1.5:
            tail += f" ({fmt_num(exp / obs)}× kratší)"
    else:
        tail = "přesně podle očekávání"
    return f"{label} **{_days(obs)}** místo obvyklých **{_days(exp)}** – {tail}."


def _driver_dim(a: AnalysisResult, pid: str) -> tuple[pd.Series, str]:
    s = a.scores.set_index("patient_id").loc[pid]
    metric = s["driver_metric"] or a.config.metrics[0]
    d = a.dims[(a.dims["patient_id"] == pid) & (a.dims["metric_id"] == metric)].iloc[0]
    return d, metric


def _outlier_list(g: GlobalResults, a: AnalysisResult) -> None:
    s = a.scores[a.scores["scored"]].sort_values("rank")
    out = s[s["outlier"]]
    near = s[s["band"] == "těsně pod prahem"]
    st.markdown(f"#### Neobvyklí pacienti ({len(out)})")
    if out.empty and near.empty:
        st.caption("Při této hranici nikdo. Zkuste hranici snížit.")
        return
    t = g.patient_table.set_index("patient_id")
    cur = state.reviews_current()
    rv = cur.set_index("patient_id")["status"] if not cur.empty else pd.Series(dtype=str)
    focus = st.session_state.get(state.K_FOCUS)
    with st.container(height=560, border=False):
        for _, r in out.iterrows():
            _card(g, a, r, t, rv, focus)
        if len(near):
            st.markdown(f"**Těsně pod hranicí ({len(near)})**")
            for _, r in near.iterrows():
                _card(g, a, r, t, rv, focus)


def _card(g, a, r: pd.Series, t: pd.DataFrame, rv: pd.Series, focus: str | None) -> None:
    pid = r["patient_id"]
    d, metric = _driver_dim(a, pid)
    group = t.at[pid, "dx_group_label"] if t.at[pid, "dx_group"] else ""
    with st.container(border=True):
        st.markdown(f"**{pid}** · {t.at[pid, 'dx_icd10']} {group} · :gray[{t.at[pid, 'age_group']} let]")
        st.markdown(_patient_sentence(d, metric, g))
        badges = []
        text, color = BAND_BADGE.get(r["band"], (r["band"], "gray"))
        badges.append(f":{color}-badge[{text}]")
        if r["support_level"] == "omezená opora":
            badges.append(":gray-badge[:material/warning: méně spolehlivé]")
        status = rv.get(pid, "")
        if status and status != ReviewStatus.NOT_REVIEWED.value:
            badges.append(f":blue-badge[{review_label(status)}]")
        if r.get("cluster_label") and str(r["cluster_label"]).startswith("Skupina"):
            badges.append(f":violet-badge[{r['cluster_label']}]")
        b1, b2 = st.columns([2.2, 1], vertical_alignment="center")
        b1.markdown(" ".join(badges))
        b2.button(
            "Vybráno" if pid == focus else "Vysvětlit",
            key=f"dv_pick_{pid}",
            type="primary" if pid == focus else "secondary",
            icon=":material/check:" if pid == focus else ":material/arrow_downward:",
            width="stretch",
            on_click=_pick,
            args=(pid,),
        )


def _pick(pid: str) -> None:
    st.session_state[state.K_INVESTIGATED] = [pid]
    st.session_state[state.K_FOCUS] = pid


# ---------------------------------------------------------------------------
# Vysvětlení vybraného pacienta
# ---------------------------------------------------------------------------


def _focus(g: GlobalResults, a: AnalysisResult) -> None:
    inv = [p for p in st.session_state.get(state.K_INVESTIGATED, []) if p in set(g.core["patient_id"])]
    st.markdown(f"### Vybraní pacienti ({len(inv)})")
    if not inv:
        st.caption(
            "Klikněte na bod v grafu nebo na „Vysvětlit“ u pacienta v seznamu – zde se ukáže, proč je "
            "neobvyklý."
        )
        return
    focus = st.session_state.get(state.K_FOCUS)
    if focus not in inv:
        focus = inv[0]
    if len(inv) > 1:
        focus = st.selectbox(
            f"Vybráno {len(inv)} pacientů – vysvětlit:", inv, index=inv.index(focus), key=f"dv_focus_{state.nonce()}"
        )
    s = a.scores.set_index("patient_id").loc[focus]
    t = g.patient_table.set_index("patient_id").loc[focus]
    with st.container(border=True):
        left, right = st.columns([2.2, 1], gap="large")
        with left:
            group = t["dx_group_label"] if t["dx_group"] else ""
            st.markdown(f"#### {focus} · {t['dx_icd10']} {group}")
            st.caption(f"Věková skupina {t['age_group']} let, pohlaví {t['sex']}.")
            if not s["scored"]:
                st.info(f"Pacienta v tomto pohledu nelze porovnat: {s['not_scored_reason']}")
            else:
                for line in _why_lines(g, a, focus, s):
                    st.markdown(line)
            with st.expander("Čísla výpočtu"):
                ex = explain_flag(s, a.dims[a.dims["patient_id"] == focus], a.config, g.metric_labels)
                st.markdown(ex["summary"])
                st.dataframe(
                    ex["table"],
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "Pozorováno": st.column_config.NumberColumn(format="%.1f"),
                        "Očekávání": st.column_config.NumberColumn(format="%.1f"),
                        "Rozdíl (dny)": st.column_config.NumberColumn(format="%+.1f"),
                        "Relativní rozdíl": st.column_config.NumberColumn(format="percent"),
                        "Standardizovaná odchylka": st.column_config.NumberColumn(format="%+.2f"),
                    },
                )
                if ex["counterfactual"]:
                    st.caption(ex["counterfactual"])
            if st.button(
                f"Otevřít kartu pacienta {focus}", key="dv_open_detail", icon=":material/person:"
            ):
                state.open_patient(focus, from_analysis=True)
                st.switch_page(state.PATIENTS_PAGE)
            if len(inv) > 1:
                st.caption("Ve výběru: " + ", ".join(inv[:40]) + (" …" if len(inv) > 40 else ""))
        with right:
            st.markdown("**Posouzení lékařem**")
            components.review_card(focus)


def _why_lines(g: GlobalResults, a: AnalysisResult, pid: str, s: pd.Series) -> list[str]:
    cfg = a.config
    d, metric = _driver_dim(a, pid)
    lines = [_patient_sentence(d, metric, g)]
    other = a.dims[(a.dims["patient_id"] == pid) & (a.dims["metric_id"] != metric)]
    for _, o in other.iterrows():
        lines.append(":gray[" + _patient_sentence(o, o["metric_id"], g).replace("**", "") + "]")

    r = g.results_long[(g.results_long["patient_id"] == pid) & (g.results_long["metric_id"] == metric)].iloc[0]
    n_ref = int(r["reference_n"])
    if n_ref:
        level = str(r.get("reference_level_label", "") or "").replace("stejná ", "stejnou ")
        lines.append(
            f"**S kým porovnáváme:** {_n_phrase(n_ref, 'podobný pacient', 'podobní pacienti', 'podobných pacientů')}"
            + (f" ({level})" if level else "")
            + f"; do výpočtu pacienta vstupuje {_n_phrase(int(d['support_n']), 'pobyt', 'pobyty', 'pobytů')}."
        )

    z = abs(float(d["z"]))
    verdict = "je **neobvyklý**" if s["outlier"] else "**není** neobvyklý"
    lines.append(
        f"**Proč {verdict}:** rozdíl oproti očekávání je {fmt_num(z, 1)}× větší než rozdíly, jaké běžně vídáme "
        f"u ostatních pacientů (hranice je {fmt_num(cfg.threshold)})."
    )
    if pd.notna(d.get("allowed_low")) and pd.notna(d.get("allowed_high")):
        lines.append(
            f"**Co by bylo obvyklé:** při stejném očekávání by za běžný platil "
            f"{PLAIN_METRIC.get(metric, '').lower() or 'pobyt'} zhruba {_days(d['allowed_low'])} až "
            f"{_days(d['allowed_high'])}."
        )
    stricter = [t for t in cfg.sensitivity_thresholds if t > cfg.threshold]
    looser = [t for t in cfg.sensitivity_thresholds if t < cfg.threshold]
    if s["outlier"]:
        keep = [t for t in stricter if s["score"] >= t]
        if keep:
            lines.append(f"**Jak pevný je nález:** neobvyklý by zůstal i při přísnější hranici {fmt_num(max(keep))}.")
        elif stricter:
            lines.append(
                f"**Jak pevný je nález:** hraniční – při hranici {fmt_num(min(stricter))} by už označen nebyl."
            )
    else:
        flag = [t for t in looser if s["score"] >= t]
        if flag:
            lines.append(f"**Jak blízko je hranici:** při mírnější hranici {fmt_num(max(flag))} by byl označen.")
    if s["support_notes"]:
        lines.append(f":orange[⚠ Méně spolehlivé srovnání: {s['support_notes']}.]")
    if s.get("cluster_label") and str(s["cluster_label"]).startswith("Skupina"):
        lines.append(f"Patří do **{s['cluster_label']}** – viz Co mají společného.")
    return lines


# ---------------------------------------------------------------------------
# Skupiny
# ---------------------------------------------------------------------------


def _plain_finding(row: dict) -> str:
    label = row["feature_label"]
    if row["kind"] == "categorical":
        n_g = int(row["n_group_available"])
        cnt = int(round(row["group_stat"] * n_g))
        return (
            f"{label}: **{row['value']}** u {cnt} z {n_g} ve skupině, u ostatních jen u "
            f"{fmt_pct(row['reference_stat'])}"
            if row["difference"] > 0
            else f"{label}: **{row['value']}** jen u {cnt} z {n_g} ve skupině, u ostatních u "
            f"{fmt_pct(row['reference_stat'])}"
        )
    more = "více" if row["difference"] > 0 else "méně"
    return (
        f"{label}: ve skupině {more} – medián **{fmt_num(row['group_stat'])}** oproti "
        f"{fmt_num(row['reference_stat'])} u ostatních"
    )


def _groups(g: GlobalResults, a: AnalysisResult) -> None:
    st.markdown("### Co mají neobvyklí pacienti společného")
    info = a.cluster_info
    if info.get("status") != "clustered" or not a.group_cards:
        msg = {
            "no_outliers": "Při této hranici nejsou žádní neobvyklí pacienti, takže není co seskupovat.",
            "too_few": f"Neobvyklých pacientů je málo na hledání skupin (potřeba alespoň "
            f"{a.config.cluster_min_outliers}). Každý z nich je jednotlivý případ – zkuste mírnější hranici.",
        }.get(info.get("status"), "Mezi neobvyklými pacienty se neopakuje žádný společný vzorec.")
        st.caption(msg)
        return
    st.caption(
        "Seskupujeme jen neobvyklé pacienty podle toho, jak a jak moc se odchylují. U každé skupiny ukazujeme, "
        "čím se liší od ostatních porovnatelných pacientů. Jsou to hypotézy k ověření, ne prokázané souvislosti."
    )
    cols = st.columns(min(len(a.group_cards), 2), gap="medium")
    sc = a.scores.set_index("patient_id")
    for i, card in enumerate(a.group_cards):
        members = card["members"]
        dirs = sc.loc[members, "direction"]
        n_long, n_short = int((dirs == "longer").sum()), int((dirs == "shorter").sum())
        if n_long == len(members):
            how = "všichni s delšími pobyty"
        elif n_short == len(members):
            how = "všichni s kratšími pobyty"
        else:
            how = f"{n_long} s delšími, {n_short} s kratšími pobyty"
        d = a.dims[a.dims["patient_id"].isin(members) & (a.dims["metric_id"] == a.config.metrics[0])]
        with cols[i % len(cols)], st.container(border=True):
            st.markdown(f"#### {card['group']}: {_n_phrase(card['n'], 'pacient', 'pacienti', 'pacientů')}, {how}")
            st.markdown(
                f"{PLAIN_METRIC.get(a.config.metrics[0], 'Pobyt')} typicky **{_days(d['observed'].median())}** "
                f"místo obvyklých **{_days(d['expected'].median())}**."
            )
            st.markdown(f"**Diagnózy:** {card['dx_composition']}  \n**Věk:** {card['age_composition']}")
            rows = card.get("top_local_rows") or []
            if rows:
                st.markdown(
                    f"**Čím se liší od ostatních** ({card['n_reference']} porovnatelných pacientů):\n"
                    + "\n".join(f"- {_plain_finding(r)}" for r in rows)
                )
            else:
                st.markdown("Od ostatních pacientů se v dostupných údajích výrazně neliší.")
            for w in card["warnings"]:
                st.caption(f"⚠ {w}")
            b1, b2 = st.columns([1, 1.4], vertical_alignment="center")
            if b1.button("Ukázat v grafu", key=f"grp_show_{card['cluster_id']}", icon=":material/scatter_plot:"):
                st.session_state[state.K_INVESTIGATED] = list(members)
                st.session_state[state.K_FOCUS] = members[0]
                st.rerun()
            b2.caption(", ".join(members))
            with st.expander("Podrobnosti"):
                for line in card["profile"]:
                    st.markdown(f"- {line}")
                st.markdown(f"**Pohlaví:** {card['sex_composition']}")
                st.markdown(f"**Ve srovnání jen s pacienty stejných diagnóz** (n={card['n_dx_reference']}):")
                for f in card["top_dx"] or ["žádný rozdíl nepřekročil pracovní hranici popisu"]:
                    st.markdown(f"- {f}")
    iso = a.clusters[a.clusters["isolated"].astype(bool)] if not a.clusters.empty else a.clusters
    if len(iso):
        st.caption("Jednotliví neobvyklí pacienti bez skupiny: " + ", ".join(iso["patient_id"]))


# ---------------------------------------------------------------------------
# Vlastní graf ze dvou údajů
# ---------------------------------------------------------------------------


def _xy_options(g: GlobalResults) -> dict[str, str]:
    """Klíč → srozumitelný název. Jen číselné údaje, jeden údaj = jedna hodnota na pacienta."""
    opts: dict[str, str] = {}
    for m in g.baseline.config.outcomes:
        name = PLAIN_METRIC.get(m, g.metric_labels[m])
        opts[f"out:{m}:observed"] = f"{name} – skutečnost (dny)"
        opts[f"out:{m}:expected"] = f"{name} – očekávání (dny)"
        opts[f"out:{m}:residual"] = f"{name} – rozdíl oproti očekávání (dny)"
    opts["score"] = "Míra odchylky (aktuální nastavení)"
    _, num = descriptor_columns(g.extra_meta)
    for c in num:
        if c in g.patient_table.columns:
            opts[f"pt:{c}"] = g.label(c)
    labs = g.lab_catalog[g.lab_catalog["n_patients"] >= 15]
    for key, label in zip(labs["test_key"], labs["test_label"], strict=False):
        opts[f"lab:{key}"] = f"Laboratoř {label} (medián pacienta)"
    return opts


def _xy_values(g: GlobalResults, a: AnalysisResult, key: str) -> pd.Series:
    if key.startswith("out:"):
        _, m, field = key.split(":", 2)
        r = g.results_long[g.results_long["metric_id"] == m].set_index("patient_id")
        return pd.to_numeric(r[field], errors="coerce")
    if key == "score":
        return a.scores.set_index("patient_id")["score"].astype(float)
    if key.startswith("pt:"):
        return pd.to_numeric(g.patient_table.set_index("patient_id")[key[3:]], errors="coerce").astype(float)
    lm = g.lab_medians[g.lab_medians["test_key"] == key[4:]]
    return lm.set_index("patient_id")["median_value"].astype(float)


def _two_values(g: GlobalResults, a: AnalysisResult, chart_key: str) -> None:
    st.markdown("### Vlastní graf ze dvou údajů")
    st.caption(
        "Vyberte libovolné dva údaje. Graf ukáže medián obou (křížek) a zvýrazní pacienty, kteří od něj leží "
        "daleko – v kterémkoli směru. Na bod nebo řádek tabulky lze kliknout."
    )
    opts = _xy_options(g)
    keys = list(opts)
    _bind("dv_xy_x", "pt:n_inpatient_completed" if "pt:n_inpatient_completed" in opts else keys[0])
    _bind("dv_xy_y", "out:median_los_dx:observed" if "out:median_los_dx:observed" in opts else keys[1])
    _bind("dv_xy_thr", 2.5)
    c1, c2, c3 = st.columns([2, 2, 1.4], vertical_alignment="bottom")
    kx = c1.selectbox("Osa x", keys, key="dv_xy_x", format_func=opts.get)
    ky = c2.selectbox("Osa y", keys, key="dv_xy_y", format_func=opts.get)
    thr = c3.slider(
        "Co je „daleko“",
        1.5,
        5.0,
        step=0.1,
        key="dv_xy_thr",
        help="Vzdálenost od mediánu v násobcích běžného rozptylu (stejný princip jako míra odchylky).",
    )
    if kx == ky:
        st.info("Vyberte dva různé údaje.")
        return
    df = pd.DataFrame({"x": _xy_values(g, a, kx), "y": _xy_values(g, a, ky)}).dropna()
    df.index.name = "patient_id"
    df = df.reset_index()
    n_all = len(g.core)
    if len(df) < 8:
        st.info(f"Oba údaje má jen {len(df)} pacientů – na smysluplné srovnání je to málo.")
        return
    cx, sx, _ = robust_scale(df["x"].to_numpy(dtype=float))
    cy, sy, _ = robust_scale(df["y"].to_numpy(dtype=float))
    zx = (df["x"] - cx) / sx if np.isfinite(sx) else pd.Series(0.0, index=df.index)
    zy = (df["y"] - cy) / sy if np.isfinite(sy) else pd.Series(0.0, index=df.index)
    df["dist"] = np.sqrt(zx**2 + zy**2)
    df["far"] = df["dist"] >= thr
    df["info"] = [
        f"{opts[kx]}: {fmt_num(x, 2)} (medián {fmt_num(cx, 2)})<br>{opts[ky]}: {fmt_num(y, 2)} "
        f"(medián {fmt_num(cy, 2)})<br>vzdálenost {fmt_num(d, 1)}"
        for x, y, d in zip(df["x"], df["y"], df["dist"], strict=True)
    ]
    if not (np.isfinite(sx) and np.isfinite(sy)):
        st.warning(
            "Jeden z údajů má u většiny pacientů stejnou hodnotu – vzdálenost se počítá jen podle druhého."
        )
    highlight = set(st.session_state.get(state.K_INVESTIGATED, []))
    fig = charts.median_scatter(df, opts[kx], opts[ky], (cx, cy), (sx, sy), thr, highlight)
    st.plotly_chart(
        fig, key=chart_key, on_select="rerun", selection_mode=("points", "box", "lasso"), width="stretch",
        theme=None,
    )
    focus = st.session_state.get(state.K_FOCUS)
    if focus in set(df["patient_id"]):
        row = df.set_index("patient_id").loc[focus]
        with st.container(border=True):
            f1, f2 = st.columns([3, 1], vertical_alignment="center")
            f1.markdown(
                f"**Vybrán {focus}:** {opts[kx].lower()} {fmt_num(row['x'], 2)} (medián {fmt_num(cx, 2)}), "
                f"{opts[ky].lower()} {fmt_num(row['y'], 2)} (medián {fmt_num(cy, 2)}); vzdálenost "
                f"{fmt_num(row['dist'], 1)} – {'daleko od mediánu' if row['far'] else 'blízko mediánu'}. "
                "Podrobné vysvětlení odchylky je výše v části Vybraní pacienti."
            )
            if f2.button("Otevřít kartu pacienta", key="dv_xy_open", icon=":material/person:", width="stretch"):
                state.open_patient(focus, from_analysis=True)
                st.switch_page(state.PATIENTS_PAGE)
    far = df[df["far"]].sort_values("dist", ascending=False)
    st.caption(
        f"V grafu je {len(df)} z {n_all} pacientů (ostatním některý údaj chybí). Daleko od mediánu: "
        f"**{len(far)}**. Elipsa ukazuje hranici „daleko“; je to popis rozložení, ne klinický závěr."
    )
    if len(far):
        t = g.patient_table.set_index("patient_id")
        sc = a.scores.set_index("patient_id")
        view = pd.DataFrame(
            {
                "ID": far["patient_id"].to_numpy(),
                "Diagnóza": t.loc[far["patient_id"], "dx_icd10"].to_numpy(),
                opts[kx]: far["x"].to_numpy(),
                opts[ky]: far["y"].to_numpy(),
                "Vzdálenost": far["dist"].to_numpy(),
                "Neobvyklý v analýze": [
                    "ano" if bool(sc.at[p, "outlier"]) else "" for p in far["patient_id"]
                ],
            }
        )
        ev = st.dataframe(
            view,
            hide_index=True,
            width="stretch",
            height=min(320, 38 + 35 * len(view)),
            on_select="rerun",
            selection_mode="single-row",
            key=f"dv_xy_table_{state.nonce()}",
            column_config={
                opts[kx]: st.column_config.NumberColumn(format="%.2f"),
                opts[ky]: st.column_config.NumberColumn(format="%.2f"),
                "Vzdálenost": st.column_config.NumberColumn(format="%.1f"),
            },
        )
        if ev is not None and ev.selection.rows:
            pid = str(view.iloc[ev.selection.rows[0]]["ID"])
            if st.session_state.get(state.K_FOCUS) != pid:
                _pick(pid)
                st.rerun()


# ---------------------------------------------------------------------------
# Další nástroje
# ---------------------------------------------------------------------------


def _tools(g: GlobalResults, a: AnalysisResult, chart_sel: list[str]) -> list[str]:
    st.markdown("### Další nástroje")
    with st.expander("Porovnat jednu charakteristiku", icon=":material/bar_chart:"):
        _context(g, a)
    with st.expander("Vlastní výběr pacientů a srovnávací skupina", icon=":material/checklist:"):
        listed_ids = _selection_panel(g, a, chart_sel)
    with st.expander("Uložit nebo načíst pohled", icon=":material/bookmark:"):
        _saved_views(g, a)
    with st.expander("Jak se to počítá", icon=":material/help:"):
        st.markdown(
            "1. Pro každého pacienta známe **skutečnost** (jeho typický nebo nejdelší pobyt) a **očekávání** "
            "(totéž u podobných pacientů).\n"
            "2. Spočítáme **rozdíl** – poměrem, nebo ve dnech (Pokročilé nastavení).\n"
            "3. Zjistíme, jak velké rozdíly jsou u pacientů **běžné** (medián a robustní rozptyl, které "
            "samotní neobvyklí pacienti téměř neovlivní).\n"
            "4. **Míra odchylky** = kolikrát je rozdíl pacienta větší než běžný rozptyl. Od hranice výš je "
            "pacient neobvyklý.\n"
            "5. Neobvyklé pacienty seskupíme podle podobnosti odchylek a popíšeme, čím se skupina liší od ostatních."
        )
        _reference_info(g, a)
        if len(a.group_summary):
            st.download_button(
                "Stáhnout popis skupin (CSV)",
                a.group_summary.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"group_summary_{a.analysis_id}.csv",
                key="dl_groups",
            )
    return listed_ids


# ---------------------------------------------------------------------------
# Pomocné funkce (výběr, reference, srovnání, uložené pohledy)
# ---------------------------------------------------------------------------


def _reference_info(g: GlobalResults, a: AnalysisResult) -> None:
    cfg = a.config
    n_scored = int(a.scores["scored"].sum())
    if cfg.reference_ids is None:
        txt = f"**Lokální reference:** všichni hodnotitelní pacienti ({len(a.reference_ids)})."
    else:
        txt = (
            f"**Lokální reference:** vlastní výběr – {cfg.reference_label or 'uživatelský výběr'} "
            f"({len(a.reference_ids)} hodnotitelných z {len(cfg.reference_ids)} vybraných)."
        )
    cal = a.calibration
    parts = [
        f"{g.metric_labels.get(r.metric_id, r.metric_id)}: střed {fmt_num(r.center, 2)}, "
        f"měřítko {fmt_num(r.scale, 2)} ({r.scale_method}, n={r.n_reference})"
        for r in cal.itertuples()
    ]
    st.markdown(txt + f" Skórováno {n_scored} pacientů, nad prahem {int(a.scores['outlier'].sum())}.")
    st.caption(
        "Standardizace: " + "; ".join(parts) + ". Reference detektoru je jiný objekt než peer reference "
        "globálního očekávání."
    )
    if not cal["standardizable"].all():
        st.warning(
            "Některý ukazatel nelze v této referenci standardizovat (nulový rozptyl nebo malá reference)."
        )



def _chart_selection(chart_key: str) -> list[str]:
    ev = st.session_state.get(chart_key)
    ids: list[str] = []
    try:
        points = ev["selection"]["points"] if ev else []
    except (KeyError, TypeError):
        points = []
    for p in points:
        cd = p.get("customdata")
        pid = cd[0] if isinstance(cd, (list, tuple)) else cd
        if isinstance(pid, str) and pid not in ids:
            ids.append(pid)
    return ids


def _list_table(g: GlobalResults, a: AnalysisResult) -> pd.DataFrame:
    s = a.scores.set_index("patient_id")
    t = g.patient_table.set_index("patient_id")
    cur = state.reviews_current()
    rv = cur.set_index("patient_id")["status"] if not cur.empty else pd.Series(dtype=str)
    df = pd.DataFrame(
        {
            "ID": s.index,
            "Dg.": t.loc[s.index, "dx_icd10"].to_numpy(),
            "Míra": s["score"].to_numpy(),
            "Směr": [
                components.direction_text(d, short=True) if sc else "–"
                for d, sc in zip(s["direction"], s["scored"], strict=True)
            ],
            "Posouzení": [review_label(rv.get(p, "")) for p in s.index],
            "_group": t.loc[s.index, "dx_group_label"]
            .where(t.loc[s.index, "dx_group"] != "", "nezařazeno")
            .to_numpy(),
            "_outlier": s["outlier"].to_numpy(),
            "_scored": s["scored"].to_numpy(),
            "_direction": s["direction"].to_numpy(),
            "_review": [rv.get(p, ReviewStatus.NOT_REVIEWED.value) for p in s.index],
            "_age": t.loc[s.index, "age_group"].to_numpy(),
        }
    )
    return df.sort_values(["_scored", "Míra", "ID"], ascending=[False, False, True]).reset_index(drop=True)


def _selection_panel(g: GlobalResults, a: AnalysisResult, chart_sel: list[str]) -> list[str]:
    st.markdown("**Pacienti a role výběru**")
    df = _list_table(g, a)
    with st.expander("Filtry seznamu", icon=":material/filter_alt:"):
        groups = st.multiselect("Orientační skupina", sorted(df["_group"].unique()), key="dv_f_group")
        ages = st.multiselect(
            "Věková skupina", ["0-5", "6-8", "9-11", "12-14", "15-17", "18-20"], key="dv_f_age"
        )
        direction = st.selectbox("Směr", ["oba", "delší", "kratší"], key="dv_f_dir")
        only_out = st.toggle("Jen nad prahem", key="dv_f_out")
        only_scored = st.toggle("Jen hodnocení", key="dv_f_scored", value=False)
        reviews = st.multiselect(
            "Posouzení", [s.value for s in ReviewStatus], format_func=review_label, key="dv_f_review"
        )
    m = pd.Series(True, index=df.index)
    if groups:
        m &= df["_group"].isin(groups)
    if ages:
        m &= df["_age"].isin(ages)
    if direction != "oba":
        m &= df["_direction"] == ("longer" if direction == "delší" else "shorter")
    if only_out:
        m &= df["_outlier"]
    if only_scored:
        m &= df["_scored"]
    if reviews:
        m &= df["_review"].isin(reviews)
    view = df[m].reset_index(drop=True)
    shown = ["ID", "Dg.", "Míra", "Směr", "Posouzení"]
    ev = st.dataframe(
        view[shown],
        key=f"dv_list_{state.nonce()}",
        on_select="rerun",
        selection_mode="multi-row",
        hide_index=True,
        height=330,
        width="stretch",
        column_config={"Míra": st.column_config.NumberColumn(format="%.2f")},
    )
    table_sel = [str(view.iloc[i]["ID"]) for i in (ev.selection.rows if ev is not None else [])]
    selection = chart_sel or table_sel
    source = "z grafu" if chart_sel else "ze seznamu"
    target = selection or view["ID"].tolist()
    if selection:
        st.caption(f"Vybráno {len(selection)} pacientů {source}.")
    else:
        st.caption(f"Bez výběru – tlačítka použijí filtrovaný seznam ({len(view)} pacientů).")

    c1, c2 = st.columns(2)
    if c1.button(
        "Zobrazit vybrané",
        key="dv_show",
        width="stretch",
        help="Nastaví vyšetřovaný výběr (zvýraznění, kontext). Nic nepřepočítává.",
    ):
        st.session_state[state.K_INVESTIGATED] = list(target)
        st.session_state[state.K_FOCUS] = target[0] if len(target) == 1 else None
        st.rerun()
    if c2.button(
        "Použít jako referenci",
        key="dv_as_ref",
        width="stretch",
        help="Kalibruje lokální detektor jen na těchto pacientech. Globální očekávání se nemění.",
    ):
        cfg = state.analysis_config()
        label = f"{'výběr ' + source if selection else 'filtrovaný seznam'} ({len(target)})"
        state.set_analysis_config(replace(cfg, reference_ids=tuple(sorted(target)), reference_label=label))
        state.flash("info", f"Lokální reference nastavena: {label}. Globální očekávání beze změny.")
        st.rerun()
    c3, c4 = st.columns(2)
    if c3.button(
        "Výchozí reference",
        key="dv_ref_reset",
        width="stretch",
        disabled=state.analysis_config().reference_ids is None,
    ):
        state.set_analysis_config(replace(state.analysis_config(), reference_ids=None, reference_label=""))
        st.rerun()
    if c4.button("Zrušit výběr", key="dv_clear", width="stretch"):
        st.session_state[state.K_INVESTIGATED] = []
        st.session_state[state.K_FOCUS] = None
        state.bump_nonce()
        st.rerun()
    return view["ID"].tolist()



def _dims_wide(g: GlobalResults, a: AnalysisResult) -> pd.DataFrame:
    d = a.dims
    s = a.scores.set_index("patient_id")
    t = g.patient_table.set_index("patient_id")
    out = []
    for pid, sub in d.groupby("patient_id"):
        if not s.at[pid, "scored"]:
            continue
        row = {
            "patient_id": pid,
            "outlier": bool(s.at[pid, "outlier"]),
            "direction": s.at[pid, "direction"],
            "group_label": t.at[pid, "dx_group_label"]
            if t.at[pid, "dx_group"]
            else f"nezařazeno ({t.at[pid, 'dx_icd10']})",
        }
        for r in sub.itertuples():
            row[f"z__{r.metric_id}"] = r.z
            row[f"obs__{r.metric_id}"] = r.observed
            row[f"exp__{r.metric_id}"] = r.expected
            row[f"res__{r.metric_id}"] = r.residual
        out.append(row)
    return pd.DataFrame(out)



def _context(g: GlobalResults, a: AnalysisResult) -> None:
    inv = [p for p in st.session_state.get(state.K_INVESTIGATED, []) if p in set(g.core["patient_id"])]
    if inv:
        sel, sel_label = inv, f"vyšetřovaný výběr ({len(inv)})"
    else:
        sel = a.scores.loc[a.scores["outlier"], "patient_id"].tolist()
        sel_label = f"outlieři při aktuálním prahu ({len(sel)})"
    ref = [p for p in a.reference_ids if p not in set(sel)]
    if not sel:
        st.info("Není co srovnávat – vyberte pacienty nebo snižte práh.")
        return
    cat, num = descriptor_columns(g.extra_meta)
    labs = g.lab_catalog[g.lab_catalog["n_patients"] >= 3]
    options = [("cat", c) for c in cat] + [("num", c) for c in num] + [("lab", k) for k in labs["test_key"]]
    lab_labels = dict(zip(labs["test_key"], labs["test_label"], strict=False))
    kind, col = st.selectbox(
        "Charakteristika",
        options,
        key="dv_ctx_feature",
        format_func=lambda o: (
            f"Laboratoř {lab_labels[o[1]]} (medián na pacienta)" if o[0] == "lab" else g.label(o[1])
        ),
    )
    st.caption(
        f"Vybraní: {sel_label} · reference: lokální reference bez vybraných ({len(ref)}). Původní hodnoty, "
        "jeden pacient = jeden hlas."
    )
    t = g.patient_table.set_index("patient_id")
    if kind == "cat":

        def counts(ids):
            v = t.loc[ids, col].map(
                lambda x: (
                    "chybí"
                    if pd.isna(x) or x == ""
                    else ("ano" if x is True else "ne" if x is False else str(x))
                )
            )
            return v.value_counts()

        cs, cr = counts(sel), counts(ref)
        vals = sorted(set(cs.index) | set(cr.index))
        df = pd.DataFrame(
            {
                "value": vals,
                "count_sel": [int(cs.get(v, 0)) for v in vals],
                "count_ref": [int(cr.get(v, 0)) for v in vals],
            }
        )
        df["n_sel"], df["n_ref"] = len(sel), len(ref)
        df["share_sel"] = df["count_sel"] / max(len(sel), 1)
        df["share_ref"] = df["count_ref"] / max(len(ref), 1)
        st.plotly_chart(
            charts.category_compare(df, g.label(col)), key=f"ctx_{col}_{state.nonce()}", width="stretch"
        )
        df["rozdíl (p. b.)"] = (100 * (df["share_sel"] - df["share_ref"])).round(0)
        st.dataframe(
            df.rename(columns={"value": "Hodnota", "count_sel": "Vybraní", "count_ref": "Reference"})[
                ["Hodnota", "Vybraní", "Reference", "rozdíl (p. b.)"]
            ],
            hide_index=True,
            width="stretch",
        )
    else:
        if kind == "lab":
            lm = g.lab_medians[g.lab_medians["test_key"] == col].set_index("patient_id")["median_value"]
            vs, vr = lm.reindex(sel).dropna(), lm.reindex(ref).dropna()
            title, unit = f"Laboratoř {lab_labels[col]} – medián na pacienta", col.split("|")[-1]
        else:
            vs = pd.to_numeric(t.loc[sel, col], errors="coerce").dropna()
            vr = pd.to_numeric(t.loc[ref, col], errors="coerce").dropna()
            title, unit = g.label(col), ""
        st.plotly_chart(
            charts.numeric_compare(vs, vr, title, unit), key=f"ctxn_{col}_{state.nonce()}", width="stretch"
        )
        st.caption(
            f"Dostupné hodnoty: vybraní {len(vs)}/{len(sel)}, reference {len(vr)}/{len(ref)}. "
            f"Medián {fmt_num(vs.median())} vs. {fmt_num(vr.median())}."
        )



def _saved_views(g: GlobalResults, a: AnalysisResult) -> None:
    name = st.text_input("Název pohledu", key="dv_view_name", placeholder="např. C91 dlouhé pobyty")
    if st.button("Uložit pohled", key="dv_view_save", disabled=not name.strip()):
        store = state.store()
        store.save_view(
            {
                "view_id": a.analysis_id + "-" + now_iso()[-11:-1].replace(":", "").replace(".", ""),
                "name": name.strip(),
                "created_at": now_iso(),
                "dataset_fingerprint": g.dataset_fingerprint,
                "source_mode": g.source_mode.value,
                "baseline_config_id": g.baseline_config_id,
                "analysis_id": a.analysis_id,
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "method_version": METHOD_VERSION,
                "baseline_config_json": canonical_json(g.baseline.config.to_dict()),
                "analysis_config_json": canonical_json(a.config.to_dict()),
                "note": "",
            }
        )
        state.flash("success", f"Pohled „{name.strip()}“ uložen.")
        st.rerun()
    views = state.store().load_views()
    if views.empty:
        st.caption("Pro tento dataset zatím nejsou uložené pohledy.")
        return
    idx = st.selectbox(
        "Uložené pohledy",
        list(range(len(views))),
        key="dv_view_pick",
        format_func=lambda i: f"{views.iloc[i]['name']} · {views.iloc[i]['created_at'][:16]}",
    )
    v = views.iloc[idx]
    version_ok = (
        v["feature_schema_version"] == FEATURE_SCHEMA_VERSION and v["method_version"] == METHOD_VERSION
    )
    if not version_ok:
        st.warning(
            "Pohled byl uložen jinou verzí výpočtu – načte se jako nový výpočet s novou identitou; "
            "původní posouzení zůstanou historická."
        )
    same_global = v["baseline_config_id"] == g.baseline_config_id
    if not same_global:
        st.info(
            "Pohled používá jiné globální očekávání. Načtením se globální konfigurace přepne a přepočítá."
        )
    if st.button("Načíst pohled", key="dv_view_load"):
        st.session_state[state.K_BASELINE] = BaselineConfig.from_dict(json.loads(v["baseline_config_json"]))
        state.set_analysis_config(AnalysisConfig.from_dict(json.loads(v["analysis_config_json"])))
        _reset_widgets()
        state.flash("success", f"Načten pohled „{v['name']}“.")
        st.rerun()
