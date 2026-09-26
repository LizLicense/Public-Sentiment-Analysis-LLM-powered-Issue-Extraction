# Agent sync — Singapore telco sentiment capstone

Handoff from Cursor agent chats in this workspace (through 21 Sep 2026). Read this before changing code, the dashboard, or `final_report.tex`. Canonical status also lives in `Project_Progress.md` and `README.md`.

**Project:** Public Sentiment Analysis of Mobile Plan Launches Using LLM-powered Issue Extraction (SMU capstone, student Zixin).
**Repo:** `https://github.com/LizLicense/Public-Sentiment-Analysis-LLM-powered-Issue-Extraction.git` on `main`.
**Run everything from** `/Users/lizliao/Downloads/capstone/WIP`.

## What the chats built

1. **Pipeline (6 Jul 2026).** Scrapers (HWZ, Reddit, Twitter scaffold) → `processing/preprocess.py` → `processing/telco_labeler.py` (brand + VADER) → `processing/issue_extraction.py` → dashboards. Folder layout is `scrapers/`, `processing/`, `models/`, `dashboard/`, `data/raw`, `data/processed`, `data/evaluation`.
2. **Coverage and analysis.** `processing/coverage_checker.py` loops scrapes toward 1,000 posts per telco. A 158-row forum sample (Reddit + HWZ) drove the first executive summary, static Chart.js dashboard, Streamlit app, professor email, and SMU-template PPT.
3. **Blind evaluation (Sep 2026).** Model-prefilled labels were thrown out. Annotator A filled `representative_annotator_a.csv` (300; 295 used) and `challenge_annotator_a.csv` (100). Those two sets must not be pooled. `double_annotation_annotator_b.csv` is still empty — do not claim Cohen’s kappa or dual annotation.
4. **LLM vs baselines.** Sentiment: `gpt-4o-mini-2024-07-18` wins (macro F1 **0.631** vs GPT-4o 0.623 vs VADER **0.360**). Issues: keyword rules beat all-row GPT-4o-mini (0.64 vs 0.50) and all-row GPT-4o (rules **0.639** vs GPT-4o **0.600**). Hybrid wins issues: rules first, then `gpt-4o-2024-08-06` only on `general_discussion` (**0.680**).
5. **Corpus hybrid (done, do not rerun).** 8,786 unresolved rows, 879 batches, 0 failures, ~29.7 min, **$3.45**. General discussion 8,786 → 6,180; most reassigned rows became `network_quality`. Outputs:
   - `data/processed/issues_posts_labeled_2026-08-21_203752_gpt4o_hybrid.csv`
   - `data/processed/issues_summary_gpt4o_hybrid.json`
   - `data/evaluation/llm_comparison_representative_gpt4o_hybrid/`
6. **Dashboard + report.** `dashboard/generate_dashboard.py` overlays hybrid labels. On the 158-row sample, 97 posts matched; Network Quality 41 (26%), App & Account 39 (25%). Sentiment unchanged: 61% happy / 22% not happy / 18% neutral. Weekly huddle playbook is in the dashboard; queue was 13, below the n≥20 act threshold. `final_report.tex`, `README.md`, and `Project_Progress.md` already describe the hybrid pass as finished.

## Decisions that must stay consistent

- **VADER** is the sentiment baseline (lexicon + rules: ≥0.05 happy, ≤−0.05 not_happy, else neutral). **Keyword regexes** are the issue baseline. **GPT-4o-mini / GPT-4o** are the LLMs. Do not call VADER an LLM.
- **Ten issue labels** (snake_case in files, readable names for annotators): Network Quality, Pricing & Promotions, Mobile Plans, Roaming, Porting, Customer Service, Billing & Payment, App & Account, Devices, General Discussion. General Discussion only when no specific label fits, and never beside a specific label.
- **Issues are multi-label. Sentiment is one label per post.** Mixed-brand posts: one overall `happy` / `not_happy` if one tone dominates, otherwise `neutral`, with the split in `notes_manual`. Never write `happy,not_happy` in `sentiment_manual`. Brand-specific sentiment would need one row per brand; that was not built.
- **`confidence_manual`** is the annotator’s certainty (`high` / `medium` / `low`), not a model score.
- **Eight Telecom** must not match the number “eight” or “eight buses”. Detection is context-gated in `processing/telco_labeler.py` (`is_eight_telco_reference`). Irrelevant hits are `telco_relevance_manual=no` with sentiment and issues left blank.
- **Do not rerun** all-row LLM issue extraction on 15,504 posts. Gold labels said rules already beat that. Do not rerun the $3.45 unresolved corpus pass unless the user asks.
- **Do not** treat the 158-row dashboard as the full corpus, publish a brand league table from small n (Giga n=6 was called out), or merge challenge metrics into headline representative metrics.
- Full-corpus LLM sentiment + summaries was estimated ~$0.45–$0.55 and was **not** run. Professor feedback did not require it.

## Still open

- Title page in `final_report.tex`: surname, student ID, course, supervisor. Then compile and skim the PDF.
- Second annotator on `double_annotation_annotator_b.csv`, then kappa. Adjudicate in a new file; never overwrite the two original annotation files. `representative_adjudicated.csv` is that adjudication slot, not a third blank sheet.
- Spot-check the 2,606 rows GPT-4o moved out of `general_discussion` before treating huddle spikes as incidents.
- Optional, not required by the professor: Twitter-RoBERTa / `transformers` benchmark; more scraping via `coverage_checker.py --target 1000`.
- Strip credentials before submission. A GitHub classic token was pasted into an old Cursor chat — revoke it if it is still valid. Do not commit real keys. `do not upload.md` is gitignored. `data/api key.md` is tracked and should stay a placeholder. Set `OPENAI_API_KEY` in the environment; leave `HARDCODED_OPENAI_API_KEY` in `processing/telco_labeler.py` empty.

## Annotation files

| File | Role |
|------|------|
| `data/evaluation/representative_annotator_a.csv` | Primary gold set (295 used) |
| `data/evaluation/challenge_annotator_a.csv` | Hard cases; report separately |
| `data/evaluation/double_annotation_annotator_b.csv` | Second annotator; empty |
| `data/evaluation/representative_adjudicated.csv` | Post-discussion adjudication copy |
| `data/evaluation/ANNOTATION_GUIDE.md` | Label rules |
| `data/evaluation/sampling_metadata.json` | Seed and source weights |

Guide: `data/evaluation/ANNOTATION_GUIDE.md`.

## Source chats

- [Pipeline build and cleanup](f30f73d8-9458-4ee6-b930-1bb4150eff52) — scrapers, labeling, preprocess, eval sample, Streamlit fixes, git remote, professor progress email.
- [Forum dashboard and PPT](263f2097-1128-4bf6-bd8e-80b0158feedc) — executive summary, `dashboard/`, SMU PPT.
- [Report and gold eval](3afe05d3-0ccc-43e4-84ae-ac7c32e5bfab) — professor LaTeX feedback, blind sets, first LLM eval.
- [Hybrid issue extraction](6b81e23a-0610-40f4-95e5-1719a7b15b49) — latest; taxonomy, hybrid GPT-4o, dashboard huddle, report marked done. Prefer this chat if it conflicts with the September 19 thread.
