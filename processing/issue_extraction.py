#!/usr/bin/env python3
"""
Structured issue extraction for telco comments.

Creates issue labels per row using:
1) Rule-based keyword taxonomy (default)
2) Optional LLM-based classifier (OpenAI-compatible API) for unresolved rows or all rows

Outputs:
- CSV with added columns: issue_labels, issue_primary
- JSON summary counts by issue and telco
"""

import argparse
import json
import os
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


ISSUE_TAXONOMY: Dict[str, List[str]] = {
    "network_quality": [
        r"\bnetwork\b", r"\bcoverage\b", r"\bsignal\b", r"\bno signal\b", r"\b4g\b", r"\b5g\b",
        r"\bspeed\b", r"\bslow\b", r"\blatency\b", r"\bconnection\b", r"\bdata loss\b", r"\bdown\b",
        r"\boutage\b", r"\bdropped call\b", r"\bdead spot\b", r"\bbandwidth\b",
    ],
    "pricing_promotions": [
        r"\bprice\b", r"\bpricing\b", r"\bcost\b", r"\bexpensive\b", r"\bcheap\b", r"\bvalue\b",
        r"\bpromo\b", r"\bpromotion\b", r"\bdiscount\b", r"\bdeal\b", r"\bvoucher\b", r"\bcashback\b",
    ],
    "mobile_plans": [
        r"\bplan\b", r"\bsim[- ]?only\b", r"\bsubscription\b", r"\bcontract\b", r"\bgb\b",
        r"\bunlimited\b", r"\bdata allowance\b", r"\bminutes\b", r"\bsms\b", r"\bmvno\b",
    ],
    "roaming": [
        r"\broaming\b", r"\broam\b", r"\bapac\b", r"\bidd\b", r"\boverseas\b",
        r"\binternational\b", r"\btravel data\b", r"\bmalaysia\b",
    ],
    "porting": [
        r"\bport\b", r"\bporting\b", r"\bport in\b", r"\bport out\b", r"\bnumber transfer\b",
        r"\btransfer number\b", r"\bmnp\b", r"\bswitch telco\b",
    ],
    "customer_service": [
        r"\bcustomer service\b", r"\bcs\b", r"\bsupport\b", r"\bhotline\b", r"\bservice center\b",
        r"\bcomplain\b", r"\bcomplaint\b", r"\bagent\b", r"\bstaff\b", r"\bescalat\w*\b",
    ],
    "billing_payment": [
        r"\bbill\b", r"\bbilling\b", r"\bcharged\b", r"\bcharge\b", r"\bpayment\b", r"\bpay\b",
        r"\brefund\b", r"\binvoice\b", r"\bcredit card\b", r"\bgiro\b", r"\bauto[- ]?debit\b",
    ],
    "app_account": [
        r"\bapp\b", r"\bapplication\b", r"\baccount\b", r"\blog[ -]?in\b", r"\bsign[ -]?in\b",
        r"\bpassword\b", r"\botp\b", r"\bportal\b", r"\bdashboard\b", r"\bverification\b",
    ],
    "devices": [
        r"\bdevice\b", r"\bphone\b", r"\bhandset\b", r"\biphone\b", r"\bandroid\b", r"\besim\b",
        r"\bsim card\b", r"\brouter\b", r"\bmodem\b", r"\bonr\b", r"\bont\b", r"\bequipment\b",
    ],
    "general_discussion": [],
}

COMPILED = {
    issue: [re.compile(p, flags=re.IGNORECASE) for p in pats]
    for issue, pats in ISSUE_TAXONOMY.items()
}


def get_llm_client() -> Optional["OpenAI"]:
    if not HAS_OPENAI:
        return None
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    base_url = os.getenv("OPENAI_BASE_URL", "").strip() or None
    return OpenAI(api_key=api_key, base_url=base_url)


def _auto_input_path(input_path: str) -> Optional[Path]:
    if input_path:
        p = Path(input_path)
        return p if p.exists() else None
    processed = Path("data/processed")
    candidates = sorted(processed.glob("posts_labeled_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        return candidates[0]
    cleaned = processed / "cleaned_posts.csv"
    if cleaned.exists():
        return cleaned
    return None


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    if "post_text" not in df.columns and "selftext" in df.columns:
        df = df.copy()
        df["post_text"] = df["selftext"]
    if "thread_title" not in df.columns and "title" in df.columns:
        df = df.copy()
        df["thread_title"] = df["title"]
    return df


def detect_issue_labels(text: str) -> List[str]:
    text = text or ""
    hits: List[str] = []
    for issue, regexes in COMPILED.items():
        if issue == "general_discussion":
            continue
        if any(r.search(text) for r in regexes):
            hits.append(issue)
    if not hits:
        hits = ["general_discussion"]
    return hits


def normalize_issue_labels(value: Any) -> List[str]:
    if isinstance(value, str):
        raw = re.split(r"[,;|/]+", value)
    elif isinstance(value, Iterable):
        raw = list(value)
    else:
        raw = []
    labels: List[str] = []
    for item in raw:
        key = str(item).strip().lower().replace("-", "_").replace(" ", "_")
        if key in ISSUE_TAXONOMY and key not in labels:
            labels.append(key)
    if len(labels) > 1 and "general_discussion" in labels:
        labels.remove("general_discussion")
    return labels


def llm_issue_system_prompt() -> str:
    return (
        "You are classifying Singapore telco forum comments into issue topics. "
        "Assign one or more issue labels from: network_quality, pricing_promotions, "
        "mobile_plans, roaming, porting, customer_service, billing_payment, "
        "app_account, devices, general_discussion. "
        "Use general_discussion only when no specific issue applies. "
        "Understand negation, sarcasm, Singlish, mixed opinions, quoted speech, "
        "and multiple telcos. Return only one JSON object with this shape: "
        '{"results":[{"sample_id":"...","issues":["..."]}]}. '
        "Include every sample_id exactly once."
    )


def llm_issue_user_prompt(rows: List[dict[str, str]], max_chars: int) -> str:
    payload = [
        {
            "sample_id": row["sample_id"],
            "thread_title": str(row.get("thread_title", ""))[:500],
            "post_text": str(row.get("post_text", ""))[:max_chars],
        }
        for row in rows
    ]
    return json.dumps({"items": payload}, ensure_ascii=False)


def parse_llm_issue_results(raw: str, expected_ids: set[str]) -> Dict[str, List[str]]:
    parsed = json.loads(raw)
    items = parsed.get("results") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        raise ValueError("LLM response must contain a results array")
    results: Dict[str, List[str]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        sample_id = str(item.get("sample_id", "")).strip()
        issues = normalize_issue_labels(item.get("issues", []))
        if sample_id not in expected_ids:
            continue
        if not issues:
            raise ValueError(f"Invalid labels returned for {sample_id}")
        if sample_id in results:
            raise ValueError(f"Duplicate result returned for {sample_id}")
        results[sample_id] = issues
    missing = expected_ids - set(results)
    if missing:
        raise ValueError(f"Missing results for: {', '.join(sorted(missing)[:8])}")
    return results


def llm_classify_issue(text: str, client: "OpenAI", model: str) -> List[str]:
    """Single-row fallback used only if batching is unavailable."""
    rows = [{"sample_id": "row-0", "thread_title": "", "post_text": text or ""}]
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": llm_issue_system_prompt()},
                {"role": "user", "content": llm_issue_user_prompt(rows, 2000)},
            ],
            temperature=0,
            max_tokens=200,
            response_format={"type": "json_object"},
        )
        raw = (response.choices[0].message.content or "").strip()
        parsed = parse_llm_issue_results(raw, {"row-0"})
        return parsed["row-0"]
    except Exception:
        return ["general_discussion"]


def _row_sample_id(row: pd.Series, index: int) -> str:
    comment_id = str(row.get("comment_id", "") or "").strip()
    post_id = str(row.get("post_id", "") or "").strip()
    if comment_id and comment_id.lower() not in {"nan", "none"}:
        return f"c:{comment_id}"
    if post_id and post_id.lower() not in {"nan", "none"}:
        return f"p:{post_id}:{index}"
    return f"r:{index}"


def _batches(items: List[Any], size: int) -> Iterable[List[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _load_checkpoint(path: Path) -> Dict[str, List[str]]:
    completed: Dict[str, List[str]] = {}
    if not path.exists():
        return completed
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            sample_id = str(item.get("sample_id", "")).strip()
            issues = normalize_issue_labels(item.get("issues", []))
            if sample_id and issues and not item.get("error"):
                completed[sample_id] = issues
    return completed


def _append_checkpoint(path: Path, rows: List[dict[str, Any]]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def call_issue_batch(
    client: "OpenAI",
    rows: List[dict[str, str]],
    model: str,
    max_text_chars: int,
    max_output_tokens: int,
    max_retries: int,
    retry_delay: float,
) -> Tuple[List[dict[str, Any]], dict[str, Any]]:
    expected_ids = {row["sample_id"] for row in rows}
    last_error = ""
    elapsed = 0.0
    for attempt in range(1, max_retries + 1):
        started = time.perf_counter()
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": llm_issue_system_prompt()},
                    {"role": "user", "content": llm_issue_user_prompt(rows, max_text_chars)},
                ],
                temperature=0,
                max_tokens=max_output_tokens,
                response_format={"type": "json_object"},
            )
            elapsed = time.perf_counter() - started
            raw = response.choices[0].message.content or ""
            parsed = parse_llm_issue_results(raw, expected_ids)
            usage = response.usage
            metadata = {
                "requested_model": model,
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
                    "issues": parsed[row["sample_id"]],
                    **metadata,
                }
                for row in rows
            ]
            return output, metadata
        except Exception as exc:
            elapsed = time.perf_counter() - started
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < max_retries:
                time.sleep(retry_delay * (2 ** (attempt - 1)))
    metadata = {
        "requested_model": model,
        "returned_model": "",
        "request_id": "",
        "attempts": max_retries,
        "elapsed_seconds": elapsed,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "error": last_error,
    }
    output = [
        {
            "sample_id": row["sample_id"],
            "issues": ["general_discussion"],
            **metadata,
        }
        for row in rows
    ]
    return output, metadata


def summarize_issues(df: pd.DataFrame) -> Dict:
    counts = Counter()
    by_telco = defaultdict(Counter)

    for _, row in df.iterrows():
        labels = [x.strip() for x in str(row.get("issue_labels", "")).split(",") if x.strip()]
        telcos = [x.strip() for x in str(row.get("telco_label", "")).split(",") if x.strip()]
        for label in labels:
            counts[label] += 1
            for telco in telcos:
                by_telco[telco][label] += 1

    return {
        "issue_counts": dict(counts),
        "issue_counts_by_telco": {k: dict(v) for k, v in by_telco.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract structured issue labels from post_text.")
    parser.add_argument("--in", dest="input_path", type=str, default="", help="Input CSV. Default: latest posts_labeled_*.csv.")
    parser.add_argument("--out", type=str, default="", help="Output CSV. Default: data/processed/issues_<inputname>.csv")
    parser.add_argument("--summary-out", type=str, default="data/processed/issues_summary.json", help="Output JSON summary path.")
    parser.add_argument("--use-llm", action="store_true", help="Use LLM for issue classification.")
    parser.add_argument("--llm-model", type=str, default="gpt-4o-mini", help="LLM model for issue classification.")
    parser.add_argument("--llm-unresolved-only", action="store_true", help="Use LLM only when rule-based result is 'general_discussion'.")
    parser.add_argument("--batch-size", type=int, default=10, help="Posts per LLM request.")
    parser.add_argument("--max-text-chars", type=int, default=2000)
    parser.add_argument("--max-output-tokens", type=int, default=1600)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=2.0)
    parser.add_argument("--checkpoint", type=str, default="", help="JSONL checkpoint for resumable LLM batches.")
    parser.add_argument("--resume", action="store_true", help="Resume from the checkpoint JSONL.")
    parser.add_argument("--input-cost-per-million", type=float, default=0.0)
    parser.add_argument("--output-cost-per-million", type=float, default=0.0)
    parser.add_argument("--dry-run", action="store_true", help="Count unresolved rows and planned batches without calling the API.")
    args = parser.parse_args()

    in_path = _auto_input_path(args.input_path)
    if not in_path:
        print("Error: No input CSV found. Pass --in or run telco_labeler first.")
        return

    df = pd.read_csv(in_path)
    df = normalize_columns(df)
    if "post_text" not in df.columns:
        print("Error: no post_text/selftext column found.")
        return

    # Rule-based first pass
    labels_col: List[List[str]] = [detect_issue_labels(str(t)) for t in df["post_text"].fillna("")]
    pending_indices = [
        i
        for i, labels in enumerate(labels_col)
        if (not args.llm_unresolved_only) or labels == ["general_discussion"]
    ]

    if args.use_llm:
        print(f"Rule-labeled rows: {len(labels_col)}")
        print(f"LLM candidate rows: {len(pending_indices)}")
        print(f"Planned LLM batches: {(len(pending_indices) + args.batch_size - 1) // args.batch_size}")
        print(f"Requested model: {args.llm_model}")
        if args.dry_run:
            print("Dry-run mode: no API calls made.")
            return

        client = get_llm_client()
        if not client:
            print("Warning: OPENAI_API_KEY not found or openai not installed. Falling back to rule-based only.")
        elif args.batch_size <= 0:
            print("Error: --batch-size must be positive.")
            return
        else:
            if args.checkpoint:
                checkpoint_path = Path(args.checkpoint)
            else:
                stem = in_path.stem
                checkpoint_path = Path(f"data/processed/llm_issues_{stem}_checkpoint.jsonl")
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            if checkpoint_path.exists() and not args.resume:
                checkpoint_path.unlink()
            completed = _load_checkpoint(checkpoint_path) if args.resume else {}

            pending_rows: List[Tuple[int, dict[str, str]]] = []
            for i in pending_indices:
                sample_id = _row_sample_id(df.iloc[i], i)
                if sample_id in completed:
                    labels_col[i] = completed[sample_id]
                    continue
                pending_rows.append(
                    (
                        i,
                        {
                            "sample_id": sample_id,
                            "thread_title": str(df.iloc[i].get("thread_title") or df.iloc[i].get("title") or ""),
                            "post_text": str(df.iloc[i].get("post_text") or ""),
                        },
                    )
                )

            input_tokens = 0
            output_tokens = 0
            failed_batches = 0
            started = time.perf_counter()
            for batch_number, batch in enumerate(_batches(pending_rows, args.batch_size), start=1):
                batch_payload = [item for _, item in batch]
                predictions, metadata = call_issue_batch(
                    client,
                    batch_payload,
                    args.llm_model,
                    args.max_text_chars,
                    args.max_output_tokens,
                    args.max_retries,
                    args.retry_delay,
                )
                _append_checkpoint(checkpoint_path, predictions)
                by_id = {row["sample_id"]: row["issues"] for row in predictions}
                for index, item in batch:
                    labels_col[index] = by_id.get(item["sample_id"], ["general_discussion"])
                input_tokens += int(metadata.get("input_tokens", 0) or 0)
                output_tokens += int(metadata.get("output_tokens", 0) or 0)
                if metadata.get("error"):
                    failed_batches += 1
                status = "ok" if not metadata.get("error") else f"failed: {metadata['error']}"
                print(
                    f"Batch {batch_number}: {len(batch)} rows, "
                    f"{metadata['elapsed_seconds']:.2f}s, {status}"
                )

            elapsed = time.perf_counter() - started
            input_cost = input_tokens / 1_000_000 * args.input_cost_per_million
            output_cost = output_tokens / 1_000_000 * args.output_cost_per_million
            print(
                f"LLM done: {len(pending_indices)} candidate rows, "
                f"{failed_batches} failed batches, {elapsed:.1f}s, "
                f"{input_tokens} in / {output_tokens} out, "
                f"est. ${input_cost + output_cost:.4f}"
            )

    df["issue_labels"] = [",".join(lbls) for lbls in labels_col]
    df["issue_primary"] = [lbls[0] if lbls else "general_discussion" for lbls in labels_col]

    if not args.out:
        stem = in_path.stem
        out_path = Path(f"data/processed/issues_{stem}.csv")
    else:
        out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")

    summary = summarize_issues(df)
    summary_path = Path(args.summary_out)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"Input:  {in_path}")
    print(f"Output: {out_path}")
    print(f"Summary: {summary_path}")
    print("Top issue counts:", summary.get("issue_counts", {}))


if __name__ == "__main__":
    main()

