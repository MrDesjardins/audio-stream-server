# Testing Documentation

## Overview

A comprehensive unit test suite with mocking for external dependencies (Trilium, YouTube/yt-dlp, OpenAI, etc.).

**Current Coverage: 63%**
**Target: 80%+**

## Test Infrastructure

### Dependencies

```bash
# Install test dependencies
uv sync --extra test
```

Test dependencies include:
- `pytest` - Testing framework
- `pytest-cov` - Coverage reporting
- `pytest-mock` - Mocking utilities
- `pytest-asyncio` - Async test support
- `httpx` - For mocking HTTP requests

### Configuration

- **pytest.ini** - Pytest configuration with coverage settings
- **tests/conftest.py** - Shared fixtures and test configuration
- **Coverage threshold**: 80% (configurable in pytest.ini)

## Running Tests

### Run All Tests

```bash
# With coverage report
uv run pytest

# Without coverage
uv run pytest --no-cov

# Verbose mode
uv run pytest -v
```

### Run Specific Test Files

```bash
# Services tests
uv run pytest tests/services/

# Routes tests
uv run pytest tests/routes/

# Specific module
uv run pytest tests/services/test_database.py
```

### Coverage Reports

```bash
# Terminal report
uv run pytest --cov-report=term-missing

# HTML report (opens in browser)
uv run pytest --cov-report=html
open htmlcov/index.html
```

## Test Structure

```
tests/
├── conftest.py              # Shared fixtures
├── services/
│   ├── test_database.py     # Database CRUD operations (96% coverage)
│   ├── test_youtube.py      # YouTube utils (93% coverage)
│   ├── test_broadcast.py    # Stream broadcasting (90% coverage)
│   ├── test_trilium.py      # Trilium integration (92% coverage)
│   └── test_cache.py        # Cache services (62% coverage)
└── routes/
    ├── test_stream.py       # Stream endpoints
    └── test_queue.py        # Queue endpoints
```

## Test Coverage by Module

### Services (well-tested)
- **database.py**: 96% ✅
- **trilium.py**: 92% ✅
- **youtube.py**: 93% ✅
- **broadcast.py**: 90% ✅
- **streaming.py**: 72%
- **cache.py**: 62%

### Services (need tests)
- **summarization.py**: 0% ❌
- **transcription.py**: 0% ❌
- **background_tasks.py**: 0% ❌

### Routes
- **stream.py**: ~70%
- **queue.py**: ~80%
- **transcription.py**: 0% ❌

## Common Fixtures

### Database Fixtures

```python
@pytest.fixture
def db_path():
    """Temporary isolated database for each test"""
```

### Mock Fixtures

```python
@pytest.fixture
def mock_config():
    """Mock configuration object"""

@pytest.fixture
def mock_subprocess():
    """Mock subprocess.Popen for yt-dlp/ffmpeg"""

@pytest.fixture
def mock_httpx_response():
    """Mock httpx responses for Trilium/OpenAI"""

@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client"""
```

### Sample Data

```python
@pytest.fixture
def sample_video_id():
    """YouTube video ID: dQw4w9WgXcQ"""

@pytest.fixture
def sample_transcript():
    """Sample transcript text"""

@pytest.fixture
def sample_summary():
    """Sample summary with markdown"""
```

## Mocking Strategy

### External API Calls

All external API calls are mocked:

1. **YouTube/yt-dlp** - `subprocess.run` mocked
2. **Trilium ETAPI** - `httpx.get/post` mocked
3. **OpenAI Whisper** - OpenAI client mocked
4. **Gemini** - Google Generative AI mocked

### Database Isolation

Each test gets a fresh temporary SQLite database:

```python
# Automatically reloads database module with test DB path
@pytest.fixture(autouse=True)
def db_path(monkeypatch):
    ...
```

### Process Isolation

Subprocess calls (ffmpeg, yt-dlp) are mocked to avoid actual process spawning.

## Known Test Failures

### Minor Fixes Needed

1. **test_cache.py**: API mismatch - cache classes have different constructor signatures
2. **test_youtube.py**: `extract_video_id` doesn't strip whitespace (feature vs bug?)
3. **test_routes.py**: Some parameter passing issues

These are easily fixable and don't affect core functionality.

## Reaching 80% Coverage

### Priority Areas (to add tests)

1. **services/transcription.py** (0% → 80%)
   - Mock OpenAI API calls
   - Test error handling
   - Test retry logic

2. **services/summarization.py** (0% → 80%)
   - Mock ChatGPT/Gemini calls
   - Test provider selection
   - Test markdown conversion

3. **services/background_tasks.py** (0% → 80%)
   - Mock worker threads
   - Test job queue management
   - Test job state transitions

4. **routes/transcription.py** (0% → 80%)
   - Test status endpoint
   - Test start/summary endpoints
   - Mock transcription queue

5. **Fix existing test failures** (~18 failures)
   - Update cache test API
   - Fix route parameter handling
   - Fix minor assertion issues

### Estimated Effort

- **Fix existing tests**: 30 minutes
- **Add transcription tests**: 1 hour
- **Add summarization tests**: 45 minutes
- **Add background_tasks tests**: 1 hour
- **Add route tests**: 45 minutes

**Total**: ~4 hours to reach 80%+ coverage

## Best Practices

### Writing New Tests

1. **Isolate dependencies**: Mock all external calls
2. **Use fixtures**: Reuse common setup via fixtures
3. **Test edge cases**: Not just happy path
4. **Clear naming**: `test_function_name_scenario_expected_result`
5. **One assertion focus**: Test one thing per test

### Example Test

```python
@patch('services.youtube.subprocess.run')
def test_get_video_title_success(self, mock_run):
    """Test successfully getting video title."""
    # Arrange
    mock_run.return_value = Mock(
        returncode=0,
        stdout='{"title": "Test Video"}'
    )

    # Act
    title = get_video_title("dQw4w9WgXcQ")

    # Assert
    assert title == "Test Video"
    mock_run.assert_called_once()
```

## Continuous Integration

Add to CI/CD pipeline:

```yaml
# .github/workflows/test.yml
- name: Run tests with coverage
  run: uv run pytest --cov-fail-under=80
```

## Troubleshooting

### Tests Using Production Database

Make sure `DATABASE_PATH` env var is set in fixture:

```python
monkeypatch.setenv('DATABASE_PATH', temp_db_path)
import importlib
importlib.reload(services.database)
```

### Import Errors

Check that all service modules are importable:

```python
pytest --collect-only
```

### Slow Tests

Use `--durations=10` to find slow tests:

```bash
pytest --durations=10
```

## Next Steps

1. Fix the 18 failing tests
2. Add tests for untested services
3. Reach 80%+ coverage
4. Add integration tests
5. Set up CI/CD with automated testing
