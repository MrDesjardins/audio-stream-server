#!/bin/bash

# Test Runner Script for Audio Stream Server
# Provides various test running modes with coverage reporting

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "========================================="
echo "Audio Stream Server - Test Runner"
echo "========================================="
echo ""

# Parse command line arguments
MODE="${1:-all}"

case "$MODE" in
    "all")
        echo "Running all tests with coverage..."
        uv run pytest -v --cov-report=term-missing --cov-report=html
        ;;

    "fast")
        echo "Running tests without coverage (fast mode)..."
        uv run pytest -v --no-cov
        ;;

    "services")
        echo "Running service layer tests..."
        uv run pytest tests/services/ -v --cov=services --cov-report=term-missing
        ;;

    "routes")
        echo "Running route layer tests..."
        uv run pytest tests/routes/ -v --cov=routes --cov-report=term-missing
        ;;

    "failed")
        echo "Re-running only failed tests..."
        uv run pytest --lf -v
        ;;

    "coverage")
        echo "Generating coverage report..."
        uv run pytest --cov-report=html --cov-report=term
        echo ""
        echo -e "${GREEN}✓ Coverage report generated${NC}"
        echo "Open: htmlcov/index.html"
        ;;

    "watch")
        echo "Running tests in watch mode..."
        echo "Note: Requires pytest-watch (pip install pytest-watch)"
        ptw -- -v --no-cov
        ;;

    "debug")
        echo "Running tests in debug mode..."
        uv run pytest -v --no-cov --tb=long -s
        ;;

    "clean")
        echo "Cleaning test artifacts..."
        rm -rf .pytest_cache htmlcov .coverage
        find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
        echo -e "${GREEN}✓ Test artifacts cleaned${NC}"
        ;;

    *)
        echo "Usage: ./run_tests.sh [mode]"
        echo ""
        echo "Available modes:"
        echo "  all        - Run all tests with coverage (default)"
        echo "  fast       - Run all tests without coverage"
        echo "  services   - Run only service layer tests"
        echo "  routes     - Run only route layer tests"
        echo "  failed     - Re-run only failed tests"
        echo "  coverage   - Generate coverage report"
        echo "  debug      - Run with verbose output and traceback"
        echo "  clean      - Clean test artifacts"
        echo ""
        exit 1
        ;;
esac

# Check exit code
if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}=========================================${NC}"
    echo -e "${GREEN}✓ Tests completed successfully${NC}"
    echo -e "${GREEN}=========================================${NC}"
else
    echo ""
    echo -e "${RED}=========================================${NC}"
    echo -e "${RED}✗ Tests failed${NC}"
    echo -e "${RED}=========================================${NC}"
    exit 1
fi
