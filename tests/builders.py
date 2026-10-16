"""Malé ručně kontrolovatelné syntetické fixtures (žádná skutečná data)."""

from __future__ import annotations

import pandas as pd
import pytest

from rakathon.configuration import DiagnosisMap, load_diagnosis_map, load_settings
from rakathon.data.dataset import prepare_dataset
from rakathon.data.io import dataframe_to_csv_bytes
from rakathon.data.validation import EPISODE_COLUMNS, LAB_COLUMNS, PATIENT_COLUMNS
from rakathon.domain import AnalysisConfig, BaselineConfig, DatasetBundle, SourceMode


@pytest.fixture(scope="session")
def dxmap() -> DiagnosisMap:
    return load_diagnosis_map(load_settings().diagnosis_map_path)


def patient(pid: str, dx: str = "C91", age: str = "0-5", sex: str = "M", tumor_id: int = 1, **kw) -> dict:
    row = {c: "" for c in PATIENT_COLUMNS}
    row.update(
        patient_id=pid,
        tumor_id=str(tumor_id),
        sex=sex,
        age_group=age,
        dx_icd10=dx,
        topography_icdo3="C42.1",
        morphology_icdo3="9836/3",
        laterality="4",
        grade="9",
        stage="7",
        extent="1",
        deceased="0",
    )
    row.update(kw)
    return row


class EpisodeBuilder:
    """Skládá epizody pacienta v chronologickém pořadí."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self._seq: dict[str, int] = {}

    def add(self, pid: str, start: int, end: int | None, dx: str) -> str:
        self._seq[pid] = self._seq.get(pid, 0) + 1
        eid = f"{pid}-E{self._seq[pid]:03d}"
        self.rows.append(
            {
                "patient_id": pid,
                "episode_id": eid,
                "day_start": str(start),
                "day_end": "" if end is None else str(end),
                "dx_main": dx,
            }
        )
        return eid

    def stays(self, pid: str, dx: str, lengths: list[int], start: int = 10) -> None:
        if pid not in self._seq:
            self.add(pid, 0, 0, "R50")
        day = start
        for los in lengths:
            self.add(pid, day, day + los, dx)
            day += los + 5


def lab(pid: str, day: int, code: str = "00582", value: str = "0.4", episode_id: str = "", **kw) -> dict:
    row = {
        "patient_id": pid,
        "episode_id": episode_id,
        "day": str(day),
        "test_code": code,
        "panel": "biochemistry",
        "value": value,
        "unit": "ukat/l",
        "ref_low": "0.25",
        "ref_high": "0.58",
        "flag": "N",
    }
    row.update(kw)
    return row


def to_files(patients: list[dict], episodes: list[dict], labs: list[dict]) -> dict[str, bytes]:
    return {
        "patients": dataframe_to_csv_bytes(pd.DataFrame(patients, columns=PATIENT_COLUMNS)),
        "episodes": dataframe_to_csv_bytes(pd.DataFrame(episodes, columns=EPISODE_COLUMNS)),
        "labs": dataframe_to_csv_bytes(pd.DataFrame(labs, columns=LAB_COLUMNS)),
    }


def build_bundle(patients, episodes, labs, dxmap, mode=SourceMode.SYNTHETIC) -> DatasetBundle:
    bundle, report = prepare_dataset(to_files(patients, episodes, labs), mode, "test", dxmap)
    assert bundle is not None, report.to_frame().to_string()
    return bundle


def cohort(
    n: int,
    dx: str,
    los: int,
    eb: EpisodeBuilder,
    start_index: int = 1,
    age: str = "0-5",
    sex: str = "M",
    n_stays: int = 3,
) -> list[dict]:
    """n pacientů se stejnou diagnózou a stejnou délkou pobytů."""
    rows = []
    for i in range(start_index, start_index + n):
        pid = f"P{i:04d}"
        rows.append(patient(pid, dx=dx, age=age, sex=sex))
        eb.stays(pid, dx, [los] * n_stays)
    return rows


@pytest.fixture
def baseline_config(dxmap) -> BaselineConfig:
    return BaselineConfig(diagnosis_map_version=dxmap.version, diagnosis_map_hash=dxmap.content_hash)


@pytest.fixture
def analysis_config() -> AnalysisConfig:
    return AnalysisConfig()
