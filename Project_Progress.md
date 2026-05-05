# Data directory

This folder holds **raw** (scraper output) and **processed** (labeler + cleaned) data for the telco sentiment pipeline.

---

## Pipeline (overview)

Flow from scrapers into this folder, then through processing scripts that read/write here:

```
  Scrapers (run from WIP/)              Output in data/
  ──────────────────────               ───────────────
  hwz_forum_scraper.py          ──►    raw/hwz_posts.csv, .jsonl
  hwz_multi_forum_scraper.py    ──►    raw/hwz_multi_posts.csv, .jsonl
  reddit_scraper.py             ──►    raw/reddit_posts_*.csv, .jsonl
  twitter_scraper.py            ──►    raw/twitter_posts_*.csv, .jsonl
                │
                ▼
  preprocess.py (reads raw/)    ──►    processed/cleaned_posts.csv
                │
                ▼
  telco_labeler.py (reads raw or cleaned)
                │
                ├────────────────────►  processed/posts_labeled_<timestamp>.csv
                └────────────────────►  processed/summary_<timestamp>.json
                │
                ▼
  create_labeled_sample.py     ──►    processed/labeled_sample_template.csv
                                      (+ you fill manual labels → labeled_sample.csv)
```

- **Step 1 — Scrape:** Scrapers write CSV + JSONL into `data/raw/`.
- **Step 2 — Preprocess (optional):** `preprocess.py` reads from `data/raw/`, writes one cleaned CSV to `data/processed/`.
- **Step 3 — Label:** `telco_labeler.py` reads raw or cleaned CSV, writes labeled CSV and summary JSON to `data/processed/`.
- **Step 4 — Evaluation (optional):** `create_labeled_sample.py` reads from `data/processed/`, writes a template CSV for manual labels.
- **Step 5 — Benchmark:** `models/sentiment_benchmark.py` reads manually labeled sample and writes model metrics to `data/processed/`.
- **Step 6 — Issue extraction:** `processing/issue_extraction.py` reads labeled/cleaned CSV and writes issue labels + summary to `data/processed/`.
- **Step 7 — Dashboard:** `dashboard/app.py` reads latest processed CSV and visualizes trends.

---

## Layout

```
data/
├── raw/          # Scraper outputs (CSV + JSONL). One run per source.
└── processed/    # Cleaned dataset, labeled outputs (telco, sentiment, summary), and evaluation templates.
```

---

## 1. Raw data (`data/raw/`)

Produced by the scrapers. Each source writes a CSV and a JSONL with the same rows.

### HWZ (single forum)

- **Script:** `scrapers/hwz_forum_scraper.py`
- **Default output prefix:** `data/raw/hwz_posts` → `hwz_posts.csv`, `hwz_posts.jsonl`

| Column         | Type   | Description |
|----------------|--------|-------------|
| thread_title   | string | Title of the forum thread |
| thread_url     | string | URL of the thread |
| thread_page    | int    | Page number within the thread |
| timestamp      | string | Post timestamp (ISO or forum format) |
| post_text      | string | Body text of the post |

### HWZ (multiple forums)

- **Script:** `scrapers/hwz_multi_forum_scraper.py`
- **Default output prefix:** `data/raw/hwz_multi_posts`

Same columns as above, plus:

| Column        | Type   | Description |
|---------------|--------|-------------|
| source_forum  | string | Which forum the thread came from |

### Reddit

- **Script:** `scrapers/reddit_scraper.py`
- **Output:** `data/raw/reddit_posts_<keywords>_<timestamp>.csv`

| Column         | Type   | Description |
|----------------|--------|-------------|
| source         | string | `"reddit"` |
| subreddit      | string | e.g. `singapore` |
| post_id        | string | Reddit post ID |
| title          | string | Post title |
| url            | string | Link to post or content URL |
| permalink      | string | Reddit permalink |
| author         | string | Username (or `[deleted]`) |
| created_utc    | float  | Unix timestamp |
| comment_time   | string | Human-readable time (UTC) |
| telco_mentioned| string | Comma-separated telcos found in text (from keyword match) |
| score          | int    | Post/comment score |
| num_comments   | int    | Number of comments (posts only) |
| post_text      | string | Post body or comment body |
| scraped_at_utc | string | When the row was scraped (ISO) |
| comment_id     | string | Present for comment rows only |

### Twitter

- **Script:** `scrapers/twitter_scraper.py`
- **Output:** `data/raw/twitter_posts_<keywords>_<timestamp>.csv`

| Column        | Type   | Description |
|---------------|--------|-------------|
| source        | string | `"twitter"` |
| tweet_id      | string | Twitter tweet ID |
| thread_title  | string | Empty (tweets have no thread) |
| title         | string | Empty |
| post_text     | string | Tweet text |
| selftext      | string | Same as post_text (for pipeline compatibility) |
| timestamp     | string | Tweet created_at (ISO) |
| created_utc   | string | Same as timestamp |
| author        | string | Twitter username |
| url           | string | Link to tweet |
| like_count    | int    | Public metric |
| retweet_count | int    | Public metric |
| reply_count   | int    | Public metric |
| scraped_at_utc| string | When the row was scraped (ISO) |

---

## 2. Processed data (`data/processed/`)

Produced by the processing scripts.

### Labeler output (telco + sentiment + summary)

- **Script:** `processing/telco_labeler.py`
- **Input:** Any raw CSV (or auto-picks latest in `data/raw/`)
- **Outputs:**
  - `posts_labeled_<timestamp>.csv` – one row per post, with added columns below.
  - `summary_<timestamp>.json` – per-telco sentiment counts and top keywords (and optional LLM summary).

**Added columns in the labeled CSV:**

| Column           | Type   | Description |
|------------------|--------|-------------|
| telco_label      | string | Detected telco(s), comma-separated if multiple |
| sentiment_label  | string | `happy` / `not_happy` / `neutral` (VADER) |
| sentiment_score  | float  | VADER compound score (-1 to 1) |
| llm_sentiment_label | string | Present if `--use-llm-sentiment` was used |
| (all original columns from the input CSV) | | |

### Cleaned dataset (for modeling and dashboard)

- **Script:** `processing/preprocess.py`
- **Input:** Raw CSV(s) from `data/raw/` (or path passed via `--in`)
- **Output:** `data/processed/cleaned_posts.csv` (or path passed via `--out`)

Same schema as the labeler input, but with:

- Normalized column names (`post_text`, `thread_title`/`title` where needed).
- Rows with too-short or placeholder text removed.
- Optional English-only filter.
- One combined file when merging multiple raw CSVs.

Use this file as the single “cleaned dataset” for sentiment modeling, issue extraction, and the dashboard.

### Labeled sample (for evaluation)

- **Script:** `processing/create_labeled_sample.py`
- **Input:** Cleaned or labeled CSV (e.g. `data/processed/cleaned_posts.csv`)
- **Output:** `data/processed/labeled_sample_template.csv`

A sampled subset of rows with extra empty columns for **manual labeling**:

| Column                 | Type   | Description |
|------------------------|--------|-------------|
| sentiment_label_manual | string | You fill: `happy` / `not_happy` / `neutral` |
| issue_manual           | string | You fill: e.g. `pricing`, `network`, `customer_service`, or comma-separated |
| notes                  | string | Optional notes |

After you fill these in (e.g. in Excel or Google Sheets), save as `labeled_sample.csv` (or similar) and use it to evaluate sentiment and issue extraction models.


### Sentiment benchmark output

- **Script:** `models/sentiment_benchmark.py`
- **Input:** `data/processed/labeled_sample.csv` (with `sentiment_label_manual` filled)
- **Outputs:**
  - `data/processed/sentiment_benchmark.json`
  - `data/processed/sentiment_benchmark_predictions.csv`

### Issue extraction output

- **Script:** `processing/issue_extraction.py`
- **Input:** latest `posts_labeled_*.csv` (or `cleaned_posts.csv`)
- **Outputs:**
  - `data/processed/issues_<input>.csv`
  - `data/processed/issues_summary.json`

### Dashboard data source

- **Script:** `dashboard/app.py`
- **Read order:**
  1) `data/processed/issues_*.csv`
  2) `data/processed/posts_labeled_*.csv`
  3) `data/processed/cleaned_posts.csv`

---

## 3. Scripts (description of each .py file)

### Scrapers (`scrapers/`) — write into `data/raw/`

| File | Description |
|------|-------------|
| **hwz_forum_scraper.py** | Scrapes a single XenForo forum (e.g. HardwareZone). Logs in, crawls by keyword, extracts post text and timestamps. Writes `data/raw/hwz_posts.csv` + `.jsonl`. Requires forum login. |
| **hwz_multi_forum_scraper.py** | Same for multiple forum URLs; adds `source_forum` per row. Writes `data/raw/hwz_multi_posts.*`. |
| **reddit_scraper.py** | Fetches posts/comments from subreddits via Reddit public API (no key). Writes `data/raw/reddit_posts_<keywords>_<timestamp>.*`. |
| **twitter_scraper.py** | Fetches tweets via Twitter API v2 search recent (Bearer token). Writes `data/raw/twitter_posts_*.*`. |

### Processing (`processing/`) — read/write `data/raw/` and `data/processed/`

| File | Description |
|------|-------------|
| **telco_labeler.py** | Reads a posts CSV (from raw or processed), adds telco_label, sentiment (VADER/LLM), per-telco summary. Writes timestamped labeled CSV and summary JSON to `data/processed/`. Auto-picks latest CSV in `data/raw/` if no `--in` given. |
| **preprocess.py** | Reads from `data/raw/` (or `--in`), normalizes columns, drops short/noise rows, optional English filter. Writes one cleaned CSV to `data/processed/cleaned_posts.csv`. No sentiment. |
| **create_labeled_sample.py** | Reads from `data/processed/` (e.g. cleaned_posts.csv), samples N rows, adds empty columns for manual labels. Writes template CSV + INSTRUCTIONS to `data/processed/`. |
| **issue_extraction.py** | Adds issue labels (`issue_labels`, `issue_primary`) using fixed taxonomy and optional LLM classification. Writes issues CSV and issue summary JSON in `data/processed/`. |

### Models / Dashboard / Root

| File | Description |
|------|-------------|
| **models/sentiment_benchmark.py** | Evaluates VADER and transformer sentiment predictions against manual labels and writes benchmark artifacts into `data/processed/`. |
| **dashboard/app.py** | Streamlit dashboard that reads latest processed CSV and visualizes sentiment/issues/trends. |
| **cursor_cloud_agent.py** | Cursor Cloud Agents API (list/launch agents on repos). Not part of this data pipeline. |

---

## 4. How to reproduce

1. **Raw data:** Run the scrapers (see project root `README.md`).
   ```bash
   python scrapers/hwz_forum_scraper.py
   python scrapers/reddit_scraper.py --subreddits "singapore"
   # Twitter if you have Bearer token: python scrapers/twitter_scraper.py
   ```
2. **Cleaned dataset:** Run the preprocessor.
   ```bash
   python processing/preprocess.py
   ```
3. **Telco + sentiment:** Run the labeler (uses latest raw or cleaned CSV).
   ```bash
   python processing/telco_labeler.py
   ```
4. **Labeled sample for evaluation:** Create a template, then fill manually.
   ```bash
   python processing/create_labeled_sample.py --n 150
   # Open data/processed/labeled_sample_template.csv, fill sentiment_label_manual and issue_manual, save as labeled_sample.csv
   ```
5. **Sentiment benchmark:** Compare VADER and transformer on your manual labels.
   ```bash
   python models/sentiment_benchmark.py --in data/processed/labeled_sample.csv
   ```
6. **Issue extraction:** Add structured issue categories for each row.
   ```bash
   python processing/issue_extraction.py
   ```
7. **Dashboard:** Open Streamlit UI for interactive analysis.
   ```bash
   streamlit run dashboard/app.py
   ```

All paths assume you run from the project root (`WIP/`). For more detail and CLI options, see the project root `README.md`.

---

## 5. Planned next steps

- **Use an LLM model to extract issues:** Run `processing/issue_extraction.py` with `--use-llm` and `OPENAI_API_KEY` set so issue categories are refined by an LLM (see project root `README.md` → **Next steps** for example commands).
