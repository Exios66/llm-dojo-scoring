"""Exercise Phoenix availability checks and fail-soft span retrieval with mocked clients."""

from unittest import mock

import pytest

from llm_dojo_scoring import phoenix_sync as ps


def test_phoenix_available_down():
    """Report Phoenix unavailable when its HTTP probe raises an OS error."""
    with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
        assert ps.phoenix_available("http://localhost:6006") is False


def test_phoenix_available_up():
    """Report Phoenix available when the HTTP response opens successfully."""
    class _Resp:
        """Provide a minimal successful HTTP response context manager."""
        def __enter__(self):
            """Return the fake response when entering the probe context."""
            return self

        def __exit__(self, *a):
            """Leave exceptions unsuppressed when the probe context exits."""
            return False

    with mock.patch("urllib.request.urlopen", return_value=_Resp()):
        assert ps.phoenix_available("http://localhost:6006") is True


def test_check_phoenix_describe_down():
    """Describe an unreachable Phoenix endpoint in the returned status."""
    with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
        status = ps.check_phoenix("http://localhost:6006")
    assert status.available is False
    assert "not reachable" in status.describe()


def test_phoenix_client_unavailable_graceful():
    """Keep an unreachable client unready and return no spans with an error recorded."""
    with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
        client = ps.PhoenixClient("http://localhost:6006")
    assert client.ready is False
    assert client.spans() is None
    assert client.error is not None


def test_phoenix_client_modern_spans_path():
    """Modern phoenix.client path: spans() calls get_spans_dataframe."""
    import pandas as pd

    fake = mock.Mock()
    fake.spans.get_spans_dataframe.return_value = pd.DataFrame([
        {"name": "OpenRouter Request", "span_kind": "LLM",
         "context.trace_id": "abc", "context.span_id": "def"},
    ])
    client = ps.PhoenixClient.__new__(ps.PhoenixClient)
    client.base_url = "http://localhost:6006"
    client._client = fake
    client._modern = True
    client.error = None
    spans = client.spans(project_name="default")
    assert spans is not None
    assert len(spans) == 1
    assert spans[0]["name"] == "OpenRouter Request"
    fake.spans.get_spans_dataframe.assert_called_once_with(project_name="default")


def test_phoenix_client_legacy_spans_path():
    """Legacy path: spans() calls get_spans_dataframe on the session client."""
    import pandas as pd

    fake = mock.Mock()
    fake.get_spans_dataframe.return_value = pd.DataFrame(
        [{"name": "span-a", "span_kind": "LLM"}]
    )
    client = ps.PhoenixClient.__new__(ps.PhoenixClient)
    client.base_url = "http://localhost:6006"
    client._client = fake
    client._modern = False
    client.error = None
    spans = client.spans()
    assert len(spans) == 1
    fake.get_spans_dataframe.assert_called_once_with(project_name="default")
