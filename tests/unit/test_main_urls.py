"""Tests for client-facing URL helpers in main.py."""

from unittest.mock import Mock

from main import _build_client_base_url


def _make_request(
    scheme: str = "http",
    hostname: str = "10.0.0.181",
    port: int = 8000,
    headers: dict | None = None,
) -> Mock:
    request = Mock()
    request.url.scheme = scheme
    request.url.hostname = hostname
    request.url.port = port
    request.headers = headers or {}
    return request


class TestBuildClientBaseUrl:
    """Tests for reverse-proxy aware base URL generation."""

    def test_http_with_non_default_port(self) -> None:
        """Should include port for plain HTTP on non-standard ports."""
        url = _build_client_base_url(_make_request())
        assert url == "http://10.0.0.181:8000"

    def test_https_default_port_omitted(self) -> None:
        """Should omit standard HTTPS port from the public URL."""
        url = _build_client_base_url(_make_request(scheme="https", port=443))
        assert url == "https://10.0.0.181"

    def test_honors_x_forwarded_proto_and_host(self) -> None:
        """Should trust reverse-proxy TLS headers when present."""
        request = _make_request(
            scheme="http",
            hostname="127.0.0.1",
            port=8000,
            headers={
                "x-forwarded-proto": "https",
                "x-forwarded-host": "10.0.0.181",
            },
        )
        url = _build_client_base_url(request)
        assert url == "https://10.0.0.181"
