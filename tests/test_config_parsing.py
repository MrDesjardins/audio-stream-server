"""Tests for config integer parsing with bounds checking."""

import os
from unittest.mock import patch
from config import _parse_int, Config


class TestParseInt:
    """Test the _parse_int helper function."""

    def test_parse_valid_integer(self):
        """Should parse valid integer strings."""
        assert _parse_int("42", 10) == 42
        assert _parse_int("0", 10) == 0
        assert _parse_int("-5", 10) == -5

    def test_parse_invalid_integer_uses_default(self):
        """Should use default for invalid input."""
        assert _parse_int("abc", 10) == 10
        assert _parse_int("12.5", 10) == 10
        assert _parse_int("", 10) == 10
        assert _parse_int(None, 10) == 10

    def test_parse_with_min_bound(self):
        """Should enforce minimum bounds."""
        assert _parse_int("5", 10, min_val=0) == 5
        assert _parse_int("-5", 10, min_val=0) == 10  # Below min, use default
        assert _parse_int("0", 10, min_val=0) == 0  # Exactly at min

    def test_parse_with_max_bound(self):
        """Should enforce maximum bounds."""
        assert _parse_int("5", 10, max_val=100) == 5
        assert _parse_int("150", 10, max_val=100) == 10  # Above max, use default
        assert _parse_int("100", 10, max_val=100) == 100  # Exactly at max

    def test_parse_with_both_bounds(self):
        """Should enforce both min and max bounds."""
        assert _parse_int("50", 10, min_val=0, max_val=100) == 50
        assert _parse_int("-5", 10, min_val=0, max_val=100) == 10
        assert _parse_int("150", 10, min_val=0, max_val=100) == 10


class TestConfigParsing:
    """Test Config loading with invalid environment variables."""

    def test_invalid_port_uses_default(self):
        """Should use default port when invalid value provided."""
        with patch.dict(os.environ, {"FASTAPI_API_PORT": "abc"}, clear=False):
            config = Config.load_from_env()
            assert config.fastapi_port == 8000

    def test_port_out_of_range_uses_default(self):
        """Should use default port when out of valid range."""
        with patch.dict(os.environ, {"FASTAPI_API_PORT": "99999"}, clear=False):
            config = Config.load_from_env()
            assert config.fastapi_port == 8000

        with patch.dict(os.environ, {"FASTAPI_API_PORT": "0"}, clear=False):
            config = Config.load_from_env()
            assert config.fastapi_port == 8000

    def test_invalid_audio_quality_uses_default(self):
        """Should use default audio quality when invalid."""
        with patch.dict(os.environ, {"AUDIO_QUALITY": "invalid"}, clear=False):
            config = Config.load_from_env()
            assert config.audio_quality == 4

    def test_audio_quality_out_of_range_uses_default(self):
        """Should use default when audio quality out of range (0-9)."""
        with patch.dict(os.environ, {"AUDIO_QUALITY": "15"}, clear=False):
            config = Config.load_from_env()
            assert config.audio_quality == 4

        with patch.dict(os.environ, {"AUDIO_QUALITY": "-1"}, clear=False):
            config = Config.load_from_env()
            assert config.audio_quality == 4

    def test_valid_port_is_accepted(self):
        """Should accept valid port values."""
        with patch.dict(os.environ, {"FASTAPI_API_PORT": "3000"}, clear=False):
            config = Config.load_from_env()
            assert config.fastapi_port == 3000

    def test_valid_audio_quality_is_accepted(self):
        """Should accept valid audio quality values."""
        with patch.dict(os.environ, {"AUDIO_QUALITY": "7"}, clear=False):
            config = Config.load_from_env()
            assert config.audio_quality == 7
