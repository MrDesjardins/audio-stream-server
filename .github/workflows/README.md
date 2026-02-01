# GitHub Actions Workflows

This directory contains CI/CD workflows for the Audio Stream Server project.

## Available Workflows

### 1. CI Workflow (`ci.yml`) - **Recommended**

**Main workflow for continuous integration.**

- **Triggers**: Push to `main`/`develop`, Pull Requests
- **Features**:
  - Runs full test suite with coverage
  - Posts coverage comment on PRs
  - Uploads coverage reports as artifacts
  - Checks coverage threshold (warns if < 80%)
  - Generates test summary in GitHub UI
  - Optional: Code quality checks (ruff linting and formatting)

**No secrets required!** Uses built-in GitHub features.

### 2. Test Workflow (`test.yml`)

Alternative workflow with more integrations.

- **Triggers**: Push to `main`/`develop`, Pull Requests
- **Features**:
  - Runs tests with coverage
  - Uploads to Codecov (optional - requires `CODECOV_TOKEN`)
  - Generates coverage badge
  - PR coverage comments
  - HTML coverage reports

**Optional Secrets**:
- `CODECOV_TOKEN` - For Codecov integration

### 3. Coverage Badge (`coverage-badge.yml`)

Creates a dynamic coverage badge using GitHub Gist.

- **Triggers**: Push to `main` branch only
- **Features**:
  - Generates coverage percentage
  - Updates dynamic badge on Gist
  - Updates on every main branch push

**Required Secrets**:
- `GIST_SECRET` - GitHub personal access token with gist scope
- `GIST_ID` - ID of the gist to update

**Setup Instructions**:
1. Create a personal access token with `gist` scope
2. Create a gist at https://gist.github.com
3. Add secrets to repository settings

## Usage

### Quick Start (No Setup Required)

The `ci.yml` workflow works out of the box with no configuration:

```yaml
# Just push your code!
git add .
git commit -m "Add new feature"
git push origin main
```

The workflow will automatically:
- Run all tests
- Calculate coverage
- Post results to PR (if applicable)
- Show coverage in Actions summary

### Viewing Coverage Reports

#### 1. In PR Comments (Automatic)

When you create a PR, the bot will comment with:
- Coverage percentage
- Coverage change vs base branch
- Per-file coverage details

#### 2. In Actions Summary

Go to: Actions → Select workflow run → View summary

Shows:
- Overall coverage percentage
- Coverage by module
- Link to detailed HTML report

#### 3. Download HTML Report

1. Go to workflow run
2. Scroll to "Artifacts"
3. Download `coverage-reports-{sha}`
4. Extract and open `htmlcov/index.html`

### Adding Coverage Badge to README

#### Option 1: Using Codecov (requires setup)

```markdown
[![codecov](https://codecov.io/gh/YOUR_USERNAME/audio-stream-server/branch/main/graph/badge.svg)](https://codecov.io/gh/YOUR_USERNAME/audio-stream-server)
```

#### Option 2: Using Dynamic Badge (requires gist setup)

```markdown
![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/YOUR_USERNAME/YOUR_GIST_ID/raw/audio-stream-server-coverage.json)
```

#### Option 3: Using GitHub Actions Badge

```markdown
![Tests](https://github.com/YOUR_USERNAME/audio-stream-server/actions/workflows/ci.yml/badge.svg)
```

## Configuration

### Changing Coverage Threshold

Edit `pytest.ini`:

```ini
[pytest]
addopts =
    --cov-fail-under=80  # Change this value
```

### Running Only on Specific Branches

Edit workflow file:

```yaml
on:
  push:
    branches: [ main ]  # Only main branch
  pull_request:
    branches: [ main ]
```

### Customizing Test Command

Edit the test step in workflow:

```yaml
- name: Run tests with coverage
  run: |
    uv run pytest \
      --cov=services \
      --cov=routes \
      -v \
      --maxfail=5  # Stop after 5 failures
```

## Troubleshooting

### Tests Pass Locally But Fail in CI

**Possible causes**:
1. Missing system dependencies (ffmpeg)
2. Different Python version
3. Environment variables not set
4. Database path issues

**Solutions**:
- Check system dependencies in workflow
- Ensure Python version matches (3.12)
- Use environment variables in workflow
- Tests use temporary databases

### Coverage Report Not Showing

**Check**:
1. Workflow completed successfully
2. Coverage files were generated (`coverage.xml`)
3. Artifact was uploaded
4. PR has permissions to comment

**Debug**:
```yaml
- name: Debug coverage
  run: |
    ls -la coverage.*
    cat coverage.xml
```

### Slow CI Runs

**Optimizations**:
1. Enable caching for uv/pip
2. Skip coverage for quick feedback
3. Run linting in parallel job
4. Use faster test database

```yaml
- name: Quick tests (no coverage)
  if: github.event_name == 'pull_request'
  run: uv run pytest --no-cov -x
```

## Best Practices

### 1. Keep CI Fast

- Use caching for dependencies
- Run expensive tests only on main branch
- Fail fast with `-x` or `--maxfail`

### 2. Maintain Coverage

- Set realistic thresholds (60-80%)
- Review coverage reports regularly
- Add tests for new features

### 3. PR Workflow

- Require tests to pass before merge
- Review coverage changes in PR
- Add branch protection rules

### 4. Security

- Never commit secrets to repository
- Use GitHub Secrets for tokens
- Rotate tokens periodically

## GitHub Repository Settings

### Recommended Settings

#### Branch Protection for `main`:
- ✅ Require status checks to pass
- ✅ Require branches to be up to date
- ✅ Required: "Test & Coverage" check
- ✅ Require conversation resolution
- ❌ Allow force pushes (dangerous!)

#### Actions Permissions:
- ✅ Allow all actions and reusable workflows
- ✅ Read and write permissions (for PR comments)

## Monitoring

### Check Workflow Status

```bash
# Using GitHub CLI
gh run list --workflow=ci.yml

# View latest run
gh run view

# Watch a run
gh run watch
```

### Coverage Trends

Track coverage over time:
1. Download coverage reports from Actions
2. Store in database or tracking service
3. Plot trends
4. Set up alerts for drops

## Examples

### Example PR Comment

```
## Coverage Report

**Coverage**: 63.2% (+2.1%)

### Changed Files
| File | Coverage | Change |
|------|----------|--------|
| services/database.py | 96% | +5% |
| services/trilium.py | 92% | +3% |

**Lines added**: 150
**Lines covered**: 95
```

### Example Actions Summary

```
## Test Summary

**Coverage:** 63.2%

### Coverage by Module
services/database.py     96%
services/trilium.py      92%
services/youtube.py      93%

📊 View detailed HTML coverage report
```

## Additional Resources

- [pytest Documentation](https://docs.pytest.org/)
- [pytest-cov Documentation](https://pytest-cov.readthedocs.io/)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Codecov Documentation](https://docs.codecov.com/)
