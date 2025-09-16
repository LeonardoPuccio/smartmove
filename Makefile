.PHONY: format lint fix test test-unit test-integration test-e2e test-performance clean install-dev all

format:
	black .
	isort . --profile black

lint:
	ruff check .
	black --check .
	isort . --check-only --profile black

fix:
	ruff check . --fix
	black .
	isort . --profile black

# Individual test suites (no coverage)
test-unit:
	pytest tests/test_unit.py tests/test_cli.py -v

test-integration:
	pytest tests/test_integration.py -v

test-e2e:
	sudo .venv/bin/python3 -m pytest tests/test_e2e.py -v

test-performance:
	sudo RUN_LARGE_SCALE_TESTS=1 .venv/bin/python3 -m pytest tests/test_e2e.py::TestLargeScalePerformance -v

# Comprehensive test with coverage (industry standard)
test:
	@echo "Running comprehensive test suite with coverage..."
	rm -f .coverage*
	pytest tests/test_unit.py tests/test_integration.py tests/test_cli.py --cov=. --cov-report=xml --cov-report=html --junitxml=test-results.xml -v
	@echo "Running E2E tests with coverage append..."
	sudo .venv/bin/python3 -m pytest tests/test_e2e.py --cov=. --cov-append --cov-report=xml --cov-report=html -v
	@echo "Coverage report generated: htmlcov/index.html"

# Quick test for development (no coverage overhead)
test-quick:
	pytest tests/test_unit.py tests/test_integration.py -v

clean:
	rm -rf .pytest_cache/ .coverage* htmlcov/ coverage.xml test-results.xml
	rm -rf build/ dist/ *.egg-info/
	find . -type d -name __pycache__ -exec rm -rf {} +

install-dev:
	pip install -r requirements-dev.txt
	pip install -e .
	pre-commit install

all: fix test