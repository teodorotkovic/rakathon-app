# 0001 – Výchozí výsledkový ukazatel

**Datum:** 2026-10-16 · **Stav:** přijato (čeká na potvrzení mentorem)

**Rozhodnutí:** Hlavní ukazatel = medián délky dokončených hospitalizací s `dx_main = dx_icd10`; druhý = maximum
těchže pobytů (volitelný). Alternativní pravidla `group_dx_match` a `from_anchor_all_inpatient` jsou dostupná jako
globální konfigurace.

**Důvody:** nepotřebuje datum diagnózy ani úplnost sledování; délka pobytu není zkreslena anonymizačním posunem;
na skutečných datech pokrývá 131/157 pacientů.

**Důsledky:** nezahrnuje komplikace s jiným hlavním kódem; pacienti s D43/D48 mají méně pobytů ve výpočtu;
počty kontaktů jsou jen kontext. Změna pravidla vytváří nové `baseline_config_id`.
