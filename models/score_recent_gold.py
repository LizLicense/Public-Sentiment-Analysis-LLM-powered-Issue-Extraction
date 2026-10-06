#!/usr/bin/env python3
"""Score the labels used in the findings against the recent-posts gold set. No API calls.

The 100 gold posts were drawn from the v2 corpus, which already holds the production labels:
GPT-4o-mini sentiment (llm_sentiment), VADER (sentiment_label), the hybrid issue labels
(issue_labels: keyword rules, then GPT-4o on unresolved rows) and GPT-4o-mini's all-post issue
labels (llm_issues_reference). Scoring those directly checks the numbers the report uses.

Obvious annotation typos are normalised here and listed in the output; the annotation file is
not modified. Relevant posts with no issue label are left out of issue scoring.

Usage (from project root):
  python models/score_recent_gold.py
"""

from __future__ import annotations

import csv
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from models.llm_evaluation import (  # noqa: E402
    ISSUE_LABELS,
    SENTIMENT_LABELS,
    classification_metrics,
    multilabel_metrics,
    normalize_issues,
    normalize_sentiment,
)
from processing.issue_extraction import detect_issue_labels  # noqa: E402

GOLD = PROJECT_ROOT / "data/evaluation/gold_labels.csv"
GOLD_SET = "recent"
CORPUS = PROJECT_ROOT / "data/processed/corpus_posts_mini_sentiment.csv"
OUT = PROJECT_ROOT / "data/evaluation/recent_gold_scores.json"
SENTIMENT_TYPOS = {"netural": "neutral"}
ISSUE_TYPOS = {"evices": "Devices", "pring & promotions": "Pricing & Promotions"}
BOOTSTRAPS, SEED = 2000, 7


def read(path: Path) -> list[dict]:
    csv.field_size_limit(10**9)
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def key(title: str, text: str) -> tuple[str, str]:
    norm = lambda s: re.sub(r"\s+", " ", s or "").strip().lower()
    return norm(title), norm(text)


def gold_sentiment(value: str, fixes: list) -> str:
    raw = (value or "").strip()
    fixed = SENTIMENT_TYPOS.get(raw.lower(), raw)
    if fixed != raw:
        fixes.append(f"sentiment {raw!r} -> {fixed!r}")
    return normalize_sentiment(fixed)


def gold_issues(value: str, fixes: list) -> list[str]:
    parts = []
    for part in (value or "").split(","):
        raw = part.strip()
        if not raw:
            continue
        fixed = ISSUE_TYPOS.get(raw.lower(), raw)
        if fixed != raw:
            fixes.append(f"issue {raw!r} -> {fixed!r}")
        parts.append(fixed)
    return normalize_issues(",".join(parts)) if parts else []


def bootstrap(n: int, diff) -> dict:
    rng = random.Random(SEED)
    idx = list(range(n))
    draws = sorted(diff([rng.choice(idx) for _ in idx]) for _ in range(BOOTSTRAPS))
    return {"diff": round(diff(idx), 3), "ci_low": round(draws[int(0.025 * BOOTSTRAPS)], 3),
            "ci_high": round(draws[int(0.975 * BOOTSTRAPS) - 1], 3)}


def main() -> None:
    corpus = {key(r["thread_title"], r["post_text"]): r for r in read(CORPUS) if str(r.get("wave", "")).startswith("2")}
    fixes: list[str] = []
    rows, unmatched = [], []
    for g in (r for r in read(GOLD) if r["evaluation_set"] == GOLD_SET):
        c = corpus.get(key(g["thread_title"], g["post_text"]))
        if c is None:
            unmatched.append(g["sample_id"])
            continue
        rows.append({"gold": g, "corpus": c, "fixes_before": len(fixes)})
        rows[-1]["sentiment"] = gold_sentiment(g["sentiment_manual"], fixes)
        rows[-1]["issues"] = gold_issues(g["issues_manual"], fixes)
        rows[-1]["relevant"] = (g["telco_relevance_manual"] or "").strip().lower() == "yes"

    sent = [r for r in rows if r["relevant"] and r["sentiment"]]
    truth = [r["sentiment"] for r in sent]
    mini = [normalize_sentiment(r["corpus"]["llm_sentiment"]) for r in sent]
    vader = [normalize_sentiment(r["corpus"]["sentiment_label"]) for r in sent]
    m_mini = classification_metrics(truth, mini, SENTIMENT_LABELS)
    m_vader = classification_metrics(truth, vader, SENTIMENT_LABELS)
    f1 = lambda y, p, ids: classification_metrics([y[i] for i in ids], [p[i] for i in ids], SENTIMENT_LABELS)["macro_f1"]

    iss = [r for r in rows if r["relevant"] and r["issues"]]
    it = [r["issues"] for r in iss]
    rules = [detect_issue_labels(r["corpus"]["post_text"]) for r in iss]
    hybrid = [normalize_issues(r["corpus"]["issue_labels"]) or ["general_discussion"] for r in iss]
    mini_i = [normalize_issues(r["corpus"]["llm_issues_reference"]) or ["general_discussion"] for r in iss]
    ml = lambda p: multilabel_metrics(it, p, ISSUE_LABELS)
    mf = lambda p, ids: multilabel_metrics([it[i] for i in ids], [p[i] for i in ids], ISSUE_LABELS)["macro_f1"]

    by_source = {}
    for src in ("reddit", "hwz"):
        ids = [i for i, r in enumerate(sent) if r["gold"]["source"] == src]
        by_source[src] = {
            "n": len(ids),
            "mini_macro_f1": round(f1(truth, mini, ids), 3),
            "vader_macro_f1": round(f1(truth, vader, ids), 3),
            "gold_shares": {k: round(100 * sum(truth[i] == k for i in ids) / len(ids)) for k in SENTIMENT_LABELS} if ids else {},
        }

    out = {
        "gold_file": str(GOLD.relative_to(PROJECT_ROOT)),
        "matched": len(rows), "unmatched_sample_ids": unmatched,
        "relevant": sum(r["relevant"] for r in rows),
        "typo_fixes_applied": dict(Counter(fixes)),
        "sentiment": {
            "n": len(sent),
            "gold_shares": {k: round(100 * truth.count(k) / len(truth)) for k in SENTIMENT_LABELS},
            "gpt4o_mini_shares": {k: round(100 * mini.count(k) / len(mini)) for k in SENTIMENT_LABELS},
            "gpt4o_mini": {k: m_mini[k] for k in ("accuracy", "macro_f1", "per_class", "confusion_matrix")},
            "vader": {k: m_vader[k] for k in ("accuracy", "macro_f1", "per_class", "confusion_matrix")},
            "bootstrap_mini_minus_vader": bootstrap(len(sent), lambda ids: f1(truth, mini, ids) - f1(truth, vader, ids)),
            "by_source": by_source,
        },
        "issues": {
            "n": len(iss),
            "excluded_relevant_without_issue_label": [r["gold"]["sample_id"] for r in rows if r["relevant"] and not r["issues"]],
            "rules_macro_f1": round(ml(rules)["macro_f1"], 3),
            "hybrid_macro_f1": round(ml(hybrid)["macro_f1"], 3),
            "gpt4o_mini_all_posts_macro_f1": round(ml(mini_i)["macro_f1"], 3),
            "hybrid_micro_f1": round(ml(hybrid)["micro_f1"], 3),
            "hybrid_per_class_f1": {k: round(v["f1"], 3) for k, v in ml(hybrid)["per_class"].items()},
            "support": {k: v["support"] for k, v in ml(hybrid)["per_class"].items()},
            "bootstrap_hybrid_minus_rules": bootstrap(len(iss), lambda ids: mf(hybrid, ids) - mf(rules, ids)),
        },
        "note": "Scores the production corpus labels (no new API calls). Small n: read per-class values with care.",
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    s, i = out["sentiment"], out["issues"]
    print(f"Matched {out['matched']}/100 gold posts ({out['relevant']} relevant). Typo fixes: {out['typo_fixes_applied']}")
    print(f"Sentiment n={s['n']}: GPT-4o-mini macro F1 {s['gpt4o_mini']['macro_f1']:.3f} (acc {s['gpt4o_mini']['accuracy']:.2f}) "
          f"vs VADER {s['vader']['macro_f1']:.3f} (acc {s['vader']['accuracy']:.2f}); diff CI {s['bootstrap_mini_minus_vader']}")
    print(f"  gold shares {s['gold_shares']} | mini shares {s['gpt4o_mini_shares']}")
    print(f"Issues n={i['n']}: rules {i['rules_macro_f1']} | hybrid {i['hybrid_macro_f1']} | mini all-post {i['gpt4o_mini_all_posts_macro_f1']}; "
          f"hybrid-rules CI {i['bootstrap_hybrid_minus_rules']}")
    print(f"Wrote {OUT.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
