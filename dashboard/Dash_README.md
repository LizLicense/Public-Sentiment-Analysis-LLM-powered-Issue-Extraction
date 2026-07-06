# Telco Sentiment Dashboard

Static HTML summary dashboard for Singapore telco forum sentiment analysis.

**Auto-generated:** 2026-07-06 12:37 UTC

## Generate / refresh

From project root:

```bash
python dashboard/generate_dashboard.py
```

Optional custom inputs:

```bash
python dashboard/generate_dashboard.py \
  --reddit data/processed/labeled_sample.csv \
  --hwz hwz_telco_posts_labeled.csv
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

- **Executive summary** and KPI cards
- **Charts** (Chart.js): sentiment distribution, source comparison, issue themes, brand mentions, negative tone by brand
- **Per-telco table**, representative quotes, recommendations, limitations

## Data source

| File | Rows (telco-relevant) |
|------|----------------------|
| `data/processed/labeled_sample.csv` | 93 |
| `hwz_telco_posts_labeled.csv` | 100 |
| **Combined** | **193** |

Sentiment: 60% happy / 23% not_happy / 18% neutral.

## Streamlit version

For an interactive filterable dashboard, run:

```bash
pip install streamlit plotly pandas
streamlit run dashboard/app.py
```
