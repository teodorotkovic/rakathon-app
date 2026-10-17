"""Srozumitelné texty pro lékaře (bez technické terminologie), sdílené stránkami a postranním panelem."""

from __future__ import annotations

# (popisek, jedna věta pod volbou, podrobné vysvětlení v nápovědě „?“)
METHOD_OPTIONS: dict[str, tuple[str, str, str]] = {
    "peer_median": (
        "Podobní pacienti (doporučeno)",
        "Očekávání = typická délka pobytu u jiných dětí se stejnou diagnózou; je-li jich dost, "
        "i stejného věku a pohlaví.",
        "Pro každého pacienta vezmeme ostatní pacienty se stejnou diagnózou (při dostatku také stejné věkové "
        "skupiny a pohlaví) a spočítáme medián jejich délky pobytu – to je očekávání. Hodnocený pacient se do "
        "srovnání nikdy nepočítá. Je-li podobných pacientů méně než 8, srovnání se postupně rozšíří (např. na "
        "širší skupinu diagnóz); při méně než 4 pacienta nehodnotíme. V detailu pacienta vždy uvidíte, s kým "
        "přesně byl porovnán.",
    ),
    "ridge_loo": (
        "Statistický model",
        "Odhad z diagnózy, věku a pohlaví současně; ukáže, o kolik každý faktor typickou délku prodlužuje "
        "nebo zkracuje.",
        "Model se pro každého pacienta naučí na všech ostatních pacientech, jak délku pobytu ovlivňuje skupina "
        "diagnózy, věk a pohlaví, a z toho odhadne typickou délku. V detailu pacienta uvidíte, kolik který faktor "
        "přidal nebo ubral. Hodí se jako druhý pohled pro srovnání s metodou podobných pacientů. U vzácných "
        "diagnóz (méně než 4 podobní pacienti) nehodnotí.",
    ),
}

RULE_OPTIONS: dict[str, tuple[str, str, str]] = {
    "exact_dx_match": (
        "Pobyty kvůli nádoru (doporučeno)",
        "Jen dokončené hospitalizace, jejichž hlavní diagnóza je diagnóza nádoru pacienta.",
        "Nezahrnuje pobyty kvůli komplikacím s jiným hlavním kódem (např. neutropenie D70, podání chemoterapie "
        "Z51, infekce). Délka pobytu je přesná i přes anonymizaci dat. Pacient bez takového pobytu se nehodnotí – "
        "nikdy se mu nepřiřadí nula dní.",
    ),
    "group_dx_match": (
        "Pobyty kvůli nádorům stejné skupiny",
        "Také pobyty s příbuznou diagnózou nádoru (např. D43 a C71 u nádorů CNS).",
        "Hodí se tam, kde se tentýž nádor v nemocnici kóduje různě. Skupiny diagnóz jsou orientační, nejde o "
        "klinicky ověřenou klasifikaci. Komplikace s jiným hlavním kódem stále nezahrnuje.",
    ),
    "from_anchor_all_inpatient": (
        "Všechny hospitalizace od prvního záznamu nádoru",
        "Včetně komplikací, od první návštěvy s diagnózou nádoru.",
        "Počítá všechny dokončené hospitalizace od první epizody s diagnózou nádoru, bez ohledu na důvod pobytu. "
        "Tato první epizoda není datum diagnózy a úplnost dalšího sledování není ověřená. Pacienti bez takového "
        "záznamu se nehodnotí.",
    ),
}

_WHAT = {
    "exact_dx_match": "hospitalizací kvůli nádoru (hlavní diagnóza pobytu je diagnóza nádoru)",
    "group_dx_match": "hospitalizací kvůli nádoru včetně příbuzných diagnóz stejné skupiny",
    "from_anchor_all_inpatient": "všech hospitalizací od prvního záznamu nádoru, včetně komplikací",
}
_STAT = {"median_los_dx": "Typická (mediánová) délka", "max_los_dx": "Délka nejdelší z"}
_WHOM = {
    "peer_median": "s podobnými pacienty – se stejnou diagnózou, a je-li jich dost, i stejným věkem a pohlavím",
    "ridge_loo": "s odhadem statistického modelu z diagnózy, věku a pohlaví",
}


def plain_context(method: str, rule: str, metric_id: str) -> str:
    """Dvě věty: co se sleduje a s kým se pacient porovnává (podle aktivního nastavení)."""
    stat = _STAT.get(metric_id, "Délka")
    return (
        f"**Co sledujeme:** {stat} {_WHAT.get(rule, 'vybraných hospitalizací')}.  \n"
        f"**S kým porovnáváme:** {_WHOM.get(method, 's podobnými pacienty')}."
    )
