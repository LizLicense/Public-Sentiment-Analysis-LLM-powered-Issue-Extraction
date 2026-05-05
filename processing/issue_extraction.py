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
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


ISSUE_TAXONOMY: Dict[str, List[str]] = {
    "pricing": [
        r"\bprice\b", r"\bpricing\b", r"\bcost\b", r"\bexpensive\b", r"\bcheap\b", r"\bvalue\b",
        r"\bplan\b", r"\bpromo\b", r"\bpromotion\b", r"\bdiscount\b", r"\bgb\b", r"\bunlimited\b",
    ],
    "network": [
        r"\bnetwork\b", r"\bcoverage\b", r"\bsignal\b", r"\bno signal\b", r"\b4g\b", r"\b5g\b",
        r"\bspeed\b", r"\bslow\b", r"\blatency\b", r"\bconnection\b", r"\bdata loss\b", r"\bdown\b",
    ],
    "customer_service": [
        r"\bcustomer service\b", r"\bcs\b", r"\bsupport\b", r"\bhotline\b", r"\bservice center\b",
        r"\bcomplain\b", r"\bcomplaint\b", r"\bbilling\b", r"\bcharged\b", r"\brefund\b",
    ],
    "porting": [
        r"\bport\b", r"\bporting\b", r"\bport in\b", r"\bport out\b", r"\bswitch\b", r"\btransfer number\b",
    ],
    "roaming": [
        r"\broaming\b", r"\bapac\b", r"\bidd\b", r"\boverseas\b", r"\binternational\b",
    ],
    "other": [],
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
        if issue == "other":
            continue
        if any(r.search(text) for r in regexes):
            hits.append(issue)
    if not hits:
        hits = ["other"]
    return hits


def llm_classify_issue(text: str, client: "OpenAI", model: str) -> List[str]:
    system = (
        "Classify telecom forum comments into issue categories. "
        "Allowed labels only: pricing, network, customer_service, porting, roaming, other. "
        "Return JSON array of 1-3 labels, no explanation."
    )
    user = f"Comment:\n{text[:1000]}\n\nReturn JSON array labels."
    try:
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0,
            max_tokens=80,
        )
        raw = (r.choices[0].message.content or "").strip()
        labels = json.loads(raw)
        if not isinstance(labels, list):
            return ["other"]
        valid = [str(x).strip() for x in labels if str(x).strip() in ISSUE_TAXONOMY]
        return valid[:3] if valid else ["other"]
    except Exception:
        return ["other"]


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
    parser.add_argument("--llm-unresolved-only", action="store_true", help="Use LLM only when rule-based result is 'other'.")
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

    # Optional LLM pass
    if args.use_llm:
        client = get_llm_client()
        if not client:
            print("Warning: OPENAI_API_KEY not found or openai not installed. Falling back to rule-based only.")
        else:
            for i, text in enumerate(df["post_text"].fillna("").astype(str).tolist()):
                if args.llm_unresolved_only and labels_col[i] != ["other"]:
                    continue
                labels_col[i] = llm_classify_issue(text, client, args.llm_model)

    df["issue_labels"] = [",".join(lbls) for lbls in labels_col]
    df["issue_primary"] = [lbls[0] if lbls else "other" for lbls in labels_col]

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

