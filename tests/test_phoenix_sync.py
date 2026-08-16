from unittest import mock

import pytest

from llm_dojo_scoring import phoenix_sync as ps


def test_phoenix_available_down():
    with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
        assert ps.phoenix_available("http://localhost:6006") is False


def test_phoenix_available_up():
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with mock.patch("urllib.request.urlopen", return_value=_Resp()):
        assert ps.phoenix_available("http://localhost:6006") is True


def test_check_phoenix_describe_down():
    with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
        status = ps.check_phoenix("http://localhost:6006")
    assert status.available is False
    assert "not reachable" in status.describe()


def test_phoenix_client_unavailable_graceful():
    with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
        client = ps.PhoenixClient("http://localhost:6006")
    assert client.ready is False
    assert client.spans() is None
    assert client.error is not None