"""Tests for stream routes (download, audio serving, status, history)."""

import os
import tempfile
import threading
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.stream import router, StreamState, init_stream_globals


@pytest.fixture
def temp_audio_dir():
    """Temporary directory for audio files during tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_config(temp_audio_dir):
    """Mock config for stream routes."""
    config = Mock()
    config.transcription_enabled = True
    config.temp_audio_dir = temp_audio_dir
    config.get_audio_path = lambda vid: os.path.join(temp_audio_dir, f"{vid}.mp3")
    return config


@pytest.fixture
def client():
    """FastAPI test client for stream router with initialized state."""
    app = FastAPI()
    app.include_router(router)
    lock = threading.Lock()
    init_stream_globals(lock)
    return TestClient(app)


class TestStreamState:
    """Tests for StreamState class."""

    def test_init(self):
        """StreamState initializes with no process."""
        lock = threading.Lock()
        state = StreamState(lock)
        assert state._current_process is None
        assert state._download_thread is None

    def test_is_streaming_false_initially(self):
        """is_streaming returns False when no process is running."""
        lock = threading.Lock()
        state = StreamState(lock)
        assert state.is_streaming() is False

    def test_is_streaming_true_after_start(self):
        """is_streaming returns True after starting a download."""
        wait_event = threading.Event()
        mock_proc = Mock()
        mock_proc.wait = Mock(side_effect=lambda: wait_event.wait())
        mock_proc.returncode = 0

        lock = threading.Lock()
        state = StreamState(lock)

        with patch("services.streaming.start_youtube_download", return_value=(mock_proc, "vid1")):
            with patch("services.streaming.finish_youtube_download"):
                state.start_stream("vid1", skip_transcription=False)
                assert state.is_streaming() is True
                wait_event.set()
                state._download_thread.join(timeout=2)

    def test_stop_stream_when_running(self):
        """stop_stream terminates process and returns True."""
        wait_event = threading.Event()
        mock_proc = Mock()
        mock_proc.wait = Mock(side_effect=lambda: wait_event.wait())
        mock_proc.returncode = 0

        lock = threading.Lock()
        state = StreamState(lock)

        with patch("services.streaming.start_youtube_download", return_value=(mock_proc, "vid1")):
            with patch("services.streaming.finish_youtube_download"):
                state.start_stream("vid1", skip_transcription=False)
                result = state.stop_stream()

        assert result is True
        mock_proc.terminate.assert_called()
        wait_event.set()

    def test_stop_stream_when_idle(self):
        """stop_stream returns False when nothing is running."""
        lock = threading.Lock()
        state = StreamState(lock)
        assert state.stop_stream() is False

    def test_start_stream_terminates_existing(self):
        """Starting a new stream kills the existing one."""
        wait_event = threading.Event()
        old_proc = Mock()
        old_proc.wait = Mock(side_effect=lambda: wait_event.wait())
        old_proc.returncode = 0
        new_proc = Mock()
        new_proc.wait = Mock(side_effect=lambda: wait_event.wait())
        new_proc.returncode = 0

        lock = threading.Lock()
        state = StreamState(lock)

        with patch(
            "services.streaming.start_youtube_download",
            side_effect=[(old_proc, "vid1"), (new_proc, "vid2")],
        ):
            with patch("services.streaming.finish_youtube_download"):
                state.start_stream("vid1", skip_transcription=False)
                state.start_stream("vid2", skip_transcription=False)

        old_proc.terminate.assert_called()
        wait_event.set()

    @patch("services.streaming.start_youtube_download")
    def test_start_stream_when_cached(self, mock_start):
        """Handles gracefully when download returns None (already cached)."""
        mock_start.return_value = (None, "cached_vid")

        lock = threading.Lock()
        state = StreamState(lock)

        with patch("services.streaming.finish_youtube_download"):
            state.start_stream("cached_vid", skip_transcription=False)

        assert state._current_process is None

    def test_stop_stream_kills_on_wait_timeout(self):
        """If wait() times out during stop, process is killed."""
        wait_event = threading.Event()
        call_count = [0]

        def wait_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                wait_event.wait()
                return 0
            else:
                raise Exception("timeout")

        mock_proc = Mock()
        mock_proc.wait = Mock(side_effect=wait_side_effect)

        lock = threading.Lock()
        state = StreamState(lock)

        with patch("services.streaming.start_youtube_download", return_value=(mock_proc, "vid1")):
            with patch("services.streaming.finish_youtube_download"):
                state.start_stream("vid1", skip_transcription=False)
                state.stop_stream()

        mock_proc.kill.assert_called()
        wait_event.set()


class TestStreamEndpoint:
    """Tests for POST /stream."""

    @patch("routes.stream.get_stream_state")
    @patch("routes.stream.config")
    @patch("routes.stream.get_video_metadata")
    @patch("routes.stream.extract_video_id")
    @patch("routes.stream.add_to_history")
    def test_stream_with_metadata(
        self, mock_history, mock_extract, mock_metadata, mock_cfg, mock_state, client
    ):
        """POST /stream saves metadata to history and starts download."""
        mock_extract.return_value = "test123"
        mock_metadata.return_value = {
            "title": "Test Audiobook",
            "channel": "Books Channel",
            "thumbnail_url": "https://example.com/thumb.jpg",
        }
        mock_cfg.transcription_enabled = False
        state = Mock()
        mock_state.return_value = state

        response = client.post("/stream", json={"youtube_video_id": "test123"})

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "stream started"
        assert data["youtube_video_id"] == "test123"
        assert data["title"] == "Test Audiobook"
        mock_history.assert_called_once_with(
            "test123", "Test Audiobook", "Books Channel", "https://example.com/thumb.jpg"
        )
        state.start_stream.assert_called_once_with("test123", False)

    @patch("routes.stream.get_stream_state")
    @patch("routes.stream.config")
    @patch("routes.stream.get_video_metadata")
    @patch("routes.stream.extract_video_id")
    @patch("routes.stream.add_to_history")
    def test_stream_without_metadata(
        self, mock_history, mock_extract, mock_metadata, mock_cfg, mock_state, client
    ):
        """POST /stream uses fallback title when metadata fetch fails."""
        mock_extract.return_value = "no_meta"
        mock_metadata.return_value = None
        mock_cfg.transcription_enabled = False
        mock_state.return_value = Mock()

        response = client.post("/stream", json={"youtube_video_id": "no_meta"})

        assert response.status_code == 200
        data = response.json()
        assert "YouTube Video no_meta" in data["title"]
        mock_history.assert_called_once_with("no_meta", "YouTube Video no_meta")

    @patch("routes.stream.get_stream_state")
    @patch("routes.stream.config")
    @patch("routes.stream.get_video_metadata")
    @patch("routes.stream.extract_video_id")
    @patch("routes.stream.add_to_history")
    def test_stream_queues_transcription_when_enabled(
        self, mock_history, mock_extract, mock_metadata, mock_cfg, mock_state, client
    ):
        """Transcription job is queued when enabled and not skipped."""
        mock_extract.return_value = "trans_vid"
        mock_metadata.return_value = {"title": "Title", "channel": None, "thumbnail_url": None}
        mock_cfg.transcription_enabled = True
        mock_cfg.get_audio_path = lambda vid: f"/tmp/{vid}.mp3"
        mock_state.return_value = Mock()

        mock_queue = Mock()
        with patch("routes.stream.get_transcription_queue", return_value=mock_queue):
            response = client.post(
                "/stream", json={"youtube_video_id": "trans_vid", "skip_transcription": False}
            )

        assert response.status_code == 200
        mock_queue.add_job.assert_called_once()
        job = mock_queue.add_job.call_args[0][0]
        assert job.video_id == "trans_vid"

    @patch("routes.stream.get_stream_state")
    @patch("routes.stream.config")
    @patch("routes.stream.get_video_metadata")
    @patch("routes.stream.extract_video_id")
    @patch("routes.stream.add_to_history")
    def test_stream_skips_transcription_when_requested(
        self, mock_history, mock_extract, mock_metadata, mock_cfg, mock_state, client
    ):
        """No transcription job when skip_transcription=True."""
        mock_extract.return_value = "skip_vid"
        mock_metadata.return_value = {"title": "Title", "channel": None, "thumbnail_url": None}
        mock_cfg.transcription_enabled = True
        mock_state.return_value = Mock()

        mock_queue = Mock()
        with patch("routes.stream.get_transcription_queue", return_value=mock_queue):
            response = client.post(
                "/stream", json={"youtube_video_id": "skip_vid", "skip_transcription": True}
            )

        assert response.status_code == 200
        mock_queue.add_job.assert_not_called()

    @patch("routes.stream.get_stream_state")
    @patch("routes.stream.config")
    @patch("routes.stream.get_video_metadata")
    @patch("routes.stream.extract_video_id")
    @patch("routes.stream.add_to_history")
    def test_stream_handles_history_error_gracefully(
        self, mock_history, mock_extract, mock_metadata, mock_cfg, mock_state, client
    ):
        """History save failure does not prevent streaming."""
        mock_extract.return_value = "err_vid"
        mock_metadata.side_effect = Exception("YouTube API error")
        mock_cfg.transcription_enabled = False
        mock_state.return_value = Mock()

        response = client.post("/stream", json={"youtube_video_id": "err_vid"})

        assert response.status_code == 200
        assert "YouTube Video err_vid" in response.json()["title"]


class TestAudioFileEndpoint:
    """Tests for GET /audio/{video_id}."""

    @patch("routes.stream.config")
    @patch("routes.stream._audio_is_ready")
    def test_serves_file_when_ready(self, mock_ready, mock_cfg, client, temp_audio_dir):
        """Returns the audio file when it exists and download is complete."""
        audio_path = os.path.join(temp_audio_dir, "ready_vid.mp3")
        with open(audio_path, "wb") as f:
            f.write(b"fake mp3 content here")

        mock_cfg.get_audio_path = lambda vid: os.path.join(temp_audio_dir, f"{vid}.mp3")
        mock_ready.return_value = True

        response = client.get("/audio/ready_vid")

        assert response.status_code == 200
        assert response.headers["accept-ranges"] == "bytes"

    @patch("routes.stream.config")
    @patch("routes.stream._audio_is_ready")
    def test_returns_404_when_downloading(self, mock_ready, mock_cfg, client, temp_audio_dir):
        """Returns 404 with Retry-After when file is still downloading."""
        mock_cfg.get_audio_path = lambda vid: os.path.join(temp_audio_dir, f"{vid}.mp3")
        mock_ready.return_value = False

        response = client.get("/audio/downloading_vid")

        assert response.status_code == 404
        data = response.json()
        assert data["status"] == "downloading"
        assert "retry-after" in response.headers

    @patch("routes.stream.config")
    @patch("routes.stream._audio_is_ready")
    def test_returns_404_when_file_missing(self, mock_ready, mock_cfg, client, temp_audio_dir):
        """Returns 404 when file doesn't exist at all."""
        mock_cfg.get_audio_path = lambda vid: os.path.join(temp_audio_dir, f"{vid}.mp3")
        mock_ready.return_value = False

        response = client.get("/audio/missing_vid")

        assert response.status_code == 404


class TestHeadAudioEndpoint:
    """Tests for HEAD /audio/{video_id}."""

    @patch("routes.stream.config")
    @patch("routes.stream._audio_is_ready")
    def test_returns_200_when_ready(self, mock_ready, mock_cfg, client, temp_audio_dir):
        """HEAD returns 200 with correct headers when file is ready."""
        audio_path = os.path.join(temp_audio_dir, "head_vid.mp3")
        with open(audio_path, "wb") as f:
            f.write(b"x" * 1024)

        mock_cfg.get_audio_path = lambda vid: os.path.join(temp_audio_dir, f"{vid}.mp3")
        mock_ready.return_value = True

        response = client.head("/audio/head_vid")

        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/mpeg"

    @patch("routes.stream.config")
    @patch("routes.stream._audio_is_ready")
    def test_returns_404_when_not_ready(self, mock_ready, mock_cfg, client, temp_audio_dir):
        """HEAD returns 404 when file is not ready."""
        mock_cfg.get_audio_path = lambda vid: os.path.join(temp_audio_dir, f"{vid}.mp3")
        mock_ready.return_value = False

        response = client.head("/audio/not_ready_vid")

        assert response.status_code == 404
        assert "retry-after" in response.headers


class TestAudioIsReady:
    """Tests for _audio_is_ready helper."""

    @patch("services.streaming.is_download_in_progress")
    @patch("routes.stream.config")
    def test_ready_when_file_exists_and_not_downloading(
        self, mock_cfg, mock_in_progress, temp_audio_dir
    ):
        """Returns True when file exists and marker is gone."""
        audio_path = os.path.join(temp_audio_dir, "check_vid.mp3")
        with open(audio_path, "w") as f:
            f.write("data")
        mock_cfg.get_audio_path = lambda vid: os.path.join(temp_audio_dir, f"{vid}.mp3")
        mock_in_progress.return_value = False

        from routes.stream import _audio_is_ready

        assert _audio_is_ready("check_vid") is True

    @patch("services.streaming.is_download_in_progress")
    @patch("routes.stream.config")
    def test_not_ready_when_still_downloading(self, mock_cfg, mock_in_progress, temp_audio_dir):
        """Returns False when marker file still exists."""
        audio_path = os.path.join(temp_audio_dir, "dl_vid.mp3")
        with open(audio_path, "w") as f:
            f.write("partial")
        mock_cfg.get_audio_path = lambda vid: os.path.join(temp_audio_dir, f"{vid}.mp3")
        mock_in_progress.return_value = True

        from routes.stream import _audio_is_ready

        assert _audio_is_ready("dl_vid") is False

    @patch("services.streaming.is_download_in_progress")
    @patch("routes.stream.config")
    def test_not_ready_when_file_missing(self, mock_cfg, mock_in_progress, temp_audio_dir):
        """Returns False when audio file doesn't exist."""
        mock_cfg.get_audio_path = lambda vid: os.path.join(temp_audio_dir, f"{vid}.mp3")
        mock_in_progress.return_value = False

        from routes.stream import _audio_is_ready

        assert _audio_is_ready("gone_vid") is False


class TestStopEndpoint:
    """Tests for POST /stop."""

    @patch("routes.stream.get_stream_state")
    def test_stop_when_streaming(self, mock_state, client):
        """Returns success when download is stopped."""
        state = Mock()
        state.stop_stream = Mock(return_value=True)
        mock_state.return_value = state

        response = client.post("/stop")

        assert response.status_code == 200
        assert response.json()["status"] == "stream stopped"

    @patch("routes.stream.get_stream_state")
    def test_stop_when_idle(self, mock_state, client):
        """Returns 400 when nothing is running."""
        state = Mock()
        state.stop_stream = Mock(return_value=False)
        mock_state.return_value = state

        response = client.post("/stop")

        assert response.status_code == 400
        assert "No stream running" in response.json()["detail"]


class TestStatusEndpoint:
    """Tests for GET /status."""

    @patch("routes.stream.get_stream_state")
    def test_status_streaming(self, mock_state, client):
        """Returns 'streaming' when download is active."""
        state = Mock()
        state.is_streaming = Mock(return_value=True)
        mock_state.return_value = state

        response = client.get("/status")

        assert response.status_code == 200
        assert response.json()["status"] == "streaming"

    @patch("routes.stream.get_stream_state")
    def test_status_idle(self, mock_state, client):
        """Returns 'idle' when no download is active."""
        state = Mock()
        state.is_streaming = Mock(return_value=False)
        mock_state.return_value = state

        response = client.get("/status")

        assert response.status_code == 200
        assert response.json()["status"] == "idle"


class TestHistoryEndpoints:
    """Tests for GET /history and POST /history/clear."""

    @patch("routes.stream.get_history")
    def test_get_history_success(self, mock_history, client):
        """Returns history list."""
        mock_history.return_value = [
            {"id": 1, "youtube_id": "vid1", "title": "Book 1", "play_count": 3},
            {"id": 2, "youtube_id": "vid2", "title": "Book 2", "play_count": 1},
        ]

        response = client.get("/history")

        assert response.status_code == 200
        data = response.json()
        assert len(data["history"]) == 2
        assert data["history"][0]["title"] == "Book 1"

    @patch("routes.stream.get_history")
    def test_get_history_empty(self, mock_history, client):
        """Returns empty list when no history."""
        mock_history.return_value = []

        response = client.get("/history")

        assert response.status_code == 200
        assert response.json()["history"] == []

    @patch("routes.stream.get_history")
    def test_get_history_error(self, mock_history, client):
        """Returns 500 on database error."""
        mock_history.side_effect = Exception("DB error")

        response = client.get("/history")

        assert response.status_code == 500

    @patch("routes.stream.clear_history")
    def test_clear_history_success(self, mock_clear, client):
        """Clears history and returns success."""
        response = client.post("/history/clear")

        assert response.status_code == 200
        assert response.json()["status"] == "cleared"
        mock_clear.assert_called_once()

    @patch("routes.stream.clear_history")
    def test_clear_history_error(self, mock_clear, client):
        """Returns 500 on database error."""
        mock_clear.side_effect = Exception("DB error")

        response = client.post("/history/clear")

        assert response.status_code == 500
