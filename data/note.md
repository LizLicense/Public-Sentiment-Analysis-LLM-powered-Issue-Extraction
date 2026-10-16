Done so far
Scrapers (HWZ, Reddit) → data/raw/
Telco labeler (telco + sentiment + summary) → data/processed/
Data docs (data/README.md)
Preprocess script → cleaned CSV
Labeled-sample template (for manual eval)
Next steps (in order)
1. Create your labeled sample (short-term)
Run: python processing/create_labeled_sample.py -n 150
Manually fill sentiment_label_manual and issue_manual in the template (e.g. in Excel/Sheets).
Save as data/processed/labeled_sample.csv.
This gives you ground truth to evaluate models later.

3. Phase 4: Structured issue extraction
Use the fixed ten-topic taxonomy: Network Quality, Pricing & Promotions, Mobile Plans, Roaming, Porting, Customer Service, Billing & Payment, App & Account, Devices, and General Discussion.
Add a step (script or part of the pipeline) that uses the LLM to assign one or more issues per post (reuse your existing LLM setup).
Store results in a column like issues or issue_1, issue_2 in your processed/cleaned CSV.
4. Phase 5: Streamlit dashboard
New app (e.g. dashboard/app.py) that:
Loads your cleaned or labeled CSV from data/processed/.
Lets users filter by date, source, telco.
Shows sentiment distribution and issue breakdown.
Adds simple temporal and cross-brand views (e.g. trends over time, compare telcos).
Suggested “do this next”
Immediate: Generate the template and start labeling (step 1).

If you say which you want to do first (labeling workflow vs. issue extraction), I can outline exact commands and code changes step by step.


Run in order (now)
From project root (WIP/):

pip install -r requirements_telco_labeler.txt
Create / fill labeled sample (you already have template flow):
python processing/create_labeled_sample.py -n 150
# fill sentiment_label_manual + issue_manual, save as data/processed/labeled_sample.csv

python processing/coverage_checker.py --target 1000 --max-rounds 10

Run it now --1111
python processing/coverage_checker.py --target 1000 --max-rounds 10

after i run this: python processing/coverage_checker.py --target 1000 --max-rounds 10, what is next comand

After coverage_checker finishes, run this next:

python processing/preprocess.py --out data/processed/cleaned_posts.csv
python processing/telco_labeler.py --in data/processed/cleaned_posts.csv
python processing/issue_extraction.py
streamlit run dashboard/app.py