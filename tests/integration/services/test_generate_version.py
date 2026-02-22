"""Integration tests for version generation — uses real git and filesystem."""

import json
import subprocess
from pathlib import Path

import pytest

import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from generate_version import get_git_hash, get_git_branch, generate_version_file


class TestGenerateVersionFile:
    """Integration tests for generate_version_file with real filesystem."""

    def test_version_file_creation_integration(self):
        """Should create version.json file without raising."""
        try:
            generate_version_file()
            assert True
        except Exception as e:
            pytest.fail(f"generate_version_file() raised {e}")


class TestIntegration:
    """Integration tests for version generation using real git commands."""

    def test_real_git_commands_work(self):
        """Should work with real git commands in repo."""
        try:
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            pytest.skip("Not in a git repository")

        hash_val = get_git_hash()
        branch_val = get_git_branch()

        assert isinstance(hash_val, str)
        assert len(hash_val) > 0
        assert hash_val != "unknown"

        assert isinstance(branch_val, str)
        assert len(branch_val) > 0
        assert branch_val != "unknown"

    def test_generated_file_is_readable(self):
        """Should generate a file that is readable as valid JSON."""
        generate_version_file()

        version_file = (
            Path(__file__).parent.parent.parent.parent / "static" / "version.json"
        )
        assert version_file.exists(), "version.json should be created"

        with open(version_file, "r") as f:
            data = json.load(f)

        assert "hash" in data
        assert "branch" in data
        assert "timestamp" in data
