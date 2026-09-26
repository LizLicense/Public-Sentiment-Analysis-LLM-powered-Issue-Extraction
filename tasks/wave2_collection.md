# Task: collect wave-2 forum data (posts after 2026-04-09)

The existing corpus ends on 2026-04-09; 74% of it is from 2026 and 39% sits in threads about one
Singtel outage. This task
collects newer Reddit and HardwareZone (HWZ) telco discussion into `data/raw/wave2/`, without
touching any existing file.

Run everything from the repository root. Stop at the first failed check and report it.

## 0. Preconditions

1. The repo is up to date and contains the fixed scrapers:
   ```bash
   git pull
   grep -q -- "--latest-pages" scrapers/hwz_forum_scraper.py && grep -q "li.pageNav-page" scrapers/hwz_forum_scraper.py && echo "HWZ scraper OK"
   grep -q -- "--mode" scrapers/reddit_scraper.py && grep -q "strict_telco_match" scrapers/reddit_scraper.py && echo "Reddit scraper OK"
   ```
   Both lines must print OK. If not, stop: the fixed scrapers have not been pushed yet.
2. Python environment (the `venv/` folder is gitignored):
   ```bash
   python3 -m venv venv
   venv/bin/pip install -q requests pandas tqdm beautifulsoup4 lxml
   mkdir -p data/raw/wave2
   ```
3. Reddit credentials are set in the user's terminal. Check presence only, never values:
   ```bash
   for v in REDDIT_CLIENT_ID REDDIT_CLIENT_SECRET REDDIT_USER_AGENT; do printenv "$v" >/dev/null && echo "$v set" || echo "$v MISSING"; done
   ```
   If any is missing, stop and ask the user to create a Reddit "script" app at
   https://www.reddit.com/prefs/apps and run, in their own terminal:
   ```bash
   export REDDIT_CLIENT_ID="..."
   export REDDIT_CLIENT_SECRET="..."
   export REDDIT_USER_AGENT="script:sg-telco-capstone:v1.0 (by /u/<their-reddit-username>)"
   ```
4. Record the list of existing raw files, so step 5 can prove nothing changed:
   ```bash
   ls -l data/raw/*.csv > data/raw/wave2/_existing_before.txt
   shasum data/raw/*.csv >> data/raw/wave2/_existing_before.txt
   ```

## 1. Reddit pilot (about 1 minute)

```bash
venv/bin/python scrapers/reddit_scraper.py --mode search \
  --subreddits singapore --queries "singtel,simba" --limit 20 --max-comments-per-post 20 \
  --since 2026-04-10 --strict-match --out data/raw/wave2/reddit_pilot
```

Check: the log says `Reddit auth: application-only OAuth`, a CSV is saved, and its `comment_time`
values are on or after 2026-04-10. On HTTP 401/403, stop and report: the credentials are wrong or
the app type is not "script".

## 2. Reddit full run (30–90 minutes)

```bash
venv/bin/python scrapers/reddit_scraper.py --mode search \
  --subreddits singapore,askSingapore --limit 300 --max-comments-per-post 500 \
  --since 2026-04-10 --strict-match --out data/raw/wave2/reddit_search
```

This runs 22 telco searches per subreddit, newest first, and fetches top-level comments. Let it
finish; it prints progress per query. If it stops on rate limits (HTTP 429), wait 10 minutes and
rerun the same command. Output names carry a timestamp, so reruns never overwrite.

## 3. HWZ run (20–40 minutes; skip if the user says HWZ is already done)

```bash
venv/bin/python scrapers/hwz_forum_scraper.py --forum-pages 5 --max-threads 60 \
  --max-thread-pages 15 --latest-pages --since 2026-04-10 --out data/raw/wave2/hwz_latest
```

`--latest-pages` reads the newest pages of each thread. Check: the saved CSV has `thread_page`
values above 1 for long threads, and `timestamp` values on or after 2026-04-10.

## 4. Summarise the new data

```bash
venv/bin/python - <<'EOF'
import glob, pandas as pd
def ids(d):
    out = set()
    for r in d.to_dict("records"):
        if str(r.get("source")) == "reddit":
            cid = r.get("comment_id")
            out.add(f"c:{cid}" if isinstance(cid, str) and cid else f"p:{r.get('post_id')}")
        else:
            out.add(f"h:{r.get('thread_url')}|{r.get('timestamp')}")
    return out
old = pd.concat([pd.read_csv(f, low_memory=False) for f in glob.glob("data/raw/*.csv")], ignore_index=True)
old_ids = ids(old)
for f in sorted(glob.glob("data/raw/wave2/*.csv")):
    d = pd.read_csv(f, low_memory=False)
    if "source" not in d:
        d["source"] = "reddit" if "reddit" in f else "hwz"
    t = d["comment_time"] if "comment_time" in d else d["timestamp"]
    new = ids(d)
    print(f"{f}: rows={len(d)} unique={len(new)} overlap_with_old={len(new & old_ids)} from={t.min()} to={t.max()}")
EOF
```

## 5. Prove existing files are untouched

```bash
shasum data/raw/*.csv | diff - <(grep -E '^[0-9a-f]{40} ' data/raw/wave2/_existing_before.txt) && echo "existing raw files unchanged"
```

Must print `existing raw files unchanged`. If not, stop and report which file differs.

## 6. Report

Write `data/raw/wave2/RUN_REPORT.md` with: commands run, each output file and its row count,
unique posts, overlap with old data, date range, and any errors. Show it to the user.

Do not run preprocessing, labelling, the OpenAI API or the dashboard. Those steps come next, on the
user's instruction, and will add the wave-2 files to the corpus without altering the original files.

## 7. Hand-off (only if the user asks)

```bash
git add data/raw/wave2/*.csv data/raw/wave2/*.jsonl data/raw/wave2/RUN_REPORT.md
git commit -m "Add wave-2 Reddit and HWZ data (posts after 2026-04-09)"
git push
```

Check `git diff --cached --stat` first: only `data/raw/wave2/` may appear.
