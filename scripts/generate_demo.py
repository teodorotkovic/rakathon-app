"""Zapíše syntetický demonstrační dataset (pevný seed) do adresáře.

Použití:  python -m uv run python scripts/generate_demo.py [--out runtime/synthetic_demo] [--seed 20261017]
Výstup: patients.csv, episodes.csv, labs.csv (nahratelné v aplikaci) a truth.csv (jen pro testy –
aplikace ji nikdy nečte).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rakathon.configuration import load_settings
from rakathon.data.demo import DEFAULT_SEED, generate_synthetic


def main() -> None:
    s = load_settings()
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=s.runtime_dir / "synthetic_demo")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = ap.parse_args()
    syn = generate_synthetic(args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, content in syn.files.items():
        (args.out / f"{name}.csv").write_bytes(content)
    syn.truth.to_csv(args.out / "truth.csv", index=False)
    print(
        f"Syntetická data (seed {args.seed}) zapsána do {args.out}: "
        f"{syn.patients['patient_id'].nunique()} pacientů, {len(syn.episodes)} epizod, {len(syn.labs)} lab. výsledků."
    )


if __name__ == "__main__":
    main()
