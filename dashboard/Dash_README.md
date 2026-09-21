# Telco Sentiment Dashboard

Static HTML summary dashboard for Singapore telco forum sentiment analysis.

**Auto-generated:** 2026-09-19 16:23 UTC

## Generate / refresh

From project root:

```bash
python dashboard/generate_dashboard.py
```

Optional custom inputs:

```bash
python dashboard/generate_dashboard.py \
  --reddit data/processed/labeled_sample.csv \
  --hwz hwz_telco_posts_labeled.csv \
  --issues data/processed/issues_posts_labeled_2026-08-21_203752_gpt4o_hybrid.csv
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

- **Weekly huddle playbook** (queue → 10 posts → tickets → one owner → next week)
- **Executive summary** and KPI cards
- **Charts** with takeaway titles: tone vs CSAT, Reddit-first complaints, issue routing, not-happy themes, mention volume, large-n negative tone
- **Per-telco table** (n<10 flagged), quotes, owner-action recommendations, limitations

## Data source

| File | Rows (telco-relevant) |
|------|----------------------|
| `data/processed/labeled_sample.csv` | 67 |
| `hwz_telco_posts_labeled.csv` | 91 |
| **Combined** | **158** |

Sentiment: 61% happy / 22% not_happy / 18% neutral.

Issue labels: keyword rules, then GPT-4o on unresolved `general_discussion` rows (`data/processed/issues_posts_labeled_2026-08-21_203752_gpt4o_hybrid.csv`; 97 of 158 dashboard posts matched).

## Streamlit version

For an interactive filterable dashboard, run:

```bash
pip install streamlit plotly pandas
streamlit run dashboard/app.py
```
