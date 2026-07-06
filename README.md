# Telco forum sentiment pipeline

Scrape posts from different forums (HWZ, Reddit, Twitter) → clean and label → sentiment analysis and evaluation.

---

## Pipeline (overview)

End-to-end flow: **collect raw posts → optionally clean → add telco + sentiment + summary → optionally create a labeled sample for model evaluation.**

```
  [Scrapers]                    [Processing]
  ─────────                    ───────────
  hwz_forum_scraper     ──┐
  hwz_multi_forum_      ──┼──►  data/raw/*.csv
  reddit_scraper        ──┤              │
  twitter_scraper       ──┘              ▼
                              preprocess.py  ──►  data/processed/cleaned_posts.csv
                                        │
                                        ▼
                              telco_labeler.py  ──►  data/processed/posts_labeled_*.csv
                                                    data/processed/summary_*.json
                                        │
                                        ▼
                              create_labeled_sample.py  ──►  labeled_sample_template.csv
                                                             (you fill manual labels for eval)
```

- **Step 1 — Scrape:** Run one or more scrapers; each writes CSV + JSONL to `data/raw/`.
- **Step 2 — Preprocess (optional):** Run `preprocess.py` to produce one cleaned CSV (noise removed, columns normalized).
- **Step 3 — Label:** Run `telco_labeler.py` on raw or cleaned CSV to add telco, sentiment (VADER/LLM), and per-telco summary.
- **Step 4 — Evaluation (optional):** Run `create_labeled_sample.py` to get a template; fill manual labels and use for evaluating sentiment/issue models.

All commands are run from the project root (`WIP/`). See `data/README.md` for column definitions and [`Project_Progress.md`](Project_Progress.md) for pipeline status and planned next steps.

---

## Folder structure

```
WIP/
├── scrapers/              # Fetch posts from each source
│   ├── hwz_forum_scraper.py      # Single XenForo (e.g. HardwareZone)
│   ├── hwz_multi_forum_scraper.py # Multiple XenForo forums
│   ├── reddit_scraper.py          # Reddit (public API, no key)
│   └── twitter_scraper.py        # Twitter API v2 recent search (Bearer token required)
├── processing/            # Sentiment + telco labeling + preprocessing
│   ├── telco_labeler.py   # Telco detection, VADER/LLM sentiment, per-telco summary
│   ├── preprocess.py      # Raw → cleaned dataset (noise removal, optional English filter)
│   ├── create_labeled_sample.py  # Sample N rows + template for manual sentiment/issue labels
│   └── issue_extraction.py # Structured issue labels (taxonomy + optional LLM)
├── models/
│   └── sentiment_benchmark.py # Compare VADER vs transformer with manual labels
├── dashboard/
│   ├── index.html         # Static HTML summary dashboard (Chart.js, capstone report)
│   ├── app.py             # Streamlit dashboard for interactive filters/trends
│   └── Dash_README.md     # How to open index.html vs Streamlit
├── data/
│   ├── raw/               # Scraper outputs (CSV + JSONL)
│   ├── processed/         # Cleaned CSV, labeled outputs, summary JSON, labeled-sample template
│   ├── README.md          # Data dictionary and reproducibility
├── Project_Progress.md    # Pipeline status, findings, reproduction steps
├── cursor_cloud_agent.py  # Cursor Cloud Agents API (optional, for repo agents)
├── requirements_telco_labeler.txt
└── README.md
```

## Pipeline

1. **Scrape** from one or more sources → files in `data/raw/`.
2. **Preprocess** (optional): `processing/preprocess.py` → one cleaned CSV in `data/processed/`.
3. **Label** raw or cleaned CSV with `processing/telco_labeler.py` → telco + sentiment + summary in `data/processed/`.
4. **Evaluation**: `processing/create_labeled_sample.py` → template for manual labels; fill and use for model eval.
5. **Benchmark**: `models/sentiment_benchmark.py` → compare VADER vs transformer (accuracy/F1).
6. **Issue extraction**: `processing/issue_extraction.py` → issue labels + issue summary JSON.
7. **Dashboard**: `dashboard/index.html` → static summary report with charts; `dashboard/app.py` → interactive analysis by source/telco/date.

Run from project root (`WIP/`). See `data/README.md` for column definitions and [`Project_Progress.md`](Project_Progress.md) for current status and findings.

### 1. Scrape

Run from project root (`WIP/`). All scrapers write to `data/raw/` by default.

**HWZ (single forum)** — requires forum login (set in script):
```bash
python scrapers/hwz_forum_scraper.py
# → data/raw/hwz_posts.csv, data/raw/hwz_posts.jsonl
```

**HWZ (multiple forums):**
```bash
python scrapers/hwz_multi_forum_scraper.py --forum-urls "https://..."
# → data/raw/hwz_multi_posts.csv
```

**Reddit:**
```bash
python scrapers/reddit_scraper.py --subreddits "singapore,askSingapore"
# → data/raw/reddit_posts*.csv
```

**Twitter (API v2, requires Bearer token):**
```bash
export TWITTER_BEARER_TOKEN="your_bearer_token"
python scrapers/twitter_scraper.py --keywords "singtel,starhub,m1" --max-tweets 500
# → data/raw/twitter_posts_<keywords>_<timestamp>.csv
```
Get a token at [Twitter Developer Portal](https://developer.twitter.com/en/portal/dashboard). Free tier: last 7 days of tweets, rate limits apply.

### 2. Process (sentiment + telco)

No need to type the input file every time: if `data/raw/posts.csv` doesn’t exist, the labeler **auto-uses the most recent CSV** in `data/raw/` (so you can just run it after any scraper).

**Default — auto-picks latest CSV in `data/raw/`, writes to `data/processed/` with timestamp:**
```bash
python processing/telco_labeler.py
# Uses latest data/raw/*.csv (e.g. hwz_posts.csv or reddit_posts_*.csv)
# Output: data/processed/posts_labeled_<timestamp>.csv, data/processed/summary_<timestamp>.json
```

**Specify input (optional):**
```bash
python processing/telco_labeler.py --in data/raw/hwz_posts.csv
```

**With optional LLM (OpenAI-compatible key in script or env):**
```bash
python processing/telco_labeler.py --use-llm-summary --use-llm-sentiment
```

### 3. Preprocess (cleaned dataset)

Build one cleaned CSV for modeling and dashboard (drops short/noise rows, normalizes columns, optional English-only):

```bash
python processing/preprocess.py
# Input: latest data/raw/*.csv. Output: data/processed/cleaned_posts.csv
```

Options: `--min-length 20`, `--require-english` (needs `pip install langdetect`), `--in` / `--out`.

### 3b. Auto coverage loop (>= target per telco)

Run iterative collection until each tracked telco reaches your target sample count (default: 1000):

```bash
python processing/coverage_checker.py --target 1000 --max-rounds 10
```

Useful examples:

```bash
# Reddit + HWZ only (skip Twitter)
python processing/coverage_checker.py --disable-twitter --target 1000

# Track only main telcos
python processing/coverage_checker.py \
  --telcos "Singtel,Starhub,M1,SIMBA,Giga,Eight" \
  --target 1000 \
  --max-rounds 12
```

### 4. Labeled sample (for evaluation)

Create a template with N sampled rows and empty columns for manual sentiment + issue labels:

```bash
python processing/create_labeled_sample.py -n 150
# Output: data/processed/labeled_sample_template.csv + INSTRUCTIONS
```

Open the CSV, fill in `sentiment_label_manual` (happy/not_happy/neutral) and `issue_manual` (e.g. pricing, network), save as `labeled_sample.csv` for evaluating models.


### 5. Sentiment benchmark (VADER vs transformer)

After labeling `data/processed/labeled_sample.csv`:

```bash
python models/sentiment_benchmark.py --in data/processed/labeled_sample.csv
# Output: data/processed/sentiment_benchmark.json
#         data/processed/sentiment_benchmark_predictions.csv
```

### 6. Structured issue extraction

```bash
python processing/issue_extraction.py
# Input: latest posts_labeled_*.csv (or cleaned_posts.csv)
# Output: data/processed/issues_<input>.csv
#         data/processed/issues_summary.json
```

Optional LLM enhancement:

```bash
python processing/issue_extraction.py --use-llm --llm-unresolved-only
```

### 7. Dashboard

**Static HTML summary** (no install; good for capstone report screenshots):

```bash
open dashboard/index.html
# or: python3 -m http.server 8080  →  http://localhost:8080/dashboard/
```

Charts: sentiment distribution, source comparison (Reddit vs HWZ), issue themes, brand mentions, negative tone by brand. See `dashboard/Dash_README.md`.

**Interactive Streamlit** (filters by source, telco, sentiment, date):

```bash
streamlit run dashboard/app.py
```

## Combining sources

1. Run each scraper; they write to `data/raw/` (e.g. `hwz_posts.csv`, `reddit_posts_*.csv`).
2. To process a single source: run `python processing/telco_labeler.py` (it picks the latest CSV in `data/raw/`).
3. To use a combined file: merge CSVs (same columns: `thread_title`/`title`, `post_text`/`selftext`, `timestamp`), save to `data/raw/`, then run the labeler (with or without `--in`).

## Which scrapers need login?

| Scraper | Login / keys |
|---------|----------------|
| **HWZ** (single + multi) | Forum username/password (set in script) |
| **Reddit** | None (public API) |
| **Twitter** | Bearer token (env or hardcoded in script) |

## Dependencies

- Scrapers: `pip install pandas requests beautifulsoup4 lxml tqdm`
- Processing + benchmark + dashboard: `pip install -r requirements_telco_labeler.txt`

---

## Scripts (description of each .py file)

### Scrapers (`scrapers/`)

| File | Description |
|------|-------------|
| **hwz_forum_scraper.py** | Scrapes a single XenForo-based forum (e.g. HardwareZone). Logs in, crawls forum listing by keyword, fetches thread pages, and extracts post text and timestamps. Writes CSV + JSONL to `data/raw/hwz_posts.*`. Requires forum username/password (set in script). |
| **hwz_multi_forum_scraper.py** | Same as above but for multiple forum URLs in one run. Each row is tagged with `source_forum`. Can also take seed thread URLs. Writes to `data/raw/hwz_multi_posts.*`. |
| **reddit_scraper.py** | Fetches posts and optionally comments from subreddits via Reddit’s public JSON API (no API key). Filters by keywords, records telco mentions. Writes to `data/raw/reddit_posts_<keywords>_<timestamp>.*`. |
| **twitter_scraper.py** | Fetches tweets via Twitter API v2 “search recent” (last 7 days). Uses Bearer token (env or hardcoded). Builds query from keywords, paginates, normalizes to same schema as other scrapers. Writes to `data/raw/twitter_posts_*.*`. |

### Processing (`processing/`)

| File | Description |
|------|-------------|
| **telco_labeler.py** | Main analysis script: reads a posts CSV (raw or cleaned), detects which telco(s) each post refers to (regex on thread_title + post_text), runs sentiment (VADER and optionally LLM), and builds per-telco summary (keyword counts + optional LLM text summary). Writes timestamped labeled CSV and summary JSON to `data/processed/`. Auto-picks latest CSV in `data/raw/` if no `--in` is given. |
| **preprocess.py** | Data cleaning only: reads from `data/raw/` (or `--in`), normalizes column names for HWZ/Reddit/Twitter, drops too-short and placeholder/noise rows, optionally keeps English-only (langdetect). Writes one cleaned CSV (default `data/processed/cleaned_posts.csv`) for use by the labeler, models, or dashboard. Does not compute sentiment. |
| **coverage_checker.py** | Automation loop for data collection coverage. Repeatedly runs enabled scrapers (Reddit/HWZ/Twitter), rebuilds cleaned+labeled data, computes per-telco counts, and stops when each tracked telco reaches the target (default 1000) or max rounds is reached. |
| **create_labeled_sample.py** | Samples N rows from a cleaned or labeled CSV, adds empty columns `sentiment_label_manual`, `issue_manual`, `notes`, and writes a template CSV plus an INSTRUCTIONS file. You fill the manual labels (e.g. in Excel) and save as e.g. `labeled_sample.csv` for evaluating sentiment and issue-extraction models. |
| **issue_extraction.py** | Adds structured issue labels using fixed taxonomy (`pricing`, `network`, `customer_service`, `porting`, `roaming`, `other`) and optional LLM classification. Writes issues CSV + summary JSON. |

### Models (`models/`)

| File | Description |
|------|-------------|
| **sentiment_benchmark.py** | Benchmarks VADER and a transformer model against `sentiment_label_manual` and reports accuracy/F1/confusion matrix. |

### Dashboard (`dashboard/`)

| File | Description |
|------|-------------|
| **index.html** | Standalone HTML summary dashboard (Chart.js): executive summary, KPI cards, sentiment/issue/brand charts, per-telco table, quotes, recommendations. Open in a browser; no server required. |
| **app.py** | Streamlit dashboard with filters (source/telco/sentiment/date), sentiment distribution, issue breakdown, time trends, and cross-brand comparison. |
| **Dash_README.md** | How to view `index.html` vs run the Streamlit app. |

### Root

| File | Description |
|------|-------------|
| **cursor_cloud_agent.py** | Standalone helper for the Cursor Cloud Agents API (list/launch/status agents on GitHub repos). Uses Cursor API key (env or hardcoded). Not part of the sentiment pipeline; for repo automation only. |

---

## Next steps

- **Use an LLM model to extract issues:** Issue extraction currently defaults to rule-based keywords. Enable the LLM classifier by setting `OPENAI_API_KEY` and running `processing/issue_extraction.py` with `--use-llm` (optionally `--llm-unresolved-only` so the model only refines rows labeled `other` by rules—lower cost).
  ```bash
  export OPENAI_API_KEY="sk-..."
  python processing/issue_extraction.py --use-llm --llm-model gpt-4o-mini
  ```
  For hybrid mode (LLM only when rules are unsure):
  ```bash
  python processing/issue_extraction.py --use-llm --llm-unresolved-only --llm-model gpt-4o-mini
  ```

# Local token for scrapers

This file is listed in `.gitignore` so it should not be pushed to GitHub.  
Still prefer a **password manager** (1Password, Bitwarden, Apple Keychain) over a text file.

Fill in **only on your machine**:

| Item | Value (you type here) |
|------|------------------------|
| HWZ / forum username | |
| HWZ / forum password | |
| GitHub username | |
| GitHub token (PAT) | `ghp_...` |
| Twitter Bearer (optional) | |
| OpenAI API key (optional) | |

Environment variables (same info, safer for scripts):

```bash
export HWZ_USERNAME=""
export HWZ_PASSWORD=""
export TWITTER_BEARER_TOKEN=""
export OPENAI_API_KEY=""
```

If any token or password was ever in git history or shared, **revoke it** and create a new one.

