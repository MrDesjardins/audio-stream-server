"""Tests for admin routes."""

from fastapi.testclient import TestClient
from unittest.mock import patch

from main import app

client = TestClient(app)


class TestTriggerWeeklySummary:
    """Tests for /admin/weekly-summary/trigger endpoint."""

    @patch("routes.admin.config")
    @patch("services.scheduler.trigger_weekly_summary_now")
    def test_triggers_weekly_summary_when_enabled(self, mock_trigger, mock_config):
        """Should trigger weekly summary when feature is enabled."""
        mock_config.weekly_summary_enabled = True

        response = client.post("/admin/weekly-summary/trigger")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "triggered"
        mock_trigger.assert_called_once()

    @patch("routes.admin.config")
    def test_returns_400_when_disabled(self, mock_config):
        """Should return 400 when weekly summary feature is disabled."""
        mock_config.weekly_summary_enabled = False

        response = client.post("/admin/weekly-summary/trigger")

        assert response.status_code == 400
        data = response.json()
        assert "disabled" in data["detail"].lower()

    @patch("routes.admin.config")
    @patch("services.scheduler.trigger_weekly_summary_now")
    def test_handles_trigger_error(self, mock_trigger, mock_config):
        """Should return 500 on trigger error."""
        mock_config.weekly_summary_enabled = True
        mock_trigger.side_effect = Exception("Trigger error")

        response = client.post("/admin/weekly-summary/trigger")

        assert response.status_code == 500


class TestGetNextRunTime:
    """Tests for /admin/weekly-summary/next-run endpoint."""

    @patch("routes.admin.config")
    @patch("services.scheduler.get_next_run_time")
    def test_returns_next_run_time(self, mock_get_next_run, mock_config):
        """Should return next scheduled run time."""
        mock_config.weekly_summary_enabled = True
        mock_get_next_run.return_value = "2026-01-30 23:00:00 PST"

        response = client.get("/admin/weekly-summary/next-run")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "scheduled"
        assert "2026-01-30 23:00:00" in data["next_run_time"]

    @patch("routes.admin.config")
    @patch("services.scheduler.get_next_run_time")
    def test_returns_not_scheduled_when_no_job(self, mock_get_next_run, mock_config):
        """Should return not_scheduled when job doesn't exist."""
        mock_config.weekly_summary_enabled = True
        mock_get_next_run.return_value = None

        response = client.get("/admin/weekly-summary/next-run")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "not_scheduled"

    @patch("routes.admin.config")
    def test_returns_400_when_disabled(self, mock_config):
        """Should return 400 when feature is disabled."""
        mock_config.weekly_summary_enabled = False

        response = client.get("/admin/weekly-summary/next-run")

        assert response.status_code == 400

    @patch("routes.admin.config")
    @patch("services.scheduler.get_next_run_time")
    def test_handles_error(self, mock_get_next_run, mock_config):
        """Should return 500 on error."""
        mock_config.weekly_summary_enabled = True
        mock_get_next_run.side_effect = Exception("Error")

        response = client.get("/admin/weekly-summary/next-run")

        assert response.status_code == 500
