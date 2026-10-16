"""Profil vstupních CSV. Výstup jde do ignorovaného runtime/profile/ – NEcommitovat.

Použití:  python -m uv run python scripts/profile_data.py [--data-dir data] [--out runtime/profile]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from rakathon.configuration import load_diagnosis_map, load_settings
from rakathon.data.dataset import prepare_dataset
from rakathon.data.io import read_dataset_dir
from rakathon.domain import SourceMode


def main() -> None:
    s = load_settings()
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=s.data_dir)
    ap.add_argument("--out", type=Path, default=s.runtime_dir / "profile")
    args = ap.parse_args()
    dx = load_diagnosis_map(s.diagnosis_map_path)
    bundle, report = prepare_dataset(read_dataset_dir(args.data_dir), SourceMode.REAL, str(args.data_dir), dx)
    args.out.mkdir(parents=True, exist_ok=True)
    report.to_frame().to_csv(args.out / "validation_report.csv", index=False)
    if bundle is None:
        print("Dataset neprošel validací – viz validation_report.csv")
        return

    lines = [f"# Profil datasetu {bundle.short_fingerprint}", ""]
    for name, df in bundle.raw.items():
        lines.append(f"## {name}: {len(df)} řádků, {df['patient_id'].nunique()} pacientů")
        prof = pd.DataFrame(
            {
                "column": df.columns,
                "empty": [(df[c] == "").sum() for c in df.columns],
                "unique": [df[c].nunique() for c in df.columns],
            }
        )
        prof.to_csv(args.out / f"columns_{name}.csv", index=False)
        lines.append(prof.to_string(index=False))
        lines.append("")
    e = bundle.episodes
    lines.append("## Třídy epizod")
    lines.append(e["episode_class"].value_counts().to_string())
    lines.append("")
    lines.append("## Počet nádorů na pacienta")
    lines.append(bundle.patients.groupby("patient_id").size().value_counts().to_string())
    lines.append("")
    lines.append("## Laboratoře – vazba na epizodu")
    lines.append(bundle.labs["episode_link"].value_counts().to_string())
    for col in ("dx_icd10", "stage", "grade", "extent", "laterality", "age_group", "sex"):
        bundle.patients[col].value_counts().rename_axis(col).reset_index().to_csv(
            args.out / f"values_{col}.csv", index=False
        )
    (args.out / "profile.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Profil zapsán do {args.out} (ignorováno Gitem).")


if __name__ == "__main__":
    main()
