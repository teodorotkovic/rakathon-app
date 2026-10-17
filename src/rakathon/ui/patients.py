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
from rakathon.ui import charts, components, state, texts

AGE_ORDER = ["0-5", "6-8", "9-11", "12-14", "15-17", "18-20"]


def render() -> None:
    state.show_flash()
    g = state.global_results()
    a = state.default_analysis()
    pid = st.session_state.get(state.K_SELECTED)
    if pid and pid not in set(g.core["patient_id"]):
        st.session_state[state.K_SELECTED] = None
        pid = None
    if pid:
        render_detail(pid, g, a)
    else:
        st.title("Pacienti")
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
    df["Typ odchylky"] = s["band"]
    df["Posouzení"] = [review_label(rv.get(p, "")) for p in df.index]
    df["Spolehlivost"] = [
        reliability_text(
            bool(s.at[p, "scored"]),
            r.at[p, "baseline_status"],
            int(r.at[p, "support_n"]),
            a.config.min_support_stays,
        )
        for p in df.index
    ]
    df["Podobných pacientů"] = r["reference_n"].astype(float).where(r["reference_n"] > 0)
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


def reliability_text(scored: bool, baseline_status: str, support_n: int, min_stays: int) -> str:
    """Spolehlivost srovnání jedním slovem + důvod; pro lékaře místo „opory reference“."""
    if not scored:
        return "– nelze porovnat"
    reasons = []
    if baseline_status == "limited_reference":
        reasons.append("málo podobných pacientů")
    if support_n < min_stays:
        reasons.append(f"jen {support_n} pobyt" if support_n == 1 else f"jen {support_n} pobyty")
    return "⚠ omezená (" + ", ".join(reasons) + ")" if reasons else "✓ dobrá"


def patient_from_cell_selection(cells: list, table: pd.DataFrame) -> str | None:
    """Klik do libovolné buňky řádku → ID pacienta (podle pozice v tabulce předané widgetu)."""
    if not cells:
        return None
    row = cells[0][0] if isinstance(cells[0], (list, tuple)) else cells[0]
    if not isinstance(row, int) or not 0 <= row < len(table):
        return None
    return str(table.iloc[row]["ID"])


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
                "jen porovnatelní",
                "jen neporovnatelní",
                "s laboratořemi",
                "bez laboratoří",
                "jen omezená spolehlivost",
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
        "jen porovnatelní": df["_scored"],
        "jen neporovnatelní": ~df["_scored"],
        "s laboratořemi": df["_has_labs"],
        "bez laboratoří": ~df["_has_labs"],
        "jen omezená spolehlivost": df["Spolehlivost"].str.startswith("⚠"),
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
    cfg = g.baseline.config
    st.markdown(texts.plain_context(cfg.method, cfg.episode_rule, metric))
    st.caption("Nastavení změníte v postranním panelu → Jak počítáme očekávání.")
    reviews_cur = state.reviews_current()
    full = overview_table(g, a, reviews_cur)
    df, filters = _filters(full, g)

    n_total = len(full)
    n_scored = int(full["_scored"].sum())
    outl = full[full["_outlier"]]
    n_strong = int((outl["Typ odchylky"] == "výrazná odchylka").sum())
    c1, c2, _ = st.columns([1, 1, 2])
    c1.metric(
        "Lze porovnat",
        f"{n_scored} / {n_total}",
        help="Pacienti, u kterých je dostupný výsledek i dost podobných pacientů pro srovnání. U ostatních je "
        "v tabulce uveden důvod.",
    )
    c2.metric(
        "Neobvyklé případy",
        len(outl),
        help=f"Pacienti, jejichž délka pobytů se od očekávání liší mnohem víc než u většiny ostatních "
        f"(výrazné {n_strong}, hraniční {len(outl) - n_strong}; ▲ delší "
        f"{int((outl['_direction'] == 'longer').sum())}, ▼ kratší {int((outl['_direction'] == 'shorter').sum())}).",
    )

    st.caption(
        f"Zobrazeno {len(df)} z {n_total} pacientů. Výchozí řazení je od největší odchylky (pacienti, které nelze "
        "porovnat, jsou na konci); kliknutím na záhlaví sloupce seřadíte jinak. **Klikněte na řádek pro detail "
        "pacienta.**"
    )
    shown = [c for c in df.columns if not c.startswith("_")]
    table = df[shown]
    event = st.dataframe(
        table,
        key=f"patients_table_{state.nonce()}",
        on_select="rerun",
        selection_mode="single-cell",
        hide_index=True,
        height=440,
        width="stretch",
        column_config={
            "Pozorováno (dny)": st.column_config.NumberColumn(format="%.1f"),
            "Očekávání (dny)": st.column_config.NumberColumn(format="%.1f"),
            "Rozdíl (dny)": st.column_config.NumberColumn(format="%+.1f"),
            "Míra odchylky": st.column_config.NumberColumn(
                format="%.2f", help="Čím vyšší, tím neobvyklejší rozdíl oproti ostatním pacientům."
            ),
            "Spolehlivost": st.column_config.TextColumn(
                help="Omezená = srovnání jen s 4–7 podobnými pacienty nebo výsledek z jediného pobytu."
            ),
            "Podobných pacientů": st.column_config.NumberColumn(format="%d"),
            "Důvod nehodnocení": st.column_config.TextColumn(width="large"),
        },
    )
    pid = patient_from_cell_selection(event.selection.cells if event is not None else [], table)
    if pid:
        state.open_patient(pid)
        st.rerun()

    _, c2 = st.columns([3, 2])
    with c2:
        _export_button(g, a, df["ID"].tolist(), "Pacienti – výchozí pohled", filters, key="dl_patients")

    st.divider()
    with st.expander("Jak číst tento přehled", icon=":material/help:"):
        st.markdown(
            "- **Pozorováno / Očekávání / Rozdíl** – skutečná délka pobytů pacienta, typická délka u srovnávaných "
            "pacientů a rozdíl ve dnech.\n"
            "- **Míra odchylky** – o kolik je rozdíl neobvyklejší než rozdíly u ostatních pacientů. **Neobvyklé "
            f"případy** jsou od hodnoty {fmt_num(a.config.threshold)} (pracovní hranice, lze změnit v Analýze "
            "odchylek); nejde o pravděpodobnost.\n"
            "- **Směr** – ▲ delší / ▼ kratší pobyty než očekávání. Kratší pobyt neznamená automaticky lepší průběh.\n"
            "- **Spolehlivost** – omezená, pokud je podobných pacientů málo nebo výsledek stojí na jediném pobytu.\n"
            f"- **Omezení dat:** {EPISODE_RULES[cfg.episode_rule]['limitation']} Den 0 v datech je první záznam "
            "v nemocnici, ne datum diagnózy."
        )


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
    core = g.core.set_index("patient_id").loc[pid]
    t = g.patient_table.set_index("patient_id").loc[pid]
    res = g.results_long[g.results_long["patient_id"] == pid].set_index("metric_id")
    srow = a.scores.set_index("patient_id").loc[pid]
    r = res.loc[a.config.metrics[0]]

    head, action = st.columns([5, 1.6], vertical_alignment="bottom")
    with head:
        if st.button("Pacienti", key="detail_back", type="tertiary", icon=":material/arrow_back:"):
            st.session_state[state.K_SELECTED] = None
            st.session_state[state.K_FROM_ANALYSIS] = False
            state.bump_nonce()
            st.rerun()
        st.header(f"Pacient {pid}", anchor=False)
        st.caption(_patient_subtitle(core))
    with action:
        if st.button(
            "Prozkoumat odchylky", key="detail_to_analysis", icon=":material/query_stats:", width="stretch"
        ):
            st.session_state[state.K_INVESTIGATED] = [pid]
            st.session_state[state.K_FOCUS] = pid
            st.switch_page(state.DEVIATIONS_PAGE)

    _summary_card(pid, g, a, r, srow, core)

    tabs = st.tabs(["Přehled", "Epizody péče", "Laboratoř", "Podobní pacienti", "Nádor a data"])
    with tabs[0]:
        _tab_overview(pid, g, a, res, srow, core, t)
    with tabs[1]:
        _tab_timeline(pid, g, t)
    with tabs[2]:
        _tab_labs(pid)
    with tabs[3]:
        _tab_similar(pid, g, a)
    with tabs[4]:
        _tab_tumour(pid, g, core, t)

    if st.session_state.get(state.K_DIALOG) == f"review:{pid}":
        components.review_dialog(pid, a.analysis_id, "Pacienti – výchozí pohled")


def _patient_subtitle(core: pd.Series) -> str:
    adult = core["age_group"] == "18-20"
    sex = {"F": "žena" if adult else "dívka", "M": "muž" if adult else "chlapec"}.get(
        core["sex"], "pohlaví neuvedeno"
    )
    age = f"{core['age_group'].replace('-', '–')} let při diagnóze" if core["age_group"] else "věk neuveden"
    parts = [f"Diagnóza {core['dx_icd10'] or 'neuvedena'}", age, sex]
    if core["multi_tumor"]:
        parts.append("více nádorů – nevstupuje do výpočtu")
    return " · ".join(parts)


def _count_phrase(n: int, one: str, few: str, many: str) -> str:
    return f"{n} {one if n == 1 else few if 2 <= n <= 4 else many}"


def _scope_text(rule: str, core: pd.Series) -> str:
    if rule == "exact_dx_match" or not core["dx_group"]:
        return f"Pouze pobyty s hlavní diagnózou {core['dx_icd10']}"
    if rule == "group_dx_match":
        return f"Pobyty s diagnózou ze skupiny {core['dx_group_label']}"
    return "Všechny pobyty od prvního záznamu nádoru"


def _summary_card(
    pid: str, g: GlobalResults, a: AnalysisResult, r: pd.Series, srow: pd.Series, core: pd.Series
) -> None:
    observed, expected, residual = r["observed"], r["expected"], r["residual"]
    if pd.isna(observed):
        headline = "Pacienta nelze porovnat – chybí započitatelné pobyty"
    elif pd.isna(expected):
        headline = "Pacienta nelze porovnat – chybí srovnatelní pacienti"
    elif residual < 0:
        headline = "Zaznamenané pobyty jsou kratší než očekávání"
    elif residual > 0:
        headline = "Zaznamenané pobyty jsou delší než očekávání"
    else:
        headline = "Zaznamenané pobyty odpovídají očekávání"
    with st.container(border=True):
        h1, h2 = st.columns([3, 1.3], vertical_alignment="center")
        h1.markdown(f"#### {headline}")
        with h2:
            if srow["scored"] and srow["outlier"]:
                st.badge("Práh odchylky překročen", color="orange", icon=":material/flag:")
            elif srow["scored"]:
                st.badge("Práh odchylky nepřekročen", color="gray")
        main = a.config.metrics[0]
        c = st.columns(3)
        c[0].metric(
            "Typická délka pobytu · medián" if main == "median_los_dx" else g.metric_labels[main],
            components.metric_value(observed),
        )
        c[1].metric("Očekávání podle srovnání", components.metric_value(expected))
        c[2].metric("Rozdíl oproti očekávání", fmt_signed_days(residual) if pd.notna(residual) else "–")
        facts = [
            _count_phrase(int(r["support_n"]), "dokončený pobyt", "dokončené pobyty", "dokončených pobytů")
            + " ve výpočtu",
            _count_phrase(
                int(r["reference_n"]), "srovnávaný pacient", "srovnávaní pacienti", "srovnávaných pacientů"
            ),
            _scope_text(g.baseline.config.episode_rule, core),
        ]
        st.caption(" · ".join(facts))
        if pd.isna(observed) or pd.isna(expected):
            st.caption(f"Důvod: {srow['not_scored_reason'] or r['evaluability_reason']}")
        if st.session_state.get(state.K_FROM_ANALYSIS):
            la = state.local_analysis()
            if la.analysis_id != a.analysis_id:
                ls = la.scores.set_index("patient_id").loc[pid]
                st.caption(
                    f"Z pohledu **Analýza odchylek** (hranice {fmt_num(la.config.threshold)}, "
                    f"ukazatele: {', '.join(g.metric_labels[m] for m in la.config.metrics)}): "
                    + (
                        "práh překročen"
                        if ls["scored"] and ls["outlier"]
                        else "práh nepřekročen"
                        if ls["scored"]
                        else "nelze porovnat"
                    )
                    + ". Očekávání je stejné jako zde."
                )


def _tab_overview(
    pid,
    g: GlobalResults,
    a: AnalysisResult,
    res: pd.DataFrame,
    srow: pd.Series,
    core: pd.Series,
    t: pd.Series,
) -> None:
    left, right = st.columns([2, 1.1], gap="medium")
    with left:
        _comparison_card(pid, g, a, res, srow, core)
        _context_card(pid, g, a, res, t)
    with right:
        with st.container(border=True):
            st.markdown("#### Posouzení lékařem")
            components.review_card(pid)
        _data_card(pid, g, a, res, core, t)


def _reference_sentence(r: pd.Series, core: pd.Series, g: GlobalResults) -> str:
    if isinstance(r.get("model_detail"), str) and r["model_detail"]:
        return (
            "Odhad statistického modelu z diagnózy, věku a pohlaví; v grafu jsou pacienti se stejnou skupinou "
            "diagnózy."
        )
    if pd.isna(r["reference_level"]):
        return r["baseline_reason"] or "Srovnatelní pacienti nejsou k dispozici."
    keys = g.baseline.config.hierarchy[int(r["reference_level"]) - 1]
    pieces = {
        "dx_icd10": f"diagnóza {core['dx_icd10']}",
        "dx_group": f"skupina diagnóz ({core['dx_group_label']})",
        "age_group": f"věková skupina {core['age_group'].replace('-', '–')} let",
        "sex": "pohlaví",
    }
    used = [pieces[k] for k in keys]
    text = "Stejná " + (used[0] if len(used) == 1 else ", ".join(used[:-1]) + " a " + used[-1]) + "."
    missing = []
    if "dx_icd10" not in keys:
        missing.append(("Přesná diagnóza", "a"))
    if "age_group" not in keys:
        missing.append(("Věk", ""))
    if "sex" not in keys:
        missing.append(("pohlaví" if missing else "Pohlaví", "o"))
    if len(missing) == 1:
        text += f" {missing[0][0]} není samostatně zohledněn{missing[0][1]}."
    elif missing:
        names = [m[0] for m in missing]
        text += " " + ", ".join(names[:-1]) + " a " + names[-1].lower() + " nejsou samostatně zohledněny."
    return text


def _comparison_card(
    pid, g: GlobalResults, a: AnalysisResult, res: pd.DataFrame, srow: pd.Series, core
) -> None:
    main = a.config.metrics[0]
    r = res.loc[main]
    peers = [p for p in str(r["reference_ids"]).split(";") if p]
    with st.container(border=True):
        st.markdown("#### Pacient a srovnávací skupina")
        st.caption(_reference_sentence(r, core, g))
        if peers and pd.notna(r["observed"]):
            vals = g.results_long[
                (g.results_long["metric_id"] == main) & g.results_long["patient_id"].isin(peers)
            ]
            direction = srow["direction"] if srow["scored"] else ""
            fig = charts.reference_strip(
                vals.set_index("patient_id")["observed"],
                float(r["observed"]),
                float(r["expected"]),
                float(r["ref_q1"]),
                float(r["ref_q3"]),
                f"{g.metric_labels[main]} pacienta (dny)",
                direction,
                pid,
            )
            st.plotly_chart(fig, key=f"refstrip_{pid}", width="stretch", config={"displayModeBar": False})
            st.caption(
                f"Šedé pásmo: prostředních 50 % pacientských hodnot ({fmt_num(r['ref_q1'])}–{fmt_num(r['ref_q3'])} "
                "dní). Nejde o predikční interval."
            )
        if pd.notna(r["residual"]) and r["residual"] < 0:
            st.info("Kratší zaznamenaný pobyt sám o sobě neznamená příznivější zdravotní výsledek.")
        elif pd.notna(r["residual"]) and r["residual"] > 0:
            st.info(
                "Delší zaznamenaný pobyt sám o sobě neznamená horší zdravotní výsledek; příčiny posoudí lékař."
            )
        with st.expander("Jak vzniklo očekávání a označení"):
            for m in g.baseline.config.outcomes:
                st.markdown(explain_expectation(res.loc[m], g.metric_labels[m]))
            if isinstance(r.get("model_detail"), str) and r["model_detail"]:
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
            st.markdown("**Označení odchylky**")
            ex = explain_flag(srow, a.dims[a.dims["patient_id"] == pid], a.config, g.metric_labels)
            st.markdown(ex["summary"])
            st.dataframe(
                ex["table"],
                hide_index=True,
                width="stretch",
                column_config={
                    "Pozorováno": st.column_config.NumberColumn(format="%.1f"),
                    "Očekávání": st.column_config.NumberColumn(format="%.1f"),
                    "Rozdíl (dny)": st.column_config.NumberColumn(format="%+.1f"),
                    "Relativní rozdíl": st.column_config.NumberColumn(
                        format="percent", help="(pozorováno − očekávání) / očekávání"
                    ),
                    "Standardizovaná odchylka": st.column_config.NumberColumn(format="%+.2f"),
                },
            )
            if ex["counterfactual"]:
                st.caption(ex["counterfactual"])
            st.caption(
                f"Technické údaje: nastavení `{g.baseline_config_id}`, pohled `{a.analysis_id}`, "
                f"data `{g.dataset_fingerprint[:12]}`."
            )


def _context_card(pid, g: GlobalResults, a: AnalysisResult, res: pd.DataFrame, t: pd.Series) -> None:
    r = res.loc[a.config.metrics[0]]
    peers = [p for p in str(r["reference_ids"]).split(";") if p]
    table = g.patient_table.set_index("patient_id")
    ref = table.loc[[p for p in peers if p in table.index]]
    items: list[tuple[str, str, str]] = []
    keys = (
        g.baseline.config.hierarchy[int(r["reference_level"]) - 1]
        if pd.notna(r["reference_level"])
        and not (isinstance(r.get("model_detail"), str) and r["model_detail"])
        else ()
    )
    if len(ref) and "age_group" not in keys:
        same = int((ref["age_group"] == t["age_group"]).sum())
        items.append(
            (
                "Stejná věková skupina v referenci",
                f"{same} z {len(ref)}",
                "Reference zahrnuje i pacienty jiného věku. Věkovou srovnatelnost posoudí lékař."
                if same < len(ref)
                else "Všichni srovnávaní pacienti jsou ve stejné věkové skupině.",
            )
        )
    typical = f" (srovnávaní typicky {fmt_num(ref['n_d70_episodes'].median())})" if len(ref) else ""
    items.append(
        (
            "Epizody s hlavním kódem D70",
            f"{int(t['n_d70_episodes'])}{typical}",
            "Počet kódovaných epizod není automaticky počet samostatných komplikací.",
        )
    )
    other = int(t["n_inpatient_completed"]) - int(t["n_stays_included"])
    typical = ""
    if len(ref):
        typical = f" (srovnávaní typicky {fmt_num((ref['n_inpatient_completed'] - ref['n_stays_included']).median())})"
    items.append(
        (
            "Hospitalizace s jinou hlavní diagnózou",
            f"{other}{typical}",
            "Mohou zahrnovat komplikace nebo jiné důvody pobytu, které hlavní ukazatel nepočítá.",
        )
    )
    with st.container(border=True):
        st.markdown("#### Co ověřit v kontextu pacienta")
        for label, value, note in items:
            st.markdown(f"{label}: **{value}**  \n:gray[{note}]")
        with st.expander("Další charakteristiky"):
            cat, num = descriptor_columns(g.extra_meta)
            cat = [c for c in cat if c not in ("dx_icd10", "dx_group_label")]
            comp = peers or [p for p in g.core["patient_id"] if p != pid]
            st.caption(
                ("Srovnání se stejnými pacienty jako v grafu" if peers else "Srovnání s celou kohortou")
                + f" ({len(comp)}). Deskriptivní souvislosti k ověření, ne příčiny ani prognostické faktory; "
                "neověřené kódy (např. rozsah NOR) a počty vyšetření nejsou biologické charakteristiky."
            )
            diff = explain_differences(pid, comp, g.patient_table, cat, num, g.label)
            st.dataframe(
                diff,
                hide_index=True,
                width="stretch",
                column_config={"Neobvyklost": st.column_config.ProgressColumn(min_value=0, max_value=1)},
            )


def _data_card(
    pid, g: GlobalResults, a: AnalysisResult, res: pd.DataFrame, core: pd.Series, t: pd.Series
) -> None:
    r = res.loc[a.config.metrics[0]]
    n_stays = int(r["support_n"])
    n_labs = int(t["n_lab_results"])
    notes = []
    k_open = int(t["n_open_matching_dx"])
    if k_open:
        notes.append(
            f"U {k_open} {'pobytu' if k_open == 1 else 'pobytů'} s diagnózou nádoru chybí datum propuštění. "
            "Délku nelze určit; ověřte souvislost s hodnoceným průběhem."
        )
    elif int(t["n_inpatient_open"]):
        notes.append(f"U {int(t['n_inpatient_open'])} jiného pobytu chybí datum propuštění.")
    if n_stays == 1:
        notes.append("Výsledek stojí na jediném pobytu.")
    if r["baseline_status"] == "limited_reference":
        notes.append(f"Srovnání jen s {int(r['reference_n'])} podobnými pacienty.")
    if int(t["n_invalid_intervals"]):
        notes.append("Některé pobyty mají konec dříve než začátek – do výpočtu nevstupují.")
    if core["multi_tumor"]:
        notes.append("Pacient má v registru více nádorů – do výpočtu očekávání nevstupuje.")
    with st.container(border=True):
        st.markdown("#### Podklady a dostupnost")
        lab_chip = f"{n_labs} lab. výsledků" if n_labs else "bez laboratoří"
        st.markdown(
            f":gray-badge[{_count_phrase(n_stays, 'pobyt', 'pobyty', 'pobytů')} ve výpočtu] "
            f":gray-badge[{lab_chip}]"
        )
        if notes:
            st.warning("\n".join(f"- {n}" for n in notes))
        else:
            st.caption("Bez zvláštních omezení dat.")
        with st.expander("Co zahrnuje výběr"):
            label, sentence, details = texts.RULE_OPTIONS[g.baseline.config.episode_rule]
            st.markdown(f"**{label}** – {sentence}")
            st.caption(details + " Den 0 v datech je první záznam v nemocnici, ne datum diagnózy.")
        components.exclusion_button(pid, "pt")


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
        f"hospitalizací ({len(selected)} ve výpočtu), {int(t['n_inpatient_open'])} bez zaznamenaného data propuštění, "
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


def similar_counted_flags(ids: list[str], reference_ids: str) -> list[bool]:
    """Které z podobných pacientů se skutečně započítávají do očekávání (patří do srovnávací skupiny)."""
    counted = {p for p in str(reference_ids or "").split(";") if p}
    return [p in counted for p in ids]


def _tab_similar(pid: str, g: GlobalResults, a: AnalysisResult) -> None:
    sim = similar_patients(pid, g.core, k=10)
    if sim.empty:
        st.info("Žádní pacienti se shodnou diagnózou/skupinou nebo věkem a pohlavím.")
        return
    main = a.config.metrics[0]
    r = g.results_long[g.results_long["metric_id"] == main].set_index("patient_id")
    counted = similar_counted_flags(sim["patient_id"].tolist(), r.at[pid, "reference_ids"])
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
    view.insert(1, "Ve srovnání", ["ano" if c else "ne" for c in counted])
    model = g.baseline.config.method == "ridge_loo"
    st.caption(
        "Seznam nejpodobnějších pacientů podle diagnózy/skupiny, věku a pohlaví je jen pro orientaci – posuzovaný "
        "výsledek není kritériem. **Šedé řádky se do očekávání nezapočítávají:** "
        + (
            "patří do jiné skupiny diagnóz, než se kterou model pacienta srovnává."
            if model
            else "liší se v údaji, podle kterého se srovnává (např. věková skupina nebo přesná diagnóza), nebo "
            "nemají započitatelný pobyt."
        )
        + " Klikněte na řádek pro detail pacienta."
    )
    for col, digits in (("Pozorováno", 1), ("Očekávání", 1), ("Míra odchylky", 2)):
        # stylovaná tabulka nezobrazí chybějící hodnotu hezky – převod na text s „–“
        view[col] = [f"{v:.{digits}f}" if pd.notna(v) else "–" for v in view[col]]
    grey = ["color: #9AA0A6"] * len(view.columns)
    styled = view.style.apply(lambda row: grey if row["Ve srovnání"] == "ne" else [""] * len(row), axis=1)
    ev = st.dataframe(
        styled,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-cell",
        key=f"similar_{pid}_{state.nonce()}",
    )
    other = patient_from_cell_selection(ev.selection.cells if ev is not None else [], view)
    if other:
        state.open_patient(other, st.session_state.get(state.K_FROM_ANALYSIS))
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
        ("Pobyty bez zaznamenaného data propuštění (dg. nádoru)", int(t["n_open_matching_dx"])),
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
