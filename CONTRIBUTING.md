# Contributing to Audio Stream Server

## Development Setup

### 1. Install Dependencies

```bash
# Install all dependencies including dev tools
uv sync --extra dev

# Or if using pip
pip install -e ".[dev]"
```

### 2. Install Pre-commit Hooks

**Important**: Pre-commit hooks automatically run linting and formatting before each commit.

```bash
# Install the hooks (one-time setup)
uv run pre-commit install

# Test the hooks on all files (optional)
uv run pre-commit run --all-files
```

## Git Hooks

### Pre-commit Hook

The pre-commit hook automatically runs before each commit to:

1. **Lint and auto-fix** Python code with Ruff
2. **Format** code with Ruff formatter
3. **Check** for common issues (large files, merge conflicts, etc.)
4. **Fix** trailing whitespace and end-of-file issues

**How it works:**
- When you run `git commit`, the hooks run automatically
- If issues are found and can be auto-fixed, the hooks will fix them
- Fixed files are automatically added to your commit
- If there are unfixable issues, the commit is blocked and you'll see error messages

**Example workflow:**

```bash
# Make your changes
vim some_file.py

# Stage your changes
git add some_file.py

# Commit (hooks run automatically)
git commit -m "Add new feature"

# If hooks fix issues, they're automatically staged
# Your commit includes the original changes + auto-fixes
```

### Bypassing Hooks (Not Recommended)

If you need to bypass the hooks for some reason:

```bash
git commit --no-verify -m "Your message"
```

**Note**: This is NOT recommended as it can introduce linting issues into the codebase.

### Updating Hooks

To update to the latest versions of the hooks:

```bash
uv run pre-commit autoupdate
```

## Code Quality Tools

### Ruff (Linter & Formatter)

```bash
# Check all files
uv run ruff check .

# Auto-fix issues
uv run ruff check --fix .

# Format code
uv run ruff format .
```

### Running Tests

```bash
# Run all tests with coverage
uv run pytest

# Run specific test file
uv run pytest tests/services/test_database.py

# Run without coverage (faster)
uv run pytest --no-cov
```

See [TESTING.md](./TESTING.md) for more testing documentation.

## Pre-commit Configuration

The hooks are configured in `.pre-commit-config.yaml`. Current hooks:

- **Ruff Lint**: Checks and auto-fixes Python linting issues
- **Ruff Format**: Formats Python code
- **Large Files Check**: Prevents committing files larger than 10MB
- **Case Conflict Check**: Prevents case-sensitive filename conflicts
- **Merge Conflict Check**: Detects uncommitted merge conflict markers
- **YAML/TOML Check**: Validates syntax
- **End of File Fixer**: Ensures files end with newline
- **Trailing Whitespace**: Removes trailing whitespace

## Best Practices

1. **Always run tests** before committing
2. **Let the hooks fix your code** - they enforce consistent style
3. **Keep commits focused** - one logical change per commit
4. **Write descriptive commit messages**
5. **Don't bypass the hooks** unless absolutely necessary

## Troubleshooting

### Hooks fail with Python version error

If you see errors about Python version mismatch:

```bash
# Clean the pre-commit cache
uv run pre-commit clean

# Re-run the hooks
uv run pre-commit run --all-files
```

### Hooks are too slow

The first run is slow as it sets up environments. Subsequent runs are fast (cached).

### Want to skip a specific hook

Edit `.pre-commit-config.yaml` and comment out the hook you want to skip.
