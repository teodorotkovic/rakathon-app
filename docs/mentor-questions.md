# Otázky pro mentory

Každá otázka: aktuální pracovní předpoklad (implementováno), dopad odpovědi, stav. Odpověď se promítne změnou
konkrétního pravidla a jeho verze (staré analýzy se zpětně nemění).

| # | Otázka | Pracovní předpoklad | Dopad odpovědi | Stav |
|---|---|---|---|---|
| 1 | Je medián délky pobytů s hlavní dg. = dg. nádoru klinicky užitečný pro první demonstraci? Které další epizody zahrnout? | ano jako konzervativní start; alternativy `group_dx_match` a `from_anchor_all_inpatient` v UI | změna výchozího `episode_rule`, případně nový ukazatel | otevřeno |
| 2 | Lze první shodu `dx_main` s dg. nádoru použít jako časovou kotvu? Existuje lepší údaj? | kotva jen v alternativním pravidle, označená jako proxy | časově vymezené ukazatele (horizont) | otevřeno |
| 3 | Co přesně export pokrývá, lze zjistit dobu úplného sledování? | neznámo → počty kontaktů nejsou skórované | umožní ukazatele typu „počet hospitalizací za X“ | otevřeno |
| 4 | Je orientační diagnostická mapa vhodná? Které skupiny neslučovat (C71+C72+D43, C82–C85, C40+C41)? | `dxmap-v1` v `config/diagnosis_groups.csv` | nová verze mapy ⇒ nové `baseline_config_id` | otevřeno |
| 5 | Význam `stage=7`, `extent`, `laterality`, `psu`, `3333/3` a kódů chování `/0`, `/2`? | zobrazeno raw, nepoužito ve výpočtu | lepší popisky, případně vstup do popisu skupin | otevřeno |
| 6 | Existuje ověřený slovník `test_code` a pediatrické referenční meze? | kód · panel · jednotka; dodané meze s upozorněním | srozumitelné laboratorní souhrny | otevřeno |
| 7 | Co má znamenat negativní posouzení: skrytí v seznamu, změna reference, nebo oprava dat? | tři oddělené akce: filtr podle posouzení, lokální reference, navržení vyřazení z globálního výpočtu | úprava výchozích akcí v UI | otevřeno |
| 8 | Pacienti s D43/D48 mají pobyty kódované často C71/D43 – má se jejich péče posuzovat ve skupině (`group_dx_match`)? | výchozí přesná shoda (méně pobytů u těchto pacientů) | změna výchozího pravidla | otevřeno |
| 9 | Jsou hranice reference 8 / 4 pacienti a práh 2,5 rozumné pro klinickou diskusi? | technické heuristiky v `config/defaults.json` | úprava konfigurace | otevřeno |
