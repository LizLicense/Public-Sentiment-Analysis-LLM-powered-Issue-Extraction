# Telco Sentiment Dashboard

Static HTML summary dashboard for Singapore telco forum sentiment analysis.

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

Metrics are from `data/processed/labeled_sample.csv` (Reddit) and `hwz_telco_posts_labeled.csv` (HWZ), n=192 telco-relevant posts.

## Streamlit version

For an interactive filterable dashboard, run:

```bash
pip install streamlit plotly pandas
streamlit run dashboard/app.py
```
