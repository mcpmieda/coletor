#!/usr/bin/env python3
"""Materialize a reproducible synthetic diary, never a real student report."""
from pathlib import Path
import argparse
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from coletor.demo import build_fixture, SLOT_STYLE

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "fixtures/annual-synthetic.html")
    parser.add_argument("--year", type=int, default=2026)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_fixture(year=args.year), encoding="utf-8")
    print("Synthetic fixture generated. No real student data was used.")

if __name__ == "__main__":
    main()
