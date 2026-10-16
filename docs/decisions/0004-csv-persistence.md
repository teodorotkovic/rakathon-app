# 0004 – CSV/JSON úložiště v runtime/

**Datum:** 2026-10-16 · **Stav:** přijato

**Rozhodnutí:** Posouzení (append-only log s `supersedes`), uložené pohledy a doplňkové vlastnosti se ukládají
do `runtime/<real|synthetic>/<fingerprint[:16]>/` jako CSV/JSON. Zápis přes dočasný soubor + `os.replace`,
read-modify-write pod zámkem na soubor (vlákna jednoho procesu).

**Režim souběhu:** jeden proces Streamlitu, jeden aktivní zapisující uživatel. Více procesů vyžaduje souborový
zámek nebo SQLite (rozhraní `storage/base.AnnotationStore`, úkol T10).

**Důsledky:** anotace jsou svázané s obsahem datasetu; „aktuální“ posouzení = shodný otisk + `baseline_config_id`;
ostatní jsou historie. Kanonický text komentářů se neupravuje; ochrana proti vzorcům jen v exportu.
