# Telco Sentiment Dashboard

Static HTML dashboard for Singapore telco forum discussion (Reddit + HWZ).

**Auto-generated:** 2026-09-27 10:52 UTC

## Generate / refresh

From project root:

```bash
python processing/build_clean_corpus.py        # once: unique posts in telco threads
python models/corpus_llm_sentiment.py          # once: GPT-4o-mini sentiment (~$0.05)
python dashboard/generate_dashboard.py
open dashboard/index.html
```

Without the GPT-4o-mini file the page falls back to VADER sentiment and says so.

## Data

- Input: `data/processed/clean_posts_v2_mini_sentiment.csv`
- 9,162 unique posts in 349 telco threads, 2019-03-26 to 2026-09-26
- Reddit 5,711 / HWZ 3,451
- Sentiment: `gpt-4o-mini-2024-07-18` via `models/corpus_llm_sentiment.py` (1,711 labelled, 0 failed, ~$0.05).
- Issues: keyword rules, then GPT-4o on unresolved rows (hybrid file).

Sentiment (GPT-4o-mini): 19% happy / 44% not happy / 37% neutral.

| Issue | Per post | Thread-weighted | Not-happy posts |
|---|---|---|---|
| Network Quality | 40.7% | 36.9% | 1991 |
| Pricing & Promotions | 8.1% | 6.6% | 311 |
| Mobile Plans | 13.8% | 12.6% | 462 |
| Roaming | 3.7% | 4.9% | 105 |
| Porting | 2.9% | 2.8% | 91 |
| Customer Service | 3.7% | 3.9% | 200 |
| Billing & Payment | 2.9% | 3.5% | 139 |
| App & Account | 3.7% | 9.2% | 135 |
| Devices | 5.9% | 6.5% | 191 |
| General Discussion | 14.6% | 13.0% | 389 |

## Contents

- Executive summary and KPI cards
- Weekly huddle queue over time against the threshold: n ≥ 115 (twice the median week of 57.5 over the last 26 weeks)
- Sentiment (with the human-label check), Reddit vs HWZ on the same labeller
- Issue shares per post and thread-weighted; not-happy posts by issue
- Brand mentions and not-happy share for brands with at least 92 posts and 10 threads
- Per-telco table, quotes, recommendations ordered by not-happy share, limitations
