"""Stránka Analýza odchylek.

Lokální konfigurace (ukazatele, škála, práh, reference) mění jen tuto analýzu. Globální
očekávání se zde nepřepočítává. Tlačítka mají odlišné role:
- „Zobrazit vybrané“ → vyšetřovaný výběr (nic nepřepočítává),
- „Použít jako referenci“ → lokální reference kalibrace detektoru,
- „Výchozí reference“ → všichni hodnotitelní pacienti.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pandas as pd
import streamlit as st

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
from rakathon.formatting import fmt_num, fmt_signed_days
from rakathon.pipeline import GlobalResults
from rakathon.storage.csv_store import now_iso
from rakathon.ui import charts, components, state
from rakathon.ui.patients import _export_button

WIDGET_KEYS = ["dv_metrics", "dv_scale", "dv_threshold", "dv_limited", "dv_cluster_dist", "dv_cluster_min"]


def _bind(key: str, value) -> None:
    if key not in st.session_state:
        st.session_state[key] = value


def _reset_widgets() -> None:
    for k in WIDGET_KEYS:
        st.session_state.pop(k, None)
    state.bump_nonce()


def render() -> None:
    st.title("Analýza odchylek")
    state.show_flash()
    components.source_banner()
    g = state.global_results()
    _controls(g)
    a = state.local_analysis()
    components.context_caption(g, f"lokální pohled `{a.analysis_id}`")
    _reference_info(g, a)

    chart_key = f"dv_chart_{state.nonce()}"
    chart_sel = _chart_selection(chart_key)
    left, center = st.columns([1, 2.6], gap="medium")
    with left:
        listed_ids = _selection_panel(g, a, chart_sel)
    with center:
        tabs = st.tabs(
            ["Rozložení odchylek", "Neobvyklé případy", "Skupinové vzorce", "Kontext charakteristik"]
        )
        with tabs[0]:
            _distribution(g, a, chart_key)
        with tabs[1]:
            _ranked(g, a)
        with tabs[2]:
            _groups(g, a)
        with tabs[3]:
            _context(g, a)
    _investigated(g, a)
    _views_and_export(g, a, listed_ids)


# ---------------------------------------------------------------------------
# Ovládání lokální konfigurace
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

    c1, c2, c3, c4, c5 = st.columns([2.2, 1.5, 2, 1.6, 1.2], vertical_alignment="bottom")
    metrics = c1.pills(
        "Ukazatele (odchylky od očekávání)",
        outcomes,
        selection_mode="multi",
        key="dv_metrics",
        format_func=lambda m: g.metric_labels[m],
        help="Které výsledkové ukazatele vstupují do skóre. Nejdelší pobyt je korelovaný s mediánem.",
    )
    scale = c2.segmented_control(
        "Škála odchylky",
        ["log", "raw"],
        key="dv_scale",
        required=True,
        format_func=lambda s: "relativní (log)" if s == "log" else "dny",
    )
    threshold = c3.slider(
        "Pracovní práh míry odchylky",
        1.5,
        5.0,
        step=0.1,
        key="dv_threshold",
        help="Heuristika, ne pravděpodobnost. Změna počtu ukazatelů mění význam skóre.",
    )
    limited = c4.toggle(
        "Hodnotit i s omezenou referencí",
        key="dv_limited",
        help="Pacienti, jejichž očekávání vychází jen ze 4–7 srovnatelných pacientů.",
    )
    if c5.button("Výchozí pohled", key="dv_reset", icon=":material/restart_alt:"):
        state.set_analysis_config(default_analysis_config(state.settings()))
        st.session_state[state.K_INVESTIGATED] = []
        st.session_state[state.K_FOCUS] = None
        _reset_widgets()
        st.rerun()
    with st.expander("Pokročilé: seskupování outlierů"):
        d1, d2 = st.columns(2)
        dist = d1.slider(
            "Vzdálenost pro sloučení do skupiny (z-jednotky)",
            0.5,
            5.0,
            step=0.25,
            key="dv_cluster_dist",
            help="Větší hodnota = méně a větších skupin (konzervativnější).",
        )
        cmin = d2.number_input("Minimum outlierů pro hledání skupin", 2, 20, step=1, key="dv_cluster_min")

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


# ---------------------------------------------------------------------------
# Levý panel: filtry, seznam, role výběru
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Grafy
# ---------------------------------------------------------------------------


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


def _distribution(g: GlobalResults, a: AnalysisResult, chart_key: str) -> None:
    w = _dims_wide(g, a)
    n_not = int((~a.scores["scored"]).sum())
    if w.empty:
        st.info("V aktuálním nastavení není žádný pacient skórován – viz důvody v seznamu.")
        return
    highlight = set(st.session_state.get(state.K_INVESTIGATED, []))
    metrics = list(a.config.metrics)
    scale_txt = "relativní (log) škála" if a.config.scale == "log" else "dny"
    st.caption(
        f"Graf zobrazuje {len(w)} skórovaných pacientů; {n_not} nehodnotitelných v grafu není (jsou v seznamu). "
        f"Osa = standardizovaná odchylka ({scale_txt}) vůči lokální referenci. Výběr bodů (klik, obdélník, "
        "laso) se propíše do panelu vlevo; alternativou je výběr řádků v seznamu."
    )
    if len(metrics) == 1:
        m = metrics[0]
        df = w.rename(
            columns={
                f"z__{m}": "z",
                f"obs__{m}": "observed",
                f"exp__{m}": "expected",
                f"res__{m}": "residual",
            }
        )
        fig = charts.residual_strip(
            df, a.config.threshold, highlight, f"standardizovaná odchylka – {g.metric_labels[m]}"
        )
        st.plotly_chart(
            fig, key=chart_key, on_select="rerun", selection_mode=("points", "box", "lasso"), width="stretch"
        )
        st.plotly_chart(
            charts.observed_vs_expected(df, highlight, g.metric_labels[m]),
            key=f"ove_{state.nonce()}",
            width="stretch",
        )
    else:
        c1, c2 = st.columns(2)
        mx = c1.selectbox("Osa x", metrics, index=0, format_func=lambda m: g.metric_labels[m], key="dv_ax_x")
        my = c2.selectbox("Osa y", metrics, index=1, format_func=lambda m: g.metric_labels[m], key="dv_ax_y")
        df = w.assign(zx=w[f"z__{mx}"], zy=w[f"z__{my}"])
        df["info"] = [
            f"{g.metric_labels[mx]}: {fmt_num(r[f'obs__{mx}'])} vs {fmt_num(r[f'exp__{mx}'])} d ({fmt_signed_days(r[f'res__{mx}'])})"
            f"<br>{g.metric_labels[my]}: {fmt_num(r[f'obs__{my}'])} vs {fmt_num(r[f'exp__{my}'])} d"
            for _, r in df.iterrows()
        ]
        fig = charts.z_scatter(
            df,
            f"standardizovaná odchylka – {g.metric_labels[mx]}",
            f"standardizovaná odchylka – {g.metric_labels[my]}",
            a.config.threshold,
            highlight,
        )
        st.plotly_chart(
            fig, key=chart_key, on_select="rerun", selection_mode=("points", "box", "lasso"), width="stretch"
        )
        st.caption("Ukazatele jsou korelované – shoda v obou osách není nezávislým potvrzením.")
        out = w[w["outlier"]]
        if len(out):
            mat = out.set_index("patient_id")[[f"z__{m}" for m in metrics]]
            mat.columns = [g.metric_labels[m] for m in metrics]
            st.plotly_chart(charts.z_heatmap(mat), key=f"heat_{state.nonce()}", width="stretch")


# ---------------------------------------------------------------------------
# Seřazené případy
# ---------------------------------------------------------------------------


def _ranked(g: GlobalResults, a: AnalysisResult) -> None:
    show_all = st.toggle("Zobrazit i případy pod prahem", key="dv_rank_all")
    s = a.scores[a.scores["scored"]].sort_values("rank")
    if not show_all:
        s = s[s["outlier"] | (s["band"] == "těsně pod prahem")]
    if s.empty:
        st.info(
            "Při aktuálním prahu nejsou žádné neobvyklé ani hraniční případy. Nulový počet outlierů je platný výsledek."
        )
        return
    dims = a.dims.set_index(["patient_id", "metric_id"])
    t = g.patient_table.set_index("patient_id")
    cur = state.reviews_current()
    rv = cur.set_index("patient_id")["status"] if not cur.empty else pd.Series(dtype=str)
    rows = []
    for r in s.itertuples():
        d = dims.loc[(r.patient_id, r.driver_metric)]
        rows.append(
            {
                "Pořadí": r.rank,
                "ID": r.patient_id,
                "Dg.": t.at[r.patient_id, "dx_icd10"],
                "Míra": r.score,
                "Pásmo": r.band,
                "Směr": components.direction_text(r.direction, short=True),
                "Proč": (
                    f"{g.metric_labels[r.driver_metric]}: {fmt_num(d['observed'])} vs. {fmt_num(d['expected'])} dní "
                    f"({fmt_signed_days(d['residual'])})"
                ),
                "Opora": r.support_level + (f" ({r.support_notes})" if r.support_notes else ""),
                "Citlivost prahu": r.sensitivity,
                "Skupina": r.cluster_label,
                "Posouzení": review_label(rv.get(r.patient_id, "")),
            }
        )
    view = pd.DataFrame(rows)
    ev = st.dataframe(
        view,
        hide_index=True,
        width="stretch",
        height=360,
        on_select="rerun",
        selection_mode="single-row",
        key=f"dv_rank_{state.nonce()}",
        column_config={
            "Míra": st.column_config.NumberColumn(format="%.2f"),
            "Proč": st.column_config.TextColumn(width="large"),
        },
    )
    if ev is not None and ev.selection.rows:
        pid = str(view.iloc[ev.selection.rows[0]]["ID"])
        if st.session_state.get(state.K_FOCUS) != pid:
            st.session_state[state.K_FOCUS] = pid
            st.session_state[state.K_INVESTIGATED] = [pid]
            st.rerun()
    st.caption(
        "Pásmo a opora jsou oddělené: vysoké skóre s omezenou oporou není „jistý“ outlier. Citlivost ukazuje, "
        "při kterých předem zvolených prazích by byl případ označen (✔/✘) – nejde o pravděpodobnost."
    )


# ---------------------------------------------------------------------------
# Skupiny outlierů
# ---------------------------------------------------------------------------


def _groups(g: GlobalResults, a: AnalysisResult) -> None:
    info = a.cluster_info
    st.markdown(f"**{info['message']}**")
    st.caption(
        "Shlukuje se jen množina označených outlierů (ne celá kohorta). Popisy jsou deskriptivní hypotézy pro "
        "mentora; nebyly testovány na statistickou významnost."
    )
    for card in a.group_cards:
        with st.container(border=True):
            st.markdown(f"##### {card['group']} · {card['n']} pacientů")
            for line in card["profile"]:
                st.markdown(f"- {line}")
            st.markdown(
                f"**Diagnózy:** {card['dx_composition']}  \n**Věk:** {card['age_composition']}  \n"
                f"**Pohlaví:** {card['sex_composition']}"
            )
            st.markdown(f"**Nejvýraznější rozdíly vůči lokální referenci** (n={card['n_reference']}):")
            for f in card["top_local"] or ["žádný rozdíl nepřekročil pracovní hranici popisu"]:
                st.markdown(f"- {f}")
            with st.expander(f"Vůči referenci se stejnými diagnózami (n={card['n_dx_reference']})"):
                for f in card["top_dx"] or ["žádný rozdíl nepřekročil pracovní hranici popisu"]:
                    st.markdown(f"- {f}")
            for w in card["warnings"]:
                st.warning(w, icon=":material/info:")
            c1, c2 = st.columns([1, 2])
            if c1.button("Zobrazit členy skupiny", key=f"grp_show_{card['cluster_id']}"):
                st.session_state[state.K_INVESTIGATED] = list(card["members"])
                st.session_state[state.K_FOCUS] = None
                st.rerun()
            c2.caption("Členové: " + ", ".join(card["members"]))
    iso = a.clusters[a.clusters["isolated"].astype(bool)] if not a.clusters.empty else a.clusters
    if len(iso):
        st.markdown("**Jednotlivé / izolované případy:** " + ", ".join(iso["patient_id"]))
    if len(a.group_summary):
        st.download_button(
            "Stáhnout popis skupin (CSV)",
            a.group_summary.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"group_summary_{a.analysis_id}.csv",
            key="dl_groups",
        )


# ---------------------------------------------------------------------------
# Kontext charakteristik (EDA uvnitř pracovního postupu)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Vyšetřovaný výběr, uložení pohledu, export
# ---------------------------------------------------------------------------


def _investigated(g: GlobalResults, a: AnalysisResult) -> None:
    inv = [p for p in st.session_state.get(state.K_INVESTIGATED, []) if p in set(g.core["patient_id"])]
    st.divider()
    st.markdown(f"#### Vyšetřovaný výběr ({len(inv)})")
    if not inv:
        st.caption(
            "Vyberte pacienty v grafu nebo seznamu a stiskněte „Zobrazit vybrané“, případně vyberte případ v "
            "záložce Neobvyklé případy."
        )
        return
    focus = st.session_state.get(state.K_FOCUS)
    if focus not in inv:
        focus = inv[0]
    if len(inv) > 1:
        focus = st.selectbox(
            "Pacient pro vysvětlení", inv, index=inv.index(focus), key=f"dv_focus_{state.nonce()}"
        )
    s = a.scores.set_index("patient_id").loc[focus]
    ex = explain_flag(s, a.dims[a.dims["patient_id"] == focus], a.config, g.metric_labels)
    c1, c2 = st.columns([2, 1])
    with c1:
        st.markdown(f"**{focus}** – " + ex["summary"])
        if ex["counterfactual"]:
            st.caption(ex["counterfactual"])
        if st.button(f"Otevřít detail pacienta {focus}", key="dv_open_detail", icon=":material/person:"):
            state.open_patient(focus, from_analysis=True)
            st.switch_page(state.PATIENTS_PAGE)
        if len(inv) > 1:
            st.caption("Ve výběru: " + ", ".join(inv[:40]) + (" …" if len(inv) > 40 else ""))
    with c2:
        components.review_panel(
            focus, a.analysis_id, f"Analýza odchylek (práh {fmt_num(a.config.threshold)})", "dv"
        )


def _views_and_export(g: GlobalResults, a: AnalysisResult, listed_ids: list[str]) -> None:
    st.divider()
    c1, c2 = st.columns(2)
    with c1, st.expander("Uložit / načíst pohled", icon=":material/bookmark:"):
        _saved_views(g, a)
    with c2:
        st.markdown("**Export aktuální analýzy**")
        st.caption(
            "ZIP obsahuje pacienty ze seznamu vlevo (ve stejném pořadí a filtru), skóre, skupiny, posouzení, "
            "konfiguraci a verze."
        )
        _export_button(
            g,
            a,
            listed_ids,
            f"Analýza odchylek ({a.analysis_id})",
            {"seznam": "levý panel", "n": len(listed_ids)},
            key="dl_analysis",
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
