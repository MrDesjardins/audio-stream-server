#!/bin/bash
# Linting and formatting script for audio-stream-server

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "🔧 Audio Stream Server - Linting & Formatting"
echo "=============================================="
echo ""

# Parse command line arguments
MODE="${1:-check}"

if [ "$MODE" = "fix" ]; then
    echo -e "${YELLOW}Running in FIX mode - will auto-format code${NC}"
    echo ""

    echo "📝 Running Black (code formatter)..."
    uv run black .
    echo -e "${GREEN}✓ Black formatting complete${NC}"
    echo ""

    echo "🔍 Running MyPy (type checker)..."
    uv run mypy .
    echo -e "${GREEN}✓ MyPy type checking complete${NC}"

    echo "🐶 Running Ruff (Linter)..."
    uv run ruff check .
    echo -e "${GREEN}✓ Ruff linting complete${NC}"

elif [ "$MODE" = "check" ]; then
    echo -e "${YELLOW}Running in CHECK mode - will not modify files${NC}"
    echo ""

    echo "📝 Checking Black formatting..."
    if uv run black --check --diff .; then
        echo -e "${GREEN}✓ All files are properly formatted${NC}"
    else
        echo -e "${RED}✗ Some files need formatting. Run './lint.sh fix' to auto-format${NC}"
        exit 1
    fi
    echo ""

    echo "🔍 Running MyPy (type checker)..."
    if uv run mypy .; then
        echo -e "${GREEN}✓ MyPy type checking passed${NC}"
    else
        echo -e "${RED}✗ MyPy found type errors${NC}"
        exit 1
    fi

    echo "🐶 Running Ruff (Linter)..."
    if uv run ruff check .; then
        echo -e "${GREEN}✓ Ruff linting passed${NC}"
    else
        echo -e "${RED}✗ Ruff found linting issues${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ Ruff linting complete${NC}"

else
    echo -e "${RED}Invalid mode: $MODE${NC}"
    echo "Usage: ./lint.sh [check|fix]"
    echo "  check - Check formatting and types (default)"
    echo "  fix   - Auto-format code and check types"
    exit 1
fi

echo ""
echo -e "${GREEN}✓ All checks passed!${NC}"
