"""Katalog vlastností, výsledkových ukazatelů a pravidel výběru epizod.

Role (FeatureRole) určují, kde se vlastnost smí použít. Do baseline vstupují
jen vlastnosti s rolí BASELINE_INPUT uvedené v hierarchii konfigurace; nic se
nevybírá automaticky jako „všechny numerické sloupce“.
"""

from __future__ import annotations

import pandas as pd

from rakathon.data.validation import AGE_GROUPS
from rakathon.domain import FeatureRole, FeatureSpec, OutcomeSpec

# ---------------------------------------------------------------------------
# Pravidla výběru epizod pro výsledkové ukazatele (globální konfigurace)
# ---------------------------------------------------------------------------

EPISODE_RULES: dict[str, dict[str, str]] = {
    "exact_dx_match": {
        "label": "Hlavní diagnóza pobytu = diagnóza nádoru (přesná shoda)",
        "stays_phrase": "s hlavní diagnózou shodnou s diagnózou nádoru",
        "description": (
            "Dokončené hospitalizace, jejichž hlavní diagnóza (dx_main) přesně odpovídá "
            "tříznakové diagnóze nádoru pacienta."
        ),
        "limitation": (
            "Nezahrnuje onkologicky související pobyty s jiným hlavním kódem (např. D70, Z51, infekce). "
            "Medián shrnuje pobyty z různých fází péče."
        ),
    },
    "group_dx_match": {
        "label": "Hlavní diagnóza pobytu ve stejné orientační skupině jako nádor",
        "stays_phrase": "s hlavní diagnózou ze stejné orientační diagnostické skupiny jako nádor",
        "description": (
            "Dokončené hospitalizace s hlavní diagnózou shodnou s nádorem nebo patřící do stejné "
            "orientační diagnostické skupiny (např. D43 a C71). U nezařazených diagnóz jen přesná shoda."
        ),
        "limitation": (
            "Závisí na orientační diagnostické mapě, která není validovanou klasifikací. "
            "Stále nezahrnuje komplikace s jiným hlavním kódem."
        ),
    },
    "from_anchor_all_inpatient": {
        "label": "Všechny dokončené hospitalizace od první epizody s diagnózou nádoru",
        "stays_phrase": "všech dokončených hospitalizací od první epizody s diagnózou nádoru (proxy kotva)",
        "description": (
            "Kotva = první epizoda (podle pořadí) s hlavní diagnózou shodnou s nádorem. Zahrnuty jsou "
            "všechny dokončené hospitalizace od kotvy včetně, bez ohledu na diagnózu."
        ),
        "limitation": (
            "Kotva je proxy začátku sledovaného průběhu, nikoli datum diagnózy. Úplnost sledování po kotvě "
            "není ověřena. Pacient bez kotvy se nehodnotí (nezačíná se skrytě od dne 0)."
        ),
    },
}


def outcome_spec(metric_id: str, episode_rule: str) -> OutcomeSpec:
    rule = EPISODE_RULES[episode_rule]
    phrase = rule["stays_phrase"]
    if metric_id == "median_los_dx":
        return OutcomeSpec(
            id=metric_id,
            label=f"Medián délky dokončených hospitalizací {phrase}",
            short_label="Medián délky pobytu",
            description=(
                "Medián délek (day_end − day_start) vybraných dokončených hospitalizací pacienta. "
                "Nejde o kompletní zátěž onkologické léčby. " + rule["limitation"]
            ),
            unit="dny",
            statistic="median",
            time_policy="Celá zaznamenaná historie; den 0 = první záznam v nemocnici, ne diagnóza.",
            evaluability="Alespoň 1 vybraný dokončený pobyt; 1 pobyt = omezená opora.",
        )
    if metric_id == "max_los_dx":
        return OutcomeSpec(
            id=metric_id,
            label=f"Nejdelší dokončená hospitalizace {phrase}",
            short_label="Nejdelší pobyt",
            description=(
                "Délka nejdelšího vybraného dokončeného pobytu. Je korelovaná s mediánem – "
                "není nezávislým potvrzením téže hypotézy. " + rule["limitation"]
            ),
            unit="dny",
            statistic="max",
            time_policy="Celá zaznamenaná historie; den 0 = první záznam v nemocnici, ne diagnóza.",
            evaluability="Alespoň 1 vybraný dokončený pobyt.",
        )
    raise KeyError(f"Neznámý výsledkový ukazatel: {metric_id}")


OUTCOME_IDS = ("median_los_dx", "max_los_dx")
OUTCOME_SHORT = {"median_los_dx": "Medián délky pobytu", "max_los_dx": "Nejdelší pobyt"}


# ---------------------------------------------------------------------------
# Vestavěné vlastnosti
# ---------------------------------------------------------------------------

_F = FeatureSpec
R = FeatureRole

BUILTIN_FEATURES: list[FeatureSpec] = [
    _F(
        "patient_id",
        "ID pacienta",
        "Pseudonym pacienta; jen identifikátor a spojovací klíč.",
        "text",
        R.IDENTIFIER,
        "patients.csv",
    ),
    _F(
        "dx_icd10",
        "Diagnóza (MKN-10)",
        "Tříznaková diagnóza nádoru.",
        "categorical",
        R.BASELINE_INPUT,
        "patients.csv",
        availability="při diagnóze",
    ),
    _F(
        "dx_group",
        "Orientační diagnostická skupina",
        "Přibližná skupina podle verzované mapy config/diagnosis_groups.csv; není validovaná klasifikace rizika.",
        "categorical",
        R.BASELINE_INPUT,
        "odvozeno z dx_icd10",
        missing_meaning="diagnóza nezařazena do skupiny",
        availability="při diagnóze",
    ),
    _F(
        "age_group",
        "Věková skupina při diagnóze",
        "Věk při diagnóze v letech (skupiny).",
        "categorical",
        R.BASELINE_INPUT,
        "patients.csv",
        unit="roky",
        availability="při diagnóze",
        order=tuple(AGE_GROUPS),
    ),
    _F(
        "sex", "Pohlaví", "M/F.", "categorical", R.BASELINE_INPUT, "patients.csv", availability="při diagnóze"
    ),
    _F(
        "median_los_dx",
        "Medián délky vybraných hospitalizací",
        "Viz výsledkové ukazatele.",
        "numeric",
        R.OUTCOME,
        "episodes.csv",
        unit="dny",
        aggregation="medián přes vybrané pobyty",
        missing_meaning="žádný vybraný pobyt – nehodnoceno, ne 0",
    ),
    _F(
        "max_los_dx",
        "Nejdelší vybraná hospitalizace",
        "Viz výsledkové ukazatele.",
        "numeric",
        R.OUTCOME,
        "episodes.csv",
        unit="dny",
        aggregation="maximum přes vybrané pobyty",
        missing_meaning="žádný vybraný pobyt – nehodnoceno, ne 0",
    ),
    _F(
        "stage_status",
        "Stadium – stav údaje",
        "Interpretace kódu stadia (7 a 9 nejsou stadium).",
        "categorical",
        R.DESCRIPTOR,
        "patients.csv: stage",
    ),
    _F(
        "grade_status",
        "Grade – typ kódu",
        "1–4 diferenciace, 5/6 buněčný typ, 9 neznámo; nejde o jednu škálu.",
        "categorical",
        R.DESCRIPTOR,
        "patients.csv: grade",
    ),
    _F(
        "morphology_behaviour_label",
        "Chování nádoru (ICD-O-3)",
        "Z kódu morfologie; 3333/3 = neznámé.",
        "categorical",
        R.DESCRIPTOR,
        "patients.csv: morphology_icdo3",
    ),
    _F(
        "extent",
        "Rozsah (kód NOR)",
        "Raw kód; význam hodnot není v podkladech potvrzen.",
        "categorical",
        R.DESCRIPTOR,
        "patients.csv",
        missing_meaning="nevyplněno",
    ),
    _F(
        "laterality",
        "Lateralita (kód NOR)",
        "Raw kód; překlad čísel není ověřen.",
        "categorical",
        R.DESCRIPTOR,
        "patients.csv",
    ),
    _F(
        "tnm_clinical_available",
        "Klinické TNM vyplněno",
        "Alespoň jedna z kategorií T/N/M je vyplněna.",
        "boolean",
        R.DESCRIPTOR,
        "patients.csv: t, n, m",
    ),
    _F(
        "n_stays_included",
        "Počet pobytů ve výpočtu",
        "Počet dokončených pobytů vybraných pravidlem.",
        "numeric",
        R.DESCRIPTOR,
        "episodes.csv",
        unit="pobyty",
        aggregation="počet",
    ),
    _F(
        "n_inpatient_open",
        "Pobyty bez data propuštění",
        "Pobyty bez zaznamenaného data propuštění (nevíme, zda hospitalizace pokračuje).",
        "numeric",
        R.DESCRIPTOR,
        "episodes.csv",
        unit="pobyty",
        aggregation="počet",
    ),
    _F(
        "n_inpatient_completed",
        "Dokončené hospitalizace (všechny dg.)",
        "Všechny dokončené hospitalizace.",
        "numeric",
        R.DESCRIPTOR,
        "episodes.csv",
        unit="pobyty",
        aggregation="počet",
    ),
    _F(
        "n_outpatient",
        "Ambulantní kontakty",
        "Počet ambulantních kontaktů za celou zaznamenanou historii; "
        "bez srovnatelné doby pozorování není skórovaným výsledkem.",
        "numeric",
        R.DESCRIPTOR,
        "episodes.csv",
        unit="kontakty",
        aggregation="počet",
    ),
    _F(
        "n_d70_episodes",
        "Epizody s hlavní dg. D70",
        "Záznamy epizod s kódem D70; není úplná incidence neutropenie.",
        "numeric",
        R.DESCRIPTOR,
        "episodes.csv",
        unit="epizody",
        aggregation="počet",
    ),
    _F(
        "history_span_days",
        "Rozsah zaznamenané historie",
        "Poslední známý den epizody; neprokazuje úplnost sledování.",
        "numeric",
        R.DESCRIPTOR,
        "episodes.csv",
        unit="dny",
    ),
    _F(
        "first_episode_birth",
        "První epizoda = porod (Z38)",
        "E001 s kódem Z38 – den 0 není začátek léčby.",
        "boolean",
        R.DESCRIPTOR,
        "episodes.csv",
    ),
    _F(
        "has_labs",
        "Laboratoře k dispozici",
        "Alespoň jeden laboratorní výsledek.",
        "boolean",
        R.DESCRIPTOR,
        "labs.csv",
        missing_meaning="není dostupný záznam, ne normální výsledek",
    ),
    _F(
        "n_lab_results",
        "Počet laboratorních výsledků",
        "Počet řádků výsledků (ne počet odběrů).",
        "numeric",
        R.DESCRIPTOR,
        "labs.csv",
        unit="výsledky",
        aggregation="počet",
    ),
    _F(
        "lab_share_low",
        "Podíl výsledků pod mezí (L)",
        "Podíl L mezi výsledky s mezemi; meze mohou být dospělé – není to klinická patologie.",
        "numeric",
        R.DESCRIPTOR,
        "labs.csv",
        unit="podíl",
        aggregation="podíl na pacienta",
        missing_meaning="bez laboratoří",
    ),
    _F(
        "lab_share_high",
        "Podíl výsledků nad mezí (H)",
        "Podíl H mezi výsledky s mezemi.",
        "numeric",
        R.DESCRIPTOR,
        "labs.csv",
        unit="podíl",
        aggregation="podíl na pacienta",
        missing_meaning="bez laboratoří",
    ),
    _F(
        "n_invalid_intervals",
        "Neplatné intervaly epizod",
        "day_end < day_start.",
        "numeric",
        R.DATA_QUALITY,
        "episodes.csv",
    ),
    _F(
        "n_dx_missing",
        "Epizody bez hlavní diagnózy",
        "Prázdné dx_main.",
        "numeric",
        R.DATA_QUALITY,
        "episodes.csv",
    ),
    _F(
        "multi_tumor",
        "Více nádorů",
        "Pacient má více nádorových řádků – vyřazen z baseline.",
        "boolean",
        R.DATA_QUALITY,
        "patients.csv",
    ),
]

FEATURES_BY_ID = {f.id: f for f in BUILTIN_FEATURES}

# Vlastnosti použité v popisu skupin a v individuálním srovnání (vrstva C).
# deceased záměrně chybí: jediný případ, riziko reidentifikace, není vstupem ani výsledkem.
GROUP_CATEGORICAL = [
    "dx_icd10",
    "dx_group_label",
    "age_group",
    "sex",
    "stage_status",
    "grade_status",
    "morphology_behaviour_label",
    "extent",
    "first_episode_birth",
    "has_labs",
]
GROUP_NUMERIC = [
    "n_stays_included",
    "n_inpatient_completed",
    "n_inpatient_open",
    "n_outpatient",
    "n_d70_episodes",
    "history_span_days",
    "n_lab_results",
    "lab_share_low",
    "lab_share_high",
]

DISPLAY_LABELS: dict[str, str] = {f.id: f.label for f in BUILTIN_FEATURES}
DISPLAY_LABELS.update({"dx_group_label": "Orientační diagnostická skupina"})


def feature_label(feature_id: str, extra_meta: pd.DataFrame | None = None) -> str:
    if extra_meta is not None and len(extra_meta) and feature_id in set(extra_meta["column"]):
        row = extra_meta[extra_meta["column"] == feature_id].iloc[0]
        unit = f" [{row['unit']}]" if row.get("unit") else ""
        return f"{row['label']}{unit} (doplněno)"
    return DISPLAY_LABELS.get(feature_id, feature_id)


def descriptor_columns(extra_meta: pd.DataFrame | None) -> tuple[list[str], list[str]]:
    """Vrací (kategorické, numerické) popisné sloupce včetně doplňkových vlastností."""
    cat = list(GROUP_CATEGORICAL)
    num = list(GROUP_NUMERIC)
    if extra_meta is not None and len(extra_meta):
        for row in extra_meta.itertuples(index=False):
            if row.role != "descriptor":
                continue
            (num if row.dtype == "numeric" else cat).append(row.column)
    return cat, num
