# MarketLens

A small data pipeline that collects public job postings, cleans them, and shows which skills employers ask for, by role family and by city.

**Live results page:** https://manaswichowdary.github.io/marketlens/

I built it to practice the parts of data work that tutorials skip: messy input, duplicate records, checks that fail loudly, and being honest about what the data can and cannot tell you.

## What it does

1. **Ingest.** Pulls postings from the public Greenhouse boards API (36 company boards) and Remotive. Adzuna is supported but optional, because its free plan only allows 25 calls. Every raw response is saved as JSON under `data/raw/<source>/` before anything is changed.
2. **Store.** Writes to DuckDB. Re-running never creates repeats, because rows are keyed by (source, source_id).
3. **Dedupe.** The same job can appear more than once, so postings are matched on cleaned company, title and location.
4. **Checks.** dbt tests run on the data: not null, unique, allowed source values, freshness, and a check that the row count did not suddenly collapse.
5. **Skills.** A dictionary of about 170 skills is matched against each posting, with context rules for words that mean something else in plain English (Go, R, C, Swift, React, Spring, Excel, Spark).
6. **Trends.** Top skills by role family and by city, plus a rising and falling view. A daily snapshot table is saved so real trends can be computed after several weeks.

## Daily run on AWS

The pipeline runs every day at 13:00 UTC (6 AM in Phoenix) on AWS Lambda, started by an EventBridge schedule. Lambda starts empty each time, so the DuckDB file lives in S3: the function downloads it, runs ingest, dedupe, skills and trends, checks that the run looks healthy, posts to Slack if it does not, and uploads the file again. Raw JSON from each run is kept in S3 and expires after 30 days.

- Deploy with `python deploy/deploy_aws.py` (see the file for what it creates). It is safe to run twice. The role it creates can only read and write its own bucket and write its own logs.
- One real run in AWS matched my laptop: 8,221 postings, 203 duplicates (2.5%), 5,516 jobs with a skill.
- The health check in `marketlens/alerts.py` flags a failed run, data older than 36 hours, a fetch that drops by more than half, and more than 5 skipped company boards. It sends a Slack message only when something is wrong, and it also makes the Lambda run count as an error.
- The dbt tests do not run inside Lambda, because dbt is too heavy to package. The health check covers the same row count and freshness rules there. dbt still runs on my laptop with `make dbt`.
- A scheduled run is not proof until it has run on its own. The first scheduled run is November 11, 2026.

Run everything with `make daily`, or one step at a time: `make ingest`, `make dedupe`, `make skills`, `make trends`, `make dbt`. Tests: `make test` (69 tests, including the Lambda handler and the deploy script on a fake AWS).

## Results on real data (one run, November 10, 2026)

- 8,224 postings collected, 8,020 unique jobs after dedupe.
- 68.8% of jobs have at least one skill found. Most of the rest are non technical roles (sales, legal, people).
- 18 role families. "Other" is 781 jobs (about 10%).
- All dbt checks passed on this run.

Example output: Solutions Engineering jobs name Python in 60% of postings, AWS in 45%, Azure in 41%. In San Francisco, 23% of jobs mention LLMs.

## Data problems I found and fixed

**The duplicate finder merged different jobs.** My first version was too loose. It reported 8.3% duplicates, but when I read the merged pairs, many were different teams at the same company (for example "CXI" and "IAM", or "Terminal" and "Tax"). I rewrote it to keep team text in parentheses, to allow only one misspelled word on longer titles, and to keep the full location set. The measured duplicate rate on real data is 2.5%. I had guessed 18% before looking.

**Company boilerplate inflated skills.** Every Databricks posting mentions Databricks, and every Elastic posting mentions Elasticsearch, so those skills looked hugely popular. I now ignore any sentence that appears in at least max(10, 20%) of one company's postings, and I ignore skills named after the company itself unless they are in the title.

**Role and city labels were noisy.** My first trends run put 1,643 jobs in "Other" and had "hybrid" and "united states" as cities. I rewrote the role rules (order matters: "Ads Policy" must be a policy job, not marketing) and the city parser, then checked the result against a sample of real titles.

**Comparing all jobs hid a mix effect.** A burst of sales postings made sales tools look like rising skills. Rising and falling now compares only technical roles.

## Limits (please read)

- The skill list is a dictionary of about 170 entries. A skill not in it is not counted. 31.2% of jobs had no skill found.
- The own product rule only removes skills named after the company. A skill mentioned in unique sentences still counts.
- The rising and falling view uses posting dates, but the API only returns jobs that are still open. Old, already closed jobs are missing, so this is a hint, not a true trend. Posting dates go back to 2019.
- Greenhouse's `first_published` date can be later than the true first posting date.
- Commas in locations are ambiguous, so a few cities may be wrong.
- The fuzzy duplicate rule found 0 merges on real data. Exact matching did all of the work.
- Remotive returned only 13 postings, so almost all data comes from Greenhouse boards.
- Companies on the boards are the ones I chose, so results describe those 36 companies, not the whole job market.
- Results page: `make site` builds `docs/index.html` from the database (top skills, role families, cities). It shows no trend chart until there are 14 days of daily snapshots, and says so on the page.
- Not built yet: an LLM fallback for jobs with no skill found. Real trends need weeks of daily snapshots first, and the daily run only started on November 10, 2026.

## Setup

```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
make test
make ingest
```

Optional: put `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` in a `.env` file and use `--source adzuna`.

## Layout

- `marketlens/ingest/` source readers and the run command
- `marketlens/store.py` DuckDB storage and run log
- `marketlens/dedupe.py` duplicate finder
- `marketlens/skills_dictionary.py`, `skills.py`, `extract.py` skill extraction
- `marketlens/trends.py` role families, cities, trends, daily snapshot
- `marketlens/site.py` builds the static results page in `docs/index.html` (`make site`)
- `dbt/` data checks
- `tests/` unit tests
