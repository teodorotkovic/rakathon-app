"""Sdílené UI komponenty (Streamlit)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from rakathon.domain import (
    BASELINE_STATUS_LABELS,
    REVIEW_LABELS,
    BaselineStatus,
    ReviewStatus,
    SourceMode,
    review_label,
)
from rakathon.formatting import fmt_days
from rakathon.pipeline import GlobalResults
from rakathon.storage.csv_store import make_review, split_history
from rakathon.ui import state
from rakathon.ui.charts import DIR_TEXT


def source_banner() -> None:
    b = state.dataset()
    if b.source_mode == SourceMode.SYNTHETIC:
        st.warning(
            "**Syntetická demonstrační data** – nejde o skutečné pacienty ani o analýzu reálné kohorty.",
            icon=":material/science:",
        )


def context_caption(g: GlobalResults, analysis_label: str | None = None) -> None:
    rule = g.baseline.config.episode_rule
    from rakathon.features.catalog import EPISODE_RULES

    parts = [
        f"Dataset `{g.dataset_fingerprint[:12]}` ({'syntetický' if g.source_mode == SourceMode.SYNTHETIC else 'skutečný'})",
        f"globální očekávání `{g.baseline_config_id}` – {EPISODE_RULES[rule]['label'].lower()}",
    ]
    if analysis_label:
        parts.append(analysis_label)
    st.caption(" · ".join(parts))


DIR_SHORT = {"longer": "▲ delší", "shorter": "▼ kratší", "equal": "● shodné"}


def direction_text(direction: str, short: bool = False) -> str:
    if short:
        return DIR_SHORT.get(direction or "", "–")
    return DIR_TEXT.get(direction or "", "–")


def support_text(row: pd.Series) -> str:
    status = row.get("baseline_status", "")
    if status in (BaselineStatus.OK.value, BaselineStatus.LIMITED.value):
        n = int(row.get("reference_n", 0))
        level = str(row.get("reference_level_label", "")).replace("stejná ", "")
        prefix = "omezená · " if status == BaselineStatus.LIMITED.value else ""
        return f"{prefix}{n} pac. ({level})"
    try:
        return BASELINE_STATUS_LABELS[BaselineStatus(status)]
    except ValueError:
        return "–"


def review_status_options() -> list[str]:
    return [s.value for s in ReviewStatus]


def review_panel(pid: str, analysis_id: str, analysis_label: str, key_prefix: str) -> None:
    """Formulář posouzení s explicitním uložením + oddělená historie."""
    g = state.global_results()
    reviews = state.reviews_all()
    hist_cur, hist_other = split_history(reviews, pid, g.dataset_fingerprint, g.baseline_config_id)
    current = hist_cur.iloc[0] if len(hist_cur) else None
    status_now = current["status"] if current is not None else ReviewStatus.NOT_REVIEWED.value
    st.markdown(f"**Aktuální posouzení:** {review_label(status_now)}")
    if current is not None:
        st.caption(
            f"Uloženo {current['created_at'][:19].replace('T', ' ')} UTC"
            + (f" · {current['reviewer']}" if current["reviewer"] else "")
            + f" · pohled: {current['analysis_label'] or current['analysis_id']}"
        )
        if current["comment"]:
            st.markdown(f"> {current['comment']}".replace("\n", "\n> "))

    options = review_status_options()
    with st.form(key=f"{key_prefix}_review_{pid}_{state.nonce()}", clear_on_submit=False):
        status = st.radio(
            "Klinické posouzení",
            options,
            index=options.index(status_now) if status_now in options else 0,
            format_func=lambda v: REVIEW_LABELS[ReviewStatus(v)],
        )
        comment = st.text_area(
            "Komentář (volný text)",
            value="",
            height=90,
            placeholder="Např. známý kontext, hypotéza, co ověřit u mentora…",
        )
        reviewer = st.text_input(
            "Štítek posuzovatele (volitelný, není ověřená identita)",
            value=st.session_state.get(state.K_REVIEWER, ""),
        )
        submitted = st.form_submit_button("Uložit posouzení", type="primary", icon=":material/save:")
    if submitted:
        record = make_review(
            dataset_fingerprint=g.dataset_fingerprint,
            source_mode=g.source_mode.value,
            patient_id=pid,
            baseline_config_id=g.baseline_config_id,
            analysis_id=analysis_id,
            analysis_label=analysis_label,
            status=ReviewStatus(status),
            comment=comment,
            reviewer=reviewer,
            supersedes=current["record_id"] if current is not None else "",
        )
        try:
            state.store().append_review(record)
        except OSError as exc:
            st.error(f"Posouzení se nepodařilo uložit: {exc}")
        else:
            st.session_state[state.K_REVIEWER] = reviewer
            state.flash(
                "success", f"Posouzení pacienta {pid} uloženo ({REVIEW_LABELS[ReviewStatus(status)]})."
            )
            st.rerun()

    if len(hist_cur) or len(hist_other):
        with st.expander(f"Historie posouzení ({len(hist_cur)} v tomto kontextu, {len(hist_other)} jinde)"):
            cols = ["created_at", "status", "comment", "reviewer", "analysis_label"]
            if len(hist_cur):
                st.dataframe(_history_view(hist_cur[cols]), hide_index=True, width="stretch")
            if len(hist_other):
                st.caption(
                    "Posouzení z jiného globálního kontextu (jiný cíl/model) – pouze historická, "
                    "neplatí jako potvrzení aktuálního nálezu."
                )
                st.dataframe(
                    _history_view(hist_other[cols + ["baseline_config_id"]]), hide_index=True, width="stretch"
                )


def _history_view(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["status"] = out["status"].map(review_label)
    out["created_at"] = out["created_at"].str[:19].str.replace("T", " ")
    return out.rename(
        columns={
            "created_at": "Čas (UTC)",
            "status": "Stav",
            "comment": "Komentář",
            "reviewer": "Posuzovatel",
            "analysis_label": "Pohled",
            "baseline_config_id": "Globální kontext",
        }
    )


def exclusion_button(pid: str, key_prefix: str) -> None:
    pending = st.session_state.get(state.K_PENDING_EXCL, {})
    excluded_now = pid in state.baseline_config().excluded_patient_ids
    if excluded_now:
        st.info("Pacient je vyřazen z aktuální verze výpočtu (viz postranní panel → Globální očekávání).")
        return
    if pid in pending:
        st.caption(
            "Vyřazení je navrženo – projeví se po potvrzení **Přepočítat očekávání** v postranním panelu."
        )
        return
    with st.popover("Navrhnout vyřazení z výpočtu", icon=":material/block:"):
        st.caption(
            "Pro podezření na chybná data. Pacient zůstane v seznamu, ale nebude ve výpočtu očekávání "
            "ani v referencích. Vznikne nová verze konfigurace; nic se nemaže."
        )
        reason = st.text_input(
            "Důvod", key=f"{key_prefix}_excl_reason_{pid}", value="podezření na datový problém"
        )
        if st.button("Přidat do návrhu vyřazení", key=f"{key_prefix}_excl_btn_{pid}"):
            pending = dict(pending)
            pending[pid] = reason.strip() or "podezření na datový problém"
            st.session_state[state.K_PENDING_EXCL] = pending
            state.flash(
                "info", f"Vyřazení {pid} navrženo; potvrďte v postranním panelu „Přepočítat očekávání“."
            )
            st.rerun()


def metric_value(x) -> str:
    return fmt_days(x)
