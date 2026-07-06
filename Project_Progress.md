# Project Progress

Capstone telco forum sentiment pipeline — scrape, label, analyse, and visualise Singapore mobile-plan discussions (Singtel, StarHub, M1, SIMBA, Giga, Eight, Zym, redONE, MVNOs).

**Last updated:** April 2026

---

## Current status

| Area | Status | Notes |
|------|--------|-------|
| Data collection | **Done** (initial) | ~15.5k cleaned posts; Reddit multi-round + HWZ threads |
| Telco + sentiment labeling | **Done** | Full labeled CSV + per-telco summary JSON |
| Manual evaluation sample | **Done** | 150 Reddit rows with `sentiment_label_manual` |
| Sentiment benchmark | **Partial** | VADER evaluated; transformer pending `pip install transformers torch` |
| Issue extraction | **Done** | `issues_posts_labeled_*.csv` with taxonomy labels |
| Forum analysis report | **Done** | Executive summary, sentiment, issues, cross-brand comparison |
| Dashboard generator | **Done** | `dashboard/generate_dashboard.py` rebuilds HTML + README from CSVs |
| Static HTML dashboard | **Done** | `dashboard/index.html` (Chart.js) |
| Streamlit dashboard | **Done** | `dashboard/app.py` (interactive filters) |

---

## Completed milestones

1. **Scrapers** — HWZ (single + multi), Reddit (10+ keyword rounds), Twitter scaffold.
2. **Preprocessing** — `cleaned_posts.csv` (15,504 rows).
3. **Labeling** — `posts_labeled_2026-04-09_221819.csv` + `summary_*.json`.
4. **Manual sample** — `labeled_sample.csv` (150 rows) for model evaluation.
5. **Benchmark** — VADER vs manual labels: **100% accuracy / F1** on n=150 (see `sentiment_benchmark.json`).
6. **Issue extraction** — `issues_posts_labeled_2026-04-09_221819.csv` (pricing, network, customer_service, porting, roaming, other).
7. **Qualitative analysis** — Forum sentiment report across all telcos (Reddit + HWZ sample).
8. **Dashboards** — `generate_dashboard.py` auto-builds static capstone summary (`index.html` + `Dash_README.md`); Streamlit app for interactive exploration.

---

## Key findings (forum analysis sample)

Based on **193 telco-relevant posts** from `data/processed/labeled_sample.csv` (Reddit) and `hwz_telco_posts_labeled.csv` (HWZ). Regenerate with `python dashboard/generate_dashboard.py`.

### Sentiment

| Sentiment | Share |
|-----------|-------|
| Happy | 60% |
| Not happy | 23% |
| Neutral | 18% |

- **Reddit** (n=93 telco-relevant): 50% happy / **32% not_happy** — more complaint-driven.
- **HWZ** (n=100): 69% happy / 14% not_happy — skewed toward launch/plan threads (Eight).

### Issues (inferred; `issue_manual` not filled on Reddit sample)

| Theme | Share |
|-------|-------|
| Other | 51% |
| Pricing | 22% |
| Network | 9% |
| Customer service | 9% |
| Roaming | 5% |
| Porting | 4% |

### Cross-brand (brands with ≥5 mentions)

| Telco | Mentions | Negative tone | Dominant themes |
|-------|----------|---------------|-----------------|
| Eight | 56 | 29% | Launch pricing, MVNO tiering, porting limits |
| StarHub | 56 | 27% | Pricing rhetoric, CS/porting friction, promo fulfilment |
| M1 | 53 | 25% | Coverage dead zones, 4G/5G transition |
| Singtel | 51 | 16% | ONR/bridge-mode policy, equipment quality |
| Zym | 22 | 0%* | Promotional plan posts (*label noise) |
| Giga | 6 | 67% | Network reliability (small n) |

**Takeaways:** Pricing and MVNO value dominate; network quality is location-dependent; StarHub/Singtel friction centres on porting, billing, and equipment policy; Giga shows highest negative rate but on very few rows.

Full narrative, quotes, and recommendations are embedded in `dashboard/index.html`.

---

## Data inventory

```
data/
├── raw/               # Scraper outputs (CSV + JSONL)
└── processed/
    ├── cleaned_posts.csv                              # 15,504 rows
    ├── posts_labeled_2026-04-09_221819.csv            # 15,504 rows
    ├── issues_posts_labeled_2026-04-09_221819.csv     # 15,504 rows (+ issue_primary)
    ├── labeled_sample.csv                             # 150 rows (manual sentiment labels)
    ├── sentiment_benchmark.json                       # VADER metrics
    └── sentiment_benchmark_predictions.csv

hwz_telco_posts_labeled.csv   # 100 HWZ posts (project root; Eight/StarHub/M1/Zym threads)
```

---

## Pipeline (overview)

```
  Scrapers                         data/raw/*.csv
  ────────                                │
  hwz_forum_scraper                       ▼
  hwz_multi_forum_scraper        preprocess.py ──► cleaned_posts.csv
  reddit_scraper                          │
  twitter_scraper                         ▼
                                   telco_labeler.py ──► posts_labeled_*.csv, summary_*.json
                                          │
                    ┌─────────────────────┼─────────────────────┐
                    ▼                     ▼                     ▼
         create_labeled_sample.py  issue_extraction.py   generate_dashboard.py
                    │                     │                     │
                    ▼                     ▼                     ▼
         labeled_sample.csv      issues_posts_labeled_*.csv   index.html + Dash_README.md
                    │                                          app.py (Streamlit)
                    ▼
         sentiment_benchmark.py ──► sentiment_benchmark.json
```

| Step | Script | Output |
|------|--------|--------|
| 1 Scrape | `scrapers/*.py` | `data/raw/*.csv` |
| 2 Preprocess | `processing/preprocess.py` | `cleaned_posts.csv` |
| 3 Label | `processing/telco_labeler.py` | `posts_labeled_*.csv`, `summary_*.json` |
| 4 Eval sample | `processing/create_labeled_sample.py` | `labeled_sample_template.csv` |
| 5 Benchmark | `models/sentiment_benchmark.py` | `sentiment_benchmark.json` |
| 6 Issues | `processing/issue_extraction.py` | `issues_posts_labeled_*.csv` |
| 7 Dashboard | `dashboard/generate_dashboard.py`, `dashboard/app.py` | `index.html`, `Dash_README.md`, Streamlit UI |

---

## Dashboards

### Generate static HTML (`dashboard/generate_dashboard.py`)

Rebuild capstone summary from labeled CSVs (stdlib only):

```bash
python dashboard/generate_dashboard.py
# optional: --reddit data/processed/labeled_sample.csv --hwz hwz_telco_posts_labeled.csv
```

Writes `dashboard/index.html` and `dashboard/Dash_README.md` with current metrics, charts, executive summary, and quotes.

### View static HTML (`dashboard/index.html`)

```bash
open dashboard/index.html
```

Includes: executive summary, KPI cards, Chart.js visualisations (sentiment, source comparison, issues, brand mentions, negative tone), per-telco table, quotes, recommendations, limitations.

See `dashboard/Dash_README.md` (auto-generated).

### Streamlit (`dashboard/app.py`)

Interactive filters by source, telco, sentiment, and date:

```bash
streamlit run dashboard/app.py
```

Reads latest `issues_*.csv` → `posts_labeled_*.csv` → `cleaned_posts.csv`.

---

## Data dictionary (summary)

Column details for raw and processed files are in [`data/README.md`](data/README.md). Core processed columns:

| Column | Description |
|--------|-------------|
| `source` | `reddit`, `hwz`, `twitter` |
| `telco_label` | Detected brand(s), comma-separated |
| `sentiment_label` | `happy` / `not_happy` / `neutral` (VADER) |
| `sentiment_label_manual` | Human label (evaluation sample only) |
| `issue_primary` | `pricing`, `network`, `customer_service`, `porting`, `roaming`, `other` |
| `thread_title` | Thread or post title |
| `post_text` | Comment/post body |

---

## How to reproduce

Run from project root (`WIP/`):

```bash
# 1. Scrape
python scrapers/reddit_scraper.py --subreddits "singapore,askSingapore"
python scrapers/hwz_forum_scraper.py

# 2. Preprocess + label
python processing/preprocess.py
python processing/telco_labeler.py

# 3. Evaluation sample + benchmark
python processing/create_labeled_sample.py -n 150
# fill sentiment_label_manual, save as labeled_sample.csv
python models/sentiment_benchmark.py --in data/processed/labeled_sample.csv

# 4. Issue extraction
python processing/issue_extraction.py

# 5. Regenerate + view dashboards
python dashboard/generate_dashboard.py
open dashboard/index.html
streamlit run dashboard/app.py
```

Full CLI options: [`README.md`](README.md).

---

## Planned next steps

- [ ] **Transformer benchmark** — install `transformers` + `torch`; compare against VADER on `labeled_sample.csv`.
- [ ] **Fill `issue_manual`** on evaluation sample; benchmark issue-extraction rules vs LLM.
- [ ] **LLM issue extraction** — `processing/issue_extraction.py --use-llm --llm-unresolved-only`.
- [ ] **Scale coverage** — `processing/coverage_checker.py --target 1000` per telco.
- [x] **Auto-regenerate dashboard** — `dashboard/generate_dashboard.py` rebuilds `index.html` + `Dash_README.md` from CSVs.
- [ ] **Label quality audit** — fix sarcasm/thread-context errors in auto-sentiment (e.g. positive roaming text tagged `not_happy`).
- [ ] **Capstone write-up** — export dashboard screenshots + findings section for final report.

---

## Scripts reference

| File | Role |
|------|------|
| `scrapers/hwz_forum_scraper.py` | Single HWZ forum scrape |
| `scrapers/hwz_multi_forum_scraper.py` | Multiple XenForo forums |
| `scrapers/reddit_scraper.py` | Reddit posts/comments (no API key) |
| `scrapers/twitter_scraper.py` | Twitter API v2 (Bearer token) |
| `processing/telco_labeler.py` | Telco detection + VADER/LLM sentiment |
| `processing/preprocess.py` | Clean + normalize raw CSVs |
| `processing/create_labeled_sample.py` | Manual-label evaluation template |
| `processing/issue_extraction.py` | Issue taxonomy + optional LLM |
| `processing/coverage_checker.py` | Auto loop until per-telco target met |
| `models/sentiment_benchmark.py` | VADER vs transformer evaluation |
| `dashboard/generate_dashboard.py` | Regenerate static HTML dashboard + Dash_README from CSVs |
| `dashboard/index.html` | Static Chart.js summary dashboard (generated) |
| `dashboard/app.py` | Streamlit interactive dashboard |
