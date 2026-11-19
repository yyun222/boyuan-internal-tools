"""Randomized bilingual homepage facts from the bundled local catalog."""

import csv
from pathlib import Path
from random import sample

_CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "home_facts.tsv"

with _CATALOG_PATH.open(encoding="utf-8", newline="") as stream:
    FACTS = tuple(csv.DictReader(stream, delimiter="\t"))


def select_home_facts() -> list[dict[str, str]]:
    return [fact.copy() for fact in sample(FACTS, k=10)]
