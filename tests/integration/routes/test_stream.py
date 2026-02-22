"""Integration tests for stream routes.

Uses real StreamState (not mocked) and/or real SQLite database to verify
that components interact correctly end-to-end.  External calls (yt-dlp,
YouTube metadata, ffmpeg) are still mocked so no network access is needed.
"""

import threading
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.stream import router, init_stream_globals


@pytest.fixture
def client():
    """FastAPI test client backed by a *real* StreamState instance."""
    app = FastAPI()
    app.include_router(router)
    lock = threading.Lock()
    init_stream_globals(lock)
    return TestClient(app)


# ---------------------------------------------------------------------------
# POST /stream → GET /status — real StreamState persists state across calls
# ---------------------------------------------------------------------------


class TestStreamToStatusIntegration:
    """POST /stream updates real StreamState; GET /status reflects the change."""

    @patch("routes.stream.get_queue_hash", return_value=30001)
    @patch("routes.stream.add_to_history")
    @patch("routes.stream.config")
    @patch("routes.stream.get_video_metadata")
    @patch("routes.stream.extract_video_id")
    @patch("routes.stream.start_youtube_download")
    @patch("routes.stream.finish_youtube_download")
    def test_status_reflects_video_and_queue_id_after_stream(
        self,
        mock_finish,
        mock_start,
        mock_extract,
        mock_metadata,
        mock_cfg,
        mock_history,
        mock_hash,
        client,
    ):
        """After POST /stream with queue_id, GET /status returns both IDs."""
        wait_event = threading.Event()
        mock_proc = Mock()
        mock_proc.wait = Mock(side_effect=lambda: wait_event.wait())
        mock_proc.returncode = 0
        mock_start.return_value = mock_proc

        mock_extract.return_value = "integ_vid"
        mock_metadata.return_value = {
            "title": "Integration Video",
            "channel": "CH",
            "thumbnail_url": None,
        }
        mock_cfg.transcription_enabled = False

        res = client.post(
            "/stream", json={"youtube_video_id": "integ_vid", "queue_id": 7}
        )
        assert res.status_code == 200

        status = client.get("/status")
        data = status.json()
        assert data["status"] == "streaming"
        assert data["current_video_id"] == "integ_vid"
        assert data["current_queue_id"] == 7
        assert data["queue_hash"] == 30001

        wait_event.set()

    @patch("routes.stream.get_queue_hash", return_value=0)
    @patch("routes.stream.add_to_history")
    @patch("routes.stream.config")
    @patch("routes.stream.get_video_metadata")
    @patch("routes.stream.extract_video_id")
    @patch("routes.stream.start_youtube_download")
    @patch("routes.stream.finish_youtube_download")
    def test_status_current_queue_id_is_none_when_no_queue_id(
        self,
        mock_finish,
        mock_start,
        mock_extract,
        mock_metadata,
        mock_cfg,
        mock_history,
        mock_hash,
        client,
    ):
        """POST /stream without queue_id → GET /status has current_queue_id=None."""
        wait_event = threading.Event()
        mock_proc = Mock()
        mock_proc.wait = Mock(side_effect=lambda: wait_event.wait())
        mock_proc.returncode = 0
        mock_start.return_value = mock_proc

        mock_extract.return_value = "direct_vid"
        mock_metadata.return_value = {
            "title": "Direct Video",
            "channel": None,
            "thumbnail_url": None,
        }
        mock_cfg.transcription_enabled = False

        res = client.post("/stream", json={"youtube_video_id": "direct_vid"})
        assert res.status_code == 200

        status = client.get("/status")
        data = status.json()
        assert data["current_video_id"] == "direct_vid"
        assert data["current_queue_id"] is None

        wait_event.set()

    @patch("routes.stream.get_queue_hash", return_value=0)
    @patch("routes.stream.add_to_history")
    @patch("routes.stream.config")
    @patch("routes.stream.get_video_metadata")
    @patch("routes.stream.extract_video_id")
    @patch("routes.stream.start_youtube_download")
    @patch("routes.stream.finish_youtube_download")
    def test_stop_clears_current_video_and_queue_id(
        self,
        mock_finish,
        mock_start,
        mock_extract,
        mock_metadata,
        mock_cfg,
        mock_history,
        mock_hash,
        client,
    ):
        """After POST /stream then POST /stop, GET /status returns current_queue_id=null."""
        wait_event = threading.Event()
        mock_proc = Mock()
        mock_proc.wait = Mock(side_effect=lambda: wait_event.wait())
        mock_proc.returncode = 0
        mock_start.return_value = mock_proc

        mock_extract.return_value = "stop_test_vid"
        mock_metadata.return_value = {
            "title": "Stop Test Video",
            "channel": "CH",
            "thumbnail_url": None,
        }
        mock_cfg.transcription_enabled = False

        # Start the stream with a queue_id
        res = client.post(
            "/stream", json={"youtube_video_id": "stop_test_vid", "queue_id": 5}
        )
        assert res.status_code == 200

        # Confirm state is set
        status = client.get("/status")
        assert status.json()["current_queue_id"] == 5

        # Stop the stream
        stop_res = client.post("/stop")
        assert stop_res.status_code == 200

        # State should be cleared
        status_after = client.get("/status")
        data = status_after.json()
        assert data["current_video_id"] is None
        assert data["current_queue_id"] is None

        wait_event.set()

    @patch("routes.stream.get_queue_hash", return_value=0)
    @patch("routes.stream.add_to_history")
    @patch("routes.stream.config")
    @patch("routes.stream.get_video_metadata")
    @patch("routes.stream.extract_video_id")
    @patch("routes.stream.start_youtube_download")
    @patch("routes.stream.finish_youtube_download")
    def test_second_stream_overwrites_current(
        self,
        mock_finish,
        mock_start,
        mock_extract,
        mock_metadata,
        mock_cfg,
        mock_history,
        mock_hash,
        client,
    ):
        """A second POST /stream replaces current_video_id and current_queue_id."""
        wait_event = threading.Event()
        proc1 = Mock()
        proc1.wait = Mock(side_effect=lambda: wait_event.wait())
        proc1.returncode = 0
        proc2 = Mock()
        proc2.wait = Mock(side_effect=lambda: wait_event.wait())
        proc2.returncode = 0
        mock_start.side_effect = [proc1, proc2]

        mock_metadata.return_value = {
            "title": "Some Title",
            "channel": None,
            "thumbnail_url": None,
        }
        mock_cfg.transcription_enabled = False

        mock_extract.return_value = "first_vid"
        client.post("/stream", json={"youtube_video_id": "first_vid", "queue_id": 1})

        mock_extract.return_value = "second_vid"
        client.post("/stream", json={"youtube_video_id": "second_vid", "queue_id": 2})

        status = client.get("/status")
        data = status.json()
        assert data["current_video_id"] == "second_vid"
        assert data["current_queue_id"] == 2

        wait_event.set()


# ---------------------------------------------------------------------------
# GET /status — queue_hash against real SQLite database
# ---------------------------------------------------------------------------


class TestStatusQueueHashWithRealDatabase:
    """GET /status queue_hash reflects actual database queue state."""

    def test_empty_queue_yields_hash_zero(self, client, db_path):
        """/status returns queue_hash=0 when the queue is empty."""
        from services.database import init_database

        init_database()

        res = client.get("/status")
        assert res.status_code == 200
        assert res.json()["queue_hash"] == 0

    def test_hash_changes_after_item_added(self, client, db_path):
        """/status queue_hash changes when an item is added to the queue."""
        from services.database import init_database, add_to_queue

        init_database()

        hash_empty = client.get("/status").json()["queue_hash"]
        assert hash_empty == 0

        add_to_queue("yt_abc", "Some Video")

        hash_with_item = client.get("/status").json()["queue_hash"]
        assert hash_with_item != 0
        assert hash_with_item != hash_empty

    def test_hash_returns_to_zero_after_clear(self, client, db_path):
        """/status queue_hash returns to 0 after the queue is cleared."""
        from services.database import init_database, add_to_queue, clear_queue

        init_database()
        add_to_queue("yt_xyz", "Another Video")

        hash_before = client.get("/status").json()["queue_hash"]
        assert hash_before != 0

        clear_queue()

        hash_after = client.get("/status").json()["queue_hash"]
        assert hash_after == 0


# ---------------------------------------------------------------------------
# POST /stream — full-app validation (real router stack)
# ---------------------------------------------------------------------------


class TestStreamEndpointValidation:
    """Input validation on POST /stream using the full application stack."""

    def test_stream_rejects_empty_video_id(self):
        """POST /stream returns 400 for an empty video_id."""
        from fastapi.testclient import TestClient
        from main import app

        c = TestClient(app)
        response = c.post("/stream", json={"youtube_video_id": ""})
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    def test_stream_rejects_whitespace_only_video_id(self):
        """POST /stream returns 400 for a whitespace-only video_id."""
        from fastapi.testclient import TestClient
        from main import app

        c = TestClient(app)
        response = c.post("/stream", json={"youtube_video_id": "   "})
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()
