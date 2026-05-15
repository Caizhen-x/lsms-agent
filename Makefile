.PHONY: install ingest catalog run clean

PY ?= python3

install:
	$(PY) -m pip install -e .

ingest:
	$(PY) -m ingest.convert_to_parquet

catalog:
	$(PY) -m ingest.build_catalog

docs-index:
	$(PY) -m ingest.build_docs_index

all-ingest: ingest catalog docs-index

run:
	chainlit run server/app.py -w --port 8000

clean:
	rm -rf catalog/
