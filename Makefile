# media-importer

PYTHON ?= python3
VENV   := .venv
BIN    := $(VENV)/bin

.PHONY: help install run test lint format clean build package \
        publish-testpypi publish-pypi check-tools check-credentials

help:
	@echo "make install           Install the project and dev dependencies"
	@echo "make run               Launch the application"
	@echo "make test              Run the test suite"
	@echo "make lint              Run static analysis"
	@echo "make format            Format the source tree"
	@echo "make clean             Remove generated artifacts"
	@echo "make build             Build the Python package"
	@echo "make package           Build all distribution artifacts"
	@echo "make publish-testpypi  Build and publish to TestPyPI"
	@echo "make publish-pypi      Build and publish to PyPI"
	@echo "make check-tools       Verify exiftool and ffprobe are installed"

$(BIN)/python:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade pip

install: $(BIN)/python
	$(BIN)/python -m pip install -e ".[dev]"

run: install
	$(BIN)/media-importer

test: install
	$(BIN)/python -m pytest

lint: install
	$(BIN)/python -m ruff check src tests
	$(BIN)/python -m ruff format --check src tests

format: install
	$(BIN)/python -m ruff format src tests
	$(BIN)/python -m ruff check --fix src tests

clean:
	rm -rf build dist *.egg-info src/*.egg-info .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

build: clean install
	$(BIN)/python -m build

package: build
	$(BIN)/python -m twine check dist/*

# Credentials come from the environment; none are stored in this file.
check-credentials:
	@if [ -z "$$TWINE_PASSWORD" ]; then \
		echo "ERROR: TWINE_PASSWORD is not set."; \
		echo "  export TWINE_USERNAME=__token__"; \
		echo "  export TWINE_PASSWORD=<your API token>"; \
		exit 1; \
	fi

publish-testpypi: test lint package check-credentials
	$(BIN)/python -m twine upload --repository testpypi dist/*

publish-pypi: test lint package check-credentials
	$(BIN)/python -m twine upload dist/*

check-tools:
	@command -v exiftool >/dev/null || { echo "MISSING: exiftool"; exit 1; }
	@command -v ffprobe  >/dev/null || { echo "MISSING: ffprobe";  exit 1; }
	@echo "exiftool and ffprobe are installed."
