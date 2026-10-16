#!/usr/bin/env python3
"""Score every method on the merged representative gold set. No API calls.

Merged set = representative sheet (295 telco-relevant, posts to 9 Apr 2026) + recent sheet (97 relevant,
posts 10 Apr-26 Sep 2026), so the headline numbers cover the whole collection period. The challenge set
stays separate (held out). Sources:
  * representative: llm_comparison_representative[_gpt4o][_hybrid]/predictions.csv (evaluation runs)
  * recent: production labels in corpus_posts_mini_sentiment.csv (GPT-4o-mini sentiment, hybrid issues,
    rules recomputed) plus llm_comparison_recent_gpt4o/predictions.csv (GPT-4o on 93 posts with issue labels)
GPT-4o rows and every comparison with GPT-4o use only the posts GPT-4o labelled (295 + 93).
Also reports human-vs-human and model-vs-human kappa on the annotator-B overlap.

Usage (from project root):  python models/score_merged_gold.py
"""

from __future__ import annotations

import csv
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from models.llm_evaluation import (ISSUE_LABELS, SENTIMENT_LABELS, classification_metrics,  # noqa: E402
                                   multilabel_metrics, normalize_issues, normalize_sentiment)
from models.robustness_checks import ANNOTATOR_B, kappa  # noqa: E402
from processing.issue_extraction import detect_issue_labels  # noqa: E402

EVAL = ROOT / "data/evaluation"
OUT = EVAL / "merged_gold_scores.json"
GD = ["general_discussion"]
ISSUE_TYPOS = {"evices": "Devices", "pring & promotions": "Pricing & Promotions"}
BOOTSTRAPS, SEED = 2000, 7
csv.field_size_limit(10**9)


def read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def boot(rows, f) -> dict:
    rng = random.Random(SEED)
    n = len(rows)
    draws = sorted(f([rows[rng.randrange(n)] for _ in range(n)]) for _ in range(BOOTSTRAPS))
    return {"diff": round(f(rows), 3), "ci_low": round(draws[int(0.025 * BOOTSTRAPS)], 3),
            "ci_high": round(draws[int(0.975 * BOOTSTRAPS) - 1], 3)}


def posts() -> list[dict]:
    """One record per relevant gold post: gold labels plus each method's labels (None = not run)."""
    pred = lambda sub: {r["sample_id"]: r for r in read(EVAL / sub / "predictions.csv")}
    rep, g4, hyb = pred("llm_comparison_representative"), pred("llm_comparison_representative_gpt4o"), \
        pred("llm_comparison_representative_gpt4o_hybrid")
    out = []
    for sid, r in rep.items():
        g, h = g4.get(sid), hyb.get(sid)
        out.append({"id": sid, "set": "representative", "gs": normalize_sentiment(r["manual_sentiment"]),
                    "gi": normalize_issues(r["manual_issues"]),
                    "mini_s": normalize_sentiment(r["llm_sentiment"]), "vader_s": normalize_sentiment(r["vader_sentiment"]),
                    "g4_s": normalize_sentiment(g["llm_sentiment"]) if g else None,
                    "rules": normalize_issues(r["rule_issues"]) or GD, "mini_i": normalize_issues(r["llm_issues"]) or GD,
                    "g4_i": (normalize_issues(g["llm_issues"]) or GD) if g else None,
                    "hyb": (normalize_issues(h["hybrid_issues"]) or GD) if h else None})
    corpus = {(norm(r["thread_title"]), norm(r["post_text"])): r
              for r in read(ROOT / "data/processed/corpus_posts_mini_sentiment.csv") if str(r.get("wave", "")).startswith("2")}
    g4r = pred("llm_comparison_recent_gpt4o")
    for gl in (r for r in read(EVAL / "gold_labels.csv") if r["evaluation_set"] == "recent"):
        c = corpus.get((norm(gl["thread_title"]), norm(gl["post_text"])))
        if c is None or (gl["telco_relevance_manual"] or "").strip().lower() != "yes":
            continue
        parts = [ISSUE_TYPOS.get(x.strip().lower(), x.strip()) for x in gl["issues_manual"].split(",") if x.strip()]
        g = g4r.get(gl["sample_id"])
        out.append({"id": gl["sample_id"], "set": "recent", "gs": normalize_sentiment(gl["sentiment_manual"]),
                    "gi": normalize_issues(",".join(parts)) if parts else [],
                    "mini_s": normalize_sentiment(c["llm_sentiment"]), "vader_s": normalize_sentiment(c["sentiment_label"]),
                    "g4_s": normalize_sentiment(g["llm_sentiment"]) if g else None,
                    "rules": detect_issue_labels(c["post_text"]) or GD, "mini_i": normalize_issues(c["llm_issues_reference"]) or GD,
                    "g4_i": (normalize_issues(g["llm_issues"]) or GD) if g else None,
                    "hyb": normalize_issues(c["issue_labels"]) or GD})
    return out


def agreement() -> dict:
    """Kappa on the annotator-B overlap: A vs B, and GPT-4o-mini vs each annotator, per set."""
    a = {r["sample_id"]: r for r in read(EVAL / "representative_annotator_a.csv") + read(EVAL / "challenge_annotator_a.csv")}
    mini = {r["sample_id"]: normalize_sentiment(r["llm_sentiment"]) for sub in
            ("llm_comparison_representative", "llm_comparison_challenge")
            for r in read(EVAL / sub / "predictions.csv")}
    out = {}
    for name in ("representative", "challenge"):
        trip = [(normalize_sentiment(a[b["sample_id"]]["sentiment_manual"]), normalize_sentiment(b["sentiment_manual"]),
                 mini.get(b["sample_id"])) for b in read(ANNOTATOR_B) if b["evaluation_set"] == name and b["sample_id"] in a]
        trip = [t for t in trip if all(t)]
        nh = lambda x: "not_happy" if x == "not_happy" else "other"
        out[name] = {"n": len(trip),
                     "kappa_a_b": round(kappa([(x, y) for x, y, _ in trip]), 3),
                     "kappa_a_mini": round(kappa([(x, z) for x, _, z in trip]), 3),
                     "kappa_b_mini": round(kappa([(y, z) for _, y, z in trip]), 3),
                     "kappa_a_b_not_happy_vs_rest": round(kappa([(nh(x), nh(y)) for x, y, _ in trip]), 3),
                     "kappa_a_b_without_a_nothappy_b_neutral": round(kappa(
                         [(x, y) for x, y, _ in trip if not (x == "not_happy" and y == "neutral")]), 3)}
    return out


def main() -> None:
    P = posts()
    S = [p for p in P if p["gs"]]
    I = [p for p in P if p["gi"] and p["hyb"] is not None]
    S4, I4 = [p for p in S if p["g4_s"]], [p for p in I if p["g4_i"]]
    for p in I4:  # rejected variant reported for completeness: rule labels plus GPT-4o labels
        p["union"] = sorted((set(p["rules"]) | set(p["g4_i"])) - {"general_discussion"}) or GD
    cm = lambda rows, k: classification_metrics([p["gs"] for p in rows], [p[k] for p in rows], SENTIMENT_LABELS)
    mm = lambda rows, k: multilabel_metrics([p["gi"] for p in rows], [p[k] for p in rows], ISSUE_LABELS)
    pc = lambda m: {k: {key: round(v[name], 3) if name != "support" else v[name] for key, name in
                        (("p", "precision"), ("r", "recall"), ("f1", "f1"), ("support", "support"))}
                    for k, v in m["per_class"].items()}
    dev = [p for p in I4 if "devices" in p["gi"]]
    out = {
        "design": "Representative (295) + recent (97) relevant gold posts; challenge stays separate. GPT-4o on 388.",
        "n": {"sentiment": len(S), "issues": len(I), "sentiment_gpt4o": len(S4), "issues_gpt4o": len(I4),
              "by_set": dict(Counter(p["set"] for p in S))},
        "gold_sentiment_shares_pct": {k: round(100 * sum(p["gs"] == k for p in S) / len(S)) for k in SENTIMENT_LABELS},
        "mini_sentiment_shares_pct": {k: round(100 * sum(p["mini_s"] == k for p in S) / len(S)) for k in SENTIMENT_LABELS},
        "sentiment": {name: {"macro_f1": round(cm(rows, k)["macro_f1"], 3), "accuracy": round(cm(rows, k)["accuracy"], 3),
                             "per_class": pc(cm(rows, k)), "n": len(rows),
                             "confusion_matrix_rows_gold": cm(rows, k)["confusion_matrix"],
                             "labels_order": cm(rows, k)["labels_order"]}
                      for name, rows, k in (("gpt4o_mini", S, "mini_s"), ("vader", S, "vader_s"), ("gpt4o", S4, "g4_s"))},
        "not_happy_gold": sum(p["gs"] == "not_happy" for p in S),
        "vader_happy_on_not_happy": sum(p["gs"] == "not_happy" and p["vader_s"] == "happy" for p in S),
        "ci_mini_minus_vader": boot(S, lambda s: cm(s, "mini_s")["macro_f1"] - cm(s, "vader_s")["macro_f1"]),
        "ci_mini_minus_gpt4o": boot(S4, lambda s: cm(s, "mini_s")["macro_f1"] - cm(s, "g4_s")["macro_f1"]),
        "issues": {name: {"macro_f1": round(m["macro_f1"], 3), "micro_f1": round(m["micro_f1"], 3),
                          "exact_match": round(m["exact_match_accuracy"], 3), "n": m["n"],
                          "per_class_f1": {k: round(v["f1"], 3) for k, v in m["per_class"].items()},
                          "general_discussion_false_positives": m["per_class"]["general_discussion"]["confusion_matrix"][0][1]}
                   for name, m in ((name, mm(rows, k)) for name, rows, k in
                                   (("rules", I, "rules"), ("hybrid", I, "hyb"), ("gpt4o_mini_all_posts", I, "mini_i"),
                                    ("gpt4o_all_posts", I4, "g4_i"), ("union_rules_gpt4o", I4, "union")))},
        "issue_support": {k: v["support"] for k, v in mm(I, "hyb")["per_class"].items()},
        "rules_left_general_discussion": sum(p["rules"] == GD for p in I),
        "hybrid_reassigned": sum(p["rules"] == GD and p["hyb"] != GD for p in I),
        "devices_recall": {"n": len(dev), "rules": round(sum("devices" in p["rules"] for p in dev) / len(dev), 2),
                           "gpt4o_mini": round(sum("devices" in p["mini_i"] for p in dev) / len(dev), 2),
                           "gpt4o": round(sum("devices" in p["g4_i"] for p in dev) / len(dev), 2)},
        "ci_hybrid_minus_rules": boot(I, lambda s: mm(s, "hyb")["macro_f1"] - mm(s, "rules")["macro_f1"]),
        "ci_rules_minus_mini_all": boot(I, lambda s: mm(s, "rules")["macro_f1"] - mm(s, "mini_i")["macro_f1"]),
        "ci_gpt4o_all_minus_rules": boot(I4, lambda s: mm(s, "g4_i")["macro_f1"] - mm(s, "rules")["macro_f1"]),
        "ci_hybrid_minus_gpt4o_all": boot(I4, lambda s: mm(s, "hyb")["macro_f1"] - mm(s, "g4_i")["macro_f1"]),
        "agreement_on_overlap": agreement(),
    }
    assert out["n"]["sentiment"] == 392 and out["n"]["issues"] == 388, out["n"]  # guards against a silent sheet change
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("n", "agreement_on_overlap")}, indent=1))
    print("issue macro F1:", {k: v["macro_f1"] for k, v in out["issues"].items()})
    print("sentiment F1:", {k: v["macro_f1"] for k, v in out["sentiment"].items()})
    print(f"Wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
