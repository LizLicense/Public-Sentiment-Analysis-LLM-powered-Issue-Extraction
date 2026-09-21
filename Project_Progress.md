# Project Progress

Capstone telco forum sentiment pipeline — scrape, label, analyse, and visualise Singapore mobile-plan discussions (Singtel, StarHub, M1, SIMBA, Giga, Eight, Zym, redONE, MVNOs).

**Last updated:** September 2026

---

## Current status

| Area | Status | Notes |
|------|--------|-------|
| Data collection | **Done** (initial) | ~15.5k cleaned posts; Reddit multi-round + HWZ threads |
| Telco + sentiment labeling | **Done** | Full labeled CSV + per-telco summary JSON |
| Manual evaluation sample | **Done** | Annotator A: 300 representative + 100 challenge; 295/100 used in LLM eval |
| Sentiment benchmark | **Done (LLM)** | GPT-4o-mini vs VADER on independent labels; transformer still not installed |
| LLM vs rules issues | **Done** | Keyword rules beat GPT-4o-mini on multi-label F1 (0.64 vs 0.50) |
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
4. **Blind evaluation package** — 300 representative rows, 100 challenge rows, and 100-row second-annotator overlap; Annotator A complete; Annotator B not used for agreement.
5. **Independent LLM evaluation** — `gpt-4o-mini-2024-07-18` on 295+100 human labels; sentiment LLM wins (macro F1 0.63 vs 0.36); issue rules win (0.64 vs 0.50); ~$0.012 total. The earlier 100% VADER file is not used.
6. **Issue extraction** — ten-topic taxonomy: Network Quality, Pricing & Promotions, Mobile Plans, Roaming, Porting, Customer Service, Billing & Payment, App & Account, Devices, General Discussion.
7. **Qualitative analysis** — Forum sentiment report across all telcos (Reddit + HWZ sample).
8. **Dashboards** — `generate_dashboard.py` auto-builds static capstone summary (`index.html` + `Dash_README.md`); Streamlit app for interactive exploration.

---

## Key findings (forum analysis sample)

Based on **158 telco-relevant posts** from `data/processed/labeled_sample.csv` (Reddit) and `hwz_telco_posts_labeled.csv` (HWZ), after contextual brand validation. Regenerate with `python dashboard/generate_dashboard.py`.

### Sentiment

| Sentiment | Share |
|-----------|-------|
| Happy | 61% |
| Not happy | 22% |
| Neutral | 18% |

- **Reddit** (n=67 telco-relevant): 49% happy / **30% not_happy** — more complaint-driven.
- **HWZ** (n=91): 69% happy / 15% not_happy — skewed toward launch/plan threads.

### Issues (inferred; `issue_manual` not filled on Reddit sample)

| Theme | Share |
|-------|-------|
| App & Account | 24% |
| Network Quality | 19% |
| General Discussion | 15% |
| Mobile Plans | 12% |
| Pricing & Promotions | 8% |
| Billing & Payment | 8% |
| Roaming | 6% |
| Devices | 4% |
| Porting | 3% |
| Customer Service | 1% |

### Cross-brand (brands with ≥5 mentions)

| Telco | Mentions | Negative tone | Dominant themes |
|-------|----------|---------------|-----------------|
| StarHub | 56 | 27% | Pricing rhetoric, CS/porting friction, promo fulfilment |
| M1 | 53 | 25% | Coverage dead zones, 4G/5G transition |
| Singtel | 51 | 16% | ONR/bridge-mode policy, equipment quality |
| Zym | 22 | 0%* | Promotional plan posts (*label noise) |
| Eight | 14 | 29% | Launch pricing, MVNO tiering, porting limits |
| Giga | 6 | 67% | Network reliability (small n) |

**Takeaways:** App/account access, network quality and mobile-plan comparisons lead the refined issue view; StarHub/Singtel friction includes porting, billing, and equipment policy; Giga shows the highest negative rate but on very few rows.

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
| `issue_primary` | One of the ten canonical issue labels, such as `network_quality`, `pricing_promotions`, or `app_account` |
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

- [x] **Fill human issue/sentiment labels** on representative and challenge sheets; compare VADER/rules vs GPT-4o-mini.
- [ ] **Second annotator / kappa** on `double_annotation_annotator_b.csv`.
- [ ] **Transformer benchmark** — install `transformers` + `torch`; compare against VADER on the representative labels.
- [ ] **LLM issue extraction on the full corpus** — optional `processing/issue_extraction.py --use-llm --llm-unresolved-only`.
- [ ] **Scale coverage** — `processing/coverage_checker.py --target 1000` per telco.
- [x] **Auto-regenerate dashboard** — `dashboard/generate_dashboard.py` rebuilds `index.html` + `Dash_README.md` from CSVs.
- [ ] **Capstone write-up** — title-page placeholders; compile `final_report.tex`.

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
| `models/llm_evaluation.py` | Blind GPT-4o-mini vs VADER/rules evaluation |
| `models/sentiment_benchmark.py` | VADER vs transformer evaluation |
| `dashboard/generate_dashboard.py` | Regenerate static HTML dashboard + Dash_README from CSVs |
| `dashboard/index.html` | Static Chart.js summary dashboard (generated) |
| `dashboard/app.py` | Streamlit interactive dashboard |
