#!/usr/bin/env python3
"""
Benchmark sentiment models against manually labeled data.

Compares:
1) VADER (rule-based baseline)
2) Transformer sentiment model (Hugging Face pipeline)

Expected input:
- CSV with at least:
  - post_text (or selftext)
  - sentiment_label_manual (happy / not_happy / neutral)
"""

import argparse
import json
from pathlib import Path
from typing import Dict, List

import pandas as pd

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    HAS_VADER = True
except ImportError:
    HAS_VADER = False

try:
    from transformers import pipeline
    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False


VALID_LABELS = ["happy", "not_happy", "neutral"]
PROCESSED_DIR = Path("data/processed")


def _latest_labeled_sample() -> Path:
    preferred = PROCESSED_DIR / "labeled_sample.csv"
    if preferred.exists():
        return preferred
    candidates = sorted(PROCESSED_DIR.glob("*labeled*sample*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        return candidates[0]
    fallback = PROCESSED_DIR / "labeled_sample_template.csv"
    return fallback


def _normalize_input_columns(df: pd.DataFrame) -> pd.DataFrame:
    if "post_text" not in df.columns and "selftext" in df.columns:
        df = df.copy()
        df["post_text"] = df["selftext"]
    if "sentiment_label_manual" not in df.columns and "sentiment_manual" in df.columns:
        df = df.copy()
        df["sentiment_label_manual"] = df["sentiment_manual"]
    return df


def _clean_manual_label(x: str) -> str:
    s = str(x).strip().lower()
    if s in {"not happy", "not_happy", "negative"}:
        return "not_happy"
    if s in {"happy", "positive"}:
        return "happy"
    if s in {"neutral", "mixed"}:
        return "neutral"
    return ""


def vader_predict(texts: List[str]) -> List[str]:
    if not HAS_VADER:
        raise RuntimeError("vaderSentiment not installed. pip install vaderSentiment")
    analyzer = SentimentIntensityAnalyzer()
    preds: List[str] = []
    for t in texts:
        score = analyzer.polarity_scores(t or "")["compound"]
        if score >= 0.05:
            preds.append("happy")
        elif score <= -0.05:
            preds.append("not_happy")
        else:
            preds.append("neutral")
    return preds


def map_hf_label(label: str) -> str:
    s = str(label).lower()
    if "pos" in s or "5 star" in s or "4 star" in s:
        return "happy"
    if "neg" in s or "1 star" in s or "2 star" in s:
        return "not_happy"
    return "neutral"


def transformer_predict(texts: List[str], model_name: str, batch_size: int = 32) -> List[str]:
    if not HAS_TRANSFORMERS:
        raise RuntimeError("transformers not installed. pip install transformers torch")
    clf = pipeline("sentiment-analysis", model=model_name, truncation=True, max_length=512)
    preds: List[str] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        outputs = clf(batch)
        preds.extend(map_hf_label(o.get("label", "")) for o in outputs)
    return preds


def evaluate(y_true: List[str], y_pred: List[str]) -> Dict:
    # Build confusion matrix in fixed label order
    idx = {label: i for i, label in enumerate(VALID_LABELS)}
    cm = [[0 for _ in VALID_LABELS] for _ in VALID_LABELS]
    for t, p in zip(y_true, y_pred):
        if t in idx and p in idx:
            cm[idx[t]][idx[p]] += 1

    total = len(y_true)
    correct = sum(cm[i][i] for i in range(len(VALID_LABELS)))
    accuracy = (correct / total) if total else 0.0

    report: Dict[str, Dict[str, float]] = {}
    f1s: List[float] = []
    weighted_f1_num = 0.0
    support_total = 0

    for i, label in enumerate(VALID_LABELS):
        tp = cm[i][i]
        fp = sum(cm[r][i] for r in range(len(VALID_LABELS)) if r != i)
        fn = sum(cm[i][c] for c in range(len(VALID_LABELS)) if c != i)
        support = sum(cm[i])

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        report[label] = {
            "precision": precision,
            "recall": recall,
            "f1-score": f1,
            "support": support,
        }

        f1s.append(f1)
        weighted_f1_num += f1 * support
        support_total += support

    macro_f1 = (sum(f1s) / len(f1s)) if f1s else 0.0
    weighted_f1 = (weighted_f1_num / support_total) if support_total else 0.0

    report["macro avg"] = {
        "precision": sum(report[l]["precision"] for l in VALID_LABELS) / len(VALID_LABELS),
        "recall": sum(report[l]["recall"] for l in VALID_LABELS) / len(VALID_LABELS),
        "f1-score": macro_f1,
        "support": support_total,
    }
    report["weighted avg"] = {
        "precision": (sum(report[l]["precision"] * report[l]["support"] for l in VALID_LABELS) / support_total) if support_total else 0.0,
        "recall": (sum(report[l]["recall"] * report[l]["support"] for l in VALID_LABELS) / support_total) if support_total else 0.0,
        "f1-score": weighted_f1,
        "support": support_total,
    }
    report["accuracy"] = accuracy

    return {
        "accuracy": float(accuracy),
        "f1_macro": float(macro_f1),
        "classification_report": report,
        "confusion_matrix": cm,
        "labels_order": VALID_LABELS,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark VADER and transformer sentiment against manual labels.")
    parser.add_argument("--in", dest="input_path", type=str, default=str(_latest_labeled_sample()), help="CSV with manual labels.")
    parser.add_argument("--out-json", type=str, default="data/processed/sentiment_benchmark.json", help="Where to write benchmark summary JSON.")
    parser.add_argument("--out-csv", type=str, default="data/processed/sentiment_benchmark_predictions.csv", help="Where to write row-level predictions.")
    parser.add_argument("--transformer-model", type=str, default="cardiffnlp/twitter-roberta-base-sentiment-latest", help="HF model name for transformer baseline.")
    parser.add_argument("--skip-transformer", action="store_true", help="Skip transformer benchmark.")
    args = parser.parse_args()

    input_path = Path(args.input_path)
    if not input_path.exists():
        print(f"Error: input file not found: {input_path}")
        return

    df = pd.read_csv(input_path)
    df = _normalize_input_columns(df)
    if "telco_relevance_manual" in df.columns:
        relevance = df["telco_relevance_manual"].fillna("").astype(str).str.strip().str.lower()
        df = df[relevance == "yes"].copy()
    if "post_text" not in df.columns:
        print("Error: need post_text (or selftext) column.")
        return
    if "sentiment_label_manual" not in df.columns:
        print("Error: need sentiment_label_manual or sentiment_manual column.")
        return

    df["sentiment_label_manual_clean"] = df["sentiment_label_manual"].apply(_clean_manual_label)
    manual_non_empty = int((df["sentiment_label_manual"].fillna("").astype(str).str.strip() != "").sum())
    df = df[df["sentiment_label_manual_clean"].isin(VALID_LABELS)].copy()
    if df.empty:
        print("Error: no valid manual sentiment labels found in sentiment_label_manual.")
        print(f"Rows with non-empty sentiment_label_manual: {manual_non_empty}")
        print("Create blind annotation sheets with:")
        print("  python processing/create_evaluation_set.py")
        print("Independently fill sentiment_manual, then rerun this benchmark.")
        return

    texts = df["post_text"].fillna("").astype(str).tolist()
    y_true = df["sentiment_label_manual_clean"].tolist()

    results: Dict[str, Dict] = {}

    # VADER baseline
    vader_preds = vader_predict(texts)
    df["pred_vader"] = vader_preds
    results["vader"] = evaluate(y_true, vader_preds)

    # Transformer baseline
    if not args.skip_transformer:
        try:
            trans_preds = transformer_predict(texts, args.transformer_model)
            df["pred_transformer"] = trans_preds
            results["transformer"] = evaluate(y_true, trans_preds)
            results["transformer"]["model"] = args.transformer_model
        except Exception as e:
            results["transformer_error"] = str(e)

    # Save outputs
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    out_csv = Path(args.out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    keep_cols = [
        c
        for c in [
            "sample_id",
            "evaluation_set",
            "source",
            "post_text",
            "sentiment_label_manual",
            "sentiment_label_manual_clean",
            "pred_vader",
            "pred_transformer",
        ]
        if c in df.columns
    ]
    df[keep_cols].to_csv(out_csv, index=False, encoding="utf-8-sig")

    print(f"Labeled rows used: {len(df)}")
    print(f"Saved benchmark summary: {out_json}")
    print(f"Saved row predictions: {out_csv}")
    print(f"VADER accuracy={results['vader']['accuracy']:.4f}, f1_macro={results['vader']['f1_macro']:.4f}")
    if "transformer" in results:
        print(f"Transformer accuracy={results['transformer']['accuracy']:.4f}, f1_macro={results['transformer']['f1_macro']:.4f}")
    elif "transformer_error" in results:
        print(f"Transformer skipped/failed: {results['transformer_error']}")


if __name__ == "__main__":
    main()

