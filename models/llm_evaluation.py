#!/usr/bin/env python3
"""Evaluate VADER/rule baselines against an OpenAI-compatible LLM.

The script operates only on independently annotated evaluation records. It:
- validates manual sentiment and multi-label issue annotations;
- runs local VADER and keyword-rule baselines;
- calls the LLM in resumable batches with no silent fallback labels;
- records the exact returned model ID, runtime, token usage, retries, and errors;
- computes sentiment and multi-label issue metrics; and
- exports disagreement rows for qualitative analysis.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

try:
    from openai import OpenAI  # type: ignore[import-not-found]
except ImportError:
    OpenAI = None  # type: ignore[assignment,misc]

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer  # type: ignore[import-not-found]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from processing.issue_extraction import ISSUE_TAXONOMY, detect_issue_labels


SENTIMENT_LABELS = ["happy", "not_happy", "neutral"]
ISSUE_LABELS = list(ISSUE_TAXONOMY)
DEFAULT_INPUT = Path("data/evaluation/representative_adjudicated.csv")
DEFAULT_OUTPUT_DIR = Path("data/evaluation/llm_comparison")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare VADER/keyword rules with an LLM on blind human labels."
    )
    parser.add_argument("--in", dest="input_path", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--base-url", default=os.getenv("OPENAI_BASE_URL", ""))
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--max-text-chars", type=int, default=2000)
    parser.add_argument("--max-output-tokens", type=int, default=1600)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=2.0)
    parser.add_argument("--limit", type=int, default=0, help="Optional row limit for a pilot.")
    parser.add_argument(
        "--input-cost-per-million",
        type=float,
        default=0.0,
        help="Provider price per one million input tokens.",
    )
    parser.add_argument(
        "--output-cost-per-million",
        type=float,
        default=0.0,
        help="Provider price per one million output tokens.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from the checkpoint JSONL in the output directory.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate annotations and print the planned run without calling the API.",
    )
    return parser.parse_args()


def normalize_sentiment(value: str) -> str:
    label = str(value or "").strip().lower().replace(" ", "_")
    aliases = {
        "positive": "happy",
        "negative": "not_happy",
        "not_happy": "not_happy",
        "happy": "happy",
        "neutral": "neutral",
        "mixed": "neutral",
    }
    return aliases.get(label, "")


def normalize_issues(value: str | Iterable[str]) -> list[str]:
    compounds = {
        "network outage & connectivity": ["network_quality"],
        "network outage and connectivity": ["network_quality"],
        "customer service & account": ["customer_service", "app_account"],
        "customer service and account": ["customer_service", "app_account"],
        "mobile plans & pricing": ["mobile_plans", "pricing_promotions"],
        "mobile plans and pricing": ["mobile_plans", "pricing_promotions"],
        "porting / switching": ["porting"],
        "porting/switching": ["porting"],
    }
    if isinstance(value, str):
        compound_key = re.sub(r"\s+", " ", value.strip().lower())
        if compound_key in compounds:
            return list(compounds[compound_key])
        raw = re.split(r"[,;|/]+", value)
    else:
        raw = list(value)

    aliases = {
        "network quality": "network_quality",
        "network_quality": "network_quality",
        "network": "network_quality",
        "coverage": "network_quality",
        "pricing & promotions": "pricing_promotions",
        "pricing and promotions": "pricing_promotions",
        "pricing_promotions": "pricing_promotions",
        "price": "pricing_promotions",
        "pricing": "pricing_promotions",
        "mobile plans": "mobile_plans",
        "mobile plan": "mobile_plans",
        "mobile_plans": "mobile_plans",
        "roaming": "roaming",
        "port": "porting",
        "porting": "porting",
        "customer service": "customer_service",
        "customer_service": "customer_service",
        "service": "customer_service",
        "billing & payment": "billing_payment",
        "billing and payment": "billing_payment",
        "billing_payment": "billing_payment",
        "billing": "billing_payment",
        "app & account": "app_account",
        "app and account": "app_account",
        "app_account": "app_account",
        "devices": "devices",
        "device": "devices",
        "general discussion": "general_discussion",
        "general_discussion": "general_discussion",
        "other": "general_discussion",
    }
    labels: list[str] = []
    for item in raw:
        key = str(item).strip().lower().replace("-", "_")
        key = re.sub(r"\s+", " ", key)
        label = aliases.get(key, key.replace(" ", "_"))
        if label in ISSUE_LABELS and label not in labels:
            labels.append(label)

    if len(labels) > 1 and "general_discussion" in labels:
        labels.remove("general_discussion")
    return labels


def read_annotated_rows(path: Path, limit: int = 0) -> list[dict[str, str]]:
    if not path.exists():
        generated_sheet = Path("data/evaluation/representative_annotator_a.csv")
        hint = (
            f"\nGenerated annotation sheet: {generated_sheet}"
            "\nComplete the human annotation and save the adjudicated copy as:"
            f"\n  {DEFAULT_INPUT}"
            "\nTo check annotation progress without API calls, run:"
            f"\n  venv/bin/python models/llm_evaluation.py "
            f"--in {generated_sheet} --validate-only"
            if generated_sheet.exists()
            else "\nRun processing/create_evaluation_set.py first."
        )
        raise SystemExit(f"Annotated input not found: {path}{hint}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if limit > 0:
        rows = rows[:limit]
    return rows


def validate_rows(rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[str]]:
    valid: list[dict[str, Any]] = []
    errors: list[str] = []
    seen_ids: set[str] = set()

    for index, row in enumerate(rows, start=2):
        sample_id = str(row.get("sample_id", "")).strip()
        text = str(row.get("post_text", "")).strip()
        relevance = str(row.get("telco_relevance_manual", "")).strip().lower()
        sentiment = normalize_sentiment(
            row.get("sentiment_manual") or row.get("sentiment_label_manual") or ""
        )
        issues = normalize_issues(
            row.get("issues_manual") or row.get("issue_manual") or ""
        )

        if not sample_id:
            errors.append(f"CSV row {index}: missing sample_id")
            continue
        if sample_id in seen_ids:
            errors.append(f"CSV row {index}: duplicate sample_id {sample_id}")
            continue
        seen_ids.add(sample_id)
        if not text:
            errors.append(f"{sample_id}: missing post_text")
            continue
        if relevance not in {"yes", "no", "unclear"}:
            errors.append(f"{sample_id}: telco_relevance_manual must be yes/no/unclear")
            continue
        if relevance != "yes":
            continue
        if not sentiment:
            errors.append(f"{sample_id}: missing or invalid sentiment_manual")
            continue
        if not issues:
            errors.append(f"{sample_id}: missing or invalid issues_manual")
            continue

        item = dict(row)
        item["manual_sentiment"] = sentiment
        item["manual_issues"] = issues
        valid.append(item)

    return valid, errors


def vader_predict(text: str, analyzer: SentimentIntensityAnalyzer) -> str:
    compound = analyzer.polarity_scores(text or "")["compound"]
    if compound >= 0.05:
        return "happy"
    if compound <= -0.05:
        return "not_happy"
    return "neutral"


def classification_metrics(
    y_true: list[str],
    y_pred: list[str],
    labels: list[str],
) -> dict[str, Any]:
    index = {label: i for i, label in enumerate(labels)}
    matrix = [[0 for _ in labels] for _ in labels]
    for truth, prediction in zip(y_true, y_pred):
        if truth in index and prediction in index:
            matrix[index[truth]][index[prediction]] += 1

    per_class: dict[str, Any] = {}
    f1_values: list[float] = []
    for i, label in enumerate(labels):
        tp = matrix[i][i]
        fp = sum(matrix[row][i] for row in range(len(labels)) if row != i)
        fn = sum(matrix[i][column] for column in range(len(labels)) if column != i)
        support = sum(matrix[i])
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        f1_values.append(f1)
        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
        }

    total = len(y_true)
    correct = sum(matrix[i][i] for i in range(len(labels)))
    return {
        "n": total,
        "accuracy": correct / total if total else 0.0,
        "macro_f1": sum(f1_values) / len(f1_values) if f1_values else 0.0,
        "per_class": per_class,
        "confusion_matrix": matrix,
        "labels_order": labels,
    }


def multilabel_metrics(
    y_true: list[list[str]],
    y_pred: list[list[str]],
    labels: list[str],
) -> dict[str, Any]:
    per_class: dict[str, Any] = {}
    total_tp = total_fp = total_fn = 0
    f1_values: list[float] = []

    for label in labels:
        tp = fp = fn = tn = 0
        for truth, prediction in zip(y_true, y_pred):
            truth_has = label in truth
            pred_has = label in prediction
            if truth_has and pred_has:
                tp += 1
            elif not truth_has and pred_has:
                fp += 1
            elif truth_has and not pred_has:
                fn += 1
            else:
                tn += 1

        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        f1_values.append(f1)
        total_tp += tp
        total_fp += fp
        total_fn += fn
        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": tp + fn,
            "confusion_matrix": [[tn, fp], [fn, tp]],
        }

    micro_precision = total_tp / (total_tp + total_fp) if total_tp + total_fp else 0.0
    micro_recall = total_tp / (total_tp + total_fn) if total_tp + total_fn else 0.0
    micro_f1 = (
        2 * micro_precision * micro_recall / (micro_precision + micro_recall)
        if micro_precision + micro_recall
        else 0.0
    )
    exact_match = sum(set(t) == set(p) for t, p in zip(y_true, y_pred))
    return {
        "n": len(y_true),
        "exact_match_accuracy": exact_match / len(y_true) if y_true else 0.0,
        "macro_f1": sum(f1_values) / len(f1_values) if f1_values else 0.0,
        "micro_precision": micro_precision,
        "micro_recall": micro_recall,
        "micro_f1": micro_f1,
        "per_class": per_class,
    }


def system_prompt() -> str:
    return (
        "You are evaluating Singapore telco forum comments. For every input item, "
        "classify sentiment toward the telco target as exactly one of: happy, "
        "not_happy, neutral. Also assign one or more issue labels from: "
        "network_quality, pricing_promotions, mobile_plans, roaming, porting, "
        "customer_service, billing_payment, app_account, devices, general_discussion. "
        "Use general_discussion only when no specific issue applies. "
        "Understand negation, sarcasm, Singlish, mixed "
        "opinions, quoted speech, and multiple telcos. Return only one JSON object "
        'with this shape: {"results":[{"sample_id":"...","sentiment":"...",'
        '"issues":["..."]}]}. Include every sample_id exactly once.'
    )


def user_prompt(rows: list[dict[str, Any]], max_chars: int) -> str:
    payload = [
        {
            "sample_id": row["sample_id"],
            "thread_title": str(row.get("thread_title", ""))[:500],
            "post_text": str(row.get("post_text", ""))[:max_chars],
        }
        for row in rows
    ]
    return json.dumps({"items": payload}, ensure_ascii=False)


def parse_llm_results(raw: str, expected_ids: set[str]) -> dict[str, dict[str, Any]]:
    parsed = json.loads(raw)
    items = parsed.get("results") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        raise ValueError("LLM response must contain a results array")

    results: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        sample_id = str(item.get("sample_id", "")).strip()
        sentiment = normalize_sentiment(item.get("sentiment", ""))
        issues = normalize_issues(item.get("issues", []))
        if sample_id not in expected_ids:
            continue
        if not sentiment or not issues:
            raise ValueError(f"Invalid labels returned for {sample_id}")
        if sample_id in results:
            raise ValueError(f"Duplicate result returned for {sample_id}")
        results[sample_id] = {
            "sentiment": sentiment,
            "issues": issues,
        }

    missing = expected_ids - set(results)
    if missing:
        raise ValueError(f"Missing results for: {', '.join(sorted(missing))}")
    return results


def call_batch(
    client: OpenAI,
    rows: list[dict[str, Any]],
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    expected_ids = {row["sample_id"] for row in rows}
    last_error = ""

    for attempt in range(1, args.max_retries + 1):
        started = time.perf_counter()
        try:
            response = client.chat.completions.create(
                model=args.model,
                messages=[
                    {"role": "system", "content": system_prompt()},
                    {
                        "role": "user",
                        "content": user_prompt(rows, args.max_text_chars),
                    },
                ],
                temperature=0,
                max_tokens=args.max_output_tokens,
                response_format={"type": "json_object"},
            )
            elapsed = time.perf_counter() - started
            raw = response.choices[0].message.content or ""
            parsed = parse_llm_results(raw, expected_ids)
            usage = response.usage
            metadata = {
                "requested_model": args.model,
                "returned_model": getattr(response, "model", ""),
                "request_id": getattr(response, "id", ""),
                "attempts": attempt,
                "elapsed_seconds": elapsed,
                "input_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                "output_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
                "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
                "error": "",
            }
            output = [
                {
                    "sample_id": row["sample_id"],
                    "llm_sentiment": parsed[row["sample_id"]]["sentiment"],
                    "llm_issues": parsed[row["sample_id"]]["issues"],
                    **metadata,
                }
                for row in rows
            ]
            return output, metadata
        except Exception as exc:
            elapsed = time.perf_counter() - started
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < args.max_retries:
                time.sleep(args.retry_delay * (2 ** (attempt - 1)))

    metadata = {
        "requested_model": args.model,
        "returned_model": "",
        "request_id": "",
        "attempts": args.max_retries,
        "elapsed_seconds": elapsed,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "error": last_error,
    }
    output = [
        {
            "sample_id": row["sample_id"],
            "llm_sentiment": "",
            "llm_issues": [],
            **metadata,
        }
        for row in rows
    ]
    return output, metadata


def batches(rows: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def load_checkpoint(path: Path) -> dict[str, dict[str, Any]]:
    completed: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return completed
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            completed[item["sample_id"]] = item
    return completed


def append_checkpoint(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def cost_summary(
    input_tokens: int,
    output_tokens: int,
    input_rate: float,
    output_rate: float,
) -> dict[str, float]:
    input_cost = input_tokens / 1_000_000 * input_rate
    output_cost = output_tokens / 1_000_000 * output_rate
    return {
        "currency": "USD",
        "pricing_provided": bool(input_rate or output_rate),
        "input_cost_per_million": input_rate,
        "output_cost_per_million": output_rate,
        "estimated_input_cost": input_cost,
        "estimated_output_cost": output_cost,
        "estimated_total_cost": input_cost + output_cost,
    }


def main() -> None:
    args = parse_args()
    if args.batch_size <= 0 or args.max_retries <= 0:
        raise ValueError("Batch size and retry count must be positive.")

    raw_rows = read_annotated_rows(args.input_path, args.limit)
    rows, validation_errors = validate_rows(raw_rows)
    if validation_errors:
        print(f"Annotation validation failed with {len(validation_errors)} error(s):")
        for error in validation_errors[:20]:
            print(f"  - {error}")
        if len(validation_errors) > 20:
            print(f"  ... and {len(validation_errors) - 20} more")
        raise SystemExit(2)
    if not rows:
        raise SystemExit("No telco-relevant, fully annotated rows found.")

    print(f"Validated annotated rows: {len(rows)}")
    print(f"Planned LLM batches: {(len(rows) + args.batch_size - 1) // args.batch_size}")
    print(f"Requested model: {args.model}")
    if args.validate_only:
        print("Validation-only mode: no API calls made.")
        return

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is not set.")
    if OpenAI is None:
        raise SystemExit(
            "The openai package is not installed. Run: "
            "venv/bin/python -m pip install openai"
        )

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = out_dir / "llm_checkpoint.jsonl"
    if checkpoint_path.exists() and not args.resume:
        checkpoint_path.unlink()
    completed = load_checkpoint(checkpoint_path) if args.resume else {}

    pending = [
        row
        for row in rows
        if row["sample_id"] not in completed
        or completed[row["sample_id"]].get("error")
    ]
    client = OpenAI(api_key=api_key, base_url=args.base_url or None)
    run_started = time.perf_counter()
    request_metadata: list[dict[str, Any]] = []

    for batch_number, batch_rows in enumerate(batches(pending, args.batch_size), start=1):
        predictions, metadata = call_batch(client, batch_rows, args)
        append_checkpoint(checkpoint_path, predictions)
        completed.update({row["sample_id"]: row for row in predictions})
        request_metadata.append(metadata)
        status = "ok" if not metadata["error"] else f"failed: {metadata['error']}"
        print(
            f"Batch {batch_number}: {len(batch_rows)} rows, "
            f"{metadata['elapsed_seconds']:.2f}s, {status}"
        )

    wall_seconds = time.perf_counter() - run_started
    analyzer = SentimentIntensityAnalyzer()
    vader_started = time.perf_counter()
    vader_by_id = {
        row["sample_id"]: vader_predict(row.get("post_text", ""), analyzer)
        for row in rows
    }
    vader_seconds = time.perf_counter() - vader_started

    rules_started = time.perf_counter()
    rules_by_id = {
        row["sample_id"]: detect_issue_labels(row.get("post_text", ""))
        for row in rows
    }
    rules_seconds = time.perf_counter() - rules_started

    output_rows: list[dict[str, Any]] = []
    for row in rows:
        prediction = completed.get(row["sample_id"], {})
        output_rows.append(
            {
                "sample_id": row["sample_id"],
                "evaluation_set": row.get("evaluation_set", ""),
                "source": row.get("source", ""),
                "thread_title": row.get("thread_title", ""),
                "post_text": row.get("post_text", ""),
                "manual_sentiment": row["manual_sentiment"],
                "manual_issues": ",".join(row["manual_issues"]),
                "vader_sentiment": vader_by_id[row["sample_id"]],
                "rule_issues": ",".join(rules_by_id[row["sample_id"]]),
                "llm_sentiment": prediction.get("llm_sentiment", ""),
                "llm_issues": ",".join(prediction.get("llm_issues", [])),
                "llm_error": prediction.get("error", "missing prediction"),
                "returned_model": prediction.get("returned_model", ""),
                "input_tokens": prediction.get("input_tokens", 0),
                "output_tokens": prediction.get("output_tokens", 0),
                "elapsed_seconds": prediction.get("elapsed_seconds", 0),
            }
        )

    successful = [row for row in output_rows if not row["llm_error"]]
    failed = [row for row in output_rows if row["llm_error"]]
    if not successful:
        raise SystemExit("All LLM batches failed; inspect llm_checkpoint.jsonl.")

    sentiment_truth = [row["manual_sentiment"] for row in successful]
    vader_predictions = [row["vader_sentiment"] for row in successful]
    llm_sentiment_predictions = [row["llm_sentiment"] for row in successful]
    issue_truth = [normalize_issues(row["manual_issues"]) for row in successful]
    rule_predictions = [normalize_issues(row["rule_issues"]) for row in successful]
    llm_issue_predictions = [normalize_issues(row["llm_issues"]) for row in successful]

    unique_requests = {
        row.get("request_id", ""): row
        for row in completed.values()
        if row.get("request_id")
    }
    input_tokens = sum(row.get("input_tokens", 0) for row in unique_requests.values())
    output_tokens = sum(row.get("output_tokens", 0) for row in unique_requests.values())
    returned_models = sorted(
        {
            row.get("returned_model", "")
            for row in successful
            if row.get("returned_model")
        }
    )

    metrics = {
        "input_file": str(args.input_path),
        "requested_model": args.model,
        "returned_models": returned_models,
        "successful_rows": len(successful),
        "failed_rows": len(failed),
        "runtime": {
            "llm_wall_seconds_this_run": wall_seconds,
            "request_seconds_total": sum(
                row.get("elapsed_seconds", 0) for row in unique_requests.values()
            ),
            "llm_request_seconds_per_successful_row": (
                sum(row.get("elapsed_seconds", 0) for row in unique_requests.values())
                / len(successful)
            ),
            "vader_seconds": vader_seconds,
            "vader_seconds_per_row": vader_seconds / len(rows),
            "keyword_rules_seconds": rules_seconds,
            "keyword_rules_seconds_per_row": rules_seconds / len(rows),
        },
        "tokens": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
        "cost": cost_summary(
            input_tokens,
            output_tokens,
            args.input_cost_per_million,
            args.output_cost_per_million,
        ),
        "sentiment": {
            "vader": classification_metrics(
                sentiment_truth, vader_predictions, SENTIMENT_LABELS
            ),
            "llm": classification_metrics(
                sentiment_truth, llm_sentiment_predictions, SENTIMENT_LABELS
            ),
        },
        "issues": {
            "keyword_rules": multilabel_metrics(
                issue_truth, rule_predictions, ISSUE_LABELS
            ),
            "llm": multilabel_metrics(
                issue_truth, llm_issue_predictions, ISSUE_LABELS
            ),
        },
        "failed_sample_ids": [row["sample_id"] for row in failed],
        "request_log": request_metadata,
    }

    prediction_fields = [
        "sample_id",
        "evaluation_set",
        "source",
        "thread_title",
        "post_text",
        "manual_sentiment",
        "manual_issues",
        "vader_sentiment",
        "rule_issues",
        "llm_sentiment",
        "llm_issues",
        "llm_error",
        "returned_model",
        "input_tokens",
        "output_tokens",
        "elapsed_seconds",
    ]
    write_csv(out_dir / "predictions.csv", output_rows, prediction_fields)

    disagreements: list[dict[str, Any]] = []
    for row in successful:
        vader_correct = row["vader_sentiment"] == row["manual_sentiment"]
        llm_sentiment_correct = row["llm_sentiment"] == row["manual_sentiment"]
        rule_correct = set(normalize_issues(row["rule_issues"])) == set(
            normalize_issues(row["manual_issues"])
        )
        llm_issue_correct = set(normalize_issues(row["llm_issues"])) == set(
            normalize_issues(row["manual_issues"])
        )
        if vader_correct != llm_sentiment_correct or rule_correct != llm_issue_correct:
            qualitative = dict(row)
            qualitative["sentiment_comparison"] = (
                "llm_only_correct"
                if llm_sentiment_correct and not vader_correct
                else "vader_only_correct"
                if vader_correct and not llm_sentiment_correct
                else "same_outcome"
            )
            qualitative["issue_comparison"] = (
                "llm_only_exact"
                if llm_issue_correct and not rule_correct
                else "rules_only_exact"
                if rule_correct and not llm_issue_correct
                else "same_outcome"
            )
            disagreements.append(qualitative)
    write_csv(
        out_dir / "qualitative_disagreements.csv",
        disagreements,
        prediction_fields + ["sentiment_comparison", "issue_comparison"],
    )

    with (out_dir / "metrics.json").open("w", encoding="utf-8") as handle:
        json.dump(metrics, handle, indent=2, ensure_ascii=False)

    print(f"Successful LLM rows: {len(successful)}; failed: {len(failed)}")
    print(
        "Sentiment macro F1 — "
        f"VADER: {metrics['sentiment']['vader']['macro_f1']:.3f}; "
        f"LLM: {metrics['sentiment']['llm']['macro_f1']:.3f}"
    )
    print(
        "Issue macro F1 — "
        f"rules: {metrics['issues']['keyword_rules']['macro_f1']:.3f}; "
        f"LLM: {metrics['issues']['llm']['macro_f1']:.3f}"
    )
    print(f"Saved results to: {out_dir}")


if __name__ == "__main__":
    main()
