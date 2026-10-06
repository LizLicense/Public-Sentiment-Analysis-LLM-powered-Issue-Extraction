#!/usr/bin/env python3
"""Combine Annotator A's three gold sheets into one file: data/evaluation/gold_labels.csv.

  representative  representative_annotator_a.csv  300 posts (295 telco-relevant); headline metrics
  challenge       challenge_annotator_a.csv       100 hard posts; reported separately
  recent          recent_annotator_a.csv          100 posts from 10 Apr-26 Sep 2026 (97 relevant)

The sets were sampled differently, so score each evaluation_set on its own; never pool them.
Labels are copied verbatim (no typo fixes; the scorers normalise those). Recent sample IDs are
renamed W2-nnnn -> REC-nnnn; the `sheet` column names the file each row came from. The three
sheets stay as the original annotation record and are never modified here.

Usage (from project root):
  python processing/build_gold_labels.py
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1] / "data/evaluation"
OUT = EVAL / "gold_labels.csv"
SHEETS = [
    ("representative", "representative_annotator_a.csv"),
    ("challenge", "challenge_annotator_a.csv"),
    ("recent", "recent_annotator_a.csv"),
]
FIELDS = [
    "sample_id", "evaluation_set", "source", "thread_title", "post_text",
    "telco_relevance_manual", "telco_targets_manual", "sentiment_manual",
    "issues_manual", "confidence_manual", "notes_manual", "sheet",
]


def main() -> None:
    csv.field_size_limit(10**9)
    rows = []
    for name, sheet in SHEETS:
        with (EVAL / sheet).open(newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                sample_id = r["sample_id"].replace("W2-", "REC-", 1) if name == "recent" else r["sample_id"]
                rows.append({**{f: r.get(f, "") for f in FIELDS}, "sample_id": sample_id,
                             "evaluation_set": name, "sheet": sheet})
    ids = Counter(r["sample_id"] for r in rows)
    dupes = [k for k, n in ids.items() if n > 1]
    if dupes:
        raise SystemExit(f"Duplicate sample IDs across sheets: {dupes[:5]}")
    with OUT.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {OUT.relative_to(EVAL.parents[1])}: {len(rows)} rows "
          f"{dict(Counter(r['evaluation_set'] for r in rows))}")


if __name__ == "__main__":
    main()
