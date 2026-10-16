# Metodika

Verze: `FEATURE_SCHEMA_VERSION = features-v1`, `METHOD_VERSION = method-v1`, diagnostická mapa `dxmap-v1`.

## 1. Výsledkový ukazatel
**Hlavní:** medián délky dokončených hospitalizací, jejichž hlavní diagnóza (`dx_main`) přesně odpovídá
diagnóze nádoru (`dx_icd10`) – `median_los_dx`. **Druhý (volitelný):** nejdelší takový pobyt – `max_los_dx`
(korelovaný s mediánem, není nezávislým potvrzením).

Proč: nepředpokládá, že den 0 je diagnóza; délky pobytů nejsou poškozeny anonymizačním posunem (posouvá se začátek
i konec společně); nepředstírá znalost úplného sledování. Na skutečných datech má výsledek 131/157 pacientů.

Omezení (zobrazena i v aplikaci): nezahrnuje pobyty s jiným hlavním kódem (D70, Z51, infekce); medián shrnuje
pobyty z různých fází péče; nejde o kompletní zátěž onkologické léčby.

Pravidla: žádný vybraný pobyt ⇒ výsledek chybí (`no_relevant_stay`), nikdy 0; jediný pobyt ⇒ hodnota se ukáže,
ale opora je označena jako omezená; pacient s více nádory ⇒ vyřazen (`excluded`).

**Alternativní pravidla výběru pobytů** (globální, „Globální očekávání (pokročilé)“):
- `group_dx_match` – hlavní dg. pobytu ve stejné orientační skupině jako nádor (např. D43 a C71),
- `from_anchor_all_inpatient` – všechny dokončené hospitalizace od kotvy = první epizoda (podle pořadí) s dg.
  nádoru. Kotva je proxy, ne datum diagnózy; bez kotvy se pacient nehodnotí (`no_anchor`).

Neprovádíme analýzu „prvních N dní od dne 0“ ani počty za pevný horizont (chybí srovnatelná doba pozorování).

## 2. Globální baseline – referenční medián podobných pacientů
Pro pacienta *i* a ukazatel *j* se prochází hierarchie (konfigurace `baseline.hierarchy`):
1. stejná diagnóza + věková skupina + pohlaví, 2. diagnóza + věk, 3. diagnóza, 4. orientační skupina + věk,
5. orientační skupina.

Na každé úrovni se spočítají **jiní** pacienti (bez *i*, bez vyřazených a multi-tumor) s dostupným výsledkem.
Zvolí se první úroveň s `n ≥ min_reference` (8) → stav `ok`; jinak první s `n ≥ min_limited_reference` (4) →
`limited_reference`; jinak `insufficient_reference` (očekávání se nevydá; populační medián jen jako kontext).
Úroveň se přeskočí, pokud faktor chybí (např. diagnóza bez orientační skupiny) – důvod se uvede.

`expected_ij = median({y_kj : k ∈ reference})` – jeden hlas na pacienta (y = pacientská hodnota ukazatele).
Ukládá se identita reference, `n`, úroveň, použité a **nepoužité** faktory a kvartily/rozsah reference
(rozložení pozorovaných hodnot, ne predikční interval). Hranice 8/4 jsou technické, ne klinicky validované.

Na skutečných datech (výchozí nastavení): 102 pacientů `ok`, 16 omezená reference (C49, C62), 39 bez reference
(vzácné diagnózy a/nebo bez výsledku). Hodnotitelných (výsledek + očekávání) 107.

**LOO invariant:** změna vlastního výsledku pacienta nezmění jeho očekávání (test
`test_own_outcome_does_not_change_own_expectation`, kontrola i v `scripts/check_real_data.py`).

## 3. Rezidua
`residual_ij = observed_ij − expected_ij` (dny, podepsané) a
`log_residual_ij = log1p(observed_ij) − log1p(expected_ij)` (relativní, stabilnější). Výchozí analýza používá
log škálu; volba „dny“ je v UI.

## 4. Lokální detektor (RobustResidualDetector)
Pro zvolené ukazatele *j* a lokální referenci *R* (výchozí: všichni hodnotitelní):
- `c_j = median_{k∈R}(r_kj)`, `s_j = 1.4826 · MAD_{k∈R}(r_kj)`;
- při `s_j = 0`: `s_j = IQR/1.349`; je-li i to 0, dimenze se **nestandardizuje** (skóre z ní nevzniká, raw rozdíly
  zůstávají);
- `z_ij = (r_ij − c_j)/s_j`; **skóre** `S_i = max_j |z_ij|`; určující ukazatel = argmax (skóre není součet);
- outlier ⇔ `S_i ≥ práh` (výchozí 2.5, pracovní heuristika, ne pravděpodobnost);
- **směr** = znaménko původního `residual` určujícího ukazatele (ne znaménko `z`);
- hodnotí se jen úplné případy pro zvolené ukazatele; ostatní jsou „nehodnoceno“ s důvodem; lokální reference
  s méně než `min_calibration_n` (8) pacienty ⇒ nic se neskóruje.

Oddělené výstupy (nikdy jedna barva pro vše): pořadí, nad prahem, směr, **pásmo** (výrazná ≥ práh + margin;
hraniční; těsně pod prahem ≥ práh − margin/2; bez výrazné), **opora** (omezená reference nebo < 2 pobyty),
**citlivost** (označení při prazích 2.0/2.5/3.0/3.5 – citlivost rozhodnutí, ne pravděpodobnost).
**Kontrafaktuál:** interval pozorované hodnoty, ve kterém by pacient nebyl označen (vlastnost skóre, ne doporučení).

Na skutečných datech (výchozí: 1 ukazatel, log, práh 2.5): 107 skórováno, 3 nad prahem.

## 5. Shlukování outlierů a popis skupin
Jen množina outlierů. Při < `cluster_min_outliers` (4) se skupiny nevytváří („příliš málo případů“).
Jinak `AgglomerativeClustering(linkage="average", distance_threshold=2.5)` nad podepsanými z-profily;
skupiny ≥ 2 pacienti, singletony = izolované případy. U jedné dimenze aplikace uvádí, že skupiny vyjadřují hlavně
směr a velikost odchylky.

Popis skupiny: profil reziduí (medián pozorováno vs. očekávání, medián z, počet delší/kratší), složení diagnóz,
věku a pohlaví; srovnání s (a) lokální referencí bez členů skupiny a (b) referencí se stejnými diagnózami:
kategorické = podíl ve skupině vs. referenci a rozdíl v p. b. (zobrazeny jen rozdíly ≥ 20 p. b. s ≥ 2 pacienty),
numerické = medián/IQR a dostupné `n`, laboratoře = medián pacientských mediánů stejného testu a jednotky.
Varování: diagnózy skupiny tvoří < 30 % reference (vzorec může odrážet skladbu diagnóz), malá reference se
stejnými diagnózami, skupina < 5. Bez testů významnosti – jde o hypotézy pro mentora.

## 6. Vysvětlení jednotlivce (tři vrstvy)
- **A – proč toto očekávání:** úroveň reference, faktory použité/nepoužité, `n`, kvartily, graf hodnot reference.
- **B – co vyvolává označení:** pozorováno, očekávání, rozdíl, relativní rozdíl, z, určující ukazatel, počet pobytů,
  kontrafaktuál, citlivost.
- **C – čím se liší:** charakteristiky pacienta vs. pacienti použití pro očekávání (podíl stejné hodnoty /
  percentil, dostupné `n`), řazeno podle neobvyklosti; označeno jako deskriptivní hypotézy.

## 7. Nejistota a omezení interpretace
Malá kohorta; hranice reference a práh jsou heuristiky; anonymizační posun ±3 dny (neovlivňuje délky pobytů,
ale ovlivňuje mezery mezi epizodami – proto readmise nejsou ukazatelem); laboratorní meze mohou být dospělé;
úplnost sledování neznámá; kratší pobyt ≠ lepší průběh; žádná kauzální interpretace.

## 8. Volitelná druhá baseline: Ridge s leave-one-patient-out (implementováno)
Volba „Metoda očekávání“ v *Globální očekávání (pokročilé)* (`BaselineConfig.method = "ridge_loo"`,
`ridge_alpha = 1.0`). Model: `Ridge` nad `y = log1p(ukazatel)` se vstupy diagnostická kategorie (orientační
skupina; u nezařazených diagnóz přesný kód), věková skupina, pohlaví – one-hot encoding s `handle_unknown="ignore"`.

- Pro každého pacienta se encoder i model fitují **jen na ostatních pacientech** (LOO); vlastní výsledek ani
  stav úmrtí ani laboratoře nejsou vstupem (test `test_ridge_loo_own_outcome_does_not_change_expectation`).
- Očekávání = `expm1(predikce)` = **modelové typické očekávání** (v log1p škále, ne aritmetický průměr dní).
  Záporná predikce v log škále by se ořízla na 0 a byla by uvedena v důvodu.
- Rozklad: `predikce = základ + Σ příspěvků faktorů` ze **stejného LOO fitu**; zobrazen v detailu jako
  tabulka (log1p příspěvek a násobek `1 + délka`), test `test_ridge_decomposition_matches_prediction`.
- Opora: počet jiných pacientů ve stejné diagnostické kategorii; ≥ 8 ok, 4–7 omezená, < 4 očekávání se nevydá
  (model by vycházel jen z věku a pohlaví). Nevídaná hodnota faktoru má nulový příspěvek a je uvedena.
- Popisné LOO chyby (obě metody) jsou v postranním panelu: na skutečných datech medián |rozdílu| hlavního
  ukazatele 1,25 dne (peer medián) vs. 1,13 dne (Ridge), 107/157 hodnoceno. Nejde o klinickou validaci.

Neimplementováno: Isolation Forest nad rezidui, bootstrap stability, PCA – viz `docs/TASKS.md`.
