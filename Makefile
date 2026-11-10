PY ?= python

test:     ## unit tests, no network needed
	PYTHONPATH=. $(PY) -m pytest -q
ingest:   ## pull postings from Greenhouse and Remotive into DuckDB
	PYTHONPATH=. $(PY) -m marketlens.ingest.run
dedupe:   ## mark repeated postings and rebuild the jobs view
	PYTHONPATH=. $(PY) -m marketlens.dedupe
dbt:      ## data quality tests: nulls, unique keys, freshness, row count drop
	cd dbt && dbt build --profiles-dir .
daily: ingest dedupe dbt  ## what the scheduled job will run

.PHONY: test ingest dedupe dbt daily
