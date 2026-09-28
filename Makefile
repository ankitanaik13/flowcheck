.PHONY: setup data run test benchmark report lint
setup:
	python3 -m venv .venv
	.venv/bin/python -m pip install -r requirements.lock.txt
	.venv/bin/python -m pip install --no-deps -e .
data:
	.venv/bin/python scripts/prepare_data.py
run:
	.venv/bin/python -m uvicorn pipelinemedic.api:app --app-dir src --host 127.0.0.1 --port 8765 --workers 1
test:
	.venv/bin/python -m pytest -q --cov=pipelinemedic --cov-report=json:artifacts/coverage.json --junitxml=artifacts/tests.xml
benchmark:
	.venv/bin/python scripts/benchmark.py
report:
	.venv/bin/python scripts/build_report.py
lint:
	.venv/bin/ruff check src scripts tests
