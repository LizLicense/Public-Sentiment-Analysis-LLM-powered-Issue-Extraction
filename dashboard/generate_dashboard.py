#!/usr/bin/env python3
"""
Regenerate dashboard/index.html and dashboard/Dash_README.md from labeled CSVs.

Default inputs:
  - data/processed/labeled_sample.csv   (Reddit)
  - hwz_telco_posts_labeled.csv         (HWZ, project root)

Usage (from project root):
  python dashboard/generate_dashboard.py
  python dashboard/generate_dashboard.py --reddit data/processed/labeled_sample.csv --hwz hwz_telco_posts_labeled.csv
"""

from __future__ import annotations

import argparse
import csv
import html
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = Path(__file__).resolve().parent

TELCO_KEYWORDS = [
    "singtel", "starhub", "m1", "simba", "giga", "eight", "zym",
    "redone", "gomo", "circles", "vivifi", "myrepublic", "maxx", "heya", "zero1", "povo",
]

BRAND_MAP = [
    ("singtel", "Singtel"), ("starhub", "StarHub"), ("m1", "M1"), ("simba", "SIMBA"),
    ("giga", "Giga"), ("eight", "Eight"), ("zym", "Zym"), ("redone", "redONE"),
    ("gomo", "GOMO"), ("circles", "Circles"), ("vivifi", "Vivifi"),
    ("myrepublic", "MyRepublic"), ("maxx", "Maxx"), ("heya", "Heya"), ("zero1", "Zero1"),
]

ISSUE_KW = {
    "pricing": r"\b(price|pricing|cheap|expensive|cost|fee|plan|gb|mvno|subscription|promo|discount|value|mth|month)\b|\$\d|s\$",
    "network": r"\b(signal|coverage|speed|slow|lte|5g|network|dead spot|dark spot|drop|latency|bandwidth|apn|connection|priority|tier)\b",
    "customer_service": r"\b(customer service|support|hotline|agent|complain|frustrat|scam|refund|billing|charge|contract|notice|outage|disabled)\b",
    "porting": r"\b(port|porting|port out|port in|switch|transfer number|mnp)\b",
    "roaming": r"\b(roam|roaming|malaysia|overseas|travel|idd|international data|apac|worldwide)\b",
}

ISSUE_LABELS = ["other", "pricing", "network", "customer_service", "roaming", "porting"]
ISSUE_DISPLAY = {
    "other": "Other",
    "pricing": "Pricing",
    "network": "Network",
    "customer_service": "Customer service",
    "roaming": "Roaming",
    "porting": "Porting",
}
ISSUE_COLORS = {
    "other": "#64748b",
    "pricing": "#f59e0b",
    "network": "#8b5cf6",
    "customer_service": "#ec4899",
    "roaming": "#14b8a6",
    "porting": "#06b6d4",
}

BRAND_TOP_ISSUE_HINTS = {
    "Eight": "Launch pricing, tiering, porting",
    "StarHub": "Pricing, CS, promo fulfilment",
    "M1": "Network coverage, 4G/5G",
    "Singtel": "ONR/bridge mode, equipment",
    "Zym": "Promotional plan posts",
    "Giga": "Network reliability (small n)",
    "SIMBA": "MVNO price benchmark",
    "GOMO": "Roaming, host-network",
}


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def normalize_row(row: dict, source: str) -> dict:
    sentiment = (
        row.get("sentiment_label")
        or row.get("sentiment_label_manual")
        or row.get("llm_sentiment_label")
        or ""
    ).strip()
    issue = (row.get("issue_primary") or row.get("issue_manual") or "").strip()
    return {
        "source": source,
        "telco_label": (row.get("telco_label") or row.get("telco_mentioned") or "").strip(),
        "sentiment": sentiment,
        "issue_primary": issue,
        "thread_title": (row.get("thread_title") or row.get("title") or "").strip(),
        "post_text": (row.get("post_text") or row.get("selftext") or "").strip(),
    }


def is_telco_relevant(row: dict) -> bool:
    label = row["telco_label"].lower()
    combined = f"{label} {row['post_text'].lower()} {row['thread_title'].lower()}"
    if label:
        return True
    return any(k in combined for k in TELCO_KEYWORDS)


def norm_sentiment(s: str) -> str:
    s = (s or "").lower().strip()
    if s in ("happy", "positive"):
        return "happy"
    if s in ("not_happy", "negative", "not happy"):
        return "not_happy"
    if s == "neutral":
        return "neutral"
    return ""


def infer_sentiment(text: str) -> str:
    s = (text or "").lower()
    neg = len(re.findall(
        r"\b(bad|poor|terrible|awful|frustrat|hate|suck|shit|scam|issue|problem|no thanks|cancel|worst|disappoint|unable|greedy)\b",
        s,
    ))
    pos = len(re.findall(
        r"\b(good|great|awesome|fine|no problem|no issue|happy|love|recommend|promising|lucky|excellent|smooth|works|reliable)\b",
        s,
    ))
    if neg > pos:
        return "not_happy"
    if pos > neg:
        return "happy"
    return "neutral"


def infer_issue(text: str, title: str = "") -> str:
    combined = f"{text} {title}".lower()
    scores = {k: len(re.findall(v, combined, re.I)) for k, v in ISSUE_KW.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "other"


def split_brands(label: str, text: str = "", title: str = "") -> list[str]:
    found: list[str] = []
    if label:
        for part in re.split(r"[,;/|&]+", label):
            pl = part.strip().lower().replace(" ", "")
            for key, name in BRAND_MAP:
                if key in pl:
                    found.append(name)
                    break
    if not found:
        combined = f"{text} {title}".lower()
        for key, name in BRAND_MAP:
            if key in combined:
                found.append(name)
    seen: set[str] = set()
    out: list[str] = []
    for b in found:
        if b not in seen:
            seen.add(b)
            out.append(b)
    return out


def pct(n: int, total: int) -> int:
    return round(100 * n / total) if total else 0


def short_quote(text: str, max_words: int = 22) -> str:
    text = re.sub(r"\s+", " ", html.unescape(text or "")).strip()
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "…"


def pick_quotes(rows: list[dict], n: int = 4) -> list[dict]:
    """Pick short, thematic quotes — prefer not_happy for pain, happy for roaming."""
    candidates: list[tuple[int, dict]] = []
    for row in rows:
        text = row["post_text"]
        if len(text) < 25 or len(text) > 400:
            continue
        if re.search(r"please log in|last edited:", text.lower()):
            continue
        score = 0
        if row["sentiment_final"] == "not_happy":
            score += 2
        if row["issue_final"] in ("network", "pricing", "customer_service", "porting"):
            score += 1
        if 40 <= len(text) <= 180:
            score += 1
        candidates.append((score, row))
    candidates.sort(key=lambda x: (-x[0], len(x[1]["post_text"])))
    seen: set[str] = set()
    quotes: list[dict] = []
    for _, row in candidates:
        q = short_quote(row["post_text"])
        if q in seen:
            continue
        seen.add(q)
        brands = ", ".join(split_brands(row["telco_label"], row["post_text"], row["thread_title"])[:3])
        quotes.append({
            "text": q,
            "source": row["source"].upper(),
            "context": brands or row["issue_final"],
        })
        if len(quotes) >= n:
            break
    return quotes


def build_executive_summary(stats: dict) -> str:
    s = stats["sentiment_pct"]
    src = stats["source_pct"]
    top_neg = stats["neg_brands"][:2]
    neg_names = " and ".join(b["brand"] for b in top_neg) if top_neg else "some MVNOs"
    least_neg = stats["brand_table"][-1]["brand"] if stats["brand_table"] else "Singtel"
    return (
        f"Forum discussion is <strong>moderately positive on balance</strong> (~{s['happy']}% happy), "
        f"but tone varies sharply by platform: Reddit is more complaint-driven "
        f"({src['reddit']['not_happy']}% negative) while HWZ skews toward launch/plan threads "
        f"({src['hwz']['not_happy']}% negative). "
        f"<strong>Pricing and MVNO value</strong> dominate conversation "
        f"({stats['issue_pct'].get('pricing', 0)}% of posts). "
        f"<strong>Network quality is location- and brand-tier-dependent</strong>; "
        f"customer-service friction drives negative spikes for StarHub and Singtel. "
        f"Among brands with enough mentions, <strong>{neg_names} attract the most scepticism</strong>, "
        f"while {least_neg} appears relatively less negative."
    )


def analyse(reddit_path: Path, hwz_path: Path) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    for path, source in [(reddit_path, "reddit"), (hwz_path, "hwz")]:
        if not path.exists():
            raise FileNotFoundError(f"Missing input: {path}")
        for raw in read_csv(path):
            rows.append(normalize_row(raw, source))

    telco_rows: list[dict] = []
    for row in rows:
        if not is_telco_relevant(row):
            continue
        row = dict(row)
        row["sentiment_final"] = norm_sentiment(row["sentiment"]) or infer_sentiment(row["post_text"])
        row["issue_final"] = row["issue_primary"] if row["issue_primary"] else infer_issue(
            row["post_text"], row["thread_title"]
        )
        telco_rows.append(row)

    n = len(telco_rows)
    sent_counts = Counter(r["sentiment_final"] for r in telco_rows)
    issue_counts = Counter(r["issue_final"] for r in telco_rows)

    source_rows = defaultdict(list)
    for r in telco_rows:
        source_rows[r["source"]].append(r)

    source_pct: dict[str, dict[str, int]] = {}
    for src, sub in source_rows.items():
        sc = Counter(r["sentiment_final"] for r in sub)
        ln = len(sub)
        source_pct[src] = {k: pct(sc[k], ln) for k in ("happy", "not_happy", "neutral")}
        source_pct[src]["n"] = ln

    brand_rows: dict[str, list[dict]] = defaultdict(list)
    for r in telco_rows:
        for b in split_brands(r["telco_label"], r["post_text"], r["thread_title"]):
            brand_rows[b].append(r)

    brand_mentions = sorted(brand_rows.items(), key=lambda x: -len(x[1]))
    neg_brands: list[dict] = []
    brand_table: list[dict] = []
    for brand, sub in brand_mentions:
        ln = len(sub)
        sc = Counter(r["sentiment_final"] for r in sub)
        neg = pct(sc["not_happy"], ln)
        ic = Counter(r["issue_final"] for r in sub)
        top_issues = ", ".join(ISSUE_DISPLAY.get(k, k) for k, _ in ic.most_common(2) if k != "other")
        brand_table.append({
            "brand": brand,
            "mentions": ln,
            "neg_pct": neg,
            "top_issues": BRAND_TOP_ISSUE_HINTS.get(brand, top_issues or "General discussion"),
        })
        if ln >= 5:
            neg_brands.append({"brand": brand, "neg_pct": neg, "mentions": ln})

    neg_brands.sort(key=lambda x: -x["neg_pct"])

    stats = {
        "n": n,
        "reddit_path": str(reddit_path.relative_to(ROOT)) if reddit_path.is_relative_to(ROOT) else str(reddit_path),
        "hwz_path": str(hwz_path.relative_to(ROOT)) if hwz_path.is_relative_to(ROOT) else str(hwz_path),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "sentiment_counts": {k: sent_counts[k] for k in ("happy", "not_happy", "neutral")},
        "sentiment_pct": {k: pct(sent_counts[k], n) for k in ("happy", "not_happy", "neutral")},
        "issue_counts": {k: issue_counts.get(k, 0) for k in ISSUE_LABELS},
        "issue_pct": {k: pct(issue_counts.get(k, 0), n) for k in ISSUE_LABELS},
        "source_pct": source_pct,
        "brand_mentions": [(b, len(sub)) for b, sub in brand_mentions[:10]],
        "neg_brands": neg_brands,
        "brand_table": [b for b in brand_table if b["mentions"] >= 5][:8],
        "n_brands": len(brand_rows),
        "n_sources": len(source_rows),
        "quotes": pick_quotes(telco_rows),
        "issues_inferred": not any(r["issue_primary"] for r in rows),
    }
    stats["exec_summary"] = build_executive_summary(stats)
    return telco_rows, stats


def render_readme(stats: dict) -> str:
    reddit_n = stats["source_pct"].get("reddit", {}).get("n", 0)
    hwz_n = stats["source_pct"].get("hwz", {}).get("n", 0)
    return f"""# Telco Sentiment Dashboard

Static HTML summary dashboard for Singapore telco forum sentiment analysis.

**Auto-generated:** {stats["generated_at"]}

## Generate / refresh

From project root:

```bash
python dashboard/generate_dashboard.py
```

Optional custom inputs:

```bash
python dashboard/generate_dashboard.py \\
  --reddit data/processed/labeled_sample.csv \\
  --hwz hwz_telco_posts_labeled.csv
```

Writes `dashboard/index.html` and this file.

## View

Open in any browser (no server required):

```bash
open dashboard/index.html
```

Or from the project root:

```bash
python3 -m http.server 8080
# then visit http://localhost:8080/dashboard/
```

## Contents

- **Executive summary** and KPI cards
- **Charts** (Chart.js): sentiment distribution, source comparison, issue themes, brand mentions, negative tone by brand
- **Per-telco table**, representative quotes, recommendations, limitations

## Data source

| File | Rows (telco-relevant) |
|------|----------------------|
| `{stats["reddit_path"]}` | {reddit_n} |
| `{stats["hwz_path"]}` | {hwz_n} |
| **Combined** | **{stats["n"]}** |

Sentiment: {stats["sentiment_pct"]["happy"]}% happy / {stats["sentiment_pct"]["not_happy"]}% not_happy / {stats["sentiment_pct"]["neutral"]}% neutral.

## Streamlit version

For an interactive filterable dashboard, run:

```bash
pip install streamlit plotly pandas
streamlit run dashboard/app.py
```
"""


def render_html(stats: dict) -> str:
    sc = stats["sentiment_counts"]
    sp = stats["sentiment_pct"]
    ic = stats["issue_counts"]
    issue_labels_js = [ISSUE_DISPLAY[k] for k in ISSUE_LABELS if k != "other"] + ["Other"]
    issue_order = ["pricing", "network", "customer_service", "roaming", "porting", "other"]
    issue_values = [ic[k] for k in issue_order]
    issue_colors = [ISSUE_COLORS[k] for k in issue_order]

    brand_labels = [b for b, _ in stats["brand_mentions"]]
    brand_values = [n for _, n in stats["brand_mentions"]]

    neg_brands = stats["neg_brands"]
    neg_labels = [b["brand"] for b in neg_brands]
    neg_rates = [b["neg_pct"] for b in neg_brands]

    reddit = stats["source_pct"].get("reddit", {"happy": 0, "not_happy": 0, "neutral": 0, "n": 0})
    hwz = stats["source_pct"].get("hwz", {"happy": 0, "not_happy": 0, "neutral": 0, "n": 0})

    table_rows = "\n".join(
        f'            <tr><td>{html.escape(r["brand"])}</td><td>{r["mentions"]}</td>'
        f'<td>{r["neg_pct"]}%</td><td>{html.escape(r["top_issues"])}</td></tr>'
        for r in stats["brand_table"]
    )

    quote_blocks = "\n".join(
        f"""        <blockquote>
          "{html.escape(q["text"])}"
          <div class="quote-source">{html.escape(q["source"])} &middot; {html.escape(q["context"])}</div>
        </blockquote>"""
        for q in stats["quotes"]
    )

    issue_note = (
        "Inferred from post_text (issue_primary not in Reddit export)"
        if stats["issues_inferred"]
        else "From issue_primary / issue_manual columns"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Singapore Telco Forum Sentiment Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    :root {{
      --bg: #0f1419; --surface: #1a2332; --surface-2: #243044; --border: #2d3a4f;
      --text: #e8edf4; --muted: #8b9cb3; --accent: #3b82f6;
      --happy: #22c55e; --not-happy: #ef4444; --neutral: #94a3b8;
      --radius: 12px; --shadow: 0 4px 24px rgba(0, 0, 0, 0.35);
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: "Segoe UI", system-ui, sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }}
    .page {{ max-width: 1280px; margin: 0 auto; padding: 2rem 1.5rem 4rem; }}
    header {{ margin-bottom: 2rem; padding-bottom: 1.5rem; border-bottom: 1px solid var(--border); }}
    header h1 {{ font-size: 1.75rem; font-weight: 700; margin-bottom: 0.35rem; }}
    header .meta {{ color: var(--muted); font-size: 0.875rem; }}
    .exec-summary {{ background: linear-gradient(135deg, var(--surface), var(--surface-2)); border: 1px solid var(--border);
      border-radius: var(--radius); padding: 1.25rem 1.5rem; margin-bottom: 1.75rem; box-shadow: var(--shadow); }}
    .exec-summary h2 {{ font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent); margin-bottom: 0.75rem; }}
    .exec-summary p {{ font-size: 0.95rem; color: #c5d0de; }}
    .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 1rem; margin-bottom: 1.75rem; }}
    .kpi {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 1rem; text-align: center; }}
    .kpi .value {{ font-size: 1.75rem; font-weight: 700; }}
    .kpi .label {{ font-size: 0.75rem; color: var(--muted); text-transform: uppercase; margin-top: 0.25rem; }}
    .charts-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 1.25rem; margin-bottom: 1.75rem; }}
    @media (max-width: 900px) {{ .charts-grid {{ grid-template-columns: 1fr; }} }}
    .chart-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 1.25rem; box-shadow: var(--shadow); }}
    .chart-card.full-width {{ grid-column: 1 / -1; }}
    .chart-card h3 {{ font-size: 0.9rem; font-weight: 600; }}
    .chart-card .subtitle {{ font-size: 0.75rem; color: var(--muted); margin: 0.25rem 0 1rem; }}
    .chart-wrap {{ position: relative; height: 280px; }}
    .chart-wrap.tall {{ height: 320px; }}
    .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.25rem; margin-bottom: 1.75rem; }}
    @media (max-width: 768px) {{ .two-col {{ grid-template-columns: 1fr; }} }}
    .panel {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 1.25rem 1.5rem; box-shadow: var(--shadow); }}
    .panel h2 {{ font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.07em; color: var(--accent); margin-bottom: 1rem; }}
    .panel ul {{ list-style: none; }}
    .panel li {{ padding: 0.5rem 0; border-bottom: 1px solid var(--border); font-size: 0.875rem; color: #c5d0de; }}
    .panel li:last-child {{ border-bottom: none; }}
    .panel li::before {{ content: "▸"; color: var(--accent); margin-right: 0.5rem; }}
    blockquote {{ border-left: 3px solid var(--accent); padding: 0.65rem 1rem; margin: 0.65rem 0;
      background: rgba(59,130,246,0.08); border-radius: 0 8px 8px 0; font-size: 0.85rem; font-style: italic; color: #b8c5d6; }}
    .quote-source {{ font-size: 0.7rem; color: var(--muted); font-style: normal; margin-top: 0.35rem; }}
    .brand-table {{ width: 100%; border-collapse: collapse; font-size: 0.8rem; }}
    .brand-table th, .brand-table td {{ padding: 0.55rem 0.75rem; text-align: left; border-bottom: 1px solid var(--border); }}
    .brand-table th {{ color: var(--muted); font-size: 0.7rem; text-transform: uppercase; }}
    footer {{ margin-top: 2rem; padding-top: 1.25rem; border-top: 1px solid var(--border); font-size: 0.75rem; color: var(--muted); }}
    footer h3 {{ font-size: 0.7rem; text-transform: uppercase; margin-bottom: 0.5rem; }}
  </style>
</head>
<body>
  <div class="page">
    <header>
      <h1>Singapore Telco Forum Sentiment Dashboard</h1>
      <p class="meta">
        Scope: All telcos &middot; Sources: Reddit + HWZ &middot;
        Sample: {stats["n"]} telco-relevant posts &middot;
        Generated {stats["generated_at"]} &middot;
        {html.escape(stats["reddit_path"])} + {html.escape(stats["hwz_path"])}
      </p>
    </header>

    <section class="exec-summary">
      <h2>Executive Summary</h2>
      <p>{stats["exec_summary"]}</p>
    </section>

    <div class="kpi-grid">
      <div class="kpi"><div class="value">{stats["n"]}</div><div class="label">Telco posts</div></div>
      <div class="kpi"><div class="value">{sp["happy"]}%</div><div class="label">Happy</div></div>
      <div class="kpi"><div class="value">{sp["not_happy"]}%</div><div class="label">Not happy</div></div>
      <div class="kpi"><div class="value">{sp["neutral"]}%</div><div class="label">Neutral</div></div>
      <div class="kpi"><div class="value">{stats["n_brands"]}</div><div class="label">Brands mentioned</div></div>
      <div class="kpi"><div class="value">{stats["n_sources"]}</div><div class="label">Sources</div></div>
    </div>

    <div class="charts-grid">
      <div class="chart-card">
        <h3>Sentiment Distribution</h3>
        <p class="subtitle">All telco-relevant posts (n={stats["n"]})</p>
        <div class="chart-wrap"><canvas id="sentimentChart"></canvas></div>
      </div>
      <div class="chart-card">
        <h3>Sentiment by Source</h3>
        <p class="subtitle">Reddit (n={reddit["n"]}) vs HWZ (n={hwz["n"]})</p>
        <div class="chart-wrap"><canvas id="sourceChart"></canvas></div>
      </div>
      <div class="chart-card full-width">
        <h3>Issue Breakdown by Theme</h3>
        <p class="subtitle">{html.escape(issue_note)}</p>
        <div class="chart-wrap tall"><canvas id="issueChart"></canvas></div>
      </div>
      <div class="chart-card">
        <h3>Brand Mentions</h3>
        <p class="subtitle">Row-expanded telco_label counts</p>
        <div class="chart-wrap tall"><canvas id="brandChart"></canvas></div>
      </div>
      <div class="chart-card">
        <h3>Negative Tone by Brand</h3>
        <p class="subtitle">% not_happy (brands with &ge;5 mentions)</p>
        <div class="chart-wrap tall"><canvas id="negRateChart"></canvas></div>
      </div>
    </div>

    <div class="two-col">
      <section class="panel">
        <h2>Per-Telco Highlights</h2>
        <table class="brand-table">
          <thead><tr><th>Telco</th><th>Mentions</th><th>Neg %</th><th>Top issues</th></tr></thead>
          <tbody>
{table_rows}
          </tbody>
        </table>
      </section>
      <section class="panel">
        <h2>Representative Quotes</h2>
{quote_blocks}
      </section>
    </div>

    <div class="two-col">
      <section class="panel">
        <h2>Recommendations</h2>
        <ul>
          <li>Disclose host-network and MVNO priority tiering transparently at launch.</li>
          <li>Fix porting and identity-document edge cases (passport validity, dropdown gaps).</li>
          <li>Market bundled roaming clearly — Malaysia threads are a key decision moment.</li>
          <li>Avoid "low price hurts quality" messaging without evidence; it triggers switching intent.</li>
          <li>Use location-based network proof points over national coverage claims.</li>
        </ul>
      </section>
      <section class="panel">
        <h2>Key Issue Insights</h2>
        <ul>
          <li><strong>Pricing:</strong> MVNO disruption vs legacy MNO plans; CEO rhetoric backlash.</li>
          <li><strong>Network:</strong> Hyper-local coverage; M1 dead zones; MVNO deprioritisation fears.</li>
          <li><strong>Customer service:</strong> StarHub porting blocks, promo delays, Singtel ONR lock-in.</li>
          <li><strong>Porting:</strong> Eight port-in limits; brand missing from port dropdowns.</li>
          <li><strong>Roaming:</strong> MVNOs (Vivifi, Giga, GOMO) mostly positive in Malaysia threads.</li>
        </ul>
      </section>
    </div>

    <footer>
      <h3>Limitations</h3>
      <p>
        Sample size {stats["n"]} telco-relevant rows — not nationally representative. Reddit over-indexes on complaints;
        HWZ over-indexes on launch threads. {"Issue themes inferred from keywords." if stats["issues_inferred"] else "Issues from labeled columns."}
        Sentiment auto-labels may misread sarcasm/thread context. Cannot infer churn, NPS, or network KPIs.
      </p>
    </footer>
  </div>

  <script>
    Chart.defaults.color = "#8b9cb3";
    Chart.defaults.borderColor = "#2d3a4f";
    Chart.defaults.font.family = "'Segoe UI', system-ui, sans-serif";

    const sentimentData = {{ labels: ["Happy", "Not happy", "Neutral"], values: [{sc["happy"]}, {sc["not_happy"]}, {sc["neutral"]}],
      colors: ["#22c55e", "#ef4444", "#94a3b8"] }};

    new Chart(document.getElementById("sentimentChart"), {{
      type: "doughnut",
      data: {{ labels: sentimentData.labels, datasets: [{{ data: sentimentData.values, backgroundColor: sentimentData.colors, borderWidth: 0 }}] }},
      options: {{ responsive: true, maintainAspectRatio: false, cutout: "58%",
        plugins: {{ legend: {{ position: "right" }}, tooltip: {{ callbacks: {{ label: (ctx) => {{
          const t = sentimentData.values.reduce((a,b)=>a+b,0);
          return ` ${{ctx.label}}: ${{ctx.raw}} (${{(100*ctx.raw/t).toFixed(1)}}%)`;
        }} }} }} }} }}
    }});

    new Chart(document.getElementById("sourceChart"), {{
      type: "bar",
      data: {{
        labels: ["Reddit", "HWZ"],
        datasets: [
          {{ label: "Happy", data: [{reddit["happy"]}, {hwz["happy"]}], backgroundColor: "#22c55e" }},
          {{ label: "Not happy", data: [{reddit["not_happy"]}, {hwz["not_happy"]}], backgroundColor: "#ef4444" }},
          {{ label: "Neutral", data: [{reddit["neutral"]}, {hwz["neutral"]}], backgroundColor: "#94a3b8" }}
        ]
      }},
      options: {{ responsive: true, maintainAspectRatio: false,
        scales: {{ x: {{ stacked: true }}, y: {{ stacked: true, max: 100, ticks: {{ callback: v => v+"%" }} }} }},
        plugins: {{ legend: {{ position: "bottom" }} }} }}
    }});

    const issueLabels = {issue_labels_js};
    const issueValues = {issue_values};
    const issueColors = {issue_colors};

    new Chart(document.getElementById("issueChart"), {{
      type: "bar",
      data: {{ labels: issueLabels, datasets: [{{ data: issueValues, backgroundColor: issueColors, borderRadius: 6 }}] }},
      options: {{ indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
    }});

    new Chart(document.getElementById("brandChart"), {{
      type: "bar",
      data: {{ labels: {brand_labels}, datasets: [{{ data: {brand_values}, backgroundColor: "#3b82f6", borderRadius: 6 }}] }},
      options: {{ indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
    }});

    const negRates = {neg_rates};
    new Chart(document.getElementById("negRateChart"), {{
      type: "bar",
      data: {{
        labels: {neg_labels},
        datasets: [{{ data: negRates, backgroundColor: negRates.map(v => v>=50?"#ef4444":v>=25?"#f59e0b":"#22c55e"), borderRadius: 6 }}]
      }},
      options: {{ responsive: true, maintainAspectRatio: false,
        scales: {{ y: {{ max: 80, ticks: {{ callback: v => v+"%" }} }} }},
        plugins: {{ legend: {{ display: false }} }} }}
    }});
  </script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate static telco sentiment dashboard HTML + README")
    parser.add_argument("--reddit", type=Path, default=ROOT / "data/processed/labeled_sample.csv")
    parser.add_argument("--hwz", type=Path, default=ROOT / "hwz_telco_posts_labeled.csv")
    parser.add_argument("--out-html", type=Path, default=DASHBOARD_DIR / "index.html")
    parser.add_argument("--out-readme", type=Path, default=DASHBOARD_DIR / "Dash_README.md")
    args = parser.parse_args()

    _, stats = analyse(args.reddit, args.hwz)

    args.out_html.write_text(render_html(stats), encoding="utf-8")
    args.out_readme.write_text(render_readme(stats), encoding="utf-8")

    print(f"Wrote {args.out_html} ({stats['n']} telco-relevant posts)")
    print(f"Wrote {args.out_readme}")
    print(
        f"Sentiment: {stats['sentiment_pct']['happy']}% happy / "
        f"{stats['sentiment_pct']['not_happy']}% not_happy / "
        f"{stats['sentiment_pct']['neutral']}% neutral"
    )


if __name__ == "__main__":
    main()
