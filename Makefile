PY ?= python

test:     ## unit tests, no network needed
	PYTHONPATH=. $(PY) -m pytest -q
ingest:   ## pull postings from Greenhouse and Remotive into DuckDB
	PYTHONPATH=. $(PY) -m marketlens.ingest.run
dedupe:   ## mark repeated postings and rebuild the jobs view
	PYTHONPATH=. $(PY) -m marketlens.dedupe
skills:   ## find skills in each job with the dictionary and print how well it did
	PYTHONPATH=. $(PY) -m marketlens.extract
trends:   ## skills by role and city, rising and falling, and today's snapshot
	PYTHONPATH=. $(PY) -m marketlens.trends
site:     ## build docs/index.html, a static results page, from the database
	PYTHONPATH=. $(PY) -m marketlens.site
llm:      ## ask Claude Haiku for skills in technical jobs with none found: make llm LIMIT=25
	PYTHONPATH=. $(PY) -m marketlens.llm_fallback --limit $(or $(LIMIT),25)
dbt:      ## data quality tests: nulls, unique keys, freshness, row count drop
	cd dbt && dbt build --profiles-dir .
alert:    ## check the latest runs and send a Slack message if something is wrong
	PYTHONPATH=. $(PY) -m marketlens.alerts
daily: ingest dedupe skills trends dbt alert  ## what the scheduled job will run

.PHONY: test ingest dedupe skills trends site llm dbt alert daily
