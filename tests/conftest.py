"""Pytest configuration and fixtures."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture
def mock_config():
    """Mock configuration object."""
    config = Mock()
    config.transcription_enabled = False
    config.trilium_url = "http://localhost:8080"
    config.trilium_etapi_token = "test_token"
    config.trilium_parent_note_id = "test_parent_id"
    config.temp_audio_dir = "/tmp/test-audio"
    config.openai_api_key = "test_openai_key"
    config.summary_provider = "openai"
    config.gemini_api_key = None
    config.get_audio_path = lambda video_id: f"/tmp/test-audio/{video_id}.mp3"
    return config


@pytest.fixture(scope="session", autouse=True)
def _set_test_db_path():
    """Set DATABASE_PATH environment variable for all tests.

    This runs once at the start of the test session to ensure no test
    can accidentally write to the development database.
    """
    original_db = os.environ.get("DATABASE_PATH")
    test_db = os.path.join(tempfile.gettempdir(), "test_audio_history.db")
    os.environ["DATABASE_PATH"] = test_db

    # Clean up any existing test database before starting
    if os.path.exists(test_db):
        try:
            os.unlink(test_db)
        except Exception:
            pass

    yield

    # Clean up queue entries and weekly summaries from test database
    import sqlite3

    try:
        if os.path.exists(test_db):
            conn = sqlite3.connect(test_db)
            cursor = conn.cursor()
            # Clear queue entries created during tests
            cursor.execute("DELETE FROM queue WHERE type = 'summary'")
            cursor.execute(
                "DELETE FROM queue WHERE title LIKE '%Summary%' OR title LIKE '%Week%'"
            )
            # Clear weekly summary entries
            cursor.execute("DELETE FROM weekly_summaries")
            conn.commit()
            conn.close()
    except Exception:
        pass

    # Restore original
    if original_db:
        os.environ["DATABASE_PATH"] = original_db
    else:
        os.environ.pop("DATABASE_PATH", None)

    # Cleanup test database
    if os.path.exists(test_db):
        try:
            os.unlink(test_db)
        except Exception:
            pass


@pytest.fixture
def db_path(monkeypatch):
    """Temporary SQLite database for testing.

    This fixture creates a fresh database for tests that explicitly request it.
    Most tests will just use the session-level database via _set_test_db_path.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = f.name

    # Set environment variable for database using monkeypatch
    monkeypatch.setenv("DATABASE_PATH", temp_path)

    # Reload database module to pick up new DATABASE_PATH
    import services.database
    import importlib

    importlib.reload(services.database)

    # Initialize the database with all required tables
    from services.database import init_database

    init_database()

    yield temp_path

    # Cleanup
    if os.path.exists(temp_path):
        try:
            os.unlink(temp_path)
        except Exception:
            pass


@pytest.fixture
def mock_subprocess():
    """Mock subprocess.Popen for testing."""
    mock = Mock()
    mock.stdout = Mock()
    mock.stdout.read = Mock(return_value=b"mock audio data")
    mock.poll = Mock(return_value=None)
    mock.wait = Mock(return_value=0)
    mock.terminate = Mock()
    return mock


@pytest.fixture
def sample_video_id():
    """Sample YouTube video ID."""
    return "dQw4w9WgXcQ"


@pytest.fixture
def sample_video_title():
    """Sample YouTube video title."""
    return "Test Video Title"


@pytest.fixture
def sample_transcript():
    """Sample transcript text."""
    return "This is a sample transcript of the video content."


@pytest.fixture
def sample_summary():
    """Sample summary text."""
    return """### Summary

- Key point 1
- Key point 2
- Key point 3

The video discusses important topics."""


@pytest.fixture
def mock_httpx_response():
    """Mock httpx response."""

    def _make_response(status_code=200, json_data=None):
        response = Mock()
        response.status_code = status_code
        response.json = Mock(return_value=json_data or {})
        response.raise_for_status = Mock()
        return response

    return _make_response


@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client."""
    client = Mock()

    # Mock audio transcription
    transcription = Mock()
    transcription.text = "Mocked transcription text"
    client.audio.transcriptions.create = Mock(return_value=transcription)

    # Mock chat completion
    completion = Mock()
    completion.choices = [Mock()]
    completion.choices[0].message.content = "Mocked summary content"
    client.chat.completions.create = Mock(return_value=completion)

    return client


@pytest.fixture
def app_client():
    """FastAPI test client."""
    # Import main app (need to mock initialization)
    from unittest.mock import patch

    with (
        patch("services.database.init_database"),
        patch("services.background_tasks.init_background_tasks"),
    ):
        from main import app

        client = TestClient(app)
        yield client
