"""Lokální CSV úložiště posouzení, uložených pohledů a doplňkových vlastností.

Adresář: <runtime>/<source_mode>/<dataset_fingerprint[:16]>/ – anotace jsou svázány
s obsahem datasetu.

Režim souběhu: jeden proces Streamlitu, jeden aktivní zapisující uživatel. Uvnitř
procesu serializuje read-modify-write zámek na soubor; zápis jde přes dočasný
soubor a atomické os.replace. Více procesů by vyžadovalo souborový zámek nebo
jiné úložiště.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from rakathon.data.io import parse_csv_text
from rakathon.domain import REVIEW_COLUMNS, ReviewRecord, ReviewStatus

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()

VIEW_COLUMNS = [
    "view_id",
    "name",
    "created_at",
    "dataset_fingerprint",
    "source_mode",
    "baseline_config_id",
    "analysis_id",
    "feature_schema_version",
    "method_version",
    "baseline_config_json",
    "analysis_config_json",
    "note",
]


def _lock_for(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        if key not in _LOCKS:
            _LOCKS[key] = threading.Lock()
        return _LOCKS[key]


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _write_csv(path: Path, df: pd.DataFrame) -> None:
    atomic_write_bytes(path, df.to_csv(index=False, lineterminator="\n").encode("utf-8"))


def _read_csv(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame(columns=columns)
    df = parse_csv_text(path.read_bytes())
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    return df[columns + [c for c in df.columns if c not in columns]]


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class CsvStore:
    def __init__(self, runtime_dir: Path, source_mode: str, dataset_fingerprint: str):
        self.dataset_fingerprint = dataset_fingerprint
        self.source_mode = source_mode
        self.dir = Path(runtime_dir) / source_mode / dataset_fingerprint[:16]
        self.reviews_path = self.dir / "reviews.csv"
        self.views_path = self.dir / "analysis_views.csv"
        self.extra_path = self.dir / "extra_features.csv"
        self.extra_meta_path = self.dir / "extra_features_meta.json"
        self.dataset_path = self.dir / "dataset.json"

    def _ensure_dataset_marker(self) -> None:
        if not self.dataset_path.is_file():
            atomic_write_bytes(
                self.dataset_path,
                json.dumps(
                    {
                        "dataset_fingerprint": self.dataset_fingerprint,
                        "source_mode": self.source_mode,
                        "created_at": now_iso(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ).encode("utf-8"),
            )

    # --- posouzení ---------------------------------------------------------
    def append_review(self, record: ReviewRecord) -> None:
        if record.dataset_fingerprint != self.dataset_fingerprint:
            raise ValueError("Posouzení patří jinému datasetu.")
        with _lock_for(self.reviews_path):
            self._ensure_dataset_marker()
            df = _read_csv(self.reviews_path, REVIEW_COLUMNS)
            df = pd.concat([df, pd.DataFrame([record.to_row()])], ignore_index=True)
            _write_csv(self.reviews_path, df[REVIEW_COLUMNS])

    def load_reviews(self) -> pd.DataFrame:
        df = _read_csv(self.reviews_path, REVIEW_COLUMNS)
        # Pojistka: záznamy jiného datasetu se nikdy nevrací jako platné.
        return df[df["dataset_fingerprint"] == self.dataset_fingerprint].reset_index(drop=True)

    # --- uložené pohledy -----------------------------------------------------
    def save_view(self, row: dict[str, str]) -> None:
        with _lock_for(self.views_path):
            self._ensure_dataset_marker()
            df = _read_csv(self.views_path, VIEW_COLUMNS)
            df = pd.concat(
                [df, pd.DataFrame([{c: str(row.get(c, "")) for c in VIEW_COLUMNS}])], ignore_index=True
            )
            _write_csv(self.views_path, df[VIEW_COLUMNS])

    def load_views(self) -> pd.DataFrame:
        df = _read_csv(self.views_path, VIEW_COLUMNS)
        return df[df["dataset_fingerprint"] == self.dataset_fingerprint].reset_index(drop=True)

    # --- doplňkové vlastnosti ------------------------------------------------
    def save_extra(self, extra: pd.DataFrame, meta: pd.DataFrame) -> None:
        with _lock_for(self.extra_path):
            self._ensure_dataset_marker()
            _write_csv(self.extra_path, extra.astype(str))
            atomic_write_bytes(
                self.extra_meta_path,
                json.dumps(
                    {
                        "dataset_fingerprint": self.dataset_fingerprint,
                        "saved_at": now_iso(),
                        "columns": meta.to_dict(orient="records"),
                    },
                    ensure_ascii=False,
                    indent=2,
                ).encode("utf-8"),
            )

    def load_extra(self) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
        if not (self.extra_path.is_file() and self.extra_meta_path.is_file()):
            return None, None
        meta_doc = json.loads(self.extra_meta_path.read_text(encoding="utf-8"))
        if meta_doc.get("dataset_fingerprint") != self.dataset_fingerprint:
            return None, None
        extra = parse_csv_text(self.extra_path.read_bytes())
        return extra, pd.DataFrame(meta_doc["columns"])

    def delete_extra(self) -> None:
        with _lock_for(self.extra_path):
            for p in (self.extra_path, self.extra_meta_path):
                if p.is_file():
                    p.unlink()


# ---------------------------------------------------------------------------
# Logika posouzení (čisté funkce)
# ---------------------------------------------------------------------------


def make_review(
    *,
    dataset_fingerprint: str,
    source_mode: str,
    patient_id: str,
    baseline_config_id: str,
    analysis_id: str,
    analysis_label: str,
    status: ReviewStatus,
    comment: str,
    reviewer: str,
    supersedes: str = "",
) -> ReviewRecord:
    return ReviewRecord(
        record_id=uuid.uuid4().hex,
        dataset_fingerprint=dataset_fingerprint,
        source_mode=source_mode,
        patient_id=patient_id,
        baseline_config_id=baseline_config_id,
        analysis_id=analysis_id,
        analysis_label=analysis_label,
        status=status.value,
        comment=comment,
        reviewer=reviewer.strip(),
        created_at=now_iso(),
        supersedes=supersedes,
    )


def current_reviews(reviews: pd.DataFrame, dataset_fingerprint: str, baseline_config_id: str) -> pd.DataFrame:
    """Poslední posouzení na pacienta platné pro daný dataset a globální kontext (cíl + model)."""
    if reviews.empty:
        return reviews.copy()
    ok = (reviews["dataset_fingerprint"] == dataset_fingerprint) & (
        reviews["baseline_config_id"] == baseline_config_id
    )
    cur = reviews[ok].reset_index().sort_values(["created_at", "index"])
    return cur.drop_duplicates("patient_id", keep="last").drop(columns="index").reset_index(drop=True)


def split_history(
    reviews: pd.DataFrame, patient_id: str, dataset_fingerprint: str, baseline_config_id: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(historie v aktuálním kontextu, posouzení z jiných kontextů – historická)."""
    mine = reviews[reviews["patient_id"] == patient_id]
    ok = (mine["dataset_fingerprint"] == dataset_fingerprint) & (
        mine["baseline_config_id"] == baseline_config_id
    )
    return (
        mine[ok].sort_values("created_at", ascending=False),
        mine[~ok].sort_values("created_at", ascending=False),
    )
