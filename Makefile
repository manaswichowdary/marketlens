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
dbt:      ## data quality tests: nulls, unique keys, freshness, row count drop
	cd dbt && dbt build --profiles-dir .
daily: ingest dedupe skills trends dbt  ## what the scheduled job will run

.PHONY: test ingest dedupe skills trends dbt daily
