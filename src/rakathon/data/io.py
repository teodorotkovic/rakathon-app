"""Čtení vstupních CSV a výpočet obsahového otisku (fingerprint).

Všechny sloupce se načítají jako text; numerické převody dělá až normalizace
s evidencí chyb. Původní bajty souborů se nemění.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pandas as pd

TABLE_FILES = {"patients": "patients.csv", "episodes": "episodes.csv", "labs": "labs.csv"}


class DatasetFilesMissing(FileNotFoundError):
    def __init__(self, directory: Path, missing: list[str]):
        self.directory = directory
        self.missing = missing
        super().__init__(f"V adresáři {directory} chybí: {', '.join(missing)}")


def fingerprint_files(files: dict[str, bytes]) -> str:
    """SHA-256 přes názvy tabulek a přesný obsah souborů (nezávislé na názvu souboru na disku)."""
    h = hashlib.sha256()
    for name in sorted(files):
        content = files[name]
        h.update(name.encode("utf-8"))
        h.update(len(content).to_bytes(8, "little"))
        h.update(content)
    return h.hexdigest()


def read_dataset_dir(directory: Path) -> dict[str, bytes]:
    missing = [fn for fn in TABLE_FILES.values() if not (directory / fn).is_file()]
    if missing:
        raise DatasetFilesMissing(directory, missing)
    return {name: (directory / fn).read_bytes() for name, fn in TABLE_FILES.items()}


def dataset_dir_available(directory: Path) -> bool:
    return all((directory / fn).is_file() for fn in TABLE_FILES.values())


def match_uploaded_files(uploads: dict[str, bytes]) -> tuple[dict[str, bytes], list[str]]:
    """Přiřadí nahrané soubory k tabulkám podle názvu souboru. Vrací (soubory, chybějící tabulky)."""
    files: dict[str, bytes] = {}
    for filename, content in uploads.items():
        base = Path(filename).name.lower()
        for name, expected in TABLE_FILES.items():
            if base == expected:
                files[name] = content
    missing = [TABLE_FILES[n] for n in TABLE_FILES if n not in files]
    return files, missing


def parse_csv_text(content: bytes) -> pd.DataFrame:
    """Načte CSV jako text. Prázdné buňky zůstávají prázdným řetězcem, ne NaN.

    Vyhazuje UnicodeDecodeError nebo pandas.errors.ParserError – volající je převede
    na blokující chybu validace.
    """
    text = content.decode("utf-8-sig")
    return pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, na_filter=False)


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, lineterminator="\n").encode("utf-8")
