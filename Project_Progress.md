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
| LLM vs rules issues | **Done** | Representative: hybrid 0.680 > rules 0.639. Challenge: GPT-4o all posts 0.596 best |
| Clean corpus | **Done** | 1,706 unique posts, 105 telco threads (`build_clean_corpus.py`) |
| Corpus LLM sentiment | **Done** | GPT-4o-mini on 1,706 posts, $0.047 (`corpus_llm_sentiment.py`) |
| Issue extraction | **Done** | `issues_posts_labeled_*.csv` with taxonomy labels |
| Forum analysis report | **Done** | Executive summary, sentiment, issues, cross-brand comparison |
| Dashboard generator | **Done** | `dashboard/generate_dashboard.py` rebuilds HTML + README from CSVs |
| Static HTML dashboard | **Done** | `dashboard/index.html` (Chart.js) |

---

## Completed milestones

1. **Scrapers** — HWZ (single + multi), Reddit (10+ keyword rounds).
2. **Preprocessing** — `cleaned_posts.csv` (15,504 rows).
3. **Labeling** — `posts_labeled_2026-04-09_221819.csv` + `summary_*.json`.
4. **Blind evaluation package** — 300 representative rows, 100 challenge rows, and 100-row second-annotator overlap; Annotator A complete; Annotator B not used for agreement.
5. **Independent LLM evaluation** — `gpt-4o-mini-2024-07-18` on 295+100 human labels; sentiment LLM wins (macro F1 0.63 vs 0.36); issue rules win (0.64 vs 0.50); ~$0.012 total. The earlier 100% VADER file is not used.
6. **Issue extraction** — ten-topic taxonomy: Network Quality, Pricing & Promotions, Mobile Plans, Roaming, Porting, Customer Service, Billing & Payment, App & Account, Devices, General Discussion.
7. **Qualitative analysis** — Forum sentiment report across all telcos (Reddit + HWZ sample).
8. **Dashboard** — `generate_dashboard.py` auto-builds the static capstone summary (`index.html` + `Dash_README.md`).

---

## Key findings (v2 corpus, 26 Sep 2026)

v2 = original corpus + wave 2 (10 Apr–26 Sep 2026): **9,162 unique posts in 349 telco threads** (5,711 Reddit, 3,451 HWZ; 12% in outage threads). Figures: `data/evaluation/robustness_summary.json` → `corpus_v2`. Dashboard: `dashboard/index_v2.html`.

- **Sentiment (GPT-4o-mini):** 19% happy / 44% not happy / 37% neutral per post; 42% not happy thread-weighted; 40% outside outage threads. VADER on the same posts: 46% happy.
- **Issues:** Network Quality 41% of posts (37% thread-weighted), Mobile Plans 14%, Pricing 8%, App & Account 4% per post but in 115 threads (9% thread-weighted).
- **Platforms:** Reddit 48% vs HWZ 37% not happy per post; 42% vs 37% outside outages — mostly topic mix.
- **Brands (outside outages):** Singtel 42%, StarHub 40%, SIMBA 43%, M1 40%, Giga 43%, Eight 35% (least negative under every weighting). No league table.
- **Huddle (threshold 2× median week = 115):** only 16 Mar 2026 (Singtel outage, 352) and 14 Sep 2026 (multi-brand: StarHub broadband, SIMBA app OTP, 149).
- **Case study (original 1,711 posts):** 39% in outage threads; not happy 55% → 42% without them; Singtel 63% → 44%; Reddit vs HWZ 60/40 → 43/40.

### Evaluation updates

- **Held-out challenge set:** GPT-4o-mini sentiment 0.773 vs GPT-4o 0.712 vs VADER 0.491. Issues: GPT-4o all posts 0.596 beats rules 0.499 and hybrid 0.509. The hybrid's representative-set 0.680 is optimistic.
- **Bootstrap 95% CIs (representative):** mini − VADER +0.271 (0.191 to 0.347); mini − GPT-4o tie; GPT-4o all posts − rules tie; hybrid − rules +0.041 (0.011 to 0.072).
- **Stability:** a second GPT-4o-mini run reproduced 292/295 sentiment labels (κ 0.98).
- **Annotator agreement** (`double_annotation_annotator_b_filled_guide.csv`): sentiment κ 0.38 (representative), 0.63 (challenge; independence unconfirmed).
- **Pending:** label `data/evaluation/wave2_annotator_a.csv` (100 blind wave-2 posts) and score GPT-4o-mini on it.

---

## Data inventory

```
data/
├── raw/               # Scraper outputs (CSV + JSONL)
└── processed/
    ├── cleaned_posts.csv                              # 15,504 rows
    ├── posts_labeled_2026-04-09_221819.csv            # 15,504 rows
    ├── issues_posts_labeled_2026-04-09_221819.csv     # 15,504 rows (+ issue_primary)
    ├── labeled_sample.csv                             # 150 rows; sentiment_label_manual is a copy of VADER, not human labels
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
  reddit_scraper                          ▼
                                   telco_labeler.py ──► posts_labeled_*.csv, summary_*.json
                                          │
                    ┌─────────────────────┼─────────────────────┐
                    ▼                     ▼                     ▼
         create_labeled_sample.py  issue_extraction.py   generate_dashboard.py
                    │                     │                     │
                    ▼                     ▼                     ▼
         labeled_sample.csv      issues_posts_labeled_*.csv   index.html + Dash_README.md
                    │
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
| 7 Clean corpus | `processing/build_clean_corpus.py` | `clean_posts_*.csv`, `clean_corpus_summary.json` |
| 8 Dashboard | `dashboard/generate_dashboard.py` | `index.html`, `Dash_README.md` |

---

## Dashboards

### Generate static HTML (`dashboard/generate_dashboard.py`)

Rebuild from the clean corpus (stdlib only). Uses GPT-4o-mini sentiment from `models/corpus_llm_sentiment.py` when that file exists, else VADER with a warning:

```bash
python processing/build_clean_corpus.py
python models/corpus_llm_sentiment.py   # needs OPENAI_API_KEY, ~$0.05
python dashboard/generate_dashboard.py
```

Writes `dashboard/index.html` and `dashboard/Dash_README.md` with current metrics, charts, executive summary, and quotes.

### View static HTML (`dashboard/index.html`)

```bash
open dashboard/index.html
```

Includes: executive summary, KPI cards, Chart.js visualisations (sentiment, source comparison, issues, brand mentions, negative tone), per-telco table, quotes, recommendations, limitations.

See `dashboard/Dash_README.md` (auto-generated).

---

## Data dictionary (summary)

Column details for raw and processed files are in [`data/README.md`](data/README.md). Core processed columns:

| Column | Description |
|--------|-------------|
| `source` | `reddit`, `hwz` |
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

# 4b. Clean corpus: dedupe, drop off-topic threads, thread-weighted shares
python processing/build_clean_corpus.py

# 5. Regenerate + view dashboard
python dashboard/generate_dashboard.py
open dashboard/index.html
```

Full CLI options: [`README.md`](README.md).

---

## Planned next steps

- [x] **Fill human issue/sentiment labels** on representative and challenge sheets; compare VADER/rules vs GPT-4o-mini and GPT-4o.
- [~] **Second annotator / kappa** — κ reported per set from the guide-applied B file; guide rule for failure reports added 26 Sep 2026; relabel the overlap under it and confirm challenge-overlap independence.
- [ ] **Transformer benchmark** — install `transformers` + `torch`; compare against VADER on the representative labels.
- [x] **LLM issue extraction** — hybrid `processing/issue_extraction.py --use-llm --llm-unresolved-only --llm-model gpt-4o` on 8,786 unresolved rows; dashboard overlay complete. Do not rerun all-row LLM issues.
- [ ] **Scale coverage** — `processing/coverage_checker.py --target 1000` per telco.
- [x] **Auto-regenerate dashboard** — `dashboard/generate_dashboard.py` rebuilds `index.html` + `Dash_README.md` from CSVs, overlaying hybrid issue labels.
- [x] **Clean corpus + GPT-4o-mini sentiment + held-out hybrid test** — report findings, recommendations and limitations rewritten (26 Sep 2026).
- [ ] **Capstone write-up** — title-page placeholders; compile `final_report.tex`.

---

## Scripts reference

| File | Role |
|------|------|
| `scrapers/hwz_forum_scraper.py` | Single HWZ forum scrape |
| `scrapers/hwz_multi_forum_scraper.py` | Multiple XenForo forums |
| `scrapers/reddit_scraper.py` | Reddit posts/comments (no API key) |
| `processing/telco_labeler.py` | Telco detection + VADER/LLM sentiment |
| `processing/preprocess.py` | Clean + normalize raw CSVs |
| `processing/create_labeled_sample.py` | Manual-label evaluation template |
| `processing/issue_extraction.py` | Issue taxonomy + optional LLM |
| `processing/coverage_checker.py` | Auto loop until per-telco target met |
| `processing/build_clean_corpus.py` | Dedupe, drop off-topic threads, per-thread shares |
| `models/llm_evaluation.py` | Blind GPT-4o-mini vs VADER/rules evaluation |
| `models/sentiment_benchmark.py` | VADER vs transformer evaluation |
| `dashboard/generate_dashboard.py` | Regenerate static HTML dashboard + Dash_README from CSVs |
| `dashboard/index.html` | Static Chart.js summary dashboard (generated) |
