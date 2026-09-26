# Telco Sentiment Dashboard

Static HTML dashboard for Singapore telco forum discussion (Reddit + HWZ).

**Auto-generated:** 2026-09-26 01:37 UTC

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

- Input: `data/processed/clean_posts_2026-08-21_203752_mini_sentiment.csv`
- 1,706 unique posts in 105 telco threads, 2019-03-26 to 2026-04-09
- Reddit 1,253 / HWZ 453
- Sentiment: `gpt-4o-mini-2024-07-18` via `models/corpus_llm_sentiment.py` (1,706 labelled, 0 failed, ~$0.05).
- Issues: keyword rules, then GPT-4o on unresolved rows (hybrid file).

Sentiment (GPT-4o-mini): 18% happy / 55% not happy / 27% neutral.

| Issue | Per post | Thread-weighted | Not-happy posts |
|---|---|---|---|
| Network Quality | 52.8% | 45.3% | 599 |
| Pricing & Promotions | 6.8% | 6.1% | 58 |
| Mobile Plans | 12.2% | 13.4% | 80 |
| Roaming | 2.2% | 3.7% | 14 |
| Porting | 2.8% | 2.7% | 11 |
| Customer Service | 3.0% | 4.1% | 31 |
| Billing & Payment | 3.6% | 4.7% | 40 |
| App & Account | 1.2% | 3.3% | 11 |
| Devices | 6.2% | 6.0% | 45 |
| General Discussion | 9.1% | 10.7% | 50 |

## Contents

- Executive summary and KPI cards
- Weekly huddle queue over time against the n ≥ 20 threshold
- Sentiment (with the human-label check), Reddit vs HWZ on the same labeller
- Issue shares per post and thread-weighted; not-happy posts by issue
- Brand mentions and not-happy share for brands with at least 10 mentions
- Per-telco table, quotes, recommendations ordered by not-happy share, limitations
