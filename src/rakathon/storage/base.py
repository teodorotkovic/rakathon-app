"""Rozhraní úložiště. Nyní implementováno CSV/JSON (csv_store.py); budoucí SQLite stačí
implementovat stejné metody a vyměnit továrnu v ui/state.py."""

from __future__ import annotations

from typing import Protocol

import pandas as pd

from rakathon.domain import ReviewRecord


class AnnotationStore(Protocol):
    def append_review(self, record: ReviewRecord) -> None: ...

    def load_reviews(self) -> pd.DataFrame: ...

    def save_view(self, row: dict[str, str]) -> None: ...

    def load_views(self) -> pd.DataFrame: ...

    def save_extra(self, extra: pd.DataFrame, meta: pd.DataFrame) -> None: ...

    def load_extra(self) -> tuple[pd.DataFrame | None, pd.DataFrame | None]: ...

    def delete_extra(self) -> None: ...
