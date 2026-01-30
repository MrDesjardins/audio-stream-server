"""Tests for scheduler service."""

import pytest
from unittest.mock import Mock, patch, MagicMock

from services.scheduler import (
    init_scheduler,
    shutdown_scheduler,
    get_scheduler,
    trigger_weekly_summary_now,
    get_next_run_time,
)


class TestInitScheduler:
    """Tests for init_scheduler function."""

    def setup_method(self):
        """Reset scheduler state before each test."""
        import services.scheduler

        services.scheduler._scheduler = None

    @patch("services.scheduler.config")
    @patch("services.scheduler.BackgroundScheduler")
    def test_initializes_scheduler_when_enabled(self, mock_scheduler_class, mock_config):
        """Should initialize scheduler when weekly_summary_enabled is True."""
        mock_config.weekly_summary_enabled = True

        mock_scheduler_instance = Mock()
        mock_scheduler_class.return_value = mock_scheduler_instance

        init_scheduler()

        mock_scheduler_class.assert_called_once()
        mock_scheduler_instance.add_job.assert_called_once()
        mock_scheduler_instance.start.assert_called_once()

    @patch("services.scheduler.config")
    @patch("services.scheduler.BackgroundScheduler")
    def test_does_not_add_job_when_disabled(self, mock_scheduler_class, mock_config):
        """Should not add weekly summary job when feature is disabled."""
        mock_config.weekly_summary_enabled = False

        mock_scheduler_instance = Mock()
        mock_scheduler_class.return_value = mock_scheduler_instance

        init_scheduler()

        mock_scheduler_instance.add_job.assert_not_called()
        mock_scheduler_instance.start.assert_called_once()

    @patch("services.scheduler.config")
    @patch("services.scheduler._scheduler", None)
    def test_does_not_reinitialize_if_already_running(self, mock_config):
        """Should not reinitialize if scheduler already exists."""
        mock_config.weekly_summary_enabled = True

        # First initialization
        with patch("services.scheduler.BackgroundScheduler") as mock_scheduler_class:
            mock_scheduler_instance = Mock()
            mock_scheduler_class.return_value = mock_scheduler_instance

            init_scheduler()

            # Try to initialize again
            init_scheduler()

            # Should only call once
            mock_scheduler_class.assert_called_once()

    @patch("services.scheduler.config")
    @patch("services.scheduler.BackgroundScheduler")
    def test_handles_initialization_error(self, mock_scheduler_class, mock_config):
        """Should handle errors during initialization gracefully."""
        mock_config.weekly_summary_enabled = True
        mock_scheduler_class.side_effect = Exception("Initialization error")

        # Should not raise exception
        init_scheduler()

        # Scheduler should be None on error
        assert get_scheduler() is None


class TestShutdownScheduler:
    """Tests for shutdown_scheduler function."""

    @patch("services.scheduler._scheduler")
    def test_shuts_down_scheduler(self, mock_scheduler):
        """Should shut down the scheduler."""
        shutdown_scheduler()

        mock_scheduler.shutdown.assert_called_once_with(wait=True)

    @patch("services.scheduler._scheduler", None)
    def test_handles_no_scheduler(self):
        """Should handle case when no scheduler exists."""
        # Should not raise exception
        shutdown_scheduler()


class TestGetScheduler:
    """Tests for get_scheduler function."""

    @patch("services.scheduler._scheduler", Mock())
    def test_returns_scheduler_instance(self):
        """Should return the scheduler instance."""
        scheduler = get_scheduler()

        assert scheduler is not None

    @patch("services.scheduler._scheduler", None)
    def test_returns_none_when_not_initialized(self):
        """Should return None when scheduler not initialized."""
        scheduler = get_scheduler()

        assert scheduler is None


class TestTriggerWeeklySummaryNow:
    """Tests for trigger_weekly_summary_now function."""

    @patch("services.scheduler.generate_and_save_weekly_summary")
    def test_triggers_weekly_summary(self, mock_generate):
        """Should trigger weekly summary generation."""
        mock_generate.return_value = {"noteId": "note123", "url": "url"}

        trigger_weekly_summary_now()

        mock_generate.assert_called_once()

    @patch("services.scheduler.generate_and_save_weekly_summary")
    def test_handles_none_result(self, mock_generate):
        """Should handle None result from summary generation."""
        mock_generate.return_value = None

        # Should not raise exception
        trigger_weekly_summary_now()

    @patch("services.scheduler.generate_and_save_weekly_summary")
    def test_handles_generation_error(self, mock_generate):
        """Should handle errors during summary generation."""
        mock_generate.side_effect = Exception("Generation error")

        # Should not raise exception
        trigger_weekly_summary_now()


class TestGetNextRunTime:
    """Tests for get_next_run_time function."""

    @patch("services.scheduler._scheduler")
    def test_returns_next_run_time(self, mock_scheduler):
        """Should return formatted next run time."""
        from datetime import datetime
        from pytz import timezone

        pacific = timezone("America/Los_Angeles")
        next_run = datetime(2026, 1, 30, 23, 0, 0, tzinfo=pacific)

        mock_job = Mock()
        mock_job.next_run_time = next_run

        mock_scheduler.get_job.return_value = mock_job

        result = get_next_run_time()

        assert result is not None
        assert "2026-01-30" in result
        assert "23:00:00" in result

    @patch("services.scheduler._scheduler")
    def test_returns_none_when_job_not_found(self, mock_scheduler):
        """Should return None when job doesn't exist."""
        mock_scheduler.get_job.return_value = None

        result = get_next_run_time()

        assert result is None

    @patch("services.scheduler._scheduler", None)
    def test_returns_none_when_scheduler_not_initialized(self):
        """Should return None when scheduler not initialized."""
        result = get_next_run_time()

        assert result is None


class TestSchedulerIntegration:
    """Integration tests for scheduler functionality."""

    @patch("services.scheduler.config")
    @patch("services.scheduler.BackgroundScheduler")
    def test_full_lifecycle(self, mock_scheduler_class, mock_config):
        """Test full init -> get -> shutdown lifecycle."""
        mock_config.weekly_summary_enabled = True

        mock_scheduler_instance = Mock()
        mock_scheduler_class.return_value = mock_scheduler_instance

        # Initialize
        init_scheduler()
        assert get_scheduler() is not None

        # Shutdown
        with patch("services.scheduler._scheduler", mock_scheduler_instance):
            shutdown_scheduler()
            mock_scheduler_instance.shutdown.assert_called_once()
