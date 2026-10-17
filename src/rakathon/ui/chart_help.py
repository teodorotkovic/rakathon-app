"""Rozbalovací vysvětlení ke grafům na stránce Analýza odchylek.

Každý text odpovídá na čtyři otázky lékaře: co graf ukazuje, jak vznikla čísla, jak ho číst a na co si
dát pozor. Čísla (hranice, škála, minima) se doplňují z aktuálního nastavení, aby text odpovídal grafu.
"""

from __future__ import annotations

import streamlit as st

from rakathon.domain import AnalysisResult
from rakathon.formatting import fmt_num

TITLE = "O grafu: co ukazuje a jak se počítá"


def _common(a: AnalysisResult) -> dict[str, str]:
    cfg = a.config
    return {
        "thr": fmt_num(cfg.threshold),
        "near": fmt_num(cfg.threshold - cfg.margin / 2),
        "strong": fmt_num(cfg.threshold + cfg.margin),
        "scale": "poměrem – log(1 + skutečnost) − log(1 + očekávání)"
        if cfg.scale == "log"
        else "ve dnech – skutečnost − očekávání",
        "n_ref": str(len(a.reference_ids)),
        "min_stays": str(cfg.min_support_stays),
    }


_EXPECTATION = (
    "**Skutečnost** je typická (mediánová) nebo nejdelší délka započtených hospitalizací pacienta. "
    "**Očekávání** je medián téže hodnoty u podobných pacientů – stejná diagnóza, a je-li jich dost "
    "(alespoň 8), i stejná věková skupina a pohlaví; při nedostatku se srovnání rozšíří. Hodnocený pacient "
    "se do vlastního očekávání nikdy nepočítá."
)

_SCORE = (
    "**Míra odchylky**: rozdíl skutečnost − očekávání se spočítá {scale}. Potom se porovná s rozdíly "
    "u srovnávací skupiny ({n_ref} porovnatelných pacientů): (rozdíl − medián rozdílů) / (1,4826 × MAD). "
    "MAD je medián absolutních odchylek – robustní obdoba směrodatné odchylky, kterou samotní neobvyklí "
    "pacienti téměř neovlivní; koeficient 1,4826 ji převádí na stejnou škálu jako běžnou „sigmu“. "
    "Hodnota 3 tedy znamená, že rozdíl je zhruba třikrát větší než rozdíly, jaké běžně vídáme."
)

_CAUTION = (
    "**Na co pozor:** hranice {thr} je pracovní heuristika, ne pravděpodobnost ani klinicky ověřená mez. "
    "Delší ani kratší pobyt sám o sobě neznamená horší či lepší průběh. Skupiny diagnóz jsou orientační. "
    "✕ (méně spolehlivé srovnání) = očekávání vychází jen ze 4–7 podobných pacientů nebo u pacienta méně "
    "než {min_stays} započtené pobyty."
)

TEXTS: dict[str, str] = {
    "strip": "\n\n".join(
        [
            "**Co ukazuje:** každý porovnatelný pacient je jeden bod; řádky jsou orientační skupiny diagnóz, "
            "vodorovná osa je míra odchylky. Vpravo jsou pobyty delší, než je u podobných pacientů obvyklé, "
            "vlevo kratší.",
            _EXPECTATION,
            _SCORE,
            "**Jak číst:** 0 = rozdíl přesně typický. Čárkované čáry ±{thr} jsou hranice neobvyklosti; body za "
            "nimi jsou barevné (oranžová delší, modrá kratší). ▲/▼ udává směr i u šedých bodů. Od {strong} je "
            "odchylka „výrazná“, mezi {thr} a {strong} „hraniční“.",
            _CAUTION,
        ]
    ),
    "groups": "\n\n".join(
        [
            "**Co ukazuje:** stejná míra odchylky jako v zobrazení „Míra odchylky“, ale svisle a po skupinách "
            "diagnóz; u každé skupiny je počet porovnatelných pacientů n. Skupiny jsou seřazené podle mediánu "
            "odchylky. Body jsou do stran rozprostřené jen kvůli čitelnosti (pozice podle ID je stálá).",
            _EXPECTATION,
            _SCORE,
            "**Jak číst:** šedý pás = běžné rozdíly (±{thr}), čára 0 = přesně podle očekávání. Nad pásem jsou "
            "pobyty neobvykle delší (oranžově, s ID), pod pásem kratší (modře). Prázdný kroužek = těsně pod "
            "hranicí (od {near}). Při dvou ukazatelích se zobrazuje větší z obou odchylek se znaménkem podle "
            "směru.",
            _CAUTION,
        ]
    ),
    "days": "\n\n".join(
        [
            "**Co ukazuje:** očekávání (osa x) proti skutečnosti (osa y) v dnech. Osy jsou logaritmické "
            "(log(1 + dny)), protože na této škále se odchylka počítá – 10 dní místo 5 je pak stejně daleko "
            "od úhlopříčky jako 40 místo 20.",
            _EXPECTATION,
            "**Čáry:** plná úhlopříčka = skutečnost přesně podle očekávání. Čárkované čáry jsou body, pro které "
            "by míra odchylky vyšla přesně ±{thr}: log(1 + y) = log(1 + x) + medián rozdílů ± {thr} × "
            "1,4826 × MAD. Body za nimi jsou neobvyklí pacienti.",
            "**Jak číst:** nad úhlopříčkou jsou pobyty delší, pod ní kratší. Barvy a symboly jako v ostatních "
            "grafech; prázdný kroužek = těsně pod hranicí.",
            _CAUTION,
        ]
    ),
    "days_raw": "\n\n".join(
        [
            "**Co ukazuje:** očekávání (osa x) proti skutečnosti (osa y) v dnech, s lineárními osami (rozdíl "
            "se nyní počítá ve dnech – Pokročilé nastavení).",
            _EXPECTATION,
            "**Čáry:** plná úhlopříčka = přesně podle očekávání. Čárkované čáry jsou posunuté o medián rozdílů "
            "± {thr} × 1,4826 × MAD dní; body za nimi jsou neobvyklí pacienti.",
            "**Jak číst:** nad úhlopříčkou delší, pod ní kratší pobyty. Ve dnech víc vyniknou dlouhé pobyty; "
            "relativní škála (poměrem) je pro různě dlouhé diagnózy spravedlivější.",
            _CAUTION,
        ]
    ),
    "zscatter": "\n\n".join(
        [
            "**Co ukazuje:** míru odchylky dvou ukazatelů zároveň – typického (mediánového) a nejdelšího pobytu.",
            _EXPECTATION,
            _SCORE,
            "**Jak číst:** čárkovaný čtverec = ±{thr} v obou osách. Pacient je neobvyklý, když leží mimo "
            "čtverec alespoň v jedné ose (celková míra = větší z obou hodnot, ne součet).",
            "**Na co pozor:** oba ukazatele jsou ze stejných pobytů a spolu silně souvisejí; shoda v obou proto "
            "není nezávislým potvrzením. Hranice {thr} je pracovní heuristika.",
        ]
    ),
    "box": "\n\n".join(
        [
            "**Co ukazuje:** rozložení zvolené hodnoty v každé skupině (Tukeyho krabicový graf). Skupiny jsou "
            "seřazené podle mediánu, n = počet pacientů s dostupnou hodnotou.",
            "**Jak se počítá:** krabice sahá od 1. do 3. kvartilu (prostředních 50 % pacientů; kvartily lineární "
            "interpolací), čára uvnitř je medián. IQR = výška krabice (Q3 − Q1). Vousy sahají k nejvzdálenější "
            "skutečné hodnotě, která je ještě v rozmezí Q1 − 1,5 × IQR až Q3 + 1,5 × IQR. Body mimo tento rozsah "
            "jsou odlehlé hodnoty a jsou vypsané v tabulce pod grafem.",
            "**Lůžkodny** = součet délek dokončených hospitalizací (konec − začátek, bez +1, stejně jako v celé "
            "aplikaci) za celou zaznamenanou historii. Den 0 v datech je první záznam v nemocnici, ne diagnóza, "
            "proto se nepočítá „první rok“.",
            "**Na co pozor:** odlehlá hodnota v krabicovém grafu je popis rozložení v jedné skupině – není to "
            "totéž jako „neobvyklý pacient“ v analýze odchylek, která srovnává s očekáváním podobných pacientů. "
            "U malých skupin (n < 10) jsou kvartily nejisté.",
        ]
    ),
    "points": "\n\n".join(
        [
            "**Co ukazuje:** každý pacient je jeden bod, černá čára je medián skupiny; n = počet pacientů "
            "s dostupnou hodnotou. Body jsou do stran rozprostřené jen kvůli čitelnosti.",
            "**Barvy** přebírá z analýzy odchylek: oranžově pacienti s neobvykle delšími, modře s neobvykle "
            "kratšími pobyty (při aktuální hranici {thr}), šedě ostatní.",
            "**Lůžkodny** = součet délek dokončených hospitalizací za celou zaznamenanou historii (den 0 = první "
            "záznam v nemocnici, ne diagnóza).",
            "**Na co pozor:** vysoká hodnota v grafu neznamená automaticky neobvyklého pacienta – analýza "
            "odchylek srovnává s očekáváním podobných pacientů, ne s mediánem celé skupiny.",
        ]
    ),
    "xy": "\n\n".join(
        [
            "**Co ukazuje:** dva libovolné údaje proti sobě; každý bod je pacient, který má oba údaje. Křížek "
            "a tečkované čáry jsou mediány obou údajů.",
            "**Jak se počítá vzdálenost:** každý údaj se převede na robustní z-skóre – (hodnota − medián) / "
            "(1,4826 × MAD); je-li MAD nulové, použije se IQR / 1,349. Vzdálenost = √(z_x² + z_y²). Elipsa "
            "odpovídá zvolené vzdálenosti „daleko“; body za ní jsou fialové a vypsané v tabulce.",
            "**Jak číst:** elipsa je protáhlá podle rozptylu každého údaje. Body daleko v jedné ose jsou "
            "neobvyklé jedním údajem, body v rohu oběma.",
            "**Na co pozor:** jde o popis rozložení, ne o odchylku od očekávání a ne o klinický závěr. "
            "Počty (pobyty, epizody) mají celočíselné hodnoty, takže se body mohou překrývat.",
        ]
    ),
    "context": "\n\n".join(
        [
            "**Co ukazuje:** jak často se zvolená vlastnost vyskytuje u neobvyklých (nebo ručně vybraných) "
            "pacientů ve srovnání s ostatními porovnatelnými pacienty.",
            "**Jak se počítá:** kategorie – podíl pacientů s danou hodnotou v obou skupinách a rozdíl v "
            "procentních bodech; číselné údaje – rozložení hodnot v obou skupinách. Laboratoře se nejdřív "
            "shrnou na medián za pacienta, takže každý pacient má jeden hlas.",
            "**Na co pozor:** popisné srovnání bez testů statistické významnosti – u malého počtu neobvyklých "
            "pacientů je to hypotéza k ověření, ne prokázaná souvislost. Chybějící údaj není nula.",
        ]
    ),
}


def about(key: str, a: AnalysisResult) -> None:
    with st.expander(TITLE, icon=":material/info:"):
        st.markdown(TEXTS[key].format(**_common(a)))
