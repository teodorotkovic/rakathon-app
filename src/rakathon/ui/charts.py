"""Plotly grafy. Barvy: oranžová = delší než očekávání, modrá = kratší (nikoli „horší/lepší“),
šedá = bez výrazné odchylky / nehodnoceno. Barva je vždy doplněna symbolem a textem."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

LONGER = "#D55E00"
SHORTER = "#0072B2"
NEUTRAL = "#8A939C"
REFERENCE = "#C3C9CF"
HIGHLIGHT = "#111111"
SYMBOL = {"longer": "triangle-up", "shorter": "triangle-down", "equal": "circle", "": "circle"}
COLOR = {"longer": LONGER, "shorter": SHORTER, "equal": NEUTRAL, "": NEUTRAL}
DIR_TEXT = {
    "longer": "▲ delší než očekávání",
    "shorter": "▼ kratší než očekávání",
    "equal": "● shodné",
    "": "–",
}

LAYOUT = dict(margin=dict(l=10, r=10, t=40, b=10), height=360, legend=dict(orientation="h", y=-0.2))


def _jitter(n: int, seed: int = 0, width: float = 0.25) -> np.ndarray:
    return np.random.default_rng(seed).uniform(-width, width, n)


def reference_strip(
    peer_values: pd.Series,
    patient_value: float,
    expected: float,
    q1: float,
    q3: float,
    x_title: str,
    direction: str,
    patient_id: str,
) -> go.Figure:
    """Pacient (výrazný bod) vůči srovnávaným pacientům (šedé body), pásmo kvartilů a očekávání (čára)."""
    from rakathon.formatting import fmt_days

    fig = go.Figure()
    if not np.isnan(q1) and not np.isnan(q3):
        fig.add_vrect(x0=q1, x1=q3, fillcolor=REFERENCE, opacity=0.35, line_width=0)
    fig.add_trace(
        go.Scatter(
            x=peer_values.to_numpy(),
            y=_jitter(len(peer_values)),
            mode="markers",
            name="srovnávaní pacienti",
            marker=dict(color=NEUTRAL, size=9, opacity=0.8),
            customdata=peer_values.index.to_numpy(),
            hovertemplate="%{customdata}: %{x} dní<extra>srovnávaný pacient</extra>",
        )
    )
    if not np.isnan(expected):
        fig.add_vline(
            x=expected,
            line=dict(color=HIGHLIGHT, dash="dash"),
            annotation_text=f"Očekávání · {fmt_days(expected)}",
            annotation_position="bottom right",
        )
    if not np.isnan(patient_value):
        fig.add_trace(
            go.Scatter(
                x=[patient_value],
                y=[0],
                mode="markers+text",
                name=f"pacient {patient_id}",
                marker=dict(
                    color=COLOR.get(direction, NEUTRAL),
                    size=16,
                    symbol=SYMBOL.get(direction, "circle"),
                    line=dict(color=HIGHLIGHT, width=1.5),
                ),
                text=[f"Pacient · {fmt_days(patient_value)}"],
                textposition="top center",
                hovertemplate=f"{patient_id}: %{{x}} dní<extra>{DIR_TEXT.get(direction, '')}</extra>",
            )
        )
    fig.update_layout(
        **{**LAYOUT, "height": 220, "margin": dict(l=10, r=10, t=20, b=10)},
        showlegend=False,
        xaxis_title=x_title,
        yaxis=dict(visible=False, range=[-1, 1]),
    )
    return fig


TIMELINE_ROWS = [
    "Ambulantní kontakt",
    "Hospitalizace – ve výpočtu",
    "Hospitalizace – ostatní",
    "Pobyt bez data propuštění",
    "Neplatný interval",
]


def timeline(eps: pd.DataFrame, selected_ids: set[str], anchor_day: float | None = None) -> go.Figure:
    fig = go.Figure()
    e = eps.copy()
    e["row"] = np.select(
        [
            e["episode_class"] == "outpatient",
            e["episode_id"].isin(selected_ids),
            e["episode_class"] == "inpatient_completed",
            e["episode_class"] == "inpatient_open",
        ],
        TIMELINE_ROWS[:4],
        default=TIMELINE_ROWS[4],
    )
    hover = "%{customdata[0]}<br>den %{customdata[1]}–%{customdata[2]}<br>dg. %{customdata[3]}<extra></extra>"

    def cd(df):
        return np.stack(
            [
                df["episode_id"],
                df["day_start"],
                df["day_end"].replace("", "?"),
                df["dx_main"].replace("", "nekódováno"),
            ],
            axis=-1,
        )

    out = e[e["row"] == TIMELINE_ROWS[0]]
    if len(out):
        fig.add_trace(
            go.Scatter(
                x=out["day_start_num"].astype(float),
                y=out["row"],
                mode="markers",
                name=TIMELINE_ROWS[0],
                marker=dict(color=NEUTRAL, size=6, symbol="line-ns-open"),
                customdata=cd(out),
                hovertemplate=hover,
            )
        )
    for row, color, width in ((TIMELINE_ROWS[2], REFERENCE, 7), (TIMELINE_ROWS[1], LONGER, 9)):
        sub = e[e["row"] == row]
        if not len(sub):
            continue
        xs, ys = [], []
        for r in sub.itertuples(index=False):
            xs += [float(r.day_start_num), float(r.day_end_num), None]
            ys += [row, row, None]
        fig.add_trace(
            go.Scatter(
                x=xs, y=ys, mode="lines", line=dict(color=color, width=width), name=row, hoverinfo="skip"
            )
        )
        fig.add_trace(
            go.Scatter(
                x=sub["day_start_num"].astype(float),
                y=sub["row"],
                mode="markers",
                marker=dict(color=color, size=7),
                customdata=cd(sub),
                hovertemplate=hover,
                showlegend=False,
            )
        )
    for row, symbol in ((TIMELINE_ROWS[3], "triangle-right-open"), (TIMELINE_ROWS[4], "x")):
        sub = e[e["row"] == row]
        if len(sub):
            fig.add_trace(
                go.Scatter(
                    x=sub["day_start_num"].astype(float),
                    y=sub["row"],
                    mode="markers",
                    name=row + (" (délka neznámá)" if symbol.startswith("triangle") else ""),
                    marker=dict(color=HIGHLIGHT, size=11, symbol=symbol),
                    customdata=cd(sub),
                    hovertemplate=hover,
                )
            )
    if anchor_day is not None and not pd.isna(anchor_day):
        fig.add_vline(
            x=float(anchor_day),
            line=dict(color=SHORTER, dash="dot"),
            annotation_text="kotva (1. epizoda s dg. nádoru)",
            annotation_position="top",
        )
    fig.update_layout(
        **{**LAYOUT, "height": 320},
        title="Časová osa epizod (den 0 = první záznam, ne diagnóza)",
        xaxis_title="den od první epizody (posun ±3 dny u pozdějších epizod)",
        yaxis=dict(categoryorder="array", categoryarray=TIMELINE_ROWS[::-1], title=""),
    )
    return fig


def lab_trend(sub: pd.DataFrame, label: str) -> go.Figure:
    s = sub.sort_values("day_num")
    fig = go.Figure()
    symbols = s["flag"].map({"L": "triangle-down", "H": "triangle-up", "N": "circle"}).fillna("circle-open")
    fig.add_trace(
        go.Scatter(
            x=s["day_num"].astype(float),
            y=s["value_num"],
            mode="lines+markers",
            name="hodnota",
            line=dict(color=NEUTRAL),
            marker=dict(symbol=symbols.tolist(), size=9, color=HIGHLIGHT),
            customdata=np.stack(
                [
                    s["flag"].replace("", "bez mezí"),
                    s["episode_link"].map(
                        {
                            "linked": "v epizodě",
                            "no_episode": "mimo epizodu",
                            "unknown_episode": "neznámá epizoda",
                            "patient_mismatch": "epizoda jiného pacienta – vazba nepoužita",
                        }
                    ),
                    s["linked_episode_id"],
                ],
                axis=-1,
            ),
            hovertemplate="den %{x}: %{y}<br>příznak %{customdata[0]}<br>%{customdata[1]} %{customdata[2]}<extra></extra>",
        )
    )
    for col, name in (("ref_low_num", "dolní mez (dodaná)"), ("ref_high_num", "horní mez (dodaná)")):
        if s[col].notna().any():
            fig.add_trace(
                go.Scatter(
                    x=s["day_num"].astype(float),
                    y=s[col],
                    mode="lines",
                    name=name,
                    line=dict(color=SHORTER, dash="dot", shape="hv"),
                )
            )
    fig.update_layout(
        **LAYOUT,
        title=f"{label} – {len(s)} výsledků",
        xaxis_title="den odběru (může být záporný)",
        yaxis_title=s["unit"].iloc[0] if len(s) else "",
    )
    return fig


def residual_strip(df: pd.DataFrame, threshold: float, highlight: set[str], x_title: str) -> go.Figure:
    """df: patient_id, z, direction, outlier, group_label, observed, expected, residual."""
    fig = go.Figure()
    grey_shown = False
    for flag, opacity in ((False, 0.45), (True, 1.0)):
        for d in ("longer", "shorter", "equal"):
            sub = df[(df["outlier"] == flag) & (df["direction"] == d)]
            if not len(sub):
                continue
            color = COLOR[d] if flag else NEUTRAL
            name = (
                {"longer": "▲ neobvykle delší", "shorter": "▼ neobvykle kratší"}.get(d, "neobvyklé")
                if flag
                else "běžný rozdíl"
            )
            show = flag or not grey_shown
            grey_shown = grey_shown or not flag
            fig.add_trace(
                go.Scatter(
                    x=sub["z"],
                    y=sub["group_label"],
                    mode="markers",
                    name=name,
                    showlegend=show,
                    legendgroup="grey" if not flag else d,
                    marker=dict(
                        color=color,
                        symbol=SYMBOL[d],
                        size=np.where(sub["patient_id"].isin(highlight), 16, 10),
                        opacity=opacity,
                        line=dict(color=HIGHLIGHT, width=np.where(sub["patient_id"].isin(highlight), 2, 0)),
                    ),
                    customdata=np.stack(
                        [sub["patient_id"], sub["observed"], sub["expected"], sub["residual"]], axis=-1
                    ),
                    hovertemplate=(
                        "%{customdata[0]}<br>pozorováno %{customdata[1]:.1f} d, očekávání %{customdata[2]:.1f} d"
                        "<br>rozdíl %{customdata[3]:+.1f} d<br>standardizovaně %{x:.2f}<extra></extra>"
                    ),
                )
            )
    for x in (threshold, -threshold):
        fig.add_vline(x=x, line=dict(color=HIGHLIGHT, dash="dash"), annotation_text=f"hranice {x:+g}")
    fig.update_layout(
        **{**LAYOUT, "height": 420, "legend": dict(orientation="h", y=1.12, x=0)},
        xaxis_title=x_title,
        yaxis_title=None,
        dragmode="select",
        clickmode="event+select",
    )
    return fig


def observed_vs_expected(df: pd.DataFrame, highlight: set[str], metric_label: str) -> go.Figure:
    fig = go.Figure()
    mx = float(np.nanmax([df["observed"].max(), df["expected"].max(), 1]))
    fig.add_trace(
        go.Scatter(
            x=[0, mx],
            y=[0, mx],
            mode="lines",
            name="pozorováno = očekávání",
            line=dict(color=REFERENCE, dash="dash"),
            hoverinfo="skip",
        )
    )
    for flag in (False, True):
        for d in ("longer", "shorter", "equal"):
            sub = df[(df["outlier"] == flag) & (df["direction"] == d)]
            if not len(sub):
                continue
            fig.add_trace(
                go.Scatter(
                    x=sub["expected"],
                    y=sub["observed"],
                    mode="markers",
                    name=("nad prahem: " if flag else "") + DIR_TEXT[d],
                    showlegend=flag,
                    marker=dict(
                        color=COLOR[d] if flag else NEUTRAL,
                        symbol=SYMBOL[d],
                        opacity=1 if flag else 0.45,
                        size=np.where(sub["patient_id"].isin(highlight), 15, 9),
                    ),
                    customdata=sub["patient_id"],
                    hovertemplate="%{customdata}: očekávání %{x:.1f}, pozorováno %{y:.1f}<extra></extra>",
                )
            )
    fig.update_layout(
        **LAYOUT,
        title=f"{metric_label}: pozorováno vs. očekávání (dny)",
        xaxis_title="referenční očekávání (dny)",
        yaxis_title="pozorovaná hodnota (dny)",
        dragmode="select",
        clickmode="event+select",
    )
    return fig


def z_scatter(
    df: pd.DataFrame, x_label: str, y_label: str, threshold: float, highlight: set[str]
) -> go.Figure:
    """df: patient_id, zx, zy, outlier, direction, info."""
    fig = go.Figure()
    t = threshold
    fig.add_shape(
        type="rect",
        x0=-t,
        x1=t,
        y0=-t,
        y1=t,
        line=dict(color=HIGHLIGHT, dash="dash"),
        fillcolor="rgba(0,0,0,0)",
    )
    for flag in (False, True):
        for d in ("longer", "shorter", "equal"):
            sub = df[(df["outlier"] == flag) & (df["direction"] == d)]
            if not len(sub):
                continue
            fig.add_trace(
                go.Scatter(
                    x=sub["zx"],
                    y=sub["zy"],
                    mode="markers",
                    name=("nad prahem: " if flag else "v rámci prahu: ") + DIR_TEXT[d],
                    marker=dict(
                        color=COLOR[d] if flag else NEUTRAL,
                        symbol=SYMBOL[d],
                        opacity=1 if flag else 0.4,
                        size=np.where(sub["patient_id"].isin(highlight), 16, 10),
                        line=dict(color=HIGHLIGHT, width=np.where(sub["patient_id"].isin(highlight), 2, 0)),
                    ),
                    customdata=np.stack([sub["patient_id"], sub["info"]], axis=-1),
                    hovertemplate="%{customdata[0]}<br>%{customdata[1]}<extra></extra>",
                )
            )
    fig.update_layout(
        **{**LAYOUT, "height": 460},
        xaxis_title=x_label,
        yaxis_title=y_label,
        dragmode="lasso",
        clickmode="event+select",
        title="Standardizované odchylky dvou ukazatelů (čárkovaný čtverec = práh)",
    )
    return fig


def z_heatmap(mat: pd.DataFrame) -> go.Figure:
    lim = float(np.nanmax(np.abs(mat.to_numpy()))) if mat.size else 1.0
    fig = go.Figure(
        go.Heatmap(
            z=mat.to_numpy(),
            x=list(mat.columns),
            y=list(mat.index),
            zmin=-lim,
            zmax=lim,
            zmid=0,
            colorscale=[[0, SHORTER], [0.5, "#F2F2F2"], [1, LONGER]],
            text=np.round(mat.to_numpy(), 1),
            texttemplate="%{text}",
            colorbar=dict(title="z"),
            hovertemplate="%{y} · %{x}: %{z:.2f}<extra></extra>",
        )
    )
    fig.update_layout(
        **{**LAYOUT, "height": max(260, 28 * len(mat) + 80)},
        title="Profil standardizovaných odchylek outlierů (modrá = kratší, oranžová = delší)",
    )
    return fig


def category_compare(df: pd.DataFrame, title: str) -> go.Figure:
    """df: value, share_sel, share_ref, n_sel, n_ref."""
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=df["value"],
            y=df["share_sel"],
            name="vybraní",
            marker_color=LONGER,
            text=[f"{c}/{n}" for c, n in zip(df["count_sel"], df["n_sel"], strict=False)],
            textposition="outside",
        )
    )
    fig.add_trace(
        go.Bar(
            x=df["value"],
            y=df["share_ref"],
            name="reference",
            marker_color=REFERENCE,
            text=[f"{c}/{n}" for c, n in zip(df["count_ref"], df["n_ref"], strict=False)],
            textposition="outside",
        )
    )
    fig.update_layout(
        **LAYOUT, barmode="group", title=title, yaxis=dict(tickformat=".0%", title="podíl pacientů")
    )
    return fig


def numeric_compare(sel: pd.Series, ref: pd.Series, title: str, unit: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Box(y=ref, name=f"reference (n={len(ref)})", marker_color=NEUTRAL, boxpoints="all", jitter=0.4)
    )
    fig.add_trace(
        go.Box(y=sel, name=f"vybraní (n={len(sel)})", marker_color=LONGER, boxpoints="all", jitter=0.4)
    )
    fig.update_layout(**LAYOUT, title=title, yaxis_title=unit, showlegend=False)
    return fig


FAR = "#6B4E9B"


def median_scatter(
    df: pd.DataFrame,
    x_label: str,
    y_label: str,
    center: tuple[float, float],
    scale: tuple[float, float],
    threshold: float,
    highlight: set[str],
) -> go.Figure:
    """Dva libovolné údaje: medián (kříž), hranice vzdálenosti (elipsa) a vzdálení pacienti.

    df: patient_id, x, y, dist, far, info. Vzdálenost = robustní (medián, 1,4826·MAD) na každé ose.
    """
    fig = go.Figure()
    cx, cy = center
    sx, sy = scale
    if np.isfinite(sx) and np.isfinite(sy):
        fig.add_shape(
            type="circle",
            x0=cx - threshold * sx,
            x1=cx + threshold * sx,
            y0=cy - threshold * sy,
            y1=cy + threshold * sy,
            line=dict(color=FAR, dash="dash", width=1.5),
            fillcolor="rgba(107,78,155,0.04)",
            layer="below",
        )
    fig.add_vline(x=cx, line=dict(color=HIGHLIGHT, width=1, dash="dot"))
    fig.add_hline(y=cy, line=dict(color=HIGHLIGHT, width=1, dash="dot"))
    fig.add_trace(
        go.Scatter(
            x=[cx],
            y=[cy],
            mode="markers",
            name="medián obou údajů",
            marker=dict(color=HIGHLIGHT, size=13, symbol="x-thin-open", line=dict(width=3, color=HIGHLIGHT)),
            hovertemplate=f"medián<br>{x_label}: %{{x:.2f}}<br>{y_label}: %{{y:.2f}}<extra></extra>",
        )
    )
    for flag, name, color, opacity, size in (
        (False, "blízko mediánu", NEUTRAL, 0.5, 9),
        (True, "daleko od mediánu", FAR, 1.0, 12),
    ):
        sub = df[df["far"] == flag]
        if not len(sub):
            continue
        sel = sub["patient_id"].isin(highlight)
        fig.add_trace(
            go.Scatter(
                x=sub["x"],
                y=sub["y"],
                mode="markers+text" if flag and len(sub) <= 12 else "markers",
                text=sub["patient_id"] if flag and len(sub) <= 12 else None,
                textposition="top center",
                textfont=dict(size=11, color=FAR),
                name=name,
                marker=dict(
                    color=color,
                    size=np.where(sel, size + 5, size),
                    opacity=opacity,
                    line=dict(color=HIGHLIGHT, width=np.where(sel, 2, 0)),
                ),
                customdata=np.stack([sub["patient_id"], sub["info"]], axis=-1),
                hovertemplate="%{customdata[0]}<br>%{customdata[1]}<extra></extra>",
            )
        )
    fig.update_layout(
        **{**LAYOUT, "height": 480},
        xaxis_title=x_label,
        yaxis_title=y_label,
        dragmode="select",
        clickmode="event+select",
    )
    return fig
