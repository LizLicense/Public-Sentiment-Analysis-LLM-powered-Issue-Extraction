# Agent sync — Singapore telco sentiment capstone

Handoff from Cursor agent chats in this workspace (through 21 Sep 2026). Read this before changing code, the dashboard, or `final_report.tex`. Canonical status also lives in `Project_Progress.md` and `README.md`.

**Project:** Public Sentiment Analysis of Mobile Plan Launches Using LLM-powered Issue Extraction (SMU capstone, student Zixin).
**Repo:** `https://github.com/LizLicense/Public-Sentiment-Analysis-LLM-powered-Issue-Extraction.git` on `main`.
**Run everything from the repo root** (the folder holding this file). Scripts use paths relative to it, such as `data/processed/`.

## What the chats built

1. **Pipeline (6 Jul 2026).** Scrapers (HWZ, Reddit) → `processing/preprocess.py` → `processing/telco_labeler.py` (brand + VADER) → `processing/issue_extraction.py` → dashboards. Folder layout is `scrapers/`, `processing/`, `models/`, `dashboard/`, `data/raw`, `data/processed`, `data/evaluation`.
2. **Coverage and analysis.** `processing/coverage_checker.py` loops scrapes toward 1,000 posts per telco. A 158-row forum sample (Reddit + HWZ) drove the first executive summary, static Chart.js dashboard, a Streamlit app (removed 25 Sep 2026; the static HTML dashboard is the only dashboard), professor email, and SMU-template PPT.
3. **Blind evaluation (Sep 2026).** Model-prefilled labels were thrown out. Annotator A filled `representative_annotator_a.csv` (300; 295 used) and `challenge_annotator_a.csv` (100). Those two sets must not be pooled. `double_annotation_annotator_b.csv` is now filled (100 rows: 60 representative, 40 challenge; 98 with sentiment). Kappa has not been reported yet; compute it per set, not pooled.
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
- **Reddit vs HWZ:** never claim one platform is more negative. VADER showed 30% vs 15%; GPT-4o-mini on the clean corpus shows 60% vs 40%, but Reddit is all 2026 and holds the outage threads — outside them it is 43% vs 40%, matching human gold (51% vs 47%). `labeled_sample.csv`'s `sentiment_label_manual` is a VADER copy, not human labels.
- **Clean corpus (25 Sep 2026):** `processing/build_clean_corpus.py` turns 15,504 rows into 2,686 unique posts, then drops 47 off-topic threads (980 posts), leaving **1,706 posts in 105 threads** (`data/processed/clean_posts_2026-08-21_203752.csv`). Quote corpus shares from `clean_corpus_summary.json`, never from raw rows, and prefer findings that hold per post, per thread and capped at 5 per thread. Corpus-level App & Account is ~1–3%, not the dashboard sample's 25%.
- **Do not** treat the 158-row dashboard as the full corpus, publish a brand league table from small n (Giga n=6 was called out), or merge challenge metrics into headline representative metrics.
- **Corpus sentiment (26 Sep 2026):** GPT-4o-mini labelled all 1,706 clean posts ($0.047) via `models/corpus_llm_sentiment.py`: 18% happy / 55% not happy / 27% neutral (human gold 18/50/32). The dashboard reads this file. Do not rerun unless the corpus changes.
- **Held-out result:** on the 100 challenge posts the hybrid (0.509) does not significantly beat rules (0.499); GPT-4o on every post is best (0.596). Present the hybrid's 0.680 as optimistic. All figures: `data/evaluation/robustness_summary.json` (`models/robustness_checks.py`, no API calls).
- **Singtel / outage:** 22 outage threads hold 39% of clean posts. Singtel is 63% not happy overall but 45% outside them (StarHub 47%). Do not rank brands.

- **One corpus, no "waves" in anything a reader sees (3 Oct 2026).** The deck, `final_report.tex` and the dashboard present a single corpus: 9,162 unique posts in 349 threads, collected up to 26 Sep 2026, in one file `data/processed/corpus_posts_mini_sentiment.csv` (intermediate `corpus_posts.csv`; build with `processing/prepare_new_posts.py` then `--merge`). Never write "wave 1/2", "v1/v2" or "original corpus" in those three. The `wave` column inside the CSV and `robustness_summary.json` keys (`corpus` = posts to 9 Apr, `corpus_v2` = full corpus) are internal and stay. One dashboard: `dashboard/index.html` (`index_v1/v2.html` deleted). The outage case study now uses the full corpus: 45 outage threads, 1,102 posts (12%), 71% not happy vs 40% elsewhere, 1,099 of them on Reddit. Reddit after 9 Apr comes from the Arctic Shift archive (`scrapers/reddit_archive_scraper.py`) because Reddit blocks unauthenticated access; HWZ `--latest-pages` (the HWZ page counter was broken before, so early HWZ data is page 1 of each thread only); raw files in `data/raw/apr_sep_2026/`. Recent-posts gold set (27 Sep 2026): Annotator A sheet `recent_annotator_a.csv` (97 relevant), scored by `models/score_recent_gold.py` → `recent_gold_scores.json`. All three gold sheets are combined in `data/evaluation/gold_labels.csv` (`processing/build_gold_labels.py`; `evaluation_set` = representative / challenge / recent, recent IDs REC-nnnn). **Since 16 Oct 2026 the deck and `final_report.tex` merge representative + recent into one 392-post representative set (388 for issues; GPT-4o run on the 93 recent posts, $0.046)**, scored by `models/score_merged_gold.py` → `merged_gold_scores.json`: mini 0.641 vs VADER 0.380 vs GPT-4o 0.611; issues hybrid 0.639, rules 0.590, GPT-4o all 0.585, mini all 0.498. The challenge set stays separate and is never pooled. The 'not-happy is a floor' caveat was dropped (merged mini not-happy share 47% = human 47%). Professor's concern was low human κ: the report's 'Human agreement' subsection shows most A–B disagreement is one pattern (A not_happy / B neutral on bare failure reports; κ 0.37 → 0.57 without it) and mini–human κ is in the human–human range. Next-step priority 1 = raise human agreement (adjudicate A vs B, relabel A's overlap under the failure-report rule, more B overlap, recompute kappa); priority 2 = improve issue tagging (Customer Service weakest), because issue F1 cannot be read against noisy labels. Earlier separate scoring of the recent set alone (no longer quoted): GPT-4o-mini sentiment macro F1 0.637 vs VADER 0.428 (CI +0.09 to +0.33); mini under-calls not_happy (recall 0.59; 41% neutral vs gold 30%), so the corpus not-happy share is likely understated. Issues: hybrid 0.477 > rules 0.413. The scorer fixes the sheet's issue typos (`evices`, `pring & promotions`) at scoring time; the user fixed `netural` in the sheet. The huddle threshold is `auto` (2× median week = 115), not 20. Brands are ranked only with ≥1% of posts and ≥10 threads.
- **LLM spend so far:** about $5.30 for finished jobs plus ~$1.15 for a discarded wave-2 pass (Reddit rows sent without thread titles); never say "under $4" again.

## Still open

- Title page in `final_report.tex`: surname, student ID, course, supervisor. Then compile and skim the PDF.
- **Annotator B file (27 Sep 2026):** use `double_annotation_annotator_b_filled2.csv` (B's independent relabelling, own notes, new failure-report rule applied). Superseded: `double_annotation_annotator_b.csv` (contradicted B's notes, matched A) and `double_annotation_annotator_b_filled_guide.csv` (only sentiment revised). Sentiment κ: representative **0.39** (n=58), challenge **0.59** (n=40); 9/40 challenge rows identical on every field, 0 identical notes. Remaining disagreements are mostly A `not_happy` vs B `neutral`. Issue κ: Network 0.79, Devices 0.16, App 0.17, Customer Service 0.28. Adjudicate in a new file; never overwrite the two original annotation files. `representative_adjudicated.csv` is that adjudication slot, not a third blank sheet.
- Spot-check the 2,606 rows GPT-4o moved out of `general_discussion` before treating huddle spikes as incidents.
- Optional, not required by the professor: more scraping via `coverage_checker.py --target 1000`.
- **Leaked credentials (found 25 Sep 2026):** the first commit contains a HardwareZone login password (both HWZ scrapers) and a Twitter/X bearer token (in the since-deleted `scrapers/twitter_scraper.py`; Twitter/X was dropped as a source on 25 Sep 2026). The code now reads `HWZ_USERNAME`/`HWZ_PASSWORD` and `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET`/`REDDIT_USER_AGENT` from the environment. Change the HWZ password and revoke the X token; git history still holds the old values. Never hardcode credentials again.
- Strip credentials before submission. A GitHub classic token was pasted into an old Cursor chat — revoke it if it is still valid. Do not commit real keys. `do not upload.md` is gitignored. `data/api key.md` is tracked and should stay a placeholder. Set `OPENAI_API_KEY` in the environment; leave `HARDCODED_OPENAI_API_KEY` in `processing/telco_labeler.py` empty.

## Annotation files

| File | Role |
|------|------|
| `data/evaluation/representative_annotator_a.csv` | Primary gold set (295 used) |
| `data/evaluation/challenge_annotator_a.csv` | Hard cases; report separately |
| `data/evaluation/double_annotation_annotator_b_filled2.csv` | Second annotator, independent relabelling (60 representative + 40 challenge overlap); **use this** |
| `data/evaluation/double_annotation_annotator_b_filled_guide.csv` | Superseded second version (sentiment-only revision) |
| `data/evaluation/recent_annotator_a.csv` | Recent-posts gold sheet (10 Apr–26 Sep 2026), 100 posts (97 relevant); scores in `recent_gold_scores.json` |
| `data/evaluation/gold_labels.csv` | Annotator A's three gold sets in one file (500 rows); score per `evaluation_set`, never pooled |
| `data/evaluation/double_annotation_annotator_b.csv` | Superseded earlier version of annotator B; kept as evidence, not used |
| `data/evaluation/representative_adjudicated.csv` | Post-discussion adjudication copy |
| `data/evaluation/ANNOTATION_GUIDE.md` | Label rules |
| `data/evaluation/sampling_metadata.json` | Seed and source weights |

Guide: `data/evaluation/ANNOTATION_GUIDE.md`.

## Source chats

- [Pipeline build and cleanup](f30f73d8-9458-4ee6-b930-1bb4150eff52) — scrapers, labeling, preprocess, eval sample, Streamlit fixes, git remote, professor progress email.
- [Forum dashboard and PPT](263f2097-1128-4bf6-bd8e-80b0158feedc) — executive summary, `dashboard/`, SMU PPT.
- [Report and gold eval](3afe05d3-0ccc-43e4-84ae-ac7c32e5bfab) — professor LaTeX feedback, blind sets, first LLM eval.
- [Hybrid issue extraction](6b81e23a-0610-40f4-95e5-1719a7b15b49) — latest; taxonomy, hybrid GPT-4o, dashboard huddle, report marked done. Prefer this chat if it conflicts with the September 19 thread.
