# Linting & Type Checking Guide

This project uses **Black** for code formatting and **MyPy** for static type checking.

## Quick Start

```bash
# Install dev dependencies (one-time setup)
uv sync --extra dev

# Check formatting and types (CI mode)
./lint.sh check

# Auto-format code and check types
./lint.sh fix
```

## Tools

### Black - Code Formatter

**Configuration:** `[tool.black]` in `pyproject.toml`
- Line length: 100 characters
- Target: Python 3.12

**Manual usage:**
```bash
# Check formatting (don't modify files)
uv run black --check --diff .

# Auto-format all files
uv run black .

# Format specific file
uv run black services/database.py
```

### MyPy - Static Type Checker

**Configuration:** `[tool.mypy]` in `pyproject.toml`
- Python version: 3.12
- Lenient configuration (can be made stricter over time)
- Ignores missing imports from third-party libraries

**Manual usage:**
```bash
# Type check entire project
uv run mypy .

# Type check specific file
uv run mypy services/database.py

# Type check specific module
uv run mypy services/
```

### Ruff - Linter


**Manual usage:**

```bash
# Check
uv run ruff check

# Fix
uv run ruff check --fix
```
## CI Integration

The lint checks are automatically run in CI. All pull requests must pass:
- ✅ Black formatting check
- ✅ MyPy type checking

## Lint Script

The `lint.sh` script provides two modes:

### Check Mode (Default)
```bash
./lint.sh check
# or just
./lint.sh
```

Runs in CI-compatible mode:
- Checks if files are formatted (doesn't modify)
- Runs MyPy type checker
- Exits with error code if any issues found

### Fix Mode
```bash
./lint.sh fix
```

Automatically fixes what it can:
- Reformats all Python files with Black
- Runs MyPy to show remaining type issues
- Use this during development

## Development Workflow

1. **Write code** as normal
2. **Before committing:**
   ```bash
   ./lint.sh fix
   ```
3. **Fix any remaining MyPy errors** manually
4. **Commit** your changes

## Common MyPy Fixes

### Add type annotations
```python
# Before
def my_function(x):
    return x * 2

# After
def my_function(x: int) -> int:
    return x * 2
```

### Handle Optional types
```python
# Before
def get_value(data: dict) -> str:
    return data.get("key")  # Error: might return None

# After
from typing import Optional

def get_value(data: dict) -> Optional[str]:
    return data.get("key")
```

### Check for None
```python
# Before
def process(value: Optional[str]) -> int:
    return len(value)  # Error: value might be None

# After
def process(value: Optional[str]) -> int:
    if value is None:
        return 0
    return len(value)
```

## Configuration Details

### Black Configuration
```toml
[tool.black]
line-length = 100
target-version = ['py312']
```

### MyPy Configuration
```toml
[tool.mypy]
python_version = "3.12"
check_untyped_defs = true
ignore_missing_imports = true
warn_redundant_casts = true
warn_unused_ignores = true
```

## Ignoring Specific Errors

If you need to ignore a specific MyPy error:

```python
# Ignore specific error on one line
value = some_function()  # type: ignore[attr-defined]

# Ignore all errors on one line (use sparingly)
value = some_function()  # type: ignore
```

## Pre-commit Hook (Optional)

To automatically run linting before every commit:

```bash
# Create pre-commit hook
cat > .git/hooks/pre-commit << 'EOF'
#!/bin/bash
./lint.sh check
EOF

chmod +x .git/hooks/pre-commit
```

## Troubleshooting

### Black says files need formatting
```bash
# Auto-format all files
./lint.sh fix
```

### MyPy errors about missing imports
```bash
# Install type stubs if available
uv add --dev types-<package-name>

# Or ignore in pyproject.toml
[[tool.mypy.overrides]]
module = "problematic_module.*"
ignore_missing_imports = true
```

### Conflicts with IDE formatter
Configure your IDE to use Black:
- **VSCode:** Install "Black Formatter" extension
- **PyCharm:** Settings → Tools → Black → Enable
- **Vim/Neovim:** Use `black` formatter plugin

## Benefits

- **Consistent code style** across the project
- **Catch bugs** before runtime with type checking
- **Better IDE support** with type hints
- **Easier code reviews** (no style discussions)
- **Self-documenting** code with types
