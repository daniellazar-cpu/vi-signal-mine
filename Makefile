.PHONY: install test run

install:
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"

test:
	.venv/bin/python -m pytest -q

run:
	.venv/bin/python -m uvicorn vsm.app:app --port 8811
