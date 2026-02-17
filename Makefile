# Makefile for Email Preprocessing Layer
# Windows and Unix compatible

PYTHON := python
PIP := pip
PYTEST := pytest
BLACK := black
MYPY := mypy
FLAKE8 := flake8
BANDIT := bandit
ISORT := isort

# Directories
SRC_DIR := src
TEST_DIR := tests
EXAMPLES_DIR := examples

# Colors for output (Windows compatible)
INFO := @echo
SUCCESS := @echo [OK]
ERROR := @echo [ERROR]

.PHONY: help install install-dev download-model test coverage lint format typecheck security clean run

help:
	$(INFO) "Email Preprocessing Layer - Makefile"
	$(INFO) ""
	$(INFO) "Available targets:"
	$(INFO) "  make install        - Install production dependencies"
	$(INFO) "  make install-dev    - Install development dependencies"
	$(INFO) "  make download-model - Download spaCy Italian NER model"
	$(INFO) "  make test          - Run all tests"
	$(INFO) "  make coverage      - Run tests with coverage report"
	$(INFO) "  make lint          - Run linting (flake8)"
	$(INFO) "  make format        - Format code (black, isort)"
	$(INFO) "  make typecheck     - Run type checking (mypy)"
	$(INFO) "  make security      - Run security audit (bandit, pip-audit)"
	$(INFO) "  make clean         - Remove generated files"
	$(INFO) "  make run           - Start FastAPI service"

install:
	$(INFO) "Installing production dependencies..."
	$(PIP) install -r requirements.txt
	$(SUCCESS) "Production dependencies installed"

install-dev:
	$(INFO) "Installing development dependencies..."
	$(PIP) install -r requirements-dev.txt
	$(SUCCESS) "Development dependencies installed"

download-model:
	$(INFO) "Downloading spaCy Italian NER model (it_core_news_lg)..."
	$(PYTHON) -m spacy download it_core_news_lg
	$(SUCCESS) "spaCy model downloaded"

test:
	$(INFO) "Running tests..."
	$(PYTEST) $(TEST_DIR) -v --tb=short
	$(SUCCESS) "Tests completed"

coverage:
	$(INFO) "Running tests with coverage..."
	$(PYTEST) $(TEST_DIR) --cov=$(SRC_DIR) --cov-report=html --cov-report=term-missing --cov-fail-under=90
	$(SUCCESS) "Coverage report generated in htmlcov/"

lint:
	$(INFO) "Running flake8..."
	$(FLAKE8) $(SRC_DIR) $(TEST_DIR) --max-line-length=120 --extend-ignore=E203,W503
	$(SUCCESS) "Linting passed"

format:
	$(INFO) "Formatting code with black..."
	$(BLACK) $(SRC_DIR) $(TEST_DIR) --line-length=120
	$(INFO) "Sorting imports with isort..."
	$(ISORT) $(SRC_DIR) $(TEST_DIR) --profile black --line-length=120
	$(SUCCESS) "Code formatted"

typecheck:
	$(INFO) "Running mypy type checker..."
	$(MYPY) $(SRC_DIR) --strict --ignore-missing-imports
	$(SUCCESS) "Type checking passed"

security:
	$(INFO) "Running bandit security scanner..."
	$(BANDIT) -r $(SRC_DIR) -ll
	$(INFO) "Running pip-audit for dependency vulnerabilities..."
	$(PYTHON) -m pip_audit
	$(SUCCESS) "Security audit completed"

clean:
	$(INFO) "Cleaning generated files..."
	@if exist __pycache__ rmdir /s /q __pycache__
	@if exist .pytest_cache rmdir /s /q .pytest_cache
	@if exist .mypy_cache rmdir /s /q .mypy_cache
	@if exist htmlcov rmdir /s /q htmlcov
	@if exist .coverage del /q .coverage
	@if exist *.egg-info rmdir /s /q *.egg-info
	@for /d /r . %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"
	$(SUCCESS) "Cleaned"

run:
	$(INFO) "Starting FastAPI service..."
	$(INFO) "API will be available at http://localhost:8000"
	$(INFO) "Health check: http://localhost:8000/health"
	$(INFO) "API docs: http://localhost:8000/docs"
	uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
