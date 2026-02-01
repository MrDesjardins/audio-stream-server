# Linting & Type Checking Guide

This project uses **Ruff** for code formatting and linting, and **MyPy** for static type checking.

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

### Ruff - Fast Linter & Formatter

Ruff is an extremely fast Python linter and formatter written in Rust. It's a drop-in replacement for Black, Flake8, isort, and more.

**Configuration:** `[tool.ruff]` in `pyproject.toml`
- Line length: 100 characters
- Target: Python 3.12
- Combines linting + formatting in one tool

**Manual usage:**
```bash
# Check linting (don't modify files)
uv run ruff check .

# Auto-fix linting issues
uv run ruff check --fix .

# Check formatting (don't modify files)
uv run ruff format --check --diff .

# Auto-format all files
uv run ruff format .

# Format specific file
uv run ruff format services/database.py
```

**Why Ruff?**
- ⚡ **10-100x faster** than Black
- 🔧 **All-in-one**: Replaces Black, Flake8, isort, pyupgrade, and more
- 🎯 **Compatible**: Same formatting as Black
- 🚀 **Auto-fix**: Automatically fixes many linting issues

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

## CI Integration

The lint checks are automatically run in CI. All pull requests must pass:
- ✅ Ruff linting check
- ✅ Ruff formatting check
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
1. Checks for linting issues (doesn't modify)
2. Checks if files are formatted (doesn't modify)
3. Runs MyPy type checker
4. Exits with error code if any issues found

### Fix Mode
```bash
./lint.sh fix
```

Automatically fixes what it can:
1. Auto-fixes linting issues with Ruff
2. Reformats all Python files with Ruff
3. Runs MyPy to show remaining type issues
4. Use this during development

## Development Workflow

1. **Write code** as normal
2. **Before committing:**
   ```bash
   ./lint.sh fix
   ```
3. **Fix any remaining MyPy errors** manually
4. **Commit** your changes

## Pre-commit Hooks

The project uses pre-commit to automatically run linting before commits:

```bash
# Install pre-commit hooks (one-time setup)
uv run pre-commit install

# Run manually
uv run pre-commit run --all-files
```

**What runs on commit:**
1. `ruff check --fix` - Auto-fix linting issues
2. `ruff format` - Format code
3. `mypy` - Type checking
4. File checks (large files, merge conflicts, etc.)

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

### Ruff Configuration
```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I"]  # Enable specific rules
ignore = []  # Ignore specific rules

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
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

### Ruff
```python
# Ignore specific rule on one line
value = some_function()  # noqa: E501

# Ignore all rules on one line (use sparingly)
value = some_function()  # noqa
```

### MyPy
```python
# Ignore specific error on one line
value = some_function()  # type: ignore[attr-defined]

# Ignore all errors on one line (use sparingly)
value = some_function()  # type: ignore
```

## Troubleshooting

### Ruff says files need formatting
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
Configure your IDE to use Ruff:
- **VSCode:** Install "Ruff" extension (charliermarsh.ruff)
- **PyCharm:** Settings → Tools → External Tools → Add Ruff
- **Vim/Neovim:** Use `ruff` formatter plugin

## Benefits

- **⚡ Fast linting and formatting** (10-100x faster than Black)
- **Consistent code style** across the project
- **Catch bugs** before runtime with type checking and linting
- **Better IDE support** with type hints
- **Easier code reviews** (no style discussions)
- **Self-documenting** code with types
- **Auto-fix** many common issues
