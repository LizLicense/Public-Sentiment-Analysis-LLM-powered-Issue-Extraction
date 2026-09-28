#!/usr/bin/env python3
"""Robustness checks behind the report's evaluation and findings. No API calls.

Reads saved predictions and the clean corpus, and writes:
- data/evaluation/llm_comparison_challenge_gpt4o_hybrid/  (hybrid scored on the held-out challenge set)
- data/evaluation/robustness_summary.json:
    * paired bootstrap 95% CIs for the headline F1 differences, per set
    * GPT-4o-mini run-to-run stability on the representative set
    * inter-annotator agreement (Cohen's kappa) per set
    * exploratory rules+GPT-4o union (chosen after seeing results; not adopted)
    * clean-corpus findings with GPT-4o-mini sentiment, including outage-thread checks

Usage (from project root):
  python models/robustness_checks.py
"""

from __future__ import annotations

import csv
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for path in (PROJECT_ROOT, PROJECT_ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import generate_dashboard as dash
from models.llm_evaluation import (
    ISSUE_LABELS,
    SENTIMENT_LABELS,
    classification_metrics,
    multilabel_metrics,
    normalize_issues,
    normalize_sentiment,
    write_csv,
)

EVAL = PROJECT_ROOT / "data/evaluation"
OUT = EVAL / "robustness_summary.json"
# Annotator B's independent relabelling (own notes throughout, new failure-report rule applied).
# Superseded: double_annotation_annotator_b.csv (labels contradicted B's notes and matched A) and
# double_annotation_annotator_b_filled_guide.csv (sentiment revised, other fields still copied).
ANNOTATOR_B = EVAL / "double_annotation_annotator_b_filled2.csv"
BOOTSTRAPS = 2000
SEED = 7
OUTAGE_TITLE = re.compile(r"outage|down\b|disruption|no (?:signal|internet)|still having issues", re.IGNORECASE)


def read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def by_id(path: Path) -> dict[str, dict[str, str]]:
    return {row["sample_id"]: row for row in read(path)}


def sentiment_f1(rows, column) -> float:
    return classification_metrics(
        [normalize_sentiment(r["manual_sentiment"]) for r in rows],
        [normalize_sentiment(r[column]) for r in rows],
        SENTIMENT_LABELS,
    )["macro_f1"]


def issue_metrics(rows, labeller) -> dict:
    return multilabel_metrics(
        [normalize_issues(r["manual_issues"]) for r in rows], [labeller(r) for r in rows], ISSUE_LABELS
    )


def rules(row):
    return normalize_issues(row["rule_issues"])


def llm(row):
    return normalize_issues(row["llm_issues"])


def hybrid(row):
    return llm(row) if rules(row) == ["general_discussion"] else rules(row)


def union(row):
    labels = [x for x in dict.fromkeys(rules(row) + llm(row)) if x != "general_discussion"]
    return labels or ["general_discussion"]


def bootstrap(ids, diff) -> dict[str, float]:
    rng = random.Random(SEED)
    draws = sorted(diff([rng.choice(ids) for _ in ids]) for _ in range(BOOTSTRAPS))
    return {
        "diff": round(diff(ids), 3),
        "ci_low": round(draws[int(0.025 * BOOTSTRAPS)], 3),
        "ci_high": round(draws[int(0.975 * BOOTSTRAPS) - 1], 3),
    }


def kappa(pairs) -> float:
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    left, right = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(left[k] * right[k] for k in left) / n / n
    return (observed - expected) / (1 - expected) if expected < 1 else 1.0


def challenge_hybrid() -> dict:
    rows = read(EVAL / "llm_comparison_challenge_gpt4o/predictions.csv")
    for row in rows:
        row["hybrid_issues"] = ",".join(hybrid(row))
        row["hybrid_used_llm"] = rules(row) == ["general_discussion"]
    out_dir = EVAL / "llm_comparison_challenge_gpt4o_hybrid"
    write_csv(out_dir / "predictions.csv", rows, list(rows[0].keys()))
    used = [r for r in rows if r["hybrid_used_llm"]]
    metrics = {
        "design": "Keyword rules; GPT-4o issue labels only where rules output only general_discussion.",
        "source_predictions": "data/evaluation/llm_comparison_challenge_gpt4o/predictions.csv",
        "n": len(rows),
        "unresolved_general_discussion": len(used),
        "llm_relabeled_from_gd": sum(llm(r) != ["general_discussion"] for r in used),
        "new_api_calls": 0,
        "issues": issue_metrics(rows, hybrid),
    }
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics


def set_comparisons(name, mini_path, gpt4o_path) -> dict:
    mini, gpt4o = by_id(mini_path), by_id(gpt4o_path)
    ids = [i for i in gpt4o if i in mini]
    m = lambda s: [mini[i] for i in s]
    g = lambda s: [gpt4o[i] for i in s]
    issue_f1 = lambda s, fn: issue_metrics(g(s), fn)["macro_f1"]
    scores = {
        "sentiment_macro_f1": {
            "vader": round(sentiment_f1(g(ids), "vader_sentiment"), 3),
            "gpt4o_mini": round(sentiment_f1(m(ids), "llm_sentiment"), 3),
            "gpt4o": round(sentiment_f1(g(ids), "llm_sentiment"), 3),
        },
        "issue_macro_f1": {
            "rules": round(issue_f1(ids, rules), 3),
            "gpt4o_mini_all_posts": round(issue_metrics(m(ids), llm)["macro_f1"], 3),
            "gpt4o_all_posts": round(issue_f1(ids, llm), 3),
            "hybrid": round(issue_f1(ids, hybrid), 3),
            "union_exploratory": round(issue_f1(ids, union), 3),
        },
        "devices_recall": {
            "rules": round(issue_metrics(g(ids), rules)["per_class"]["devices"]["recall"], 3),
            "gpt4o_mini_all_posts": round(issue_metrics(m(ids), llm)["per_class"]["devices"]["recall"], 3),
            "gpt4o_all_posts": round(issue_metrics(g(ids), llm)["per_class"]["devices"]["recall"], 3),
            "hybrid": round(issue_metrics(g(ids), hybrid)["per_class"]["devices"]["recall"], 3),
        },
    }
    scores["bootstrap_95ci"] = {
        "sentiment_mini_minus_vader": bootstrap(ids, lambda s: sentiment_f1(m(s), "llm_sentiment") - sentiment_f1(g(s), "vader_sentiment")),
        "sentiment_mini_minus_gpt4o": bootstrap(ids, lambda s: sentiment_f1(m(s), "llm_sentiment") - sentiment_f1(g(s), "llm_sentiment")),
        "issues_hybrid_minus_rules": bootstrap(ids, lambda s: issue_f1(s, hybrid) - issue_f1(s, rules)),
        "issues_gpt4o_all_minus_rules": bootstrap(ids, lambda s: issue_f1(s, llm) - issue_f1(s, rules)),
        "issues_gpt4o_all_minus_hybrid": bootstrap(ids, lambda s: issue_f1(s, llm) - issue_f1(s, hybrid)),
        "issues_union_minus_hybrid": bootstrap(ids, lambda s: issue_f1(s, union) - issue_f1(s, hybrid)),
    }
    scores["n"] = len(ids)
    scores["set"] = name
    return scores


def stability() -> dict:
    first = by_id(EVAL / "llm_comparison_representative/predictions.csv")
    second = by_id(EVAL / "llm_comparison_representative_rerun/predictions.csv")
    ids = [i for i in first if i in second]
    pairs = [(normalize_sentiment(first[i]["llm_sentiment"]), normalize_sentiment(second[i]["llm_sentiment"])) for i in ids]
    return {
        "model": "gpt-4o-mini-2024-07-18",
        "n": len(ids),
        "sentiment_labels_identical": sum(a == b for a, b in pairs),
        "sentiment_kappa_between_runs": round(kappa(pairs), 3),
        "issue_sets_identical": sum(set(llm(first[i])) == set(llm(second[i])) for i in ids),
        "sentiment_macro_f1_run1": round(sentiment_f1([first[i] for i in ids], "llm_sentiment"), 3),
        "sentiment_macro_f1_run2": round(sentiment_f1([second[i] for i in ids], "llm_sentiment"), 3),
    }


def annotator_agreement() -> dict:
    a = {r["sample_id"]: r for r in read(EVAL / "representative_annotator_a.csv") + read(EVAL / "challenge_annotator_a.csv")}
    out = {}
    for name in ("representative", "challenge"):
        rows = [(a[b["sample_id"]], b) for b in read(ANNOTATOR_B)
                if b["evaluation_set"] == name and b["sample_id"] in a]
        pairs = [(normalize_sentiment(x["sentiment_manual"]), normalize_sentiment(y["sentiment_manual"])) for x, y in rows]
        pairs = [p for p in pairs if all(p)]
        issue_pairs = [(set(normalize_issues(x["issues_manual"])), set(normalize_issues(y["issues_manual"])))
                       for x, y in rows if x["issues_manual"].strip() and y["issues_manual"].strip()]
        out[name] = {
            "overlap_rows": len(rows),
            "sentiment_pairs": len(pairs),
            "sentiment_agreement": round(sum(x == y for x, y in pairs) / len(pairs), 3),
            "sentiment_kappa": round(kappa(pairs), 3),
            "issue_mean_jaccard": round(sum(len(x & y) / len(x | y) for x, y in issue_pairs) / len(issue_pairs), 3),
            "rows_identical_on_all_fields": sum(
                all(x[c].strip().lower() == y[c].strip().lower()
                    for c in ("sentiment_manual", "issues_manual", "telco_targets_manual", "confidence_manual"))
                for x, y in rows
            ),
            "identical_notes": sum(x["notes_manual"].strip() == y["notes_manual"].strip() != "" for x, y in rows),
            "sentiment_confusion_a_rows_b_cols": {
                a_label: dict(Counter(b_label for x, b_label in pairs if x == a_label)) for a_label in SENTIMENT_LABELS
            },
        }
    out["annotator_b_file"] = str(ANNOTATOR_B.relative_to(PROJECT_ROOT))
    out["caveat"] = "B relabelled with its own notes; remaining disagreements are mostly A not_happy vs B neutral."
    return out


V2_CORPUS = PROJECT_ROOT / "data/processed/clean_posts_v2_mini_sentiment.csv"


def corpus_findings(path: Path | None = None, threshold: str = str(dash.HUDDLE_THRESHOLD)) -> dict:
    rows, stats = dash.analyse(path or dash.MINI_CORPUS, EVAL / "representative_annotator_a.csv", threshold)
    outage = {r["thread_key"] for r in rows if OUTAGE_TITLE.search(r["thread_title"])}
    rest = [r for r in rows if r["thread_key"] not in outage]
    pct_nh = lambda sub: dash.pct(sum(r["sentiment_final"] == "not_happy" for r in sub), len(sub))
    by_source = lambda sub: {s: dash.sentiment_pct([r for r in sub if r["source"] == s]) for s in ("reddit", "hwz")}
    brands = {}
    for brand in dash.BRAND_MAP:
        name = brand[1]
        allb = [r for r in rows if name in r["brands"]]
        if len(allb) < dash.MIN_BRAND_MENTIONS:
            continue
        outside = [r for r in rest if name in r["brands"]]
        brands[name] = {
            "posts": len(allb),
            "threads": len({r["thread_key"] for r in allb}),
            "not_happy_pct": pct_nh(allb),
            "not_happy_pct_thread_weighted": dash.shares(allb, "sentiment_final", SENTIMENT_LABELS, True)["not_happy"],
            "posts_outside_outage_threads": len(outside),
            "not_happy_pct_outside_outage_threads": pct_nh(outside) if outside else None,
        }
    issues = {}
    for key in dash.ISSUE_LABELS:
        sub = [r for r in rows if r["issue_final"] == key]
        issues[key] = {
            "posts": len(sub),
            "threads": len({r["thread_key"] for r in sub}),
            "share_per_post": stats["issue_post"][key],
            "share_thread_weighted": stats["issue_thread"][key],
            "not_happy_rate_pct": pct_nh(sub) if sub else None,
            "share_of_not_happy_thread_weighted": stats["unhappy_thread"].get(key, 0),
        }
    vader_happy = [r for r in rows if r["sentiment_vader"] == "happy"]
    return {
        "posts": len(rows),
        "threads": stats["n_threads"],
        "sentiment_gpt4o_mini": stats["sentiment_pct"],
        "sentiment_gpt4o_mini_thread_weighted": dash.shares(rows, "sentiment_final", SENTIMENT_LABELS, True),
        "sentiment_vader_same_posts": stats["vader_pct"],
        "sentiment_human_gold": stats["gold_pct"].get("all"),
        "vader_happy_relabelled_by_mini": dict(Counter(r["sentiment_final"] for r in vader_happy)),
        "outage_threads": len(outage),
        "posts_in_outage_threads": len(rows) - len(rest),
        "sentiment_outside_outage_threads": dash.sentiment_pct(rest),
        "source_sentiment": by_source(rows),
        "source_sentiment_outside_outage_threads": by_source(rest),
        "source_sentiment_human_gold": {s: stats["gold_pct"].get(s) for s in ("reddit", "hwz")},
        "source_years": {s: dict(sorted(Counter(r["time"].year for r in rows if r["source"] == s).items())) for s in ("reddit", "hwz")},
        "brands": brands,
        "issues": issues,
        "action_order": stats["action_order"],
        "weeks_over_threshold": stats["weeks_over"],
        "huddle_rule": stats["huddle_rule"],
        "brand_rank_rule": stats["brand_rank_rule"],
        "posts_without_llm_sentiment": stats["llm_missing"],
        "posts_by_source": {s: sum(r["source"] == s for r in rows) for s in ("reddit", "hwz")},
        "weeks_with_queue_posts": len(stats["weeks"]),
    }


def main() -> None:
    challenge_hybrid()
    summary = {
        "representative": set_comparisons(
            "representative",
            EVAL / "llm_comparison_representative/predictions.csv",
            EVAL / "llm_comparison_representative_gpt4o/predictions.csv",
        ),
        "challenge": set_comparisons(
            "challenge",
            EVAL / "llm_comparison_challenge/predictions.csv",
            EVAL / "llm_comparison_challenge_gpt4o/predictions.csv",
        ),
        "stability": stability(),
        "annotator_agreement": annotator_agreement(),
        "corpus": corpus_findings(),
        "corpus_v2": corpus_findings(V2_CORPUS, "auto") if V2_CORPUS.exists() else None,
        "method": f"Paired bootstrap over posts, {BOOTSTRAPS} resamples, seed {SEED}. Union is exploratory: chosen after seeing results.",
    }
    OUT.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {OUT}")
    print(f"Wrote {EVAL / 'llm_comparison_challenge_gpt4o_hybrid'}/")


if __name__ == "__main__":
    main()
