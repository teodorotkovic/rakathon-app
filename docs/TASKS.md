# Úkoly

Stav: `todo` / `doing` / `done`. Vlastník: role z AGENTS.md §9 (data, UI, integrace). Hotovo = kritérium splněno
a ověřeno.

| ID | Priorita | Úkol | Závisí na | Vlastník | Stav | Hotovo když |
|---|---|---|---|---|---|---|
| T01 | P0 | Ruční průchod checklistem `docs/demo.md` v prohlížeči | – | UI | todo | všechny body zaškrtnuté, vady zapsané |
| T02 | P0 | Konzultace s mentorem (otázky 1, 4, 8) a zápis odpovědí | – | integrace | todo | `mentor-questions.md` aktualizováno, případná nová verze pravidla/mapy |
| T03 | P0 | Připravit 3–5min demo na syntetice podle `docs/demo.md` | T01 | integrace | todo | nacvičeno, export otevřen |
| T04 | P1 | `models/regression.py`: Ridge nad log1p (dx skupina, věk, pohlaví), LOO, encoding uvnitř foldu, rozklad příspěvků | – | data | todo | test LOO invariantu + vysvětlení ze stejného fitu; přepínač metody v globální konfiguraci |
| T05 | P1 | Isolation Forest nad rezidui jako alternativní lokální metoda (seed, směr skóre) | – | data | todo | `AnalysisConfig.method`, test determinismu, popis v metodice |
| T06 | P1 | Bootstrap stability označení (resampling pacientů) | – | data | todo | interval mediánu jasně odlišen od intervalu výsledku |
| T07 | P1 | PCA orientační projekce (ne zdroj skóre) | – | UI | todo | graf s upozorněním na zkreslení |
| T08 | P1 | Ukazatel D70/infekcí jako samostatný modul se srovnatelným pozorováním | T02 (odpověď 3) | data | todo | definice + hodnotitelnost + test |
| T09 | P2 | Ověřený slovník laboratorních testů (soubor se zdrojem) | odpověď 6 | data | todo | názvy jen ze zdroje |
| T10 | P2 | Souborový zámek / SQLite úložiště pro více procesů | – | integrace | todo | implementace `storage/base.AnnotationStore` + test souběhu |
| T11 | P2 | Import uložených komentářů/pohledů s kontrolou verze a otisku | – | integrace | todo | test odmítnutí cizího otisku |
