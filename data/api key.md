export OPENAI_API_KEY="sk-..."

venv/bin/python processing/telco_labeler.py \
  --in data/processed/cleaned_posts.csv \
  --use-llm-sentiment --use-llm-summary --llm-model gpt-4o-mini

venv/bin/python processing/issue_extraction.py \
  --use-llm --llm-unresolved-only --llm-model gpt-4o-mini