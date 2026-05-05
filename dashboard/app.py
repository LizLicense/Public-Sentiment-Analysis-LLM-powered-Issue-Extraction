#!/usr/bin/env python3
"""
Streamlit dashboard for telco sentiment + issue analysis.

Reads:
- data/processed/issues_*.csv (preferred)
- else data/processed/posts_labeled_*.csv
- else data/processed/cleaned_posts.csv
"""

from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.express as px
import streamlit as st

DATA_DIR = Path("data/processed")


def pick_latest_dataset() -> Optional[Path]:
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
        missing = df["timestamp"].isna() | (df["timestamp"].astype(str).str.strip() == "")
        df.loc[missing, "timestamp"] = df.loc[missing, "created_utc"]
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
        df["issue_primary"] = "other"
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
    df["issue_primary"] = df["issue_primary"].fillna("other").astype(str)

    # Sidebar filters
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
    if "dt" in f.columns and date_range and len(date_range) == 2 and pd.notna(f["dt"]).any():
        start = pd.Timestamp(date_range[0], tz="UTC")
        end = pd.Timestamp(date_range[1], tz="UTC") + pd.Timedelta(days=1)
        f = f[(f["dt"] >= start) & (f["dt"] < end)]

    # Re-ensure after all filtering operations
    f = ensure_required_columns(f)

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
        st.markdown("#### Sentiment distribution")
        sentiment_counts = f["sentiment_label"].fillna("unknown").value_counts().reset_index()
        sentiment_counts.columns = ["sentiment", "count"]
        fig = px.bar(sentiment_counts, x="sentiment", y="count", color="sentiment")
        st.plotly_chart(fig, use_container_width=True)

    with right:
        st.markdown("#### Issue breakdown")
        issue_counts = f["issue_primary"].fillna("other").value_counts().reset_index()
        issue_counts.columns = ["issue", "count"]
        fig = px.bar(issue_counts, x="issue", y="count", color="issue")
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Temporal trend")
    if "dt" in f.columns and f["dt"].notna().any():
        tmp = f.dropna(subset=["dt"]).copy()
        tmp["week_start"] = tmp["dt"].dt.to_period("W").dt.start_time
        trend = tmp.groupby(["week_start", "sentiment_label"], as_index=False).size()
        trend.columns = ["week_start", "sentiment_label", "count"]
        trend = trend.sort_values("week_start")
        fig = px.line(trend, x="week_start", y="count", color="sentiment_label", markers=True)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No valid timestamps to plot trend.")

    st.markdown("#### Cross-brand sentiment comparison")
    exploded = []
    for _, row in f.iterrows():
        telcos = [t.strip() for t in str(row.get("telco_label", "")).split(",") if t.strip()]
        if not telcos:
            continue
        for t in telcos:
            exploded.append({"telco": t, "sentiment": str(row.get("sentiment_label", "unknown"))})
    if exploded:
        edf = pd.DataFrame(exploded)
        cmp_df = edf.groupby(["telco", "sentiment"], as_index=False).size()
        cmp_df.columns = ["telco", "sentiment", "count"]
        fig = px.bar(cmp_df, x="telco", y="count", color="sentiment", barmode="group")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No telco labels found for comparison.")

    st.markdown("#### Sample rows")
    show_cols = [c for c in ["source", "telco_label", "sentiment_label", "issue_primary", "timestamp", "thread_title", "post_text"] if c in f.columns]
    st.dataframe(f[show_cols].head(200), use_container_width=True)


if __name__ == "__main__":
    main()

