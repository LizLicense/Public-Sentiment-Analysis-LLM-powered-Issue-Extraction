#!/usr/bin/env python3
"""Create blind, thread-disjoint annotation sets for model evaluation.

Outputs:
1. A representative, source-stratified sample for primary metrics.
2. A separate challenge sample for contextual error analysis.
3. A blinded overlap sheet for a second annotator.
4. Sampling metadata needed to describe the evaluation reproducibly.

Model labels, scores, usernames, URLs, and engagement fields are deliberately
excluded from every annotation file.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


DEFAULT_INPUT = Path("data/processed/posts_labeled_2026-04-09_221819.csv")
DEFAULT_OUTPUT_DIR = Path("data/evaluation")
VALID_SOURCES = ("reddit", "hwz")

OUTPUT_FIELDS = [
    "sample_id",
    "evaluation_set",
    "source",
    "thread_title",
    "post_text",
    "telco_relevance_manual",
    "telco_targets_manual",
    "sentiment_manual",
    "issues_manual",
    "confidence_manual",
    "notes_manual",
]

NEGATION_RE = re.compile(
    r"\b(no|not|never|neither|without|cannot|can't|don't|doesn't|didn't|won't|isn't|aren't)\b",
    re.IGNORECASE,
)
CONTRAST_RE = re.compile(
    r"\b(but|however|although|though|yet|except|despite|on the other hand)\b",
    re.IGNORECASE,
)
LOCAL_OR_SARCASM_RE = re.compile(
    r"\b(lah|leh|lor|sia|sian|walao|lol|lmao|yeah right|as if|sure|thanks ah)\b|"
    r"[😂🤣🙃🤡💀]",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create blind representative and challenge annotation sets."
    )
    parser.add_argument(
        "--in",
        dest="input_path",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Labeled corpus used only for sampling (default: {DEFAULT_INPUT}).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--representative-size",
        type=int,
        default=300,
        help="Size of the primary representative set (default: 300).",
    )
    parser.add_argument(
        "--challenge-size",
        type=int,
        default=100,
        help="Size of the separate difficult-case set (default: 100).",
    )
    parser.add_argument(
        "--double-size",
        type=int,
        default=100,
        help="Rows independently labeled by a second annotator (default: 100).",
    )
    parser.add_argument(
        "--min-per-source",
        type=int,
        default=50,
        help="Minimum representative rows per available source (default: 50).",
    )
    parser.add_argument(
        "--max-per-thread",
        type=int,
        default=5,
        help="Maximum sampled comments from one thread in each set (default: 5).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20260813,
        help="Random seed (default: 20260813).",
    )
    return parser.parse_args()


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def thread_key(row: dict[str, str]) -> str:
    source = normalize_text(row.get("source", "")).lower() or "unknown"
    title = normalize_text(row.get("thread_title") or row.get("title") or "")
    post_id = normalize_text(row.get("post_id", ""))
    thread_url = normalize_text(row.get("thread_url") or row.get("permalink") or "")
    identity = title or post_id or thread_url or normalize_text(row.get("post_text", ""))
    return f"{source}:{stable_hash(identity.lower())}"


def prepare_candidates(rows: Iterable[dict[str, str]]) -> tuple[list[dict[str, str]], dict]:
    candidates: list[dict[str, str]] = []
    seen_text: set[str] = set()
    exclusions = Counter()

    for row in rows:
        source = normalize_text(row.get("source", "")).lower()
        text = normalize_text(row.get("post_text") or row.get("selftext") or "")
        title = normalize_text(row.get("thread_title") or row.get("title") or "")
        telco_label = normalize_text(row.get("telco_label", ""))

        if source not in VALID_SOURCES:
            exclusions["unsupported_source"] += 1
            continue
        if not telco_label:
            exclusions["no_detected_telco"] += 1
            continue
        if len(text) < 20:
            exclusions["too_short"] += 1
            continue

        text_key = stable_hash(text.lower())
        if text_key in seen_text:
            exclusions["duplicate_text"] += 1
            continue
        seen_text.add(text_key)

        candidate = dict(row)
        candidate["_source"] = source
        candidate["_text"] = text
        candidate["_title"] = title
        candidate["_thread_key"] = thread_key(row)
        candidates.append(candidate)

    metadata = {
        "eligible_rows": len(candidates),
        "eligible_by_source": dict(Counter(r["_source"] for r in candidates)),
        "excluded_rows": dict(exclusions),
    }
    return candidates, metadata


def group_by_thread(
    rows: Iterable[dict[str, str]],
) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row["_thread_key"]].append(row)
    return grouped


def capped_thread_rows(
    groups: Iterable[list[dict[str, str]]],
    maximum: int,
    rng: random.Random,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for group in groups:
        rows.extend(rng.sample(group, min(maximum, len(group))))
    rng.shuffle(rows)
    return rows


def split_threads(
    grouped: dict[str, list[dict[str, str]]],
    rng: random.Random,
    challenge_fraction: float = 0.25,
) -> tuple[list[list[dict[str, str]]], list[list[dict[str, str]]]]:
    by_source: dict[str, list[list[dict[str, str]]]] = defaultdict(list)
    for group in grouped.values():
        by_source[group[0]["_source"]].append(group)

    representative_groups: list[list[dict[str, str]]] = []
    challenge_groups: list[list[dict[str, str]]] = []
    for groups in by_source.values():
        shuffled = list(groups)
        rng.shuffle(shuffled)
        challenge_count = max(1, round(len(shuffled) * challenge_fraction))
        challenge_groups.extend(shuffled[:challenge_count])
        representative_groups.extend(shuffled[challenge_count:])

    rng.shuffle(representative_groups)
    rng.shuffle(challenge_groups)
    return representative_groups, challenge_groups


def source_allocation(
    rows: list[dict[str, str]],
    requested_size: int,
    minimum: int,
) -> dict[str, int]:
    counts = Counter(r["_source"] for r in rows)
    sources = [source for source in VALID_SOURCES if counts[source]]
    if not sources:
        return {}

    size = min(requested_size, sum(counts.values()))
    allocation = {
        source: min(counts[source], round(size * counts[source] / sum(counts.values())))
        for source in sources
    }

    if len(sources) > 1:
        for source in sources:
            needed = min(minimum, counts[source]) - allocation[source]
            if needed <= 0:
                continue
            donors = sorted(
                (s for s in sources if s != source),
                key=lambda s: allocation[s],
                reverse=True,
            )
            for donor in donors:
                transferable = max(0, allocation[donor] - min(minimum, counts[donor]))
                moved = min(needed, transferable)
                allocation[donor] -= moved
                allocation[source] += moved
                needed -= moved
                if needed == 0:
                    break

    difference = size - sum(allocation.values())
    while difference:
        if difference > 0:
            options = [s for s in sources if allocation[s] < counts[s]]
            if not options:
                break
            source = max(options, key=lambda s: counts[s] - allocation[s])
            allocation[source] += 1
            difference -= 1
        else:
            options = [s for s in sources if allocation[s] > 0]
            if not options:
                break
            source = max(options, key=lambda s: allocation[s])
            allocation[source] -= 1
            difference += 1

    return allocation


def stratified_sample(
    rows: list[dict[str, str]],
    allocation: dict[str, int],
    rng: random.Random,
) -> list[dict[str, str]]:
    by_source: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_source[row["_source"]].append(row)

    sample: list[dict[str, str]] = []
    for source, size in allocation.items():
        sample.extend(rng.sample(by_source[source], min(size, len(by_source[source]))))
    rng.shuffle(sample)
    return sample


def difficulty_score(row: dict[str, str]) -> int:
    text = row["_text"]
    score = 0

    try:
        vader_score = abs(float(row.get("sentiment_score", "")))
        if vader_score <= 0.20:
            score += 3
    except (TypeError, ValueError):
        pass

    if NEGATION_RE.search(text):
        score += 2
    if CONTRAST_RE.search(text):
        score += 2
    if LOCAL_OR_SARCASM_RE.search(text):
        score += 3
    if "?" in text:
        score += 1
    if len(text) >= 400:
        score += 1
    if "," in normalize_text(row.get("telco_label", "")):
        score += 2
    return score


def challenge_sample(
    rows: list[dict[str, str]],
    size: int,
    rng: random.Random,
) -> list[dict[str, str]]:
    scored = [(difficulty_score(row), rng.random(), row) for row in rows]
    difficult = [item for item in scored if item[0] >= 2]
    difficult.sort(key=lambda item: (-item[0], item[1]))

    pool_size = min(len(difficult), max(size * 3, size))
    pool = [item[2] for item in difficult[:pool_size]]
    if len(pool) < size:
        used = {id(row) for row in pool}
        pool.extend(item[2] for item in scored if id(item[2]) not in used)

    by_source = Counter(row["_source"] for row in pool)
    minimum = min(20, size // max(1, len(by_source)))
    allocation = source_allocation(pool, size, minimum)
    return stratified_sample(pool, allocation, rng)


def annotation_rows(
    rows: Iterable[dict[str, str]],
    prefix: str,
    set_name: str,
) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for index, row in enumerate(rows, start=1):
        output.append(
            {
                "sample_id": f"{prefix}-{index:04d}",
                "evaluation_set": set_name,
                "source": row["_source"],
                "thread_title": row["_title"],
                "post_text": row["_text"],
                "telco_relevance_manual": "",
                "telco_targets_manual": "",
                "sentiment_manual": "",
                "issues_manual": "",
                "confidence_manual": "",
                "notes_manual": "",
            }
        )
    return output


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_metadata(path: Path, metadata: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=False)


def main() -> None:
    args = parse_args()
    if min(
        args.representative_size,
        args.challenge_size,
        args.double_size,
        args.min_per_source,
    ) < 0:
        raise ValueError("Sample sizes and source minimums must be non-negative.")
    if args.max_per_thread <= 0:
        raise ValueError("--max-per-thread must be greater than zero.")

    rng = random.Random(args.seed)
    raw_rows = read_rows(args.input_path)
    candidates, metadata = prepare_candidates(raw_rows)
    grouped = group_by_thread(candidates)
    representative_groups, challenge_groups = split_threads(grouped, rng)
    representative_pool = capped_thread_rows(
        representative_groups,
        args.max_per_thread,
        rng,
    )
    challenge_pool = capped_thread_rows(
        challenge_groups,
        args.max_per_thread,
        rng,
    )

    representative_allocation = source_allocation(
        representative_pool,
        args.representative_size,
        args.min_per_source,
    )
    representative_source_rows = stratified_sample(
        representative_pool,
        representative_allocation,
        rng,
    )
    challenge_source_rows = challenge_sample(
        challenge_pool,
        min(args.challenge_size, len(challenge_pool)),
        rng,
    )

    representative = annotation_rows(
        representative_source_rows,
        "REP",
        "representative",
    )
    challenge = annotation_rows(challenge_source_rows, "CHL", "challenge")

    overlap_rep_size = min(len(representative), round(args.double_size * 0.6))
    overlap_challenge_size = min(
        len(challenge),
        args.double_size - overlap_rep_size,
    )
    overlap = (
        rng.sample(representative, overlap_rep_size)
        + rng.sample(challenge, overlap_challenge_size)
    )
    rng.shuffle(overlap)

    out_dir = args.out_dir
    write_csv(out_dir / "representative_annotator_a.csv", representative)
    write_csv(out_dir / "challenge_annotator_a.csv", challenge)
    write_csv(out_dir / "double_annotation_annotator_b.csv", overlap)

    source_population = Counter(row["_source"] for row in candidates)
    source_sample = Counter(row["source"] for row in representative)
    metadata.update(
        {
            "input_path": str(args.input_path),
            "seed": args.seed,
            "raw_rows": len(raw_rows),
            "unique_eligible_threads": len(grouped),
            "representative_threads_available": len(representative_groups),
            "challenge_threads_reserved": len(challenge_groups),
            "max_rows_per_thread": args.max_per_thread,
            "representative_size": len(representative),
            "representative_by_source": dict(source_sample),
            "representative_source_allocation": representative_allocation,
            "source_sampling_weights": {
                source: source_population[source] / source_sample[source]
                for source in source_sample
                if source_sample[source]
            },
            "challenge_size": len(challenge),
            "challenge_by_source": dict(
                Counter(row["source"] for row in challenge)
            ),
            "double_annotation_size": len(overlap),
            "double_annotation_mix": {
                "representative": overlap_rep_size,
                "challenge": overlap_challenge_size,
            },
            "model_fields_excluded": [
                "telco_label",
                "sentiment_label",
                "sentiment_score",
                "llm_sentiment_label",
                "issue_labels",
                "issue_primary",
            ],
        }
    )
    write_metadata(out_dir / "sampling_metadata.json", metadata)

    print(f"Input rows: {len(raw_rows)}")
    print(f"Unique eligible threads: {len(grouped)}")
    print(
        f"Thread split: {len(representative_groups)} representative / "
        f"{len(challenge_groups)} challenge"
    )
    print(
        "Representative set: "
        f"{len(representative)} {dict(Counter(r['source'] for r in representative))}"
    )
    print(
        "Challenge set: "
        f"{len(challenge)} {dict(Counter(r['source'] for r in challenge))}"
    )
    print(f"Double-annotation overlap: {len(overlap)}")
    print(f"Saved blind annotation files to: {out_dir}")


if __name__ == "__main__":
    main()
