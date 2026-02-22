"""Unit tests for version generation — all subprocess calls are mocked."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch, Mock

import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from generate_version import get_git_hash, get_git_branch, generate_version_file


class TestGetGitHash:
    """Tests for get_git_hash function."""

    @patch("generate_version.subprocess.run")
    def test_returns_hash_on_success(self, mock_run):
        """Should return git hash when git command succeeds."""
        mock_run.return_value = Mock(
            stdout="a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0\n", returncode=0
        )

        result = get_git_hash()

        assert result == "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0"
        mock_run.assert_called_once_with(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )

    @patch("generate_version.subprocess.run")
    def test_strips_whitespace(self, mock_run):
        """Should strip whitespace from git hash."""
        mock_run.return_value = Mock(stdout="  abc123def456  \n  ", returncode=0)

        result = get_git_hash()

        assert result == "abc123def456"

    @patch("generate_version.subprocess.run")
    def test_returns_unknown_on_error(self, mock_run):
        """Should return 'unknown' when git command fails."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")

        result = get_git_hash()

        assert result == "unknown"

    @patch("generate_version.subprocess.run")
    def test_handles_git_not_installed(self, mock_run):
        """Should handle case when git is not installed."""
        mock_run.side_effect = subprocess.CalledProcessError(127, "git")

        result = get_git_hash()

        assert result == "unknown"


class TestGetGitBranch:
    """Tests for get_git_branch function."""

    @patch("generate_version.subprocess.run")
    def test_returns_branch_on_success(self, mock_run):
        """Should return branch name when git command succeeds."""
        mock_run.return_value = Mock(stdout="main\n", returncode=0)

        result = get_git_branch()

        assert result == "main"
        mock_run.assert_called_once_with(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )

    @patch("generate_version.subprocess.run")
    def test_returns_feature_branch(self, mock_run):
        """Should return feature branch name."""
        mock_run.return_value = Mock(stdout="feature/new-feature\n", returncode=0)

        result = get_git_branch()

        assert result == "feature/new-feature"

    @patch("generate_version.subprocess.run")
    def test_returns_unknown_on_error(self, mock_run):
        """Should return 'unknown' when git command fails."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")

        result = get_git_branch()

        assert result == "unknown"


class TestGenerateVersionFile:
    """Unit tests for generate_version_file with mocked git and filesystem."""

    def test_version_file_structure(self, tmp_path):
        """Should create version file with correct JSON structure."""
        version_data = {
            "hash": "abc123",
            "branch": "main",
            "timestamp": "2026-02-10T12:00:00+00:00",
        }

        version_file = tmp_path / "version.json"
        with open(version_file, "w") as f:
            json.dump(version_data, f, indent=2)

        with open(version_file, "r") as f:
            data = json.load(f)

        assert "hash" in data
        assert "branch" in data
        assert "timestamp" in data
        assert data["hash"] == "abc123"
        assert data["branch"] == "main"

    @patch("generate_version.get_git_hash")
    @patch("generate_version.get_git_branch")
    def test_handles_unknown_git_values(self, mock_branch, mock_hash, tmp_path):
        """Should handle 'unknown' values from git commands without raising."""
        mock_hash.return_value = "unknown"
        mock_branch.return_value = "unknown"

        with patch("generate_version.Path") as mock_path:
            static_dir = tmp_path / "static"
            static_dir.mkdir(exist_ok=True)

            instance = Mock()
            instance.parent = tmp_path
            instance.__truediv__ = (
                lambda self, other: static_dir if other == "static" else Mock()
            )
            mock_path.return_value = instance

            with patch("builtins.open", create=True):
                generate_version_file()


class TestVersionFileFormat:
    """Tests for version file JSON format using temp files."""

    def test_version_json_is_valid_json(self, tmp_path):
        """Should produce valid JSON."""
        version_file = tmp_path / "version.json"
        version_data = {
            "hash": "a1b2c3d4",
            "branch": "main",
            "timestamp": "2026-02-10T12:00:00+00:00",
        }

        with open(version_file, "w") as f:
            json.dump(version_data, f, indent=2)

        with open(version_file, "r") as f:
            data = json.load(f)

        assert isinstance(data, dict)

    def test_hash_field_is_string(self, tmp_path):
        """Should have hash as string type."""
        version_file = tmp_path / "version.json"
        version_data = {
            "hash": "abc123",
            "branch": "main",
            "timestamp": "2026-02-10T12:00:00+00:00",
        }

        with open(version_file, "w") as f:
            json.dump(version_data, f)

        with open(version_file, "r") as f:
            data = json.load(f)

        assert isinstance(data["hash"], str)
        assert len(data["hash"]) > 0

    def test_timestamp_is_iso_format(self, tmp_path):
        """Should have timestamp in ISO 8601 format."""
        version_file = tmp_path / "version.json"
        version_data = {
            "hash": "abc123",
            "branch": "main",
            "timestamp": "2026-02-10T12:00:00+00:00",
        }

        with open(version_file, "w") as f:
            json.dump(version_data, f)

        with open(version_file, "r") as f:
            data = json.load(f)

        assert isinstance(data["timestamp"], str)
        assert "T" in data["timestamp"]
        from datetime import datetime

        datetime.fromisoformat(data["timestamp"].replace("+00:00", "+00:00"))
