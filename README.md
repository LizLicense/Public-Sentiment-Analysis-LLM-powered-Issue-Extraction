# Telco forum sentiment pipeline

Scrape posts from forums (HWZ, Reddit) → clean and label → sentiment analysis and evaluation.

---

## Pipeline (overview)

End-to-end flow: **collect raw posts → clean → add telco + VADER sentiment → extract issues (keyword rules, then GPT-4o on unresolved rows) → evaluate vs human labels → dashboard.**

```
  [Scrapers]                    [Processing]
  ─────────                    ───────────
  hwz_forum_scraper     ──┐
  hwz_multi_forum_      ──┼──►  data/raw/*.csv
  reddit_scraper        ──┘              │
                                         ▼
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

All commands are run from the repo root. See `data/README.md` for column definitions and [`Project_Progress.md`](Project_Progress.md) for pipeline status.

---

## Folder structure

```
./                         # repo root
├── scrapers/              # Fetch posts from each source
│   ├── hwz_forum_scraper.py      # Single XenForo (e.g. HardwareZone); --latest-pages for recent posts
│   ├── hwz_multi_forum_scraper.py # Multiple XenForo forums
│   ├── reddit_scraper.py          # Reddit listing or search mode (OAuth app needed)
│   └── reddit_archive_scraper.py  # Reddit via Arctic Shift archive (no Reddit key)
├── processing/            # Sentiment + telco labeling + preprocessing
│   ├── telco_labeler.py   # Telco detection, VADER/LLM sentiment, per-telco summary
│   ├── preprocess.py      # Raw → cleaned dataset (noise removal, optional English filter)
│   ├── coverage_checker.py # Loop scrapes until each telco reaches a target count
│   ├── issue_extraction.py # Keyword taxonomy, then optional/batched GPT-4o on unresolved rows
│   ├── build_clean_corpus.py # Deduplicate, drop off-topic threads, thread-weighted shares
│   ├── prepare_new_posts.py  # Clean, label and merge posts from 10 Apr 2026 into the full corpus
│   ├── create_evaluation_set.py  # Blind representative / challenge / overlap annotation sheets
│   ├── create_recent_gold_set.py # Gold sample from the posts collected after 10 Apr 2026
│   ├── build_gold_labels.py      # Combine the three gold sheets into data/evaluation/gold_labels.csv
│   └── create_labeled_sample.py  # Quick exploratory sample (not for formal benchmarking)
├── models/
│   ├── llm_evaluation.py      # VADER/rules vs GPT-4o-mini / GPT-4o on gold labels
│   ├── corpus_llm_sentiment.py # GPT-4o-mini sentiment on the full corpus
│   ├── score_recent_gold.py   # Score production labels on the recent gold set
│   ├── score_merged_gold.py   # Score on the merged representative + recent set
│   └── robustness_checks.py   # Bootstrap CIs, kappa, held-out checks (no API calls)
├── dashboard/
│   ├── generate_dashboard.py  # Regenerate index.html + Dash_README.md from CSVs
│   ├── index.html             # Static HTML summary dashboard (Chart.js, capstone report)
│   └── Dash_README.md         # Auto-generated; how to view/regenerate dashboard
├── data/
│   ├── raw/               # Scraper outputs (CSV + JSONL)
│   ├── processed/         # Cleaned CSV, labeled outputs, corpus files, summary JSON
│   ├── evaluation/        # Gold sheets, annotation guide, model comparison outputs
│   └── README.md          # Data dictionary and reproducibility
├── report/                # final_report_revised.tex/.pdf, poster, dashboard PDF
├── presentation/          # Capstone deck (.pptx) and SMU template
├── diagrams/              # Pipeline diagrams (HTML)
├── hwz/, reddit/          # Source-specific working folders
├── CLAUDE.md              # Agent handoff: decisions that must stay consistent
├── Project_Progress.md    # Pipeline status, findings, reproduction steps
├── requirements_telco_labeler.txt
└── README.md
```

## Pipeline

1. **Scrape** from one or more sources → files in `data/raw/`.
2. **Preprocess** (optional): `processing/preprocess.py` → one cleaned CSV in `data/processed/`.
3. **Label** raw or cleaned CSV with `processing/telco_labeler.py` → telco + sentiment + summary in `data/processed/`.
4. **Evaluation**: `processing/create_evaluation_set.py` → blind annotation sheets; fill them and score with `models/llm_evaluation.py`.
5. **Issue extraction**: `processing/issue_extraction.py` → keyword rules, then GPT-4o on `general_discussion` rows.
6. **Clean corpus**: `processing/build_clean_corpus.py` → one row per unique post, off-topic threads dropped, shares per post and per thread.
7. **Full corpus**: `processing/prepare_new_posts.py` merges posts from 10 Apr to 26 Sep 2026 → `data/processed/corpus_posts.csv` (9,162 posts).
8. **Corpus sentiment**: `models/corpus_llm_sentiment.py` → GPT-4o-mini sentiment on the full corpus, same prompt and settings as the evaluation.
9. **Dashboard**: `dashboard/generate_dashboard.py` reads the full corpus; open `dashboard/index.html` to view.

Run from the repo root. See `data/README.md` for column definitions and [`Project_Progress.md`](Project_Progress.md) for current status and findings.

### 1. Scrape

Run from the repo root. All scrapers write to `data/raw/` by default.

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

**Reddit search mode (reaches months back; needs a Reddit "script" app):**
```bash
export REDDIT_CLIENT_ID="..." REDDIT_CLIENT_SECRET="..."
export REDDIT_USER_AGENT="script:sg-telco-capstone:v1.0 (by /u/yourname)"
python scrapers/reddit_scraper.py --mode search --subreddits singapore,askSingapore \
  --since 2026-04-10 --strict-match --out data/raw/apr_sep_2026/reddit_api
```
`--strict-match` keeps only whole-word brand mentions; ambiguous names (M1, Eight, Giga, SIMBA, Circles) need a telco word nearby.

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
# Reddit + HWZ
python processing/coverage_checker.py --target 1000

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
# - double_annotation_annotator_b.csv (100-row overlap template; the filled labels used for κ are
#   double_annotation_annotator_b_filled_guide.csv — the earlier filled sheet is superseded)
# - sampling_metadata.json and ANNOTATION_GUIDE.md
```

Annotators must not view VADER or LLM outputs. Fill the manual
columns using `data/evaluation/ANNOTATION_GUIDE.md`; keep both annotators'
original files unchanged and adjudicate disagreements in a separate copy.

`processing/create_labeled_sample.py` remains available for quick exploratory
sampling. Its `--prefill-from-model` option is unsafe for formal benchmarking
because uncorrected prefills create target leakage.


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

Headline results use the merged representative set (the 300-row representative sheet plus the recent-posts sheet: 392 posts for sentiment, 388 for issues), scored by `models/score_merged_gold.py` → `data/evaluation/merged_gold_scores.json`:

| Method | Sentiment macro F1 | Issue macro F1 |
|---|---:|---:|
| VADER / keyword rules | 0.380 | 0.590 |
| gpt-4o-mini-2024-07-18 (all rows) | **0.641** | 0.498 |
| gpt-4o-2024-08-06 (all rows) | 0.611 | 0.585 |
| GPT-4o hybrid (rules, then unresolved only) | — | **0.639** |

Per-run token counts and costs are in each run's `metrics.json`. Challenge metrics (`data/evaluation/llm_comparison_challenge/`) are never pooled with the headline table; on those 100 posts the hybrid (0.509) does not significantly beat rules (0.499), so treat the hybrid's lead as optimistic. See `data/evaluation/robustness_summary.json`.

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

### 7. Clean analysis corpus

The 15,504 rows hold only 2,686 unique posts (the scraper collected many posts several times), and 47 of 152 threads are off-topic (for example an insurance lawsuit thread). Build the clean corpus before quoting any share:

```bash
python processing/build_clean_corpus.py
# → data/processed/clean_posts_2026-08-21_203752.csv   (1,706 unique posts, 105 telco threads)
# → data/processed/clean_corpus_summary.json          (issue/sentiment/brand shares per post, per thread, capped at 5 per thread)
```

A thread is kept if at least 20% of its unique posts name a telco (`--min-telco-share`) or its title is about a telco. Report findings that hold under all three weightings.

### 7b. Posts from 10 Apr 2026 and the full corpus

The analysis corpus is one file, `data/processed/corpus_posts_mini_sentiment.csv` (9,162 posts in 349 threads). It merges the posts above with posts collected from 10 Apr to 26 Sep 2026 (internally `wave=2`):

```bash
python scrapers/hwz_forum_scraper.py --forum-pages 5 --max-threads 60 --max-thread-pages 15 \
  --latest-pages --since 2026-04-10 --out data/raw/apr_sep_2026/hwz_latest
python scrapers/reddit_archive_scraper.py --subreddits singapore,askSingapore \
  --since 2026-04-10 --out data/raw/apr_sep_2026/reddit_archive     # Arctic Shift archive, no Reddit key
python processing/prepare_new_posts.py         # clean, label, keyword issues -> data/processed/apr_sep_2026/
# GPT-4o hybrid pass (command printed by the script), then:
python processing/prepare_new_posts.py --merge # -> data/processed/corpus_posts.csv (9,162 posts)
python models/corpus_llm_sentiment.py --in data/processed/corpus_posts.csv \
  --out data/processed/corpus_posts_mini_sentiment.csv \
  --summary-out data/processed/corpus_posts_mini_sentiment_summary.json
python dashboard/generate_dashboard.py         # -> dashboard/index.html (full corpus, auto huddle threshold)
```

Both scrapers add a timestamp to output names and refuse to overwrite. `--latest-pages` reads the newest HWZ thread pages (the page counter was fixed on 26 Sep 2026; earlier HWZ data covers page 1 of each thread only). The recent-posts gold sample is created by `processing/create_recent_gold_set.py`; `processing/build_gold_labels.py` combines all three gold sheets into `data/evaluation/gold_labels.csv` (score each `evaluation_set` separately), and `models/score_recent_gold.py` scores the production labels on the recent set.

### 8. Corpus sentiment and dashboard

GPT-4o-mini labels sentiment on the full corpus with the exact prompt, batching and model settings used in the gold-set evaluation. It is resumable: rerun the same command to retry failed batches only. The full-corpus command is in §7b; the earlier 1,706-post clean corpus was labelled the same way.

```bash
export OPENAI_API_KEY="..."
python models/corpus_llm_sentiment.py --in data/processed/corpus_posts.csv --dry-run   # count batches and cost first
# → data/processed/corpus_posts_mini_sentiment.csv
# → data/processed/corpus_posts_mini_sentiment_summary.json
```

**Regenerate static HTML** (writes `index.html` + `Dash_README.md`):

```bash
python dashboard/generate_dashboard.py
# default: corpus_posts_mini_sentiment.csv; falls back to VADER with a warning on the page
```

**View static summary** (no install; good for capstone report screenshots):

```bash
open dashboard/index.html
# or: python3 -m http.server 8080  →  http://localhost:8080/dashboard/
```

Charts: weekly huddle queue against the n ≥ 20 threshold, sentiment with the human-label check, Reddit vs HWZ, issue shares per post and thread-weighted, not-happy posts by issue, brand mentions, not-happy share for brands with 10+ mentions. Recommendations are ordered by each issue's share of not-happy discussion. See `dashboard/Dash_README.md`.

## Combining sources

1. Run each scraper; they write to `data/raw/` (e.g. `hwz_posts.csv`, `reddit_posts_*.csv`).
2. To process a single source: run `python processing/telco_labeler.py` (it picks the latest CSV in `data/raw/`).
3. To use a combined file: merge CSVs (same columns: `thread_title`/`title`, `post_text`/`selftext`, `timestamp`), save to `data/raw/`, then run the labeler (with or without `--in`).

## Which scrapers need login?

| Scraper | Login / keys |
|---------|----------------|
| **HWZ** (single + multi) | Optional login via `HWZ_USERNAME` / `HWZ_PASSWORD` env vars |
| **Reddit** | `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` / `REDDIT_USER_AGENT` (unauthenticated access is often blocked) |

## Dependencies

- Scrapers: `pip install pandas requests beautifulsoup4 lxml tqdm`
- Processing + benchmark + dashboard: `pip install -r requirements_telco_labeler.txt`

---

## Scripts (description of each .py file)

### Scrapers (`scrapers/`)

| File | Description |
|------|-------------|
| **hwz_forum_scraper.py** | Scrapes a single XenForo-based forum (e.g. HardwareZone). Logs in, crawls forum listing by keyword, fetches thread pages, and extracts post text and timestamps. Writes CSV + JSONL to `data/raw/hwz_posts.*`. Optional login via `HWZ_USERNAME` / `HWZ_PASSWORD`. |
| **hwz_multi_forum_scraper.py** | Same as above but for multiple forum URLs in one run. Each row is tagged with `source_forum`. Can also take seed thread URLs. Writes to `data/raw/hwz_multi_posts.*`. |
| **reddit_scraper.py** | Fetches posts and optionally comments from subreddits via Reddit's API. Reddit blocks unauthenticated access, so set `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` / `REDDIT_USER_AGENT`. Filters by keywords, records telco mentions. Writes to `data/raw/reddit_posts_<keywords>_<timestamp>.*`. |
| **reddit_archive_scraper.py** | Pulls subreddit posts and comments from the Arctic Shift archive (no Reddit key) from a `--since` date. Used for Reddit data after 9 Apr 2026. Adds a timestamp to the output name and refuses to overwrite. |

### Processing (`processing/`)

| File | Description |
|------|-------------|
| **telco_labeler.py** | Main analysis script: reads a posts CSV (raw or cleaned), detects which telco(s) each post refers to (regex on thread_title + post_text), runs sentiment (VADER and optionally LLM), and builds per-telco summary (keyword counts + optional LLM text summary). Writes timestamped labeled CSV and summary JSON to `data/processed/`. Auto-picks latest CSV in `data/raw/` if no `--in` is given. |
| **preprocess.py** | Data cleaning only: reads from `data/raw/` (or `--in`), normalizes column names for HWZ/Reddit, drops too-short and placeholder/noise rows, optionally keeps English-only (langdetect). Writes one cleaned CSV (default `data/processed/cleaned_posts.csv`) for use by the labeler, models, or dashboard. Does not compute sentiment. |
| **coverage_checker.py** | Automation loop for data collection coverage. Repeatedly runs enabled scrapers (Reddit/HWZ), rebuilds cleaned+labeled data, computes per-telco counts, and stops when each tracked telco reaches the target (default 1000) or max rounds is reached. |
| **create_labeled_sample.py** | Samples N rows from a cleaned or labeled CSV, adds empty columns `sentiment_label_manual`, `issue_manual`, `notes`, and writes a template CSV plus an INSTRUCTIONS file. You fill the manual labels (e.g. in Excel) and save as e.g. `labeled_sample.csv` for evaluating sentiment and issue-extraction models. |
| **build_clean_corpus.py** | Deduplicates the hybrid issue file to one row per (thread, post text), drops threads where under 20% of posts name a telco unless the title is telco-related, and writes shares per post, per thread (each thread weighted equally) and capped at 5 posts per thread to `clean_corpus_summary.json`. |
| **issue_extraction.py** | Keyword issue labels using the ten-topic taxonomy, plus a batched GPT-4o pass on unresolved `general_discussion` rows (`--use-llm --llm-unresolved-only`). Completed hybrid output: `data/processed/issues_posts_labeled_2026-08-21_203752_gpt4o_hybrid.csv`. |
| **prepare_new_posts.py** | Cleans, labels and keyword-tags posts collected from 10 Apr 2026, prints the GPT-4o hybrid command, and with `--merge` builds `data/processed/corpus_posts.csv` (9,162 posts in 349 threads). |
| **create_evaluation_set.py** | Builds thread-disjoint, model-blind annotation sheets (representative, challenge, double-annotation overlap) plus `ANNOTATION_GUIDE.md` and sampling metadata. |
| **create_recent_gold_set.py** | Samples the recent-posts gold sheet (10 Apr to 26 Sep 2026) for annotation. |
| **build_gold_labels.py** | Combines the three gold sheets into `data/evaluation/gold_labels.csv`; score each `evaluation_set` separately. |

### Models (`models/`)

| File | Description |
|------|-------------|
| **llm_evaluation.py** | Blind comparison of VADER, keyword rules, GPT-4o-mini, and GPT-4o against human labels. Writes metrics, predictions, disagreements, and cost. |
| **corpus_llm_sentiment.py** | Resumable GPT-4o-mini sentiment pass over the corpus; writes the `*_mini_sentiment.csv` the dashboard reads. |
| **score_recent_gold.py** | Scores the production labels on the recent gold set → `recent_gold_scores.json`. |
| **score_merged_gold.py** | Scores on the merged representative + recent set → `merged_gold_scores.json` (the headline table). |
| **robustness_checks.py** | Bootstrap CIs, kappa and held-out checks → `robustness_summary.json`. No API calls. |

### Dashboard (`dashboard/`)

| File | Description |
|------|-------------|
| **generate_dashboard.py** | Reads the clean corpus (GPT-4o-mini sentiment if present, else VADER with a warning) and hybrid issue labels, computes per-post and thread-weighted shares, weekly huddle queue and brand metrics, and regenerates `index.html` and `Dash_README.md`. Stdlib only; no pandas required. |
| **index.html** | Standalone HTML summary dashboard (Chart.js): executive summary, KPI cards, sentiment/issue/brand charts, per-telco table, quotes, recommendations. Open in a browser; no server required. |
| **Dash_README.md** | Auto-generated by `generate_dashboard.py`; documents data sources, row counts, and how to view/regenerate. |

---

## Remaining work

LLM issue extraction is **done** (hybrid: keyword rules, then `gpt-4o-2024-08-06` on 8,786 unresolved rows). Do not paste the corpus into ChatGPT or rerun `--use-llm` on all 15,504 rows.

Still open:

- Adjudicate annotator A vs B (`double_annotation_annotator_b_filled2.csv`; sentiment κ 0.39 representative / 0.59 challenge) under the guide rule for first-hand failure reports, in a new file. Then recompute kappa.
- Fill title-page placeholders and compile `report/final_report_revised.tex`
- Optional: `processing/coverage_checker.py --target 1000` per telco
- Spot-check the 2,606 corpus rows GPT-4o moved out of `general_discussion` before treating huddle spikes as incidents

## Credentials

Never put keys or passwords in this repo. Scrapers and labelers read them from the environment:

```bash
export HWZ_USERNAME=""
export HWZ_PASSWORD=""
export REDDIT_CLIENT_ID=""
export REDDIT_CLIENT_SECRET=""
export OPENAI_API_KEY=""
```

If any token or password was ever in git history or shared, revoke it and create a new one (see `CLAUDE.md`, "Leaked credentials").
