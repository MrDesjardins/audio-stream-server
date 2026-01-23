# CI/CD Setup Guide

Complete guide for setting up continuous integration with coverage reporting.

## Quick Start (Zero Configuration)

The `ci.yml` workflow works immediately with no setup required!

### Step 1: Push to GitHub

```bash
git add .
git commit -m "Add CI workflow"
git push origin main
```

### Step 2: Check Results

1. Go to your repository on GitHub
2. Click **Actions** tab
3. See your workflow running
4. View coverage in the summary

**That's it!** Coverage will automatically appear in PRs and Actions summaries.

## What You Get

### ✅ On Every Push/PR

- **Automated testing** - Full test suite runs
- **Coverage calculation** - Percentage and per-file stats
- **Test results** - Pass/fail status for all tests
- **HTML reports** - Downloadable detailed coverage
- **Warnings** - Alerts if coverage drops below threshold

### ✅ On Pull Requests

- **Coverage comment** - Automatic comment with:
  - Current coverage percentage
  - Coverage change vs base branch
  - Per-file coverage details
  - Coverage trend (↑↓)

- **Status checks** - PR shows:
  - ✅ Tests passed
  - 📊 Coverage: 63%
  - 📝 View details

### ✅ In Actions Summary

Every workflow run shows:
```
## Test Summary

**Coverage:** 63.2%

### Coverage by Module
services/database.py     96%
services/trilium.py      92%
services/youtube.py      93%
...

📊 View detailed HTML coverage report
```

## Available Workflows

We provide three workflow files:

### 1. `ci.yml` - **Recommended** ⭐

**Best for**: Most users, no configuration needed

**Features**:
- Runs tests with coverage
- Posts PR comments
- Shows coverage in Actions summary
- Uploads HTML reports
- No secrets required

**Use this if**: You want CI/CD that "just works"

### 2. `test.yml` - Extended

**Best for**: Teams using Codecov or wanting badges

**Features**:
- Everything in `ci.yml`
- Codecov integration (optional)
- Coverage badge generation
- More detailed reporting

**Requires**: `CODECOV_TOKEN` secret (optional)

### 3. `coverage-badge.yml` - Badge Generator

**Best for**: README badges via Gist

**Features**:
- Creates dynamic coverage badge
- Updates on every main push
- Hosted on GitHub Gist

**Requires**:
- `GIST_SECRET` - Personal access token
- `GIST_ID` - Gist ID to update

## Optional Integrations

### Option 1: Codecov (Recommended for Open Source)

**Benefits**: Beautiful coverage visualization, trends, comparisons

**Setup**:
1. Go to [codecov.io](https://codecov.io)
2. Sign up with GitHub
3. Add your repository
4. Copy the token
5. Add `CODECOV_TOKEN` to repository secrets
   - Settings → Secrets → New repository secret

**Badge**:
```markdown
[![codecov](https://codecov.io/gh/USERNAME/REPO/branch/main/graph/badge.svg)](https://codecov.io/gh/USERNAME/REPO)
```

### Option 2: Coverage Badge via Gist

**Benefits**: Self-hosted badge, no external service

**Setup**:
1. Create a personal access token:
   - GitHub Settings → Developer settings → Personal access tokens
   - Scopes: `gist`
   - Copy token

2. Create a new gist:
   - Go to [gist.github.com](https://gist.github.com)
   - Create gist named `audio-stream-server-coverage.json`
   - Content: `{}`
   - Copy gist ID from URL

3. Add secrets to repository:
   - `GIST_SECRET` = your personal access token
   - `GIST_ID` = your gist ID

4. Enable `coverage-badge.yml` workflow

**Badge**:
```markdown
![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/USERNAME/GIST_ID/raw/audio-stream-server-coverage.json)
```

### Option 3: Shields.io Dynamic Badge

**Benefits**: Customizable, free, no account needed

**Setup**:
1. No setup required!
2. Use workflow badge:

```markdown
![Tests](https://github.com/USERNAME/audio-stream-server/actions/workflows/ci.yml/badge.svg)
```

## Testing CI Locally

Before pushing, test that CI will pass:

```bash
# Run CI checks locally
./test-ci-locally.sh

# Or manually
uv run pytest --cov --cov-report=term
```

This runs the exact same commands as CI, so you'll catch issues early.

## Branch Protection

Protect your main branch to require tests:

### Recommended Settings

1. Go to: Settings → Branches → Branch protection rules
2. Add rule for `main` branch
3. Enable:
   - ✅ Require status checks to pass before merging
   - ✅ Require branches to be up to date before merging
   - ✅ Require conversation resolution before merging
   - ✅ Status checks: Select "Test & Coverage"

4. Save changes

Now all PRs must pass tests before merging!

## Viewing Coverage

### Method 1: PR Comment (Automatic)

When you open a PR, a bot comments with coverage details:

```
## Coverage Report

**Overall Coverage**: 63.2% (+2.1%)

### Changed Files
| File | Coverage | Lines | Change |
|------|----------|-------|--------|
| services/database.py | 96% | 97 | +5% ↑ |
| services/trilium.py | 92% | 147 | +3% ↑ |

### Coverage Trend
63.2% (+2.1% from base)
```

### Method 2: Actions Summary

1. Go to Actions tab
2. Click on a workflow run
3. See summary with coverage stats

### Method 3: Download HTML Report

1. Go to workflow run
2. Scroll to **Artifacts**
3. Download `coverage-reports-{sha}.zip`
4. Extract and open `htmlcov/index.html`

### Method 4: Codecov Web UI (if enabled)

Visit `https://codecov.io/gh/USERNAME/REPO` for:
- Coverage trends over time
- File-by-file coverage
- Pull request comparison
- Sunburst visualizations

## Customization

### Change Coverage Threshold

Edit `pytest.ini`:

```ini
[pytest]
addopts =
    --cov-fail-under=80  # Fail if below 80%
```

Edit `.github/workflows/ci.yml`:

```yaml
- name: Check coverage threshold
  run: |
    if (( $(echo "$COVERAGE < 80" | bc -l) )); then
      echo "::error::Coverage below 80%"
      exit 1  # Fail the build
    fi
```

### Run Tests on Specific Events

Edit workflow trigger:

```yaml
on:
  push:
    branches: [ main ]      # Only main
  pull_request:
    branches: [ main, develop ]
  schedule:
    - cron: '0 0 * * 0'     # Weekly
```

### Add Pre-commit Checks

Create `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: local
    hooks:
      - id: pytest
        name: pytest
        entry: uv run pytest
        language: system
        pass_filenames: false
        always_run: true
```

Install:
```bash
pip install pre-commit
pre-commit install
```

## Troubleshooting

### Tests Fail in CI But Pass Locally

**Cause**: Environment differences

**Solutions**:
- Check Python version matches (3.12)
- Ensure system dependencies installed (ffmpeg)
- Check for hardcoded paths
- Use `./test-ci-locally.sh` to simulate CI

### Coverage Comment Not Appearing

**Cause**: Permissions or configuration

**Solutions**:
1. Check workflow has `contents: write` permission
2. Verify `GITHUB_TOKEN` is available
3. Check if PR is from fork (limited permissions)
4. Review Actions logs for errors

### Workflow Taking Too Long

**Optimizations**:
1. Enable caching:
   ```yaml
   - uses: actions/cache@v3
     with:
       path: ~/.cache/uv
       key: ${{ runner.os }}-uv-${{ hashFiles('**/pyproject.toml') }}
   ```

2. Run quick tests first:
   ```yaml
   - name: Quick smoke test
     run: uv run pytest tests/services/test_database.py --no-cov
   ```

3. Parallel jobs:
   ```yaml
   strategy:
     matrix:
       test-group: [services, routes]
   ```

### Codecov Upload Fails

**Cause**: Missing or invalid token

**Solutions**:
1. Verify `CODECOV_TOKEN` secret is set
2. Check token is valid (regenerate if needed)
3. Make sure upload step has `continue-on-error: true`

## Advanced Usage

### Matrix Testing

Test multiple Python versions:

```yaml
strategy:
  matrix:
    python-version: ["3.11", "3.12", "3.13"]

steps:
  - uses: actions/setup-python@v5
    with:
      python-version: ${{ matrix.python-version }}
```

### Conditional Steps

Run steps only on specific conditions:

```yaml
- name: Deploy
  if: github.ref == 'refs/heads/main' && github.event_name == 'push'
  run: ./deploy.sh
```

### Scheduled Runs

Run tests daily:

```yaml
on:
  schedule:
    - cron: '0 0 * * *'  # Daily at midnight UTC
```

### Manual Triggers

Allow manual workflow runs:

```yaml
on:
  workflow_dispatch:
    inputs:
      coverage-threshold:
        description: 'Coverage threshold'
        required: false
        default: '80'
```

## Best Practices

### ✅ Do

- Run tests on every PR
- Require tests to pass before merge
- Review coverage changes
- Keep CI fast (< 5 minutes)
- Cache dependencies
- Use branch protection

### ❌ Don't

- Skip CI on important branches
- Commit directly to main
- Ignore failing tests
- Hardcode secrets in workflows
- Run expensive operations on every commit

## Monitoring

### Check Workflow Health

```bash
# View recent runs
gh run list --workflow=ci.yml --limit=10

# View specific run
gh run view 1234567890

# Download artifacts
gh run download 1234567890
```

### Set Up Notifications

1. Watch repository for workflow failures
2. Configure email notifications
3. Use GitHub mobile app
4. Set up Slack integration (optional)

## Next Steps

1. ✅ Push code to trigger first workflow
2. ✅ Verify tests pass in CI
3. ✅ Check coverage appears in PR
4. 📊 Optional: Set up Codecov
5. 🛡️ Enable branch protection
6. 📈 Monitor coverage trends

## Support

- [GitHub Actions Docs](https://docs.github.com/en/actions)
- [pytest-cov Docs](https://pytest-cov.readthedocs.io/)
- [Project TESTING.md](./TESTING.md)
- [Workflows README](./.github/workflows/README.md)
