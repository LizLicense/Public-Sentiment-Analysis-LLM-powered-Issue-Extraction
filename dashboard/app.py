#!/usr/bin/env python3
"""
Streamlit dashboard for telco sentiment + issue analysis.

Reads:
- data/processed/*gpt4o_hybrid.csv (preferred)
- else data/processed/issues_*.csv
- else data/processed/posts_labeled_*.csv
- else data/processed/cleaned_posts.csv
"""

from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.express as px
import streamlit as st

DATA_DIR = Path("data/processed")

ISSUE_DISPLAY = {
    "network_quality": "Network Quality",
    "pricing_promotions": "Pricing & Promotions",
    "mobile_plans": "Mobile Plans",
    "roaming": "Roaming",
    "porting": "Porting",
    "customer_service": "Customer Service",
    "billing_payment": "Billing & Payment",
    "app_account": "App & Account",
    "devices": "Devices",
    "general_discussion": "General Discussion",
}
ISSUE_ORDER = list(ISSUE_DISPLAY)
HUDDLE_ISSUES = ("network_quality", "app_account", "porting")
HUDDLE_THRESHOLD = 20


def issue_display_name(value: str) -> str:
    key = str(value or "").strip().lower().replace(" ", "_").replace("&", "and")
    aliases = {
        "network": "network_quality",
        "pricing": "pricing_promotions",
        "other": "general_discussion",
    }
    key = aliases.get(key, key)
    return ISSUE_DISPLAY.get(key, str(value or "General Discussion"))


def row_issue_keys(row: pd.Series) -> list[str]:
    keys: list[str] = []
    for raw in (row.get("issue_primary", ""), row.get("issue_labels", "")):
        for part in str(raw or "").split(","):
            key = part.strip()
            if key and key not in keys:
                keys.append(key)
    return keys or ["general_discussion"]


def is_huddle_row(row: pd.Series) -> bool:
    sentiment = str(row.get("sentiment_label", "")).strip().lower().replace(" ", "_")
    if sentiment not in {"not_happy", "negative"}:
        return False
    return any(key in HUDDLE_ISSUES for key in row_issue_keys(row))


def pick_latest_dataset() -> Optional[Path]:
    hybrid = sorted(
        DATA_DIR.glob("*gpt4o_hybrid.csv"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if hybrid:
        return hybrid[0]
    for pattern in ["issues_*.csv", "posts_labeled_*.csv", "cleaned_posts.csv"]:
        files = sorted(DATA_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            return files[0]
    return None


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    if "post_text" not in df.columns and "selftext" in df.columns:
        df = df.copy()
        df["post_text"] = df["selftext"]
    if "thread_title" not in df.columns and "title" in df.columns:
        df = df.copy()
        df["thread_title"] = df["title"]
    if "timestamp" not in df.columns and "created_utc" in df.columns:
        df = df.copy()
        df["timestamp"] = df["created_utc"]
    elif "timestamp" in df.columns and "created_utc" in df.columns:
        # Keep any existing timestamp, but backfill missing values from created_utc.
        df = df.copy()
        timestamp = df["timestamp"].astype(object)
        created_utc = df["created_utc"].astype(object)
        missing = timestamp.isna() | (timestamp.astype(str).str.strip() == "")
        # Replace the complete column so pandas 3 does not reject numeric epoch
        # values assigned into an Arrow-backed string column.
        df["timestamp"] = timestamp.where(~missing, created_utc)
    return df


def to_datetime_safe(s: pd.Series) -> pd.Series:
    # Handle epoch seconds (e.g. 1772882464.0) and ISO strings.
    if s is None:
        return pd.Series(dtype="datetime64[ns, UTC]")
    num = pd.to_numeric(s, errors="coerce")
    # If mostly numeric and in plausible Unix-seconds range, parse as seconds
    if num.notna().mean() > 0.6:
        valid = num.dropna()
        if not valid.empty and valid.between(946684800, 4102444800).mean() > 0.6:
            return pd.to_datetime(num, unit="s", errors="coerce", utc=True)
    return pd.to_datetime(s, errors="coerce", utc=True)


def ensure_required_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Guarantee core columns exist so UI code never KeyErrors."""
    if "telco_label" not in df.columns:
        df = df.copy()
        df["telco_label"] = "Unknown"
    if "sentiment_label" not in df.columns and "llm_sentiment_label" in df.columns:
        df = df.copy()
        df["sentiment_label"] = df["llm_sentiment_label"]
    if "sentiment_label" not in df.columns:
        df = df.copy()
        df["sentiment_label"] = "unknown"
    if "issue_primary" not in df.columns:
        df = df.copy()
        df["issue_primary"] = "general_discussion"
    if "source" not in df.columns:
        df = df.copy()
        df["source"] = "unknown"
    if "dt" not in df.columns:
        df = df.copy()
        df["dt"] = pd.NaT
    return df


def main() -> None:
    st.set_page_config(page_title="Telco Sentiment Dashboard", layout="wide")
    st.title("Telco Sentiment & Issue Dashboard")
    st.caption(
        "This dashboard is for a weekly 30-minute huddle, not a brand league table or CSAT score. "
        "VADER under-detects complaints. Issues are keyword rules, then GPT-4o on unresolved "
        "general_discussion rows. Never publish ranks from n = 6."
    )

    dataset = pick_latest_dataset()
    if not dataset:
        st.error("No processed CSV found in data/processed/. Run telco_labeler.py or issue_extraction.py first.")
        return

    st.caption(f"Using dataset: {dataset}")
    df = pd.read_csv(dataset)
    df = normalize_columns(df)

    if "post_text" not in df.columns:
        st.error("Dataset missing post_text/selftext column.")
        return

    df["dt"] = to_datetime_safe(df.get("timestamp", pd.Series(index=df.index, dtype=object)))
    df = ensure_required_columns(df)
    # Normalize filter-critical columns to avoid NaN/"unknown" mismatch
    df["source"] = df["source"].fillna("unknown").astype(str)
    df["sentiment_label"] = df["sentiment_label"].fillna("unknown").astype(str)
    df["telco_label"] = df["telco_label"].fillna("").astype(str)
    df["issue_primary"] = df["issue_primary"].fillna("general_discussion").astype(str)

    st.sidebar.header("Weekly huddle")
    huddle_mode = st.sidebar.checkbox(
        "Focus huddle queue",
        value=True,
        help="Keep only not-happy posts in Network Quality, App & Account, or Porting.",
    )
    huddle_threshold = st.sidebar.slider("Act only if queue n ≥", min_value=5, max_value=50, value=20, step=1)
    huddle_owner = st.sidebar.text_input("This week's owner", placeholder="Name / squad")

    st.sidebar.header("Filters")
    all_sources = sorted(df["source"].unique().tolist())
    selected_sources = st.sidebar.multiselect("Source", all_sources, default=all_sources)

    # explode telcos for filter
    telco_vals = sorted(
        {
            t.strip()
            for raw in df["telco_label"].fillna("").astype(str).tolist()
            for t in raw.split(",")
            if t.strip()
        }
    )
    selected_telcos = st.sidebar.multiselect("Telco", telco_vals, default=telco_vals[: min(6, len(telco_vals))] or telco_vals)

    sentiments = sorted(df["sentiment_label"].unique().tolist())
    selected_sentiments = st.sidebar.multiselect("Sentiment", sentiments, default=sentiments)

    issue_keys = []
    for raw in df["issue_primary"].tolist() + df.get("issue_labels", pd.Series(dtype=str)).fillna("").tolist():
        for part in str(raw).split(","):
            key = part.strip()
            if key and key not in issue_keys:
                issue_keys.append(key)
    issue_options = [key for key in ISSUE_ORDER if key in issue_keys]
    issue_options.extend(sorted(key for key in issue_keys if key not in ISSUE_ORDER))
    selected_issues = st.sidebar.multiselect(
        "Issue breakdown",
        issue_options,
        default=issue_options,
        format_func=issue_display_name,
    )

    if huddle_mode:
        selected_sentiments = [
            s for s in sentiments if str(s).strip().lower().replace(" ", "_") in {"not_happy", "negative"}
        ]
        selected_issues = [key for key in issue_options if key in HUDDLE_ISSUES]
        if not selected_sentiments:
            selected_sentiments = ["not_happy"]
        if not selected_issues:
            selected_issues = list(HUDDLE_ISSUES)

    # Date filter
    min_dt = df["dt"].min()
    max_dt = df["dt"].max()
    if pd.notna(min_dt) and pd.notna(max_dt):
        date_range = st.sidebar.date_input("Date range", value=(min_dt.date(), max_dt.date()))
    else:
        date_range = None

    # Apply filters
    f = ensure_required_columns(df.copy())
    if "source" in f.columns:
        f = f[f["source"].fillna("unknown").astype(str).isin(selected_sources)]
    if "sentiment_label" in f.columns:
        f = f[f["sentiment_label"].fillna("unknown").astype(str).isin(selected_sentiments)]
    if selected_telcos:
        f = f[f["telco_label"].fillna("").astype(str).apply(lambda s: any(t in [x.strip() for x in s.split(",")] for t in selected_telcos))]
    if selected_issues:
        selected_issue_set = set(selected_issues)
        f = f[f.apply(lambda row: any(key in selected_issue_set for key in row_issue_keys(row)), axis=1)]
    if "dt" in f.columns and date_range and len(date_range) == 2 and pd.notna(f["dt"]).any():
        start = pd.Timestamp(date_range[0], tz="UTC")
        end = pd.Timestamp(date_range[1], tz="UTC") + pd.Timedelta(days=1)
        f = f[(f["dt"] >= start) & (f["dt"] < end)]

    # Re-ensure after all filtering operations
    f = ensure_required_columns(f)

    st.subheader("How to use this dashboard — weekly 30-minute huddle")
    steps = st.columns(5)
    step_copy = [
        ("1. Queue", "Keep not-happy + Network / App / Porting. Act only if n ≥ the threshold."),
        ("2. Open 10", "Read ten source posts. Drop sarcasm, mixed-brand, and off-target labels."),
        ("3. Match", "Tie remaining posts to tickets, outages, or billing — not to a vibe."),
        ("4. One owner", "Assign a squad and a response date. No league table."),
        ("5. Next week", "Check whether that issue share fell. If not, escalate the same owner."),
    ]
    for col, (title, body) in zip(steps, step_copy):
        col.markdown(f"**{title}**")
        col.caption(body)
    st.warning("Never publish a brand league table from n = 6. Rank only brands with at least 10 mentions.")

    queue = f[f.apply(is_huddle_row, axis=1)] if not huddle_mode else f
    queue_n = len(queue)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Huddle queue", queue_n)
    m2.metric("Threshold", huddle_threshold)
    m3.metric("Decision", "Hold huddle" if queue_n >= huddle_threshold else "Do not escalate")
    m4.metric("Owner", huddle_owner.strip() or "Unassigned")
    if huddle_mode:
        st.info("Huddle focus is on: not-happy posts in Network Quality, App & Account, or Porting.")
    if queue_n >= huddle_threshold:
        st.success(f"Queue n = {queue_n} meets the threshold. Open 10 posts below, match tickets, assign one owner.")
    else:
        st.warning(
            f"Queue n = {queue_n} is below {huddle_threshold}. "
            "Do not treat this as an incident and do not rank brands from a handful of posts."
        )

    st.markdown("#### This week's 10 posts to open")
    huddle_cols = [
        c
        for c in ["source", "telco_label", "sentiment_label", "issue_primary", "timestamp", "thread_title", "post_text"]
        if c in queue.columns
    ]
    if queue_n == 0:
        st.info("No huddle-queue posts in the current filters.")
    else:
        review = queue.head(10)
        st.dataframe(review[huddle_cols], width="stretch")
        st.caption("These 10 are the huddle reading list. Models triage; people decide.")

    st.subheader("Overview")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rows", len(f))
    c2.metric("Sources", f["source"].nunique())
    c3.metric("Telcos", len({t.strip() for raw in f["telco_label"].fillna("").astype(str) for t in raw.split(",") if t.strip()}))
    if "dt" in f.columns and not f["dt"].isna().all():
        date_span = f"{f['dt'].min().date()} → {f['dt'].max().date()}"
    else:
        date_span = "N/A"
    c4.metric("Date span", date_span)

    # Charts
    left, right = st.columns(2)
    with left:
        st.markdown("#### Forum tone is a screen, not a CSAT score")
        sentiment_counts = f["sentiment_label"].fillna("unknown").value_counts().reset_index()
        sentiment_counts.columns = ["sentiment", "count"]
        fig = px.bar(sentiment_counts, x="sentiment", y="count", color="sentiment")
        st.plotly_chart(fig, width="stretch")
        st.caption(
            "Independent labels show VADER not-happy recall of 0.34. Treat a high happy share as an upper bound on positivity."
        )

    with right:
        st.markdown("#### Route App & Account and Network Quality first")
        issue_counts = (
            f["issue_primary"]
            .fillna("general_discussion")
            .map(issue_display_name)
            .value_counts()
            .reindex([ISSUE_DISPLAY[k] for k in ISSUE_ORDER], fill_value=0)
            .reset_index()
        )
        issue_counts.columns = ["issue", "count"]
        issue_counts = issue_counts[issue_counts["count"] > 0]
        fig = px.bar(issue_counts, x="issue", y="count", color="issue")
        fig.update_layout(xaxis_title="Issue", yaxis_title="Count")
        st.plotly_chart(fig, width="stretch")
        st.caption(
            "These are hybrid tags: keyword rules first, GPT-4o only on unresolved general_discussion. "
            "General Discussion is a residual, not a team. Filter the table and export rows for the owning squad."
        )

    st.markdown("#### Alert on a real volume jump, not a quiet week")
    if "dt" in f.columns and f["dt"].notna().any():
        tmp = f.dropna(subset=["dt"]).copy()
        tmp["week_start"] = tmp["dt"].dt.to_period("W").dt.start_time
        trend = tmp.groupby(["week_start", "sentiment_label"], as_index=False).size()
        trend.columns = ["week_start", "sentiment_label", "count"]
        trend = trend.sort_values("week_start")
        fig = px.line(trend, x="week_start", y="count", color="sentiment_label", markers=True)
        st.plotly_chart(fig, width="stretch")
        st.caption(
            "Flag a week only if not-happy share rises and that week has enough posts (for example n ≥ 20). "
            "A spike of three comments is not an incident."
        )
    else:
        st.info("No valid timestamps to plot trend.")

    st.markdown("#### Investigate large-n brands; do not publish a league table")
    exploded = []
    for _, row in f.iterrows():
        telcos = [t.strip() for t in str(row.get("telco_label", "")).split(",") if t.strip()]
        if not telcos:
            continue
        for t in telcos:
            exploded.append({"telco": t, "sentiment": str(row.get("sentiment_label", "unknown"))})
    if exploded:
        edf = pd.DataFrame(exploded)
        totals = edf.groupby("telco").size().rename("n")
        unhappy = (
            edf[edf["sentiment"].isin(["not_happy", "negative", "not happy"])]
            .groupby("telco")
            .size()
            .rename("not_happy")
        )
        rate = (
            pd.concat([totals, unhappy], axis=1)
            .fillna(0)
            .reset_index()
        )
        rate["not_happy_pct"] = (rate["not_happy"] / rate["n"] * 100).round(1)
        rate = rate[rate["n"] >= 10].sort_values("not_happy_pct", ascending=False)
        if rate.empty:
            st.info("No brand has at least 10 mentions in the current filter — do not publish a league table.")
        else:
            fig = px.bar(
                rate,
                x="telco",
                y="not_happy_pct",
                hover_data=["n", "not_happy"],
                labels={"not_happy_pct": "% not happy", "telco": "Brand"},
            )
            st.plotly_chart(fig, width="stretch")
            st.caption(
                "Hover for mention count. Brands below 10 mentions are hidden. Never publish a league table from n = 6."
            )
    else:
        st.info("No telco labels found for comparison.")

    st.markdown("#### Sample rows — inspect before acting")
    show_cols = [c for c in ["source", "telco_label", "sentiment_label", "issue_primary", "timestamp", "thread_title", "post_text"] if c in f.columns]
    st.dataframe(f[show_cols].head(200), width="stretch")
    st.caption("Open the posts behind any chart spike. Models triage; people decide.")


if __name__ == "__main__":
    main()

