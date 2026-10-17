"""Plotly grafy. Barvy: oranžová = delší než očekávání, modrá = kratší (nikoli „horší/lepší“),
šedá = bez výrazné odchylky / nehodnoceno. Barva je vždy doplněna symbolem a textem."""

from __future__ import annotations

import zlib

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

# Výběr bodů: dragmode NENASTAVOVAT. Streamlit při dragmode „select“/„lasso“ vypne výběr kliknutím;
# bez něj klik na bod vybere pacienta a výběr obdélníkem zůstává v liště nástrojů grafu.


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
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)
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
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)
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
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)
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
                {"longer": "neobvykle delší", "shorter": "neobvykle kratší"}.get(d, "neobvyklé")
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
        fig.add_vline(
            x=x,
            line=dict(color=HIGHLIGHT, dash="dash"),
            annotation_text=f"hranice {x:+g}".replace(".", ","),
            annotation_position="bottom right" if x > 0 else "bottom left",
            annotation_font=dict(size=11, color="#56635F"),
        )
    fig.update_layout(
        **{
            **LAYOUT,
            "height": 440,
            "margin": dict(l=10, r=10, t=50, b=10),
            "legend": dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"),
        },
        xaxis_title=x_title,
        yaxis_title=None,
    )
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)
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
    )
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)
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
        title="Standardizované odchylky dvou ukazatelů (čárkovaný čtverec = práh)",
    )
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)
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
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)
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
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)
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
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)
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
    )
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)
    return fig


BOX_FILL = "rgba(11,110,102,0.10)"
BOX_LINE = "#0B6E66"


def group_boxplot(
    df: pd.DataFrame, order: list[str], value_label: str, highlight: set[str], show_all: bool
) -> go.Figure:
    """Krabicový graf po skupinách (vodorovně, skupiny na ose y).

    df: group (popisek včetně n), value, patient_id, info. Krabice = 1.–3. kvartil, čára = medián,
    vousy = nejvzdálenější hodnota do 1,5 × IQR od krabice (Tukey, výchozí chování Plotly),
    body mimo vousy = odlehlé hodnoty. Při show_all se zobrazí všichni pacienti.
    """
    fig = go.Figure()
    for grp in order:
        sub = df[df["group"] == grp]
        fig.add_trace(
            go.Box(
                x=sub["value"],
                y=[grp] * len(sub),
                name=grp,
                orientation="h",
                boxpoints="all" if show_all else "outliers",
                jitter=0.35 if show_all else 0,
                pointpos=0,
                quartilemethod="linear",
                fillcolor=BOX_FILL,
                line=dict(color=BOX_LINE, width=1.5),
                marker=dict(
                    color=FAR,
                    size=7 if show_all else 9,
                    opacity=0.55 if show_all else 1,
                    outliercolor=FAR,
                    line=dict(width=0),
                ),
                customdata=np.stack([sub["patient_id"], sub["info"]], axis=-1),
                hovertemplate="%{customdata[0]}<br>%{customdata[1]}<extra></extra>",
                showlegend=False,
            )
        )
    hl = df[df["patient_id"].isin(highlight)]
    if len(hl):
        fig.add_trace(
            go.Scatter(
                x=hl["value"],
                y=hl["group"],
                mode="markers+text",
                text=hl["patient_id"],
                textposition="top center",
                marker=dict(color="rgba(0,0,0,0)", size=15, line=dict(color=HIGHLIGHT, width=2)),
                name="vybraný pacient",
                hoverinfo="skip",
                showlegend=False,
            )
        )
    fig.update_layout(
        **{**LAYOUT, "height": max(280, 90 + 46 * len(order)), "margin": dict(l=10, r=10, t=20, b=20)},
        xaxis=dict(title=value_label, automargin=True),
        yaxis=dict(
            categoryorder="array",
            categoryarray=list(reversed(order)),
            title=None,
            automargin=True,
            type="category",
        ),
    )
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)
    return fig


# ---------------------------------------------------------------------------
# Grafy ve stylu „bod = pacient“ (kategorie, popisky, skupiny s n)
# ---------------------------------------------------------------------------

BORDER_GREY = "#5B6866"
_CATEGORIES = [
    # klíč, popisek v legendě, barva, symbol, velikost, popisovat ID
    ("longer", "neobvykle delší", LONGER, "circle", 11, True),
    ("shorter", "neobvykle kratší", SHORTER, "circle", 11, True),
    ("near", "těsně pod hranicí", BORDER_GREY, "circle-open", 9, False),
    ("normal", "běžný rozdíl", "#B4BCBA", "circle", 8, False),
]


def _jitter_for(ids: pd.Series, width: float = 0.28) -> np.ndarray:
    """Stabilní rozptyl bodu podle ID (stejný pacient je vždy na stejném místě)."""
    return np.array([((zlib.crc32(str(p).encode()) % 1000) / 999 - 0.5) * 2 * width for p in ids])


def wrap_label(text: str, width: int = 14) -> str:
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return "<br>".join(lines)


def category_of(df: pd.DataFrame) -> pd.Series:
    """outlier+direction → longer/shorter; band „těsně pod prahem“ → near; jinak normal."""
    cat = pd.Series("normal", index=df.index)
    cat[df["band"] == "těsně pod prahem"] = "near"
    cat[df["outlier"] & (df["direction"] == "longer")] = "longer"
    cat[df["outlier"] & (df["direction"] == "shorter")] = "shorter"
    return cat


def _add_category_traces(fig, df, x, y, highlight: set[str], text_pos: str = "middle right") -> None:
    cat = category_of(df)
    for key, name, color, symbol, size, label in _CATEGORIES:
        m = (cat == key).to_numpy()
        if not m.any():
            continue
        sub = df[m]
        sel = sub["patient_id"].isin(highlight).to_numpy()
        fig.add_trace(
            go.Scatter(
                x=np.asarray(x)[m],
                y=np.asarray(y)[m],
                mode="markers+text" if label else "markers",
                text=sub["patient_id"] if label else None,
                textposition=text_pos,
                textfont=dict(size=11, color=color),
                name=name,
                marker=dict(
                    color=color,
                    symbol=symbol,
                    size=np.where(sel, size + 5, size),
                    line=dict(color=np.where(sel, HIGHLIGHT, color).tolist(), width=np.where(sel, 2.5, 1.5)),
                ),
                customdata=np.stack([sub["patient_id"], sub["info"]], axis=-1),
                hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<extra></extra>",
            )
        )
    weak = df["weak"].to_numpy(dtype=bool)
    if weak.any():
        sub = df[weak]
        fig.add_trace(
            go.Scatter(
                x=np.asarray(x)[weak],
                y=np.asarray(y)[weak],
                mode="markers",
                name="méně spolehlivé srovnání",
                marker=dict(color=HIGHLIGHT, symbol="x-thin", size=9, line=dict(width=1.6, color=HIGHLIGHT)),
                customdata=np.stack([sub["patient_id"], sub["info"]], axis=-1),
                hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<br>méně spolehlivé srovnání"
                "<extra></extra>",
            )
        )


def deviation_by_group(df: pd.DataFrame, threshold: float, highlight: set[str], y_title: str) -> go.Figure:
    """Svislý graf: skupiny diagnóz na ose x (s n), míra odchylky na ose y, pás běžných rozdílů.

    df: patient_id, z, group_label, outlier, direction, band, weak, info.
    """
    order = df.groupby("group_label")["z"].median().sort_values(ascending=False).index.tolist()
    counts = df["group_label"].value_counts()
    pos = {g: i for i, g in enumerate(order)}
    x = df["group_label"].map(pos).to_numpy(dtype=float) + _jitter_for(df["patient_id"])
    fig = go.Figure()
    fig.add_hrect(
        y0=-threshold, y1=threshold, fillcolor="rgba(120,135,132,0.13)", line_width=0, layer="below"
    )
    fig.add_hline(y=0, line=dict(color=HIGHLIGHT, width=1))
    _add_category_traces(fig, df, x, df["z"], highlight)
    fig.update_layout(
        **{
            **LAYOUT,
            "height": 500,
            "margin": dict(l=10, r=10, t=60, b=10),
            "legend": dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"),
        },
        xaxis=dict(
            tickmode="array",
            tickvals=list(range(len(order))),
            ticktext=[f"{wrap_label(g)}<br>(n={counts[g]})" for g in order],
            range=[-0.6, len(order) - 0.4],
            showgrid=False,
            zeroline=False,
            automargin=True,
        ),
        yaxis=dict(title=y_title, zeroline=False, automargin=True),
    )
    fig.add_annotation(
        x=1,
        xref="paper",
        xanchor="right",
        y=threshold,
        yanchor="bottom",
        showarrow=False,
        text=f"hranice ±{threshold:g}".replace(".", ","),
        font=dict(size=11, color="#56635F"),
    )
    return fig


_LOG_TICKS = [0, 1, 2, 5, 10, 20, 50, 100, 200, 500]


def fact_vs_expectation(
    df: pd.DataFrame,
    scale: str,
    center: float,
    spread: float,
    threshold: float,
    highlight: set[str],
    metric_label: str,
) -> go.Figure:
    """Skutečnost vs. očekávání. Úhlopříčka = přesně podle očekávání, čárkované čáry = hranice.

    Na škále „log“ jsou osy log(1 + dny) (stejná škála, na které se odchylka počítá), popisky jsou ve dnech.
    df: patient_id, observed, expected, outlier, direction, band, weak, info.
    """
    log = scale == "log"
    tf = np.log1p if log else (lambda v: v)
    x, y = tf(df["expected"].astype(float)), tf(df["observed"].astype(float))
    hi = float(np.nanmax([x.max(), y.max()])) * 1.05 + (0.1 if log else 1)
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=[0, hi],
            y=[0, hi],
            mode="lines",
            name="přesně podle očekávání",
            line=dict(color=HIGHLIGHT, width=1.2),
            hoverinfo="skip",
        )
    )
    if np.isfinite(spread):
        for k, nm in ((1, "hranice neobvyklosti"), (-1, None)):
            off = center + k * threshold * spread
            fig.add_trace(
                go.Scatter(
                    x=[0, hi],
                    y=[off, hi + off],
                    mode="lines",
                    name=nm or "",
                    showlegend=nm is not None,
                    line=dict(color=HIGHLIGHT, width=1, dash="dash"),
                    hoverinfo="skip",
                )
            )
    _add_category_traces(fig, df, x, y, highlight, text_pos="top center")
    axis = dict(range=[0, hi], zeroline=False, automargin=True)
    if log:
        ticks = [t for t in _LOG_TICKS if np.log1p(t) <= hi]
        axis.update(
            tickmode="array", tickvals=[float(np.log1p(t)) for t in ticks], ticktext=[str(t) for t in ticks]
        )
    fig.update_layout(
        **{
            **LAYOUT,
            "height": 560,
            "margin": dict(l=10, r=10, t=60, b=10),
            "legend": dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"),
        },
        xaxis=dict(axis, title=f"očekávání – {metric_label.lower()} (dny)"),
        yaxis=dict(axis, title=f"skutečnost – {metric_label.lower()} (dny)", scaleanchor="x", scaleratio=1),
    )
    return fig


def group_points(df: pd.DataFrame, order: list[str], value_label: str, highlight: set[str]) -> go.Figure:
    """Body po skupinách s čarou mediánu (svisle). df: group, value, patient_id, info, cat."""
    pos = {g: i for i, g in enumerate(order)}
    fig = go.Figure()
    colors = {"longer": LONGER, "shorter": SHORTER}
    for i, g in enumerate(order):
        med = float(df.loc[df["group"] == g, "value"].median())
        fig.add_shape(
            type="line", x0=i - 0.32, x1=i + 0.32, y0=med, y1=med, line=dict(color=HIGHLIGHT, width=3)
        )
    x = df["group"].map(pos).to_numpy(dtype=float) + _jitter_for(df["patient_id"], 0.22)
    kinds = (
        ("normal", "pacient"),
        ("longer", "neobvykle delší pobyty"),
        ("shorter", "neobvykle kratší pobyty"),
    )
    for key, name in kinds:
        m = (df["cat"] == key).to_numpy()
        if not m.any():
            continue
        sub = df[m]
        sel = sub["patient_id"].isin(highlight).to_numpy()
        fig.add_trace(
            go.Scatter(
                x=x[m],
                y=sub["value"],
                mode="markers",
                name=name,
                marker=dict(
                    color=colors.get(key, "#8E9896"),
                    size=np.where(sel, 14, 8),
                    opacity=0.9,
                    line=dict(color=HIGHLIGHT, width=np.where(sel, 2.5, 0)),
                ),
                customdata=np.stack([sub["patient_id"], sub["info"]], axis=-1),
                hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<extra></extra>",
            )
        )
    fig.update_layout(
        **{
            **LAYOUT,
            "height": 500,
            "margin": dict(l=10, r=10, t=50, b=10),
            "legend": dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"),
        },
        xaxis=dict(
            tickmode="array",
            tickvals=list(range(len(order))),
            ticktext=[
                f"{wrap_label(g.rsplit(' (n=', 1)[0])}<br>(n={g.rsplit(' (n=', 1)[1]}" if " (n=" in g else g
                for g in order
            ],
            range=[-0.6, len(order) - 0.4],
            showgrid=False,
            automargin=True,
        ),
        yaxis=dict(title=value_label, automargin=True),
    )
    return fig


# ---------------------------------------------------------------------------
# Shlukování (záložka Shlukování na stránce Analýza odchylek)
# ---------------------------------------------------------------------------

# Barvy shluků – záměrně bez oranžové a modré (ty nesou směr odchylky).
CLUSTER_COLORS = ["#0B6E66", "#6B4E9B", "#8C564B", "#C2185B", "#7A8B1E", "#455A64", "#B8860B", "#2E7D32"]
CONTEXT_GREY = "#D3D9D7"
LINK_GREY = "#9AA5A2"


def cluster_color(cluster_id) -> str:
    try:
        return CLUSTER_COLORS[(int(cluster_id) - 1) % len(CLUSTER_COLORS)]
    except (TypeError, ValueError):
        return LINK_GREY


def cluster_scatter(
    points: pd.DataFrame,
    context: pd.DataFrame | None,
    x_title: str,
    y_title: str,
    selected: int | None,
    one_dim: bool = False,
) -> go.Figure:
    """Body v prostoru obarvené podle shluků; šedě ostatní porovnatelní pacienti.

    points: patient_id, x, y, cluster_id, cluster_label, info. context: x, y (může být None).
    """
    fig = go.Figure()
    if context is not None and len(context):
        fig.add_trace(
            go.Scatter(
                x=context["x"],
                y=context["y"],
                mode="markers",
                name="ostatní porovnatelní pacienti",
                marker=dict(color=CONTEXT_GREY, size=7),
                hoverinfo="skip",
            )
        )
    for cid, sub in points.groupby("cluster_id", sort=True):
        is_sel = selected is None or int(cid) == selected
        color = cluster_color(cid)
        n = len(sub)
        fig.add_trace(
            go.Scatter(
                x=sub["x"],
                y=sub["y"],
                mode="markers+text",
                text=sub["patient_id"],
                textposition="top center",
                textfont=dict(size=10, color=color),
                name=f"{sub['cluster_label'].iloc[0]} ({n})",
                opacity=1.0 if is_sel else 0.3,
                marker=dict(
                    color=color,
                    size=15 if (selected is not None and is_sel) else 11,
                    line=dict(color=HIGHLIGHT if (selected is not None and is_sel) else "white", width=1.5),
                ),
                customdata=np.stack([sub["patient_id"], sub["info"], sub["cluster_id"].astype(int)], axis=-1),
                hovertemplate="<b>%{customdata[0]}</b> · Shluk %{customdata[2]}<br>%{customdata[1]}<extra></extra>",
            )
        )
    fig.update_layout(
        **{
            **LAYOUT,
            "height": 440,
            "margin": dict(l=10, r=10, t=50, b=10),
            "legend": dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"),
        },
        xaxis=dict(title=x_title, zeroline=False, automargin=True),
        yaxis=dict(title=y_title, zeroline=False, automargin=True, visible=not one_dim),
        clickmode="event+select",
    )
    return fig


def dendrogram_figure(
    segments: list[dict],
    leaf_order: list[str],
    leaf_cluster: dict[str, int],
    cut_height: float | None,
    selected: int | None,
    leaf_info: dict[str, str],
) -> go.Figure:
    """Dendrogram: U-tvary spojení, větve obarvené shlukem, čárkovaný řez. Klik na list vybere jeho shluk."""
    fig = go.Figure()
    for seg in segments:
        c = seg["cluster"]
        is_sel = selected is not None and c == selected
        fig.add_trace(
            go.Scatter(
                x=seg["x"],
                y=seg["y"],
                mode="lines",
                showlegend=False,
                hoverinfo="skip",
                line=dict(
                    color=cluster_color(c) if c is not None else LINK_GREY, width=3.2 if is_sel else 1.8
                ),
                opacity=1.0 if (selected is None or is_sel or c is None) else 0.35,
            )
        )
    xs = list(range(len(leaf_order)))
    clusters = [leaf_cluster.get(p) for p in leaf_order]
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=[0] * len(xs),
            mode="markers",
            showlegend=False,
            marker=dict(
                color=[cluster_color(c) for c in clusters], size=11, line=dict(color="white", width=1)
            ),
            customdata=np.stack(
                [
                    leaf_order,
                    [leaf_info.get(p, "") for p in leaf_order],
                    [int(c) if c is not None else 0 for c in clusters],
                ],
                axis=-1,
            ),
            hovertemplate="<b>%{customdata[0]}</b> · Shluk %{customdata[2]}<br>%{customdata[1]}<extra></extra>",
        )
    )
    if cut_height is not None:
        fig.add_hline(y=cut_height, line=dict(color=HIGHLIGHT, dash="dash", width=1.2))
        fig.add_annotation(
            x=1,
            xref="paper",
            xanchor="right",
            y=cut_height,
            yanchor="bottom",
            showarrow=False,
            text="řez → shluky",
            font=dict(size=11, color="#56635F"),
        )
    fig.update_layout(
        **{**LAYOUT, "height": 440, "margin": dict(l=10, r=10, t=20, b=10)},
        xaxis=dict(
            tickmode="array",
            tickvals=xs,
            ticktext=leaf_order,
            tickangle=-60,
            showgrid=False,
            zeroline=False,
            automargin=True,
            range=[-0.7, len(xs) - 0.3],
        ),
        yaxis=dict(title="vzdálenost při spojení", zeroline=False, automargin=True, rangemode="tozero"),
        clickmode="event+select",
    )
    return fig


def cluster_profile_heatmap(profile: pd.DataFrame, sizes: dict[int, int], selected: int | None) -> go.Figure:
    """Shluky × proměnné: o kolik běžných rozptylů je průměr shluku nad/pod průměrem všech shlukovaných."""
    mat = profile.pivot(index="cluster_id", columns="label", values="std_diff").sort_index()
    labels_y = [f"{'▶ ' if selected == c else ''}Shluk {c} ({sizes.get(c, 0)})" for c in mat.index]
    lim = float(np.nanmax(np.abs(mat.to_numpy()))) if mat.size else 1.0
    lim = max(lim, 0.5)
    fig = go.Figure(
        go.Heatmap(
            z=mat.to_numpy(),
            x=[wrap_label(c, 18) for c in mat.columns],
            y=labels_y,
            zmin=-lim,
            zmax=lim,
            zmid=0,
            colorscale=[[0, "#0B6E66"], [0.5, "#F4F6F5"], [1, "#6B4E9B"]],
            text=np.vectorize(lambda v: f"{v:+.1f}".replace(".", ","))(mat.to_numpy()),
            texttemplate="%{text}",
            colorbar=dict(title="rozdíl"),
            hovertemplate="%{y} · %{x}: %{z:+.2f}<extra></extra>",
        )
    )
    fig.update_layout(
        **{**LAYOUT, "height": max(220, 46 * len(mat) + 110), "margin": dict(l=10, r=10, t=20, b=10)},
        yaxis=dict(autorange="reversed", automargin=True),
        xaxis=dict(automargin=True),
    )
    return fig
