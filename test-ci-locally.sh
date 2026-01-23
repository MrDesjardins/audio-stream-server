#!/bin/bash

# Test CI Locally
# Simulates GitHub Actions CI workflow locally before pushing

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=========================================${NC}"
echo -e "${BLUE}Testing CI Workflow Locally${NC}"
echo -e "${BLUE}=========================================${NC}"
echo ""

# Check if we're in the right directory
if [ ! -f "pyproject.toml" ]; then
    echo -e "${RED}Error: Must run from project root${NC}"
    exit 1
fi

# Step 1: Check system dependencies
echo -e "${YELLOW}Step 1: Checking system dependencies...${NC}"
if ! command -v ffmpeg &> /dev/null; then
    echo -e "${RED}✗ ffmpeg not found${NC}"
    echo "Install with: sudo apt-get install ffmpeg"
    exit 1
fi
echo -e "${GREEN}✓ ffmpeg installed${NC}"
echo ""

# Step 2: Install Python dependencies
echo -e "${YELLOW}Step 2: Installing Python dependencies...${NC}"
uv sync --extra test
echo -e "${GREEN}✓ Dependencies installed${NC}"
echo ""

# Step 3: Run tests with coverage (like CI does)
echo -e "${YELLOW}Step 3: Running tests with coverage...${NC}"
echo ""

uv run pytest \
  --cov=services \
  --cov=routes \
  --cov=main \
  --cov=config \
  --cov-report=xml \
  --cov-report=term \
  --cov-report=html \
  --cov-report=json \
  --junitxml=junit.xml \
  -v

# Step 4: Extract coverage
echo ""
echo -e "${YELLOW}Step 4: Analyzing coverage...${NC}"

if [ -f "coverage.json" ]; then
    COVERAGE=$(uv run python -c "import json; data=json.load(open('coverage.json')); print(f\"{data['totals']['percent_covered']:.1f}\")")
    echo -e "${BLUE}Coverage: ${COVERAGE}%${NC}"

    # Check threshold
    if (( $(echo "$COVERAGE < 60" | bc -l) )); then
        echo -e "${RED}⚠ Coverage is below 60%${NC}"
        echo "CI will show a warning"
    elif (( $(echo "$COVERAGE < 80" | bc -l) )); then
        echo -e "${YELLOW}⚠ Coverage is below target 80%${NC}"
        echo "CI will show a warning"
    else
        echo -e "${GREEN}✓ Coverage meets target!${NC}"
    fi
else
    echo -e "${RED}✗ coverage.json not found${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 5: Generating summary...${NC}"
echo ""
echo "Coverage by Module:"
echo "-------------------"
uv run coverage report --skip-empty

echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}✓ All CI checks passed!${NC}"
echo -e "${GREEN}=========================================${NC}"
echo ""
echo "Next steps:"
echo "  1. Review coverage report: open htmlcov/index.html"
echo "  2. Commit and push your changes"
echo "  3. CI will run automatically on GitHub"
echo ""
