# Telco forum sentiment pipeline

Scrape posts from different forums (HWZ, Reddit, Twitter) → clean and label → sentiment analysis and evaluation.

---

## Pipeline (overview)

End-to-end flow: **collect raw posts → clean → add telco + VADER sentiment → extract issues (keyword rules, then GPT-4o on unresolved rows) → evaluate vs human labels → dashboard.**

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

All commands are run from the project root (`WIP/`). See `data/README.md` for column definitions and [`Project_Progress.md`](Project_Progress.md) for pipeline status.

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
│   └── issue_extraction.py # Keyword taxonomy, then optional/batched GPT-4o on unresolved rows
├── models/
│   ├── llm_evaluation.py      # VADER/rules vs GPT-4o-mini / GPT-4o on gold labels
│   └── sentiment_benchmark.py # Compare VADER vs transformer with manual labels
├── dashboard/
│   ├── generate_dashboard.py  # Regenerate index.html + Dash_README.md from CSVs
│   ├── index.html             # Static HTML summary dashboard (Chart.js, capstone report)
│   ├── app.py                 # Streamlit dashboard for interactive filters/trends
│   └── Dash_README.md         # Auto-generated; how to view/regenerate dashboard
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
6. **Issue extraction**: `processing/issue_extraction.py` → keyword rules, then GPT-4o on `general_discussion` rows.
7. **Dashboard**: `dashboard/generate_dashboard.py` overlays those hybrid issue labels; `dashboard/index.html` to view; `dashboard/app.py` for interactive filters.

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

### 4. Blind evaluation sample

Create thread-disjoint, model-blind annotation sheets for formal evaluation:

```bash
python processing/create_evaluation_set.py
# Outputs under data/evaluation/:
# - representative_annotator_a.csv (300 rows)
# - challenge_annotator_a.csv (100 rows; report separately)
# - double_annotation_annotator_b.csv (100-row independent overlap)
# - sampling_metadata.json and ANNOTATION_GUIDE.md
```

Annotators must not view VADER, transformer, or LLM outputs. Fill the manual
columns using `data/evaluation/ANNOTATION_GUIDE.md`; keep both annotators'
original files unchanged and adjudicate disagreements in a separate copy.

`processing/create_labeled_sample.py` remains available for quick exploratory
sampling. Its `--prefill-from-model` option is unsafe for formal benchmarking
because uncorrected prefills create target leakage.


### 5. Sentiment benchmark (VADER vs transformer)

After independently labeling the representative evaluation file:

```bash
python models/sentiment_benchmark.py \
  --in data/evaluation/representative_annotator_a.csv \
  --out-json data/evaluation/sentiment_benchmark.json \
  --out-csv data/evaluation/sentiment_predictions.csv
```

### 5b. Baseline vs LLM evaluation

After independent annotation and adjudication, validate without an API call, then run the comparison. Headline metrics use the 300-row representative sheet, not the older 100-row mix:

```bash
venv/bin/python models/llm_evaluation.py \
  --in data/evaluation/representative_annotator_a.csv \
  --out-dir data/evaluation/llm_comparison_representative \
  --model gpt-4o-mini \
  --validate-only

export OPENAI_API_KEY="..."

venv/bin/python models/llm_evaluation.py \
  --in data/evaluation/representative_annotator_a.csv \
  --out-dir data/evaluation/llm_comparison_representative \
  --model gpt-4o-mini \
  --input-cost-per-million <CURRENT_INPUT_PRICE> \
  --output-cost-per-million <CURRENT_OUTPUT_PRICE>
```

Report the challenge sheet separately (`challenge_annotator_a.csv`, `--out-dir data/evaluation/llm_comparison_challenge`). Enter the provider's current USD prices per one million tokens so the saved cost calculation is traceable.

Persisted runs on the 295-row representative set:

| Model | Sentiment macro F1 | Issue macro F1 | Est. USD |
|---|---:|---:|---:|
| VADER / keyword rules | 0.360 | **0.639** | 0 |
| gpt-4o-mini-2024-07-18 | **0.631** | 0.504 | 0.0087 |
| gpt-4o-2024-08-06 (all rows) | 0.623 | 0.600 | 0.145 |
| GPT-4o hybrid (rules, then unresolved only) | — | **0.680** | (reuses the GPT-4o predictions) |

Challenge metrics are in `data/evaluation/llm_comparison_challenge/` and are not pooled with the headline table.

Results include:

- `metrics.json`: per-class sentiment metrics, issue metrics, confusion
  matrices, exact returned model IDs, runtime, tokens, failures, and cost
- `predictions.csv`: manual, baseline, and LLM labels for every row
- `qualitative_disagreements.csv`: examples where methods differ
- `llm_checkpoint.jsonl`: resumable API progress (`--resume`)

### 6. Structured issue extraction

Keyword rules are the default. GPT-4o is used only on rows that rules labelled `general_discussion`. That hybrid **is done** on the 15,504-row corpus (`gpt-4o-2024-08-06`, 8,786 unresolved rows, 879 batches, 0 failures, ~$3.45). Do not rerun `--use-llm` on every row: all-row GPT-4o lost to rules on the gold set.

```bash
python processing/issue_extraction.py
# Keyword-only: latest posts_labeled_*.csv → data/processed/issues_<input>.csv
#                 data/processed/issues_summary.json
```

Completed hybrid command (outputs already in `data/processed/`):

```bash
export OPENAI_API_KEY="..."
python processing/issue_extraction.py \
  --in data/processed/posts_labeled_2026-08-21_203752.csv \
  --out data/processed/issues_posts_labeled_2026-08-21_203752_gpt4o_hybrid.csv \
  --summary-out data/processed/issues_summary_gpt4o_hybrid.json \
  --checkpoint data/processed/llm_unresolved_gpt4o_checkpoint.jsonl \
  --use-llm --llm-unresolved-only --llm-model gpt-4o \
  --input-cost-per-million 2.50 \
  --output-cost-per-million 10.00
```

General discussion counts fell from 8,786 to 6,180. The dashboard reads this hybrid file; the keyword-only issues CSV is kept for comparison.

### 7. Dashboard

**Regenerate static HTML** from labeled CSVs (writes `index.html` + `Dash_README.md`):

```bash
python dashboard/generate_dashboard.py
# default overlay: data/processed/issues_posts_labeled_2026-08-21_203752_gpt4o_hybrid.csv
# optional: --reddit ... --hwz ... --issues ...
```

**View static summary** (no install; good for capstone report screenshots):

```bash
open dashboard/index.html
# or: python3 -m http.server 8080  →  http://localhost:8080/dashboard/
```

Charts: sentiment distribution, source comparison (Reddit vs HWZ), issue themes, brand mentions, negative tone by brand. See `dashboard/Dash_README.md`.

**Interactive Streamlit** (filters by source, telco, sentiment, issue breakdown, date):

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
| **issue_extraction.py** | Keyword issue labels using the ten-topic taxonomy, plus a batched GPT-4o pass on unresolved `general_discussion` rows (`--use-llm --llm-unresolved-only`). Completed hybrid output: `data/processed/issues_posts_labeled_2026-08-21_203752_gpt4o_hybrid.csv`. |

### Models (`models/`)

| File | Description |
|------|-------------|
| **llm_evaluation.py** | Blind comparison of VADER, keyword rules, GPT-4o-mini, and GPT-4o against human labels. Writes metrics, predictions, disagreements, and cost. |
| **sentiment_benchmark.py** | Benchmarks VADER and a transformer model against `sentiment_label_manual` and reports accuracy/F1/confusion matrix. |

### Dashboard (`dashboard/`)

| File | Description |
|------|-------------|
| **generate_dashboard.py** | Reads Reddit + HWZ labeled CSVs, overlays hybrid issue labels, computes sentiment/issue/brand metrics, and regenerates `index.html` and `Dash_README.md`. Stdlib only; no pandas required. |
| **index.html** | Standalone HTML summary dashboard (Chart.js): executive summary, KPI cards, sentiment/issue/brand charts, per-telco table, quotes, recommendations. Open in a browser; no server required. |
| **app.py** | Streamlit dashboard with filters (source/telco/sentiment/date), sentiment distribution, issue breakdown, time trends, and cross-brand comparison. |
| **Dash_README.md** | Auto-generated by `generate_dashboard.py`; documents data sources, row counts, and how to view/regenerate. |

### Root

| File | Description |
|------|-------------|
| **cursor_cloud_agent.py** | Standalone helper for the Cursor Cloud Agents API (list/launch/status agents on GitHub repos). Uses Cursor API key (env or hardcoded). Not part of the sentiment pipeline; for repo automation only. |

---

## Remaining work

LLM issue extraction is **done** (hybrid: keyword rules, then `gpt-4o-2024-08-06` on 8,786 unresolved rows). Do not paste the corpus into ChatGPT or rerun `--use-llm` on all 15,504 rows.

Still open:

- Second annotator and Cohen's κ on `double_annotation_annotator_b.csv`
- Twitter-RoBERTa on the same 295 gold labels (`transformers` + `torch`)
- Fill title-page placeholders and compile `final_report.tex`
- Optional: `processing/coverage_checker.py --target 1000` per telco
- Spot-check the 2,606 corpus rows GPT-4o moved out of `general_discussion` before treating huddle spikes as incidents

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

