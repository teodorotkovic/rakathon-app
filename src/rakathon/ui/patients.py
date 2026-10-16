"""Stránka Pacienti: přehled seřazený podle odchylky a detail pacienta.

Pořadí a skóre vychází z uloženého globálního kontextu a VÝCHOZÍ lokální konfigurace
(config/defaults.json); experimenty ze stránky Analýza odchylek ho nemění.
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from rakathon.analysis.explanations import (
    explain_differences,
    explain_expectation,
    explain_flag,
    model_terms_table,
)
from rakathon.analysis.similarity import similar_patients
from rakathon.domain import EPISODE_CLASS_LABELS, AnalysisResult, EpisodeClass, ReviewStatus, review_label
from rakathon.features.catalog import EPISODE_RULES, descriptor_columns
from rakathon.formatting import fmt_days, fmt_num, fmt_signed_days
from rakathon.pipeline import GlobalResults
from rakathon.storage import exports
from rakathon.ui import charts, components, state

AGE_ORDER = ["0-5", "6-8", "9-11", "12-14", "15-17", "18-20"]


def render() -> None:
    st.title("Pacienti")
    state.show_flash()
    components.source_banner()
    g = state.global_results()
    a = state.default_analysis()
    pid = st.session_state.get(state.K_SELECTED)
    if pid and pid not in set(g.core["patient_id"]):
        st.session_state[state.K_SELECTED] = None
        pid = None
    if pid:
        render_detail(pid, g, a)
    else:
        render_overview(g, a)


# ---------------------------------------------------------------------------
# Přehled
# ---------------------------------------------------------------------------


def overview_table(g: GlobalResults, a: AnalysisResult, reviews_cur: pd.DataFrame) -> pd.DataFrame:
    metric = a.config.metrics[0]
    r = g.results_long[g.results_long["metric_id"] == metric].set_index("patient_id")
    s = a.scores.set_index("patient_id")
    t = g.patient_table.set_index("patient_id")
    rv = reviews_cur.set_index("patient_id")["status"] if not reviews_cur.empty else pd.Series(dtype=str)
    df = pd.DataFrame(index=t.index)
    df["ID"] = t.index
    df["Věk"] = t["age_group"]
    df["Diagnóza"] = t["dx_icd10"] + " · " + t["dx_group_label"].where(t["dx_group"] != "", "nezařazeno")
    df["Pozorováno (dny)"] = r["observed"]
    df["Očekávání (dny)"] = r["expected"]
    df["Rozdíl (dny)"] = r["residual"]
    df["Míra odchylky"] = s["score"]
    df["Směr"] = (
        s["direction"].map(lambda d: components.direction_text(d, short=True)).where(s["scored"], "–")
    )
    df["Opora reference"] = r.apply(components.support_text, axis=1)
    df["Posouzení"] = [review_label(rv.get(p, "")) for p in df.index]
    df["Pásmo"] = s["band"]
    df["Pobytů"] = r["support_n"].astype(int)
    df["Důvod nehodnocení"] = s["not_scored_reason"]
    # skryté pomocné sloupce pro filtry
    df["_sex"] = t["sex"]
    df["_scored"] = s["scored"].astype(bool)
    df["_outlier"] = s["outlier"].astype(bool)
    df["_direction"] = s["direction"]
    df["_review"] = [rv.get(p, ReviewStatus.NOT_REVIEWED.value) for p in df.index]
    df["_has_labs"] = t["has_labs"]
    df["_dx"] = t["dx_icd10"]
    df["_group"] = t["dx_group_label"]
    df["_support"] = s["support_level"]
    df = df.sort_values(
        ["_scored", "Míra odchylky", "ID"], ascending=[False, False, True], na_position="last"
    )
    return df.reset_index(drop=True)


def _filters(df: pd.DataFrame, g: GlobalResults) -> tuple[pd.DataFrame, dict]:
    with st.expander("Filtry a vyhledávání", expanded=False, icon=":material/filter_alt:"):
        c1, c2, c3, c4 = st.columns([1.2, 1.5, 1, 2])
        q = c1.text_input("Hledat ID", key="pf_q", placeholder="např. P0123")
        ages = c2.multiselect("Věková skupina", AGE_ORDER, key="pf_age")
        sexes = c3.multiselect("Pohlaví", ["M", "F"], key="pf_sex")
        dx_opts = sorted(df["Diagnóza"].unique())
        dxs = c4.multiselect("Diagnóza / skupina", dx_opts, key="pf_dx")
        c5, c6, c7, c8 = st.columns([1.5, 1.4, 1.3, 1.8])
        avail = c5.selectbox(
            "Dostupnost",
            [
                "vše",
                "jen hodnocení",
                "jen nehodnotitelní",
                "s laboratořemi",
                "bez laboratoří",
                "jen omezená opora",
            ],
            key="pf_avail",
        )
        direction = c6.selectbox(
            "Směr odchylky", ["oba", "delší než očekávání", "kratší než očekávání"], key="pf_dir"
        )
        min_score = c7.number_input("Míra odchylky ≥", 0.0, 20.0, 0.0, 0.5, key="pf_min")
        review_opts = [s.value for s in ReviewStatus]
        reviews = c8.multiselect("Stav posouzení", review_opts, format_func=review_label, key="pf_review")
        extra_filter = None
        b = state.dataset()
        if b.extra_meta is not None and len(b.extra_meta):
            col = st.selectbox(
                "Doplňková vlastnost",
                ["—"] + list(b.extra_meta["column"]),
                key="pf_extra_col",
                format_func=lambda c: c if c == "—" else g.label(c),
            )
            if col != "—":
                vals = g.patient_table.set_index("patient_id")[col]
                if b.extra_meta.set_index("column").at[col, "dtype"] == "numeric" and vals.notna().any():
                    lo, hi = float(vals.min()), float(vals.max())
                    rng = st.slider("Rozsah", lo, hi, (lo, hi), key="pf_extra_rng") if hi > lo else (lo, hi)
                    extra_filter = (col, vals[(vals >= rng[0]) & (vals <= rng[1])].index)
                else:
                    opts = sorted(vals.dropna().astype(str).unique())
                    chosen = st.multiselect("Hodnoty", opts, key="pf_extra_vals")
                    if chosen:
                        extra_filter = (col, vals[vals.astype(str).isin(chosen)].index)
    m = pd.Series(True, index=df.index)
    if q:
        m &= df["ID"].str.contains(q.strip(), case=False, regex=False)
    if ages:
        m &= df["Věk"].isin(ages)
    if sexes:
        m &= df["_sex"].isin(sexes)
    if dxs:
        m &= df["Diagnóza"].isin(dxs)
    m &= {
        "vše": True,
        "jen hodnocení": df["_scored"],
        "jen nehodnotitelní": ~df["_scored"],
        "s laboratořemi": df["_has_labs"],
        "bez laboratoří": ~df["_has_labs"],
        "jen omezená opora": df["_support"] == "omezená opora",
    }[avail]
    if direction != "oba":
        m &= df["_direction"] == ("longer" if direction.startswith("delší") else "shorter")
        m &= df["_scored"]
    if min_score > 0:
        m &= df["Míra odchylky"].fillna(-1) >= min_score
    if reviews:
        m &= df["_review"].isin(reviews)
    if extra_filter is not None:
        m &= df["ID"].isin(set(extra_filter[1]))
    filters = {
        "hledat": q,
        "vek": ages,
        "pohlavi": sexes,
        "diagnoza": dxs,
        "dostupnost": avail,
        "smer": direction,
        "min_mira": min_score,
        "posouzeni": reviews,
        "doplnkova": extra_filter[0] if extra_filter else "",
    }
    return df[m].reset_index(drop=True), filters


def render_overview(g: GlobalResults, a: AnalysisResult) -> None:
    metric = a.config.metrics[0]
    components.context_caption(
        g,
        f"výchozí pohled: práh {fmt_num(a.config.threshold)}, "
        f"{'relativní (log) škála' if a.config.scale == 'log' else 'dny'}",
    )
    rule = g.baseline.config.episode_rule
    with st.expander("Jak číst tento přehled", icon=":material/help:"):
        st.markdown(
            f"- **Ukazatel:** {g.metric_long_labels[metric]}. Nejde o kompletní zátěž onkologické léčby.\n"
            f"- **Očekávání** = medián stejného ukazatele u jiných podobných pacientů (stejná diagnóza, případně věk a "
            "pohlaví; při nedostatku případů širší skupina). Pacient se do vlastní reference nepočítá.\n"
            "- **Míra odchylky** = o kolik se rozdíl liší od typického rozdílu v kohortě (robustní standardizace). "
            f"Práh {fmt_num(a.config.threshold)} je pracovní heuristika, ne pravděpodobnost.\n"
            "- **Směr**: ▲ delší / ▼ kratší zaznamenaný pobyt než očekávání. Kratší pobyt neznamená automaticky "
            "lepší průběh.\n"
            f"- **Omezení:** {EPISODE_RULES[rule]['limitation']} Den 0 je první záznam v nemocnici, ne diagnóza."
        )
    reviews_cur = state.reviews_current()
    full = overview_table(g, a, reviews_cur)
    df, filters = _filters(full, g)

    n_total = len(full)
    n_scored = int(full["_scored"].sum())
    outl = full[full["_outlier"]]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Hodnoceno", f"{n_scored} / {n_total}")
    c2.metric(
        f"Nad prahem {fmt_num(a.config.threshold)}",
        len(outl),
        help=f"▲ delší: {int((outl['_direction'] == 'longer').sum())} · ▼ kratší: "
        f"{int((outl['_direction'] == 'shorter').sum())}",
    )
    c3.metric(
        "Omezená opora dat",
        int((full["_support"] == "omezená opora").sum()),
        help="Omezená reference (4–7 pacientů) nebo méně než 2 pobyty ve výpočtu.",
    )
    c4.metric(
        "Nelze posoudit",
        n_total - n_scored,
        help="Chybí výsledek nebo srovnatelná reference. Zobrazí se na konci tabulky; filtr Dostupnost.",
    )

    st.caption(
        f"Zobrazeno {len(df)} z {n_total} pacientů · seřazeno podle míry odchylky, nehodnotitelní na konci. "
        "Kliknutím na řádek otevřete detail."
    )
    shown = [c for c in df.columns if not c.startswith("_")]
    event = st.dataframe(
        df[shown],
        key=f"patients_table_{state.nonce()}",
        on_select="rerun",
        selection_mode="single-row",
        hide_index=True,
        height=440,
        width="stretch",
        column_config={
            "Pozorováno (dny)": st.column_config.NumberColumn(format="%.1f"),
            "Očekávání (dny)": st.column_config.NumberColumn(format="%.1f"),
            "Rozdíl (dny)": st.column_config.NumberColumn(format="%+.1f"),
            "Míra odchylky": st.column_config.NumberColumn(
                format="%.2f", help="Maximum |standardizované odchylky|."
            ),
            "Důvod nehodnocení": st.column_config.TextColumn(width="large"),
        },
    )
    rows = event.selection.rows if event is not None else []
    if rows:
        state.open_patient(str(df.iloc[rows[0]]["ID"]))
        st.rerun()

    c1, c2, c3 = st.columns([2, 1, 2])
    pick = c1.selectbox(
        "Otevřít pacienta podle ID", df["ID"].tolist(), index=None, key="pf_pick", placeholder="vyberte ID…"
    )
    if c2.button("Otevřít detail", key="pf_open", disabled=pick is None):
        state.open_patient(pick)
        st.rerun()
    with c3:
        _export_button(g, a, df["ID"].tolist(), "Pacienti – výchozí pohled", filters, key="dl_patients")


def _export_button(
    g: GlobalResults, a: AnalysisResult, ids: list[str], view: str, filters: dict, key: str
) -> None:
    reviews = state.reviews_all()
    from rakathon.storage.csv_store import current_reviews

    cur = current_reviews(reviews, g.dataset_fingerprint, g.baseline_config_id)
    tables = {
        "patient_results.csv": exports.patient_results_table(g, ids),
        "analysis_results.csv": exports.analysis_results_table(g, a, cur, ids, view),
        "reviews.csv": exports.reviews_export_table(reviews),
        "analysis_config.csv": exports.config_table(g, a, view, filters),
        "group_summary.csv": a.group_summary,
        "data_quality.csv": state.dataset().validation.to_frame(),
    }
    meta = {
        "view": view,
        "n_patients": len(ids),
        "patient_order": ids,
        "analysis_id": a.analysis_id,
        "baseline_config_id": g.baseline_config_id,
        "dataset_fingerprint": g.dataset_fingerprint,
        "source_mode": g.source_mode.value,
        "filters": filters,
    }
    st.download_button(
        f"Exportovat zobrazený pohled ({len(ids)} pac.) – ZIP",
        exports.build_zip(tables, meta),
        file_name=f"rakathon_export_{a.analysis_id}.zip",
        mime="application/zip",
        key=key,
        icon=":material/download:",
        width="stretch",
    )


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------


def render_detail(pid: str, g: GlobalResults, a: AnalysisResult) -> None:
    if st.button("← Zpět na seznam", key="detail_back"):
        st.session_state[state.K_SELECTED] = None
        st.session_state[state.K_FROM_ANALYSIS] = False
        state.bump_nonce()
        st.rerun()
    core = g.core.set_index("patient_id").loc[pid]
    t = g.patient_table.set_index("patient_id").loc[pid]
    res = g.results_long[g.results_long["patient_id"] == pid].set_index("metric_id")
    srow = a.scores.set_index("patient_id").loc[pid]
    main = a.config.metrics[0]
    r = res.loc[main]

    st.subheader(f"Pacient {pid}")
    st.markdown(
        f"**{core['dx_icd10']}** · {core['dx_group_label'] if core['dx_group'] else 'diagnóza nezařazena do skupiny'} · "
        f"věková skupina {core['age_group']} · pohlaví {core['sex']}"
        + (" · ⚠ více nádorů – vyřazen z baseline" if core["multi_tumor"] else "")
    )
    components.context_caption(g, f"výchozí pohled `{a.analysis_id}`")
    c = st.columns(5)
    c[0].metric(
        g.metric_labels[main],
        components.metric_value(r["observed"]),
        help=f"{g.metric_long_labels[main]}. Vychází z {int(r['support_n'])} pobytů.",
    )
    c[1].metric(
        "Očekávání", components.metric_value(r["expected"]), help="Medián stejného ukazatele u reference."
    )
    c[2].metric("Rozdíl", fmt_signed_days(r["residual"]) if pd.notna(r["residual"]) else "–")
    c[3].metric(
        "Míra odchylky",
        fmt_num(srow["score"], 2) if srow["scored"] else "nehodnoceno",
        help="Pracovní práh " + fmt_num(a.config.threshold),
    )
    n_ref = int(r["reference_n"])
    c[4].metric(
        "Opora reference",
        f"{n_ref} pac." if n_ref else "nelze posoudit",
        help=components.support_text(r) + (f" – {r['baseline_reason']}" if r["baseline_reason"] else ""),
    )
    if srow["scored"]:
        st.markdown(
            f"**{srow['band'].capitalize()}** · {components.direction_text(srow['direction'])}"
            + (f" · ⚠ {srow['support_notes']}" if srow["support_notes"] else "")
        )
    else:
        st.info(f"Pacient není hodnocen: {srow['not_scored_reason']}")

    if st.session_state.get(state.K_FROM_ANALYSIS):
        la = state.local_analysis()
        if la.analysis_id != a.analysis_id:
            ls = la.scores.set_index("patient_id").loc[pid]
            st.caption(
                f"Z pohledu **Analýza odchylek** (`{la.analysis_id}`, práh {fmt_num(la.config.threshold)}, "
                f"ukazatele: {', '.join(g.metric_labels[m] for m in la.config.metrics)}): "
                + (
                    f"míra odchylky {fmt_num(ls['score'], 2)}, {ls['band']}"
                    if ls["scored"]
                    else "nehodnoceno"
                )
                + ". Globální očekávání je stejné."
            )

    left, right = st.columns([2.3, 1])
    with left:
        tabs = st.tabs(["Proč je neobvyklý", "Časová osa", "Laboratoře", "Podobní pacienti", "Nádor a data"])
        with tabs[0]:
            _tab_explanation(pid, g, a, res, srow)
        with tabs[1]:
            _tab_timeline(pid, g, t)
        with tabs[2]:
            _tab_labs(pid)
        with tabs[3]:
            _tab_similar(pid, g, a)
        with tabs[4]:
            _tab_tumour(pid, g, core, t)
    with right:
        st.markdown("#### Posouzení lékařem")
        components.review_panel(pid, a.analysis_id, "Pacienti – výchozí pohled", "pt")
        st.divider()
        if st.button(
            "Prozkoumat v analýze odchylek",
            key="detail_to_analysis",
            icon=":material/query_stats:",
            type="primary",
            width="stretch",
        ):
            st.session_state[state.K_INVESTIGATED] = [pid]
            st.session_state[state.K_FOCUS] = pid
            st.switch_page(state.DEVIATIONS_PAGE)
        st.caption("Přenese pacienta jako vyšetřovaný výběr; globální očekávání se nepřepočítává.")
        components.exclusion_button(pid, "pt")


def _tab_explanation(pid, g: GlobalResults, a: AnalysisResult, res: pd.DataFrame, srow: pd.Series) -> None:
    st.markdown("##### A. S čím pacienta porovnáváme")
    for m in g.baseline.config.outcomes:
        st.markdown(explain_expectation(res.loc[m], g.metric_labels[m]))
    main = a.config.metrics[0]
    r = res.loc[main]
    peers = [p for p in str(r["reference_ids"]).split(";") if p]
    is_model = isinstance(r.get("model_detail"), str) and bool(r.get("model_detail"))
    if is_model:
        st.caption(
            f"Rozklad predikce modelu pro „{g.metric_labels[main]}“ (stejný leave-one-out fit, který vydal "
            "očekávání; součet příspěvků v log1p škále = predikce)."
        )
        st.dataframe(
            model_terms_table(json.loads(r["model_detail"])),
            hide_index=True,
            width="stretch",
            column_config={
                "Příspěvek (log1p)": st.column_config.NumberColumn(format="%+.3f"),
                "Násobek (1 + délka)": st.column_config.NumberColumn(format="×%.2f"),
            },
        )
    peer_word = "pacientů se stejnou diagnostickou kategorií" if is_model else "referenčních pacientů"
    if peers:
        vals = g.results_long[
            (g.results_long["metric_id"] == main) & g.results_long["patient_id"].isin(peers)
        ]
        fig = charts.reference_strip(
            vals.set_index("patient_id")["observed"],
            float(r["observed"]),
            float(r["expected"]),
            float(r["ref_q1"]),
            float(r["ref_q3"]),
            g.metric_labels[main],
            srow["direction"] if srow["scored"] else "",
            pid,
        )
        st.plotly_chart(fig, key=f"refstrip_{pid}", width="stretch")
        st.caption(
            f"Body = {len(peers)} {peer_word} (jeden bod = jeden pacient). Šedé pásmo = kvartily "
            "(rozložení pozorovaných hodnot, ne predikční interval)."
        )

    st.markdown("##### B. Co vyvolává označení")
    dims = a.dims[a.dims["patient_id"] == pid]
    ex = explain_flag(srow, dims, a.config, g.metric_labels)
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

    st.markdown("##### C. Čím se pacient liší od srovnávaných")
    cat, num = descriptor_columns(g.extra_meta)
    cat = [c for c in cat if c not in ("dx_icd10", "dx_group_label")]  # u peerů dané výběrem reference
    if peers:
        comp = peers
        comp_label = (
            f"pacienti se stejnou diagnostickou kategorií ({len(peers)})"
            if is_model
            else f"pacienti použití pro očekávání ({len(peers)})"
        )
    else:
        comp = [p for p in g.core["patient_id"] if p != pid]
        comp_label = f"celá kohorta ({len(comp)}) – srovnatelná reference neexistuje"
    diff = explain_differences(pid, comp, g.patient_table, cat, num, g.label)
    st.caption(
        f"Srovnávací množina: {comp_label}. Deskriptivní souvislosti = hypotézy k ověření, ne příčiny "
        "ani prognostické faktory. Řazeno podle neobvyklosti hodnoty pacienta v této množině."
    )
    st.dataframe(diff.head(6).drop(columns="Neobvyklost"), hide_index=True, width="stretch")
    with st.expander("Všechny srovnávané charakteristiky"):
        st.dataframe(
            diff,
            hide_index=True,
            width="stretch",
            column_config={"Neobvyklost": st.column_config.ProgressColumn(min_value=0, max_value=1)},
        )


def _tab_timeline(pid: str, g: GlobalResults, t: pd.Series) -> None:
    b = state.dataset()
    eps = b.episodes[b.episodes["patient_id"] == pid].sort_values("seq")
    selected = set(g.selected_episodes.loc[g.selected_episodes["patient_id"] == pid, "episode_id"])
    only = st.toggle("Jen epizody vstupující do výpočtu ukazatele", key=f"tl_only_{pid}")
    show = eps[eps["episode_id"].isin(selected)] if only else eps
    if show.empty:
        st.info("Žádné epizody k zobrazení (pacient nemá pobyt splňující pravidlo výběru).")
    else:
        anchor = (
            t.get("anchor_day") if g.baseline.config.episode_rule == "from_anchor_all_inpatient" else None
        )
        st.plotly_chart(
            charts.timeline(show, selected, anchor), key=f"timeline_{pid}_{only}", width="stretch"
        )
    st.caption(
        f"{len(eps)} epizod: {int(t['n_outpatient'])} ambulantních, {int(t['n_inpatient_completed'])} dokončených "
        f"hospitalizací ({len(selected)} ve výpočtu), {int(t['n_inpatient_open'])} bez propuštění, "
        f"{int(t['n_invalid_intervals'])} neplatných intervalů. Rozsah historie {fmt_days(t['history_span_days'])}"
        " (není důkaz úplného sledování)."
        + (" První epizoda je porod (Z38)." if t["first_episode_birth"] else "")
    )
    with st.expander("Podkladová tabulka epizod"):
        view = show[["episode_id", "day_start", "day_end", "dx_main", "episode_class", "los_days"]].copy()
        view["episode_class"] = view["episode_class"].map(lambda c: EPISODE_CLASS_LABELS[EpisodeClass(c)])
        view["ve výpočtu"] = view["episode_id"].isin(selected).map({True: "ano", False: ""})
        st.dataframe(
            view.rename(
                columns={
                    "episode_id": "Epizoda",
                    "day_start": "Začátek (den)",
                    "day_end": "Konec (den)",
                    "dx_main": "Hlavní dg.",
                    "episode_class": "Typ",
                    "los_days": "Délka (dny)",
                }
            ),
            hide_index=True,
            width="stretch",
            height=300,
        )


def _tab_labs(pid: str) -> None:
    b = state.dataset()
    labs = b.labs[(b.labs["patient_id"] == pid) & b.labs["value_num"].notna()]
    if labs.empty:
        st.info(
            "Pro pacienta nejsou dostupné laboratorní záznamy. Chybějící laboratoř neznamená normální výsledek."
        )
        return
    summary = (
        labs.groupby("test_label")
        .agg(
            n=("value_num", "size"),
            median=("value_num", "median"),
            mimo_meze=("flag", lambda s: int(s.isin(["L", "H"]).sum())),
            bez_epizody=("episode_link", lambda s: int((s != "linked").sum())),
        )
        .sort_values("n", ascending=False)
    )
    tests = summary.index.tolist()
    choice = st.selectbox(
        "Test (kód · panel · jednotka)",
        tests,
        key=f"lab_test_{pid}",
        format_func=lambda x: f"{x} ({summary.at[x, 'n']} výsledků)",
    )
    sub = labs[labs["test_label"] == choice]
    st.plotly_chart(charts.lab_trend(sub, choice), key=f"lab_{pid}_{choice}", width="stretch")
    st.caption(
        "Názvy testů nejsou v datech ověřené – zobrazen kód, panel a jednotka. Meze mohou být dospělé; "
        "příznak L/H není automaticky klinická patologie. Hodnoty pod/nad mezí detekce nejsou označené."
    )
    with st.expander("Souhrn testů pacienta"):
        st.dataframe(
            summary.rename(
                columns={
                    "n": "Výsledků",
                    "median": "Medián",
                    "mimo_meze": "L/H",
                    "bez_epizody": "Mimo epizodu",
                }
            ),
            width="stretch",
        )


def _tab_similar(pid: str, g: GlobalResults, a: AnalysisResult) -> None:
    sim = similar_patients(pid, g.core, k=10)
    if sim.empty:
        st.info("Žádní pacienti se shodnou diagnózou/skupinou nebo věkem a pohlavím.")
        return
    main = a.config.metrics[0]
    r = g.results_long[g.results_long["metric_id"] == main].set_index("patient_id")
    s = a.scores.set_index("patient_id")
    sim["Pozorováno"] = sim["patient_id"].map(r["observed"])
    sim["Očekávání"] = sim["patient_id"].map(r["expected"])
    sim["Míra odchylky"] = sim["patient_id"].map(s["score"])
    view = sim.rename(
        columns={
            "patient_id": "ID",
            "reason": "Proč podobný",
            "dx_icd10": "Diagnóza",
            "age_group": "Věk",
            "sex": "Pohlaví",
        }
    ).drop(columns="similarity")
    st.caption(
        "Podobnost podle výchozích charakteristik (diagnóza/skupina, věk, pohlaví) – posuzovaný výsledek "
        "není kritériem. Kliknutím otevřete pacienta."
    )
    ev = st.dataframe(
        view,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key=f"similar_{pid}_{state.nonce()}",
        column_config={
            "Pozorováno": st.column_config.NumberColumn(format="%.1f"),
            "Očekávání": st.column_config.NumberColumn(format="%.1f"),
            "Míra odchylky": st.column_config.NumberColumn(format="%.2f"),
        },
    )
    if ev is not None and ev.selection.rows:
        state.open_patient(
            str(view.iloc[ev.selection.rows[0]]["ID"]), st.session_state.get(state.K_FROM_ANALYSIS)
        )
        state.bump_nonce()
        st.rerun()


def _tab_tumour(pid: str, g: GlobalResults, core: pd.Series, t: pd.Series) -> None:
    b = state.dataset()
    rows = b.patients[b.patients["patient_id"] == pid].sort_values("tumor_id_num")
    for _, p in rows.iterrows():
        st.markdown(f"**Nádor {p['tumor_id']}**")
        items = [
            (
                "Diagnóza MKN-10",
                p["dx_icd10"],
                p["dx_group_label"] if p["dx_group"] else "nezařazeno do skupiny",
            ),
            ("Topografie ICD-O-3", p["topography_icdo3"], "lokalizace (není totožná s MKN-10)"),
            (
                "Morfologie ICD-O-3",
                p["morphology_icdo3"],
                f"{p['morphology_status']}; {p['morphology_behaviour_label']}",
            ),
            ("Grade", p["grade"] or "–", p["grade_status"]),
            ("Stadium", p["stage"] or "–", p["stage_status"]),
            ("Rozsah (extent)", p["extent"] or "–", "význam kódu nepotvrzen"),
            ("Lateralita", p["laterality"] or "–", "kód NOR, překlad neověřen"),
            ("Klinické TNM", " ".join(x or "·" for x in (p["t"], p["n"], p["m"])), "raw kategorie"),
            (
                "Patologické TNM (+psu)",
                " ".join(x or "·" for x in (p["pt"], p["pn"], p["pm"], p["psu"])),
                "není automaticky dostupné v čase očekávání; psu význam nepotvrzen",
            ),
            ("Stav při exportu registru", p["deceased"], "není výsledkem ani vstupem baseline"),
        ]
        st.dataframe(
            pd.DataFrame(items, columns=["Údaj", "Původní hodnota", "Interpretace / stav"]),
            hide_index=True,
            width="stretch",
        )
    st.markdown("**Kvalita dat pacienta**")
    q = [
        ("Epizody bez hlavní diagnózy", int(t["n_dx_missing"])),
        ("Neplatné intervaly", int(t["n_invalid_intervals"])),
        ("Hospitalizace bez propuštění (shodná dg.)", int(t["n_open_matching_dx"])),
        ("Laboratoře mimo epizodu", int(t["n_labs_without_episode"])),
        ("První epizoda = porod (Z38)", "ano" if t["first_episode_birth"] else "ne"),
    ]
    st.dataframe(pd.DataFrame(q, columns=["Příznak", "Hodnota"]), hide_index=True, width="stretch")
    if b.extra_meta is not None and len(b.extra_meta):
        st.markdown("**Doplňkové vlastnosti** (popisné, neověřené klinicky)")
        ex = [(g.label(c), t.get(c)) for c in b.extra_meta["column"]]
        st.dataframe(
            pd.DataFrame(ex, columns=["Vlastnost", "Hodnota"]).astype(str), hide_index=True, width="stretch"
        )
