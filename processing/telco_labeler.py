import argparse
import json
import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

OUTPUT_DIR = "data/processed"

import pandas as pd

# Sentiment: pip install vaderSentiment
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    HAS_VADER = True
except ImportError:
    HAS_VADER = False

# LLM (ChatGPT / OpenAI-compatible): pip install openai
try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


# ----------------------------
# Telco detection logic
# ----------------------------

TELCO_PATTERNS: Dict[str, List[str]] = {
    # Major MNOs
    "Starhub": [
        r"\bstarhub\b",
        r"\bstar hub\b",
        r"\bstar plan\b",
        r"\bheya\b",
    ],
    "Singtel": [
        r"\bsingtel\b",
        r"\bsing tel\b",
    ],
    "M1": [
        r"\bm1\b",
        r"\bm1 maxx\b",
        r"\bmaxx\.sg\b",
        r"\bmaxx\b",
    ],
    "SIMBA": [
        r"\bsimba\b",
        r"\btpg\b",
    ],
    # MVNOs and brands explicitly seen in the data
    "Eight": [
        r"\beight\s+(?:telecom|telco|mobile|sim(?:-only)?|plan)\b",
        r"\b(?:telecom|telco|mobile|mvno)\s+(?:brand\s+)?eight\b",
        r"\beight\.sg\b",
    ],
    "Zym": [
        r"\bzym\b",
        r"\bzym\.sg\b",
    ],
    "Giga": [
        r"\bgiga\b",
    ],
    "redONE": [
        r"\bredone\b",
        r"\bred one\b",
    ],
}


COMPILED_PATTERNS: Dict[str, re.Pattern] = {
    telco: re.compile("|".join(pats), flags=re.IGNORECASE)
    for telco, pats in TELCO_PATTERNS.items()
}

EIGHT_CONTEXT_TERMS = (
    r"telco|telecom|mobile|mvno|sim(?:-only)?|plan|network|roaming|"
    r"port(?:ing)?|data|gb|4g|5g|starhub|singtel|m1|simba|giga|zym"
)
EIGHT_CONTEXT_PATTERN = re.compile(
    rf"(?:\beight\b.{{0,60}}\b(?:{EIGHT_CONTEXT_TERMS})\b|"
    rf"\b(?:{EIGHT_CONTEXT_TERMS})\b.{{0,60}}\beight\b)",
    flags=re.IGNORECASE | re.DOTALL,
)
EIGHT_NON_BRAND_PATTERN = re.compile(
    r"\beight(?:\s+|-)(?:"
    r"buses?|people|persons?|years?|months?|weeks?|days?|hours?|minutes?|seconds?|"
    r"times?|students?|workers?|cars?|teams?|points?|seats?|stations?|stops?|"
    r"cases?|episodes?|members?|children|men|women"
    r")\b",
    flags=re.IGNORECASE,
)


def is_eight_telco_reference(text: Optional[str]) -> bool:
    """Return True only when 'Eight' is used as a telco brand."""
    if not isinstance(text, str) or not re.search(r"\beight\b", text, re.IGNORECASE):
        return False

    strong_brand_pattern = COMPILED_PATTERNS["Eight"]
    if strong_brand_pattern.search(text):
        return True

    # Explicit count/transport phrases take precedence over generic context
    # elsewhere in the same title or comment.
    if EIGHT_NON_BRAND_PATTERN.search(text):
        return False

    return bool(EIGHT_CONTEXT_PATTERN.search(text))


def detect_telcos(text: Optional[str]) -> List[str]:
    if not isinstance(text, str) or not text:
        return []
    hits: List[str] = []
    for telco, pattern in COMPILED_PATTERNS.items():
        if telco == "Eight":
            if is_eight_telco_reference(text):
                hits.append(telco)
        elif pattern.search(text):
            hits.append(telco)
    return hits


def assign_telco(row: pd.Series) -> Optional[str]:
    """
    Decide which telco(s) a post is about using both thread_title and post_text.
    - If none detected -> None
    - If one detected  -> telco name
    - If multiple      -> comma-separated list preserving detection order
    """
    title = row.get("thread_title", "")
    text = row.get("post_text", "")

    title_telcos = detect_telcos(title)
    text_telcos = detect_telcos(text)
    combined_text = f"{title} {text}"
    combined_eight = (
        ["Eight"]
        if "Eight" not in title_telcos + text_telcos
        and is_eight_telco_reference(combined_text)
        else []
    )

    # Preserve order but deduplicate
    combined: List[str] = []
    for t in title_telcos + text_telcos + combined_eight:
        if t not in combined:
            combined.append(t)

    if not combined:
        return None
    if len(combined) == 1:
        return combined[0]
    return ",".join(combined)


# ----------------------------
# Sentiment analysis (happy / not happy)
# ----------------------------

def _get_analyzer():
    if not HAS_VADER:
        return None
    return SentimentIntensityAnalyzer()


def sentiment_for_text(text: Optional[str], analyzer) -> Tuple[Optional[str], Optional[float]]:
    """
    Returns (sentiment_label, compound_score).
    sentiment_label: "happy" | "not_happy" | "neutral"
    compound_score: -1 to 1 (None if no analyzer or empty text).
    """
    if not analyzer or not isinstance(text, str) or not text.strip():
        return None, None
    try:
        scores = analyzer.polarity_scores(text)
        compound = scores["compound"]
        if compound >= 0.05:
            return "happy", round(compound, 4)
        if compound <= -0.05:
            return "not_happy", round(compound, 4)
        return "neutral", round(compound, 4)
    except Exception:
        return None, None


# ----------------------------
# Summary: top keywords/themes per telco
# ----------------------------

# Simple English stopwords (subset) so we don't need nltk
STOPWORDS = frozenset(
    "a an and are as at be by for from has he in is it its of on that the to was were will with "
    "this your please log verify age view post why login register".split()
)


def _tokenize_for_summary(text: str) -> List[str]:
    """Lowercase, keep only letters, split, drop short and stopwords."""
    if not text:
        return []
    text = re.sub(r"[^a-zA-Z\s]", " ", text).lower()
    words = [w for w in text.split() if len(w) >= 2 and w not in STOPWORDS]
    return words


def top_keywords_per_telco(
    df: pd.DataFrame,
    telco_col: str = "telco_label",
    text_col: str = "post_text",
    top_n: int = 15,
) -> Dict[str, List[Tuple[str, int]]]:
    """
    For each telco (including each part of comma-separated labels), collect all
    post_text, tokenize, and return top_n most common words per telco.
    Returns dict: telco -> [(word, count), ...].
    """
    by_telco: Dict[str, List[str]] = {}
    for _, row in df.iterrows():
        telcos_raw = row.get(telco_col)
        text = row.get(text_col) or ""
        if pd.isna(telcos_raw) or not str(telcos_raw).strip():
            continue
        words = _tokenize_for_summary(str(text))
        if not words:
            continue
        for telco in [t.strip() for t in str(telcos_raw).split(",") if t.strip()]:
            by_telco.setdefault(telco, []).extend(words)

    result: Dict[str, List[Tuple[str, int]]] = {}
    for telco, words in by_telco.items():
        result[telco] = Counter(words).most_common(top_n)
    return result


def sentiment_summary_per_telco(
    df: pd.DataFrame,
    telco_col: str = "telco_label",
    sentiment_col: str = "sentiment_label",
) -> Dict[str, Dict[str, int]]:
    """
    For each telco (split comma-separated), count happy / not_happy / neutral.
    Returns dict: telco -> {"happy": n, "not_happy": n, "neutral": n}.
    """
    counts: Dict[str, Counter] = {}
    for _, row in df.iterrows():
        telcos_raw = row.get(telco_col)
        sent = row.get(sentiment_col)
        if pd.isna(telcos_raw) or pd.isna(sent):
            continue
        sent_str = str(sent).strip()
        for telco in [t.strip() for t in str(telcos_raw).split(",") if t.strip()]:
            c = counts.setdefault(telco, Counter())
            c[sent_str] = c.get(sent_str, 0) + 1
    return {telco: dict(c) for telco, c in counts.items()}


# ----------------------------
# LLM (OpenAI / ChatGPT compatible) for smarter results
# ----------------------------

# WARNING: Hard-coding API keys is insecure. Only do this in a private environment
# and NEVER commit your real key to git or share this file.
#
# For sentiment/summary we need an OpenAI-compatible CHAT API (e.g. OpenAI, Azure).
# Cursor Cloud Agents API is for repo/code tasks only and does NOT provide chat completions.
HARDCODED_OPENAI_API_KEY = ""  # e.g. "sk-xxx..." (OpenAI or compatible provider)
HARDCODED_OPENAI_BASE_URL = None  # e.g. "https://api.openai.com/v1" (None = default OpenAI)


def get_llm_client():
    """
    Build OpenAI client for LLM chat completions (sentiment + summary).
    Uses an OpenAI-compatible endpoint only. Cursor Cloud Agents API cannot be used here.
    """
    if not HAS_OPENAI:
        return None

    # 1) Hard-coded key (OpenAI or compatible)
    if HARDCODED_OPENAI_API_KEY:
        return OpenAI(
            api_key=HARDCODED_OPENAI_API_KEY,
            base_url=HARDCODED_OPENAI_BASE_URL or None,
        )

    # 2) Environment variables
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL") or None

    # 3) Fallback to local config file if env vars are not set
    if not api_key:
        cfg_path = Path(__file__).with_name("llm_config.json")
        if cfg_path.exists():
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                api_key = cfg.get("api_key") or api_key
                base_url = cfg.get("base_url") or base_url
            except Exception as e:
                print(f"Warning: Failed to read llm_config.json: {e}")

    if not api_key:
        return None

    return OpenAI(api_key=api_key, base_url=base_url or None)


def _truncate(text: str, max_chars: int = 400) -> str:
    if not text or len(text) <= max_chars:
        return (text or "").strip()
    return text[: max_chars - 3].rsplit(maxsplit=1)[0] + "..."


def llm_summarize_telco(telco: str, post_excerpts: List[str], client, model: str) -> Optional[str]:
    """
    Ask LLM for a short summary of what commenters are saying about this telco.
    """
    if not post_excerpts or not client:
        return None
    # Limit total input size
    max_excerpts = 25
    excerpt_len = 350
    excerpts = [_truncate(s, excerpt_len) for s in post_excerpts[:max_excerpts]]
    block = "\n\n---\n\n".join(f"[{i+1}] {e}" for i, e in enumerate(excerpts))

    system = (
        "You are summarizing forum comments about telecom providers in Singapore. "
        "Output 2-4 short sentences only: overall sentiment toward the telco, main themes (pricing, coverage, porting, etc.), and any common complaints or praise. Be concise and neutral."
    )
    user = (
        f"Telco: {telco}\n\nBelow are forum comment excerpts. Summarize what commenters are saying about {telco}.\n\n{block}"
    )

    try:
        r = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=300,
            temperature=0.3,
        )
        if r.choices and r.choices[0].message.content:
            return r.choices[0].message.content.strip()
    except Exception as e:
        print(f"  LLM summary error ({telco}): {e}")
    return None


def llm_sentiment_batch(texts: List[str], client, model: str) -> List[str]:
    """
    Ask LLM to classify sentiment for a batch of short texts.
    Returns list of "happy" | "not_happy" | "neutral" (one per input; same order).
    """
    if not texts or not client:
        return ["neutral"] * len(texts)
    numbered = "\n".join(f"{i+1}. {_truncate(t, 200)}" for i, t in enumerate(texts))
    system = (
        "You classify sentiment of forum comments about telecoms. For each numbered line, output exactly one word: happy, not_happy, or neutral. "
        "happy = satisfied, positive, recommending. not_happy = frustrated, complaining, negative. neutral = factual, mixed, or unclear. "
        "Reply with only the labels, one per line, same order as the input (e.g. happy\\nneutral\\nnot_happy)."
    )
    user = f"Classify each comment:\n{numbered}"

    try:
        r = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=min(500, len(texts) * 15),
            temperature=0,
        )
        raw = (r.choices[0].message.content or "").strip()
        labels = []
        for line in raw.splitlines():
            line = line.strip().lower()
            if "not_happy" in line or "not happy" in line:
                labels.append("not_happy")
            elif "happy" in line and "not" not in line:
                labels.append("happy")
            else:
                labels.append("neutral")
        # Pad or trim to match input length
        while len(labels) < len(texts):
            labels.append("neutral")
        return labels[: len(texts)]
    except Exception as e:
        print(f"  LLM sentiment batch error: {e}")
        return ["neutral"] * len(texts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Label HWZ telco posts with telco, sentiment (happy/not happy), and per-telco summary.",
    )
    parser.add_argument(
        "--in",
        dest="input_path",
        type=str,
        default="data/raw/posts.csv",
        help="Input CSV of posts from any scraper (default: data/raw/posts.csv). Use one file or combine HWZ/Reddit CSVs.",
    )
    parser.add_argument(
        "--out",
        dest="output_path",
        type=str,
        default=None,
        help="Output CSV path. If not set, writes to data/processed/ with timestamp in filename.",
    )
    parser.add_argument(
        "--summary-out",
        dest="summary_path",
        type=str,
        default=None,
        help="Output summary JSON path. If not set, writes to data/processed/ with timestamp in filename.",
    )
    parser.add_argument(
        "--no-sentiment",
        action="store_true",
        help="Skip sentiment analysis (e.g. if vaderSentiment not installed).",
    )
    parser.add_argument(
        "--top-keywords",
        type=int,
        default=15,
        help="Number of top keywords per telco in summary (default: 15).",
    )
    # LLM options (OpenAI / ChatGPT compatible)
    parser.add_argument(
        "--use-llm-summary",
        action="store_true",
        help="Use LLM (e.g. ChatGPT) to generate a short text summary per telco. Set OPENAI_API_KEY (and optional OPENAI_BASE_URL).",
    )
    parser.add_argument(
        "--use-llm-sentiment",
        action="store_true",
        help="Use LLM to classify sentiment per post (happy/not_happy/neutral). Set OPENAI_API_KEY; batches requests to save cost.",
    )
    parser.add_argument(
        "--llm-model",
        type=str,
        default="gpt-4o-mini",
        help="Model for LLM calls, e.g. gpt-4o-mini, gpt-4o, gpt-3.5-turbo (default: gpt-4o-mini).",
    )
    parser.add_argument(
        "--llm-sentiment-batch-size",
        type=int,
        default=15,
        help="Number of posts per LLM call for sentiment (default: 15).",
    )

    args = parser.parse_args()

    # Default: save to output/ with timestamp in filename
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = Path(OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.output_path is None:
        args.output_path = str(out_dir / f"posts_labeled_{ts}.csv")
    if args.summary_path is None:
        args.summary_path = str(out_dir / f"summary_{ts}.json")

    input_path = Path(args.input_path)
    if not input_path.exists():
        # Auto-pick most recent CSV in data/raw/ so you don't have to type --in every time
        raw_dir = Path("data/raw")
        if raw_dir.exists():
            all_csvs = sorted(raw_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
            raw_csvs = [c for c in all_csvs if "labeled" not in c.name.lower() and "summary" not in c.name.lower()]
            chosen = raw_csvs[0] if raw_csvs else (all_csvs[0] if all_csvs else None)
            if chosen:
                input_path = chosen
                args.input_path = str(input_path)
                print(f"Using latest CSV in data/raw/: {input_path.name}")
    if not input_path.exists():
        print(f"Error: No input file found. Put a posts CSV in data/raw/ or pass --in path/to/file.csv")
        return

    df = pd.read_csv(args.input_path)

    # Normalize columns so HWZ and Reddit CSVs both work (Reddit uses title/selftext)
    if "post_text" not in df.columns and "selftext" in df.columns:
        df["post_text"] = df["selftext"]
    if "thread_title" not in df.columns and "title" in df.columns:
        df["thread_title"] = df["title"]

    # 1) Telco label
    df["telco_label"] = df.apply(assign_telco, axis=1)

    # 2) Sentiment (VADER by default; optionally overwritten by LLM)
    if not args.no_sentiment and HAS_VADER:
        analyzer = _get_analyzer()
        sentiment_results = df["post_text"].apply(lambda t: sentiment_for_text(t, analyzer))
        df["sentiment_label"] = [r[0] for r in sentiment_results]
        df["sentiment_score"] = [r[1] for r in sentiment_results]
    else:
        df["sentiment_label"] = None
        df["sentiment_score"] = None
        if not args.no_sentiment and not HAS_VADER:
            print("Note: Install vaderSentiment for sentiment: pip install vaderSentiment")

    # 2b) Optional: LLM sentiment (overwrites or adds llm_sentiment_label)
    llm_client = get_llm_client() if HAS_OPENAI else None
    if args.use_llm_sentiment and llm_client:
        batch_size = max(1, args.llm_sentiment_batch_size)
        texts = df["post_text"].fillna("").astype(str).tolist()
        all_labels = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            labels = llm_sentiment_batch(batch, llm_client, args.llm_model)
            all_labels.extend(labels)
        df["llm_sentiment_label"] = all_labels[: len(df)]
        print(f"LLM sentiment done for {len(df)} posts (model={args.llm_model}).")
    elif args.use_llm_sentiment and not llm_client:
        print("Skipping --use-llm-sentiment: set OPENAI_API_KEY and install openai (pip install openai).")

    Path(args.output_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output_path, index=False, encoding="utf-8-sig")
    print(f"Read  {len(df)} rows from {args.input_path}")
    print(f"Wrote {len(df)} rows to {args.output_path} (telco_label + sentiment)")

    # 3) Per-telco summary: sentiment counts + top keywords + optional LLM summary
    summary = {}
    sentiment_col = "llm_sentiment_label" if (args.use_llm_sentiment and "llm_sentiment_label" in df.columns) else "sentiment_label"
    if not args.no_sentiment or (args.use_llm_sentiment and "llm_sentiment_label" in df.columns):
        sent_by_telco = sentiment_summary_per_telco(df, "telco_label", sentiment_col)
        summary["sentiment_by_telco"] = sent_by_telco
    keywords_by_telco = top_keywords_per_telco(df, "telco_label", "post_text", top_n=args.top_keywords)
    summary["top_keywords_by_telco"] = {k: v for k, v in keywords_by_telco.items()}

    if args.use_llm_summary and llm_client:
        summary["llm_summary_by_telco"] = {}
        telcos = sorted({t.strip() for tl in df["telco_label"].dropna().astype(str) for t in tl.split(",") if t.strip()})
        for telco in telcos:
            excerpts = df.loc[df["telco_label"].astype(str).str.contains(re.escape(telco), na=False), "post_text"].dropna().astype(str).tolist()
            s = llm_summarize_telco(telco, excerpts, llm_client, args.llm_model)
            if s:
                summary["llm_summary_by_telco"][telco] = s
                print(f"  LLM summary: {telco}")
        print("LLM per-telco summaries done.")
    elif args.use_llm_summary and not llm_client:
        print("Skipping --use-llm-summary: set OPENAI_API_KEY and install openai (pip install openai).")

    summary_path = Path(args.summary_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"Wrote per-telco summary to {summary_path}")

    # Console summary
    if summary.get("sentiment_by_telco"):
        print("\n--- Sentiment by telco (happy / not_happy / neutral) ---")
        for telco, counts in sorted(summary["sentiment_by_telco"].items()):
            total = sum(counts.values())
            parts = [f"{label}: {c}" for label, c in sorted(counts.items())]
            print(f"  {telco}: total={total} | " + " | ".join(parts))
    print("\n--- Top keywords per telco ---")
    for telco, kws in sorted(summary["top_keywords_by_telco"].items()):
        words = [w for w, _ in kws[:10]]
        print(f"  {telco}: " + ", ".join(words))
    if summary.get("llm_summary_by_telco"):
        print("\n--- LLM summary per telco ---")
        for telco, s in sorted(summary["llm_summary_by_telco"].items()):
            print(f"  {telco}: {s[:200]}{'...' if len(s) > 200 else ''}")


if __name__ == "__main__":
    main()

