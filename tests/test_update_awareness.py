"""Offline release discovery, policy, filesystem, concurrency, and CLI contracts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil
import tomllib
import threading

import pytest

import llm_dojo_scoring as dojo
from llm_dojo_scoring import update_awareness as updates


NOW = 1792713600.0  # 2026-10-23 UTC; no wall-clock dependence.


def response(version="v0.24.0", **changes):
    """Construct a public release; callers can express malformed GitHub payloads."""
    data = {"tag_name": version, "draft": False, "prerelease": False,
            "published_at": "2026-10-22T00:00:00Z", "html_url": "https://evil.invalid/"}
    data.update(changes)
    return updates.ReleaseResponse(200, json.dumps(data).encode())


class FakeHTTP:
    """An injectable HTTP boundary with responses, OS errors, and blocking I/O."""

    def __init__(self, result=None):
        """Record calls and default to a published newer minor release."""
        self.result = response() if result is None else result
        self.calls = 0

    def __call__(self):
        """Return a response or raise an actual transport exception."""
        self.calls += 1
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """Fix policy inputs independently of the next release; strict tests pin real code identity."""
    monkeypatch.setattr(updates, "__version__", "0.23.1")
    clock = [NOW]
    http = FakeHTTP()
    checker = updates.UpdateChecker(tmp_path, transport=http, clock=lambda: clock[0])
    return checker, http, clock


def test_new_release_daily_cache_and_boundary(harness):
    """A successful observation is shared until exactly the next daily boundary."""
    checker, http, clock = harness
    first = checker.check()
    assert asdict(first) == {
        "status": "update_available", "installed_version": "0.23.1", "latest_version": "0.24.0",
        "checked_at": NOW, "stale": False, "source": "network", "error": None,
        "cache_persisted": True, "release_url": updates.RELEASE_URL,
    }
    another = updates.UpdateChecker(checker.cache_dir, transport=http, clock=lambda: clock[0])
    clock[0] += 86399
    assert another.check().source == "cache"
    assert http.calls == 1
    clock[0] += 1
    assert another.check().source == "network"
    assert http.calls == 2


@pytest.mark.parametrize("version,status", [
    ("v0.23.1", "up_to_date"), ("v0.23.0", "up_to_date"),
    ("v0.9.9", "up_to_date"), ("v0.100.0", "update_available"),
    ("v1.0.0", "update_available"), ("v0.23.1.post1", "update_available"),
])
def test_pep440_comparison(harness, version, status):
    """Numeric components and post releases use packaging rather than lexical order."""
    checker, http, _ = harness
    http.result = response(version)
    assert checker.check().status == status


@pytest.mark.parametrize("installed", ["0.24.0rc1", "0.24.0.dev1", "0.23.1+vendor.7"])
def test_loaded_prerelease_and_local_code_versions(harness, monkeypatch, installed):
    """Loaded PEP 440 prerelease and vendor identities compare with stable releases."""
    checker, _, _ = harness
    monkeypatch.setattr(updates, "__version__", installed)
    result = checker.check()
    assert result.installed_version == installed
    assert result.status == "update_available"


@pytest.mark.parametrize("payload", [
    response(prerelease=True), response(draft=True), response(draft=0),
    response(published_at=None), response(published_at="2026-10-24T00:00:00Z"),
    response(published_at="2026-10-22"), response("v0.24.0rc1"),
    response("v0.24.0.dev1"), response("0.24.0+private"), response("0.24.0\nwarning"),
    response("\x1b[31m0.24.0"), response("9" * 65), response("banana"),
    updates.ReleaseResponse(200, b"[]"), updates.ReleaseResponse(200, b"not json"),
    updates.ReleaseResponse(200, b"\xff"),
    updates.ReleaseResponse(200, b"[" * 2000),
    updates.ReleaseResponse(200, b" " * (updates.MAX_RESPONSE_BYTES + 1)),
])
def test_malformed_unsafe_unpublished_or_huge_response(harness, payload):
    """Invalid release knowledge fails softly and never becomes an update notice."""
    checker, http, _ = harness
    http.result = payload
    result = checker.check()
    assert (result.status, result.error, result.latest_version) == ("unavailable", "invalid_response", None)
    assert checker.startup("pipeline").notice is None
    assert http.calls == 1


@pytest.mark.parametrize("failure,error", [
    (TimeoutError("private hostname"), "network_error"), (OSError("private path"), "network_error"),
    (RuntimeError("secret token"), "transport_error"),
    (updates.ReleaseResponse(401, b"secret body"), "http_error"),
    (updates.ReleaseResponse(404, b"missing"), "http_error"),
    (updates.ReleaseResponse(500, b"server"), "http_error"),
    (updates.ReleaseResponse(301, b"", "10"), "http_error"),
    (updates.ReleaseResponse(403, b"rate limit"), "rate_limited"),
    (updates.ReleaseResponse(429, b"slow down"), "rate_limited"),
])
def test_errors_are_cached_and_categorical(harness, failure, error):
    """No raw exception, URL, path, or server body is persisted or displayed."""
    checker, http, clock = harness
    http.result = failure
    result = checker.check()
    assert (result.status, result.error) == ("unavailable", error)
    clock[0] += 3599
    assert checker.check().status == "unavailable"
    assert http.calls == 1
    clock[0] += 1
    assert checker.check().source == "network"
    assert http.calls == 2
    assert "secret" not in (checker.cache_dir / "updates-v1.json").read_text()


@pytest.mark.parametrize("retry,delay", [("7200", 7200), ("9999999999", 86400),
                                       ("-1", 3600), ("oops", 3600), ("0", 3600)])
def test_rate_limit_retry_after_is_bounded(harness, retry, delay):
    """Retry hints can lengthen, never shorten or indefinitely extend, error backoff."""
    checker, http, clock = harness
    http.result = updates.ReleaseResponse(429, b"", retry)
    assert checker.check().error == "rate_limited"
    clock[0] += delay - 1
    checker.check()
    assert http.calls == 1
    clock[0] += 1
    checker.check()
    assert http.calls == 2


def test_force_bypasses_backoff_but_failures_are_not_up_to_date(harness):
    """An explicit failed refresh reports unavailable even with an equal cached release."""
    checker, http, _ = harness
    http.result = response("v0.23.1")
    assert checker.check().status == "up_to_date"
    http.result = OSError("offline")
    result = checker.check(force=True)
    assert (result.status, result.latest_version, result.error) == ("unavailable", "0.23.1", "network_error")
    assert checker.check().status == "unavailable"
    http.result = response()
    assert checker.check(force=True).status == "update_available"
    assert http.calls == 3


def test_offline_unknown_stale_and_positive_knowledge(harness):
    """Stale equality cannot promise currentness; a cached newer release remains useful."""
    checker, http, clock = harness
    assert checker.check(offline=True).status == "unknown"
    assert not list(checker.cache_dir.iterdir())
    http.result = response("v0.23.1")
    checker.check()
    clock[0] += updates.CHECK_INTERVAL
    result = checker.check(offline=True)
    assert (result.status, result.stale) == ("unknown", True)
    http.result = response()
    checker.check()
    clock[0] += updates.CHECK_INTERVAL
    result = checker.check(offline=True)
    assert (result.status, result.stale) == ("update_available", True)
    assert http.calls == 2
    with pytest.raises(ValueError, match="mutually exclusive"):
        checker.check(force=True, offline=True)


@pytest.mark.parametrize("value", ["0", "false", "OFF", " no "])
def test_opt_out_does_no_io_even_force(harness, monkeypatch, value):
    """Disabled startup and explicit checks do not read or create the user cache."""
    checker, http, _ = harness
    monkeypatch.setenv("LLM_DOJO_UPDATE_CHECK", value)
    assert checker.check(force=True).status == "disabled"
    assert checker.cached().status == "disabled"
    assert checker.startup("pipeline").update.status == "disabled"
    assert list(checker.cache_dir.iterdir()) == []
    assert http.calls == 0


@pytest.mark.parametrize("payload", [b"bad json", b"\xff", b"[]", b"[" * 2000,
    b" " * (updates.MAX_CACHE_BYTES + 1),
    b'{"schema":1,"latest":"0.24.0\\nwarning","checked_at":1,"attempted_at":1}',
    b'{"schema":1,"latest":"0.24.0","checked_at":NaN,"attempted_at":1}',
    b'{"schema":1,"latest":"0.24.0","checked_at":1,"attempted_at":Infinity}',
    b'{"schema":1,"latest":"0.24.0","checked_at":true,"attempted_at":1}',
    b'{"schema":1,"latest":"0.24.0","checked_at":9999999999,"attempted_at":9999999999}',
    b'{"schema":1,"attempted_at":1,"error":"rate_limited","retry_at":9999999999}',
    b'{"schema":1,"attempted_at":1,"error":[]}',
])
def test_corrupt_oversized_future_cache_is_refreshable(harness, payload):
    """Untrusted cache values cannot suppress refreshes or inject notices."""
    checker, http, _ = harness
    (checker.cache_dir / "updates-v1.json").write_bytes(payload)
    assert checker.cached().status == "unknown"
    assert checker.check().status == "update_available"
    assert http.calls == 1


def test_cache_failure_remains_successful_network_knowledge(harness, monkeypatch):
    """Unwritable cache directories cannot turn a valid explicit observation into failure."""
    checker, _, _ = harness

    def denied(*args, **kwargs):
        """Represent read-only media regardless of the test process's permissions."""
        raise PermissionError("read only")

    monkeypatch.setattr(Path, "mkdir", denied)
    result = checker.check()
    assert (result.status, result.cache_persisted) == ("update_available", False)


def test_atomic_replace_failure_keeps_previous_cache(harness, monkeypatch):
    """Disk errors cannot leave truncated JSON or abandoned temporary files."""
    checker, http, _ = harness
    checker.check()
    before = (checker.cache_dir / "updates-v1.json").read_bytes()
    http.result = response("v0.25.0")

    def denied(*args):
        """Represent a full or read-only destination during atomic replacement."""
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", denied)
    result = checker.check(force=True)
    assert result.latest_version == "0.25.0"
    assert result.cache_persisted is False
    assert (checker.cache_dir / "updates-v1.json").read_bytes() == before
    assert not list(checker.cache_dir.glob(".updates-*"))


@pytest.mark.skipif(os.name != "posix", reason="POSIX special files; Windows CRT boundary covered separately")
def test_cache_symlink_and_fifo_are_not_followed_or_blocked(harness, tmp_path):
    """Unsafe special cache files are treated as empty without blocking startup."""
    checker, _, _ = harness
    outside = tmp_path / "private"
    outside.write_text("private")
    cache = checker.cache_dir / "updates-v1.json"
    cache.symlink_to(outside)
    assert checker.cached().status == "unknown"
    cache.unlink()
    os.mkfifo(cache)
    assert checker.cached().status == "unknown"
    assert checker.check().status == "update_available"
    assert outside.read_text() == "private"


def test_notice_daily_per_consumer_and_per_release(harness):
    """One consumer's persisted notice never suppresses another or a newer release."""
    checker, http, clock = harness
    checker.check()
    expected = f"Dojo update available: installed 0.23.1, latest 0.24.0. {updates.RELEASE_URL}"
    assert checker.startup("pipeline").notice == expected
    assert checker.startup("pipeline").notice is None
    assert checker.startup("sandbox").notice == expected
    assert checker.startup("visualizer").notice == expected
    clock[0] += updates.NOTICE_INTERVAL
    checker.check(force=True)
    assert checker.startup("pipeline").notice == expected
    http.result = response("v0.25.0")
    checker.check(force=True)
    assert "latest 0.25.0" in checker.startup("pipeline").notice
    assert "evil.invalid" not in expected
    # A publisher moving latest back cannot repeat an already claimed pair.
    http.result = response("v0.24.0")
    checker.check(force=True)
    assert checker.startup("pipeline").notice is None


def test_invalid_consumer_and_future_notice_do_not_hide_updates(harness):
    """Unsafe consumer text is refused and future notification markers are ignored."""
    checker, http, _ = harness
    assert checker.startup("pipeline\nwarning").update.error == "invalid_consumer"
    assert http.calls == 0
    checker.check()
    cache = checker.cache_dir / "updates-v1.json"
    data = json.loads(cache.read_text())
    data["notices"] = {"pipeline@0.24.0": NOW + 100}
    cache.write_text(json.dumps(data))
    assert checker.startup("pipeline").notice is not None


def test_cached_notice_has_stale_label_during_error_backoff(harness):
    """A known update remains explainable when the most recent request failed."""
    checker, http, clock = harness
    checker.check()
    clock[0] += updates.CHECK_INTERVAL
    http.result = TimeoutError()
    checker.check()
    result = checker.startup("pipeline")
    assert result.update.status == "unavailable"
    assert result.notice.startswith("Cached Dojo update available: installed 0.23.1, latest 0.24.0")
    assert result.refresh_scheduled is False


def test_startup_returns_before_transport_and_later_cache_is_visible(harness):
    """Cold startup never waits for network and long-lived consumers can read the result."""
    checker, _, _ = harness
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def blocking():
        """Hold the honest HTTP boundary until startup has already returned."""
        entered.set()
        assert release.wait(2)
        return response()

    class ObservedChecker(updates.UpdateChecker):
        """Signal after the real background cache write without polling sleeps."""

        def check(self, **kwargs):
            """Run the product check and expose its completion to the test."""
            try:
                return super().check(**kwargs)
            finally:
                finished.set()

    checker = ObservedChecker(checker.cache_dir, transport=blocking, clock=lambda: NOW)
    try:
        result = checker.startup("pipeline")
        assert (result.update.status, result.notice, result.refresh_scheduled) == ("unknown", None, True)
        assert entered.wait(1)
        assert not finished.is_set()
        assert checker.startup("sandbox").refresh_scheduled is False
    finally:
        release.set()
    assert finished.wait(2)
    assert checker.cached().latest_version == "0.24.0"
    assert updates._REFRESH_LOCK.acquire(timeout=2)
    updates._REFRESH_LOCK.release()


def test_wait_budget_and_single_transport_slot(harness, monkeypatch):
    """A hung DNS/HTTP worker cannot hold explicit callers or multiply unboundedly."""
    checker, _, _ = harness
    entered, release = threading.Event(), threading.Event()

    def blocking():
        """Simulate an uncancellable system call, released in test cleanup."""
        entered.set()
        assert release.wait(2)
        return response()

    checker._transport = blocking
    monkeypatch.setattr(updates, "CHECK_TIMEOUT", 0.03)
    try:
        first = checker.check()
        assert entered.is_set()
        assert (first.status, first.error) == ("unavailable", "check_timeout")
        assert checker.check(force=True).error == "check_busy"
    finally:
        release.set()
    assert updates._TRANSPORT_LOCK.acquire(timeout=2)
    updates._TRANSPORT_LOCK.release()


def test_concurrent_process_notice_claims_and_merge(harness):
    """Independent strict processes deduplicate a consumer and preserve other markers."""
    import numpy

    checker, _, _ = harness
    checker.check()
    site = Path(numpy.__file__).resolve().parents[1]
    root = Path(__file__).resolve().parents[1]
    program = '''
"""Claim a real file-locked notice with strict source-only imports."""
import sys, pathlib, json
sys.path[:0] = [sys.argv[1], sys.argv[2]]
from llm_dojo_scoring import update_awareness as u
u.__version__ = "0.23.1"  # fixed installed-code input for concurrent notice policy
checker = u.UpdateChecker(pathlib.Path(sys.argv[3]), clock=lambda: 1792713600.0)
print(json.dumps(checker.startup("pipeline").notice))
'''
    processes = [subprocess.Popen([sys.executable, "-I", "-S", "-B", "-c", program,
                                   str(root), str(site), str(checker.cache_dir)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for _ in range(5)]
    notices = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=20)
        assert process.returncode == 0, stderr
        notices.append(json.loads(stdout))
    assert sum(item is not None for item in notices) == 1
    assert checker.startup("sandbox").notice is not None
    data = json.loads((checker.cache_dir / "updates-v1.json").read_text())
    assert set(data["notices"]) == {"pipeline@0.24.0", "sandbox@0.24.0"}
    if os.name == "posix":
        assert (checker.cache_dir / "updates-v1.json").stat().st_mode & 0o777 == 0o600


def test_refresh_merge_preserves_notice_written_during_http(harness):
    """A response cannot overwrite a notification recorded while no HTTP lock was held."""
    checker, _, clock = harness
    checker.check()
    entered, release = threading.Event(), threading.Event()

    def blocking():
        """Delay the response while a second checker modifies cache metadata."""
        entered.set()
        assert release.wait(2)
        return response()

    checker._transport = blocking
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(checker.check, force=True)
        try:
            assert entered.wait(1)
            assert checker.startup("pipeline").notice is not None
        finally:
            release.set()
        assert future.result(timeout=2).latest_version == "0.24.0"
    assert checker.startup("pipeline").notice is None


def test_fixed_direct_http_request_has_no_auth_identity_or_redirect(harness, monkeypatch):
    """Execute the default transport against a local connection double, inspecting its request."""
    calls = []

    class FakeResponse:
        """Record the production read limit and return a plausible GitHub response."""

        status = 200

        def read(self, limit):
            """Enforce a bounded read instead of an unlimited response drain."""
            calls.append(("read", limit))
            return response().body

        def getheader(self, name):
            """Offer no retry hint on a successful response."""
            assert name == "Retry-After"
            return None

    class FakeConnection:
        """Emulate http.client without touching sockets or real providers."""

        def __init__(self, host, timeout):
            """Record the fixed destination and timeout."""
            calls.append(("connect", host, timeout))

        def request(self, method, path, headers):
            """Record exactly what would leave the machine."""
            calls.append(("request", method, path, headers))

        def getresponse(self):
            """Return the bounded body double."""
            return FakeResponse()

        def close(self):
            """Record deterministic connection cleanup."""
            calls.append(("close",))

    monkeypatch.setenv("GITHUB_TOKEN", "must-not-leave")
    monkeypatch.setenv("HTTPS_PROXY", "https://must-not-use.invalid")
    monkeypatch.setattr(updates.http.client, "HTTPSConnection", FakeConnection)
    assert updates._http_transport().status == 200
    assert calls[0] == ("connect", "api.github.com", 2.0)
    assert calls[1] == ("request", "GET", "/repos/Exios66/llm-dojo-scoring/releases/latest", {
        "Accept": "application/vnd.github+json", "User-Agent": "llm-dojo-scoring-update-check",
        "X-GitHub-Api-Version": "2026-03-10",
    })
    assert calls[2:] == [("read", 131073), ("close",)]


def test_cli_executes_product_with_fake_http_and_json(harness, monkeypatch, capsys):
    """Exercise parsing, the real checker, JSON output, and the explicit error exit contract."""
    checker, http, _ = harness
    config = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    assert config["project"]["scripts"]["dojo-version"] == "llm_dojo_scoring.update_awareness:main"
    monkeypatch.setattr(updates, "_default_cache_dir", lambda: checker.cache_dir)
    monkeypatch.setattr(updates, "_http_transport", http)
    monkeypatch.setattr(updates.time, "time", lambda: NOW)
    assert updates.main(["--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"installed_version": "0.23.1"}
    assert http.calls == 0
    assert updates.main(["--check", "--offline", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "unknown"
    assert updates.main(["--check", "--force", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "update_available"
    assert payload["release_url"] == updates.RELEASE_URL
    http.result = TimeoutError()
    assert updates.main(["--check", "--force", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "unavailable"
    with pytest.raises(SystemExit, match="2"):
        updates.main(["--check", "--force", "--offline"])


@pytest.mark.parametrize("vendored", [False, True])
def test_strict_source_import_scoring_and_cli_do_not_network(tmp_path, vendored):
    """Fresh isolated execution rejects sockets, ignores installed metadata, and proves code origins."""
    import numpy

    root = Path(__file__).resolve().parents[1]
    expected_version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    site = Path(numpy.__file__).resolve().parents[1]
    if vendored:
        vendor = tmp_path / "vendor" / "llm-dojo-scoring" / "src"
        shutil.copytree(root / "llm_dojo_scoring", vendor / "llm_dojo_scoring")
        root = vendor
    program = '''
"""Strict no-network runtime for vendored/source update-awareness identity."""
import sys, pathlib, socket, importlib.metadata, json
sys.path[:0] = [sys.argv[1], sys.argv[2]]
attempts = []
def deny(event, args):
    """Record even a caught network attempt, so silent fallback cannot pass."""
    if event in {"socket.connect", "socket.getaddrinfo"}:
        attempts.append(event)
        raise OSError("network forbidden")
sys.addaudithook(deny)
def unrelated(name):
    """Simulate a different installed wheel next to vendored code."""
    return "99.9.9"
importlib.metadata.version = unrelated
import llm_dojo_scoring as dojo
from llm_dojo_scoring import update_awareness as u
assert pathlib.Path(dojo.__file__).is_relative_to(pathlib.Path(sys.argv[1]))
assert pathlib.Path(u.__file__).is_relative_to(pathlib.Path(sys.argv[1]))
assert dojo.__version__ == sys.argv[4]
assert dojo.accuracy(["a", "b", "b"], ["a", "a", "b"]) == 0.6667
assert dojo.score_transcription("a b", "a c")["wer"] == 0.5
assert u.UpdateChecker(pathlib.Path(sys.argv[3])).check(offline=True).installed_version == sys.argv[4]
assert u.main(["--json"]) == 0
assert not attempts, attempts
assert not pathlib.Path(sys.argv[3]).exists()
print(json.dumps({"dojo":dojo.__file__, "updates":u.__file__, "network_attempts":attempts}))
'''
    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", program,
                             str(root), str(site), str(tmp_path / "never-created"), expected_version],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.splitlines()[-1])["network_attempts"] == []


def test_slow_process_cannot_erase_newer_release(harness):
    """A late response merges under lock and respects a newer independent observation."""
    import numpy

    checker, http, clock = harness
    site = Path(numpy.__file__).resolve().parents[1]
    root = Path(__file__).resolve().parents[1]
    program = '''
"""Block an older fake request while another process saves a newer release."""
import sys, pathlib, json
sys.path[:0] = [sys.argv[1], sys.argv[2]]
from llm_dojo_scoring.update_awareness import UpdateChecker, ReleaseResponse
moments = iter([1792713600.0, 1792713602.0])
def transport():
    """Coordinate without sockets and return the earlier stable release."""
    print("entered", flush=True)
    assert sys.stdin.readline().strip() == "release"
    return ReleaseResponse(200, json.dumps({"tag_name":"v0.24.0", "draft":False,
        "prerelease":False,"published_at":"2026-10-22T00:00:00Z"}).encode())
checker = UpdateChecker(pathlib.Path(sys.argv[3]), transport=transport, clock=lambda: next(moments))
assert checker.check(force=True).latest_version == "0.25.0"
'''
    child = subprocess.Popen([sys.executable, "-I", "-S", "-B", "-c", program,
                               str(root), str(site), str(checker.cache_dir)],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "entered"
        clock[0] += 1
        http.result = response("v0.25.0")
        assert checker.check(force=True).latest_version == "0.25.0"
        assert checker.startup("sandbox").notice is not None
    finally:
        stdout, stderr = child.communicate("release\n", timeout=20)
    assert child.returncode == 0, stdout + stderr
    assert checker.cached().latest_version == "0.25.0"
    assert checker.startup("sandbox").notice is None


@pytest.mark.skipif(os.name != "posix", reason="POSIX flock contention; Windows CRT contention covered separately")
def test_held_cache_lock_never_blocks_startup(harness):
    """A competing process's short write lock suppresses a notice, never the caller."""
    import fcntl

    checker, _, _ = harness
    checker.check()
    fd = os.open(checker.cache_dir / "updates-v1.lock", os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = checker.startup("pipeline")
        assert (result.update.status, result.notice) == ("update_available", None)
    finally:
        os.close(fd)
    assert checker.startup("pipeline").notice is not None


def test_worker_start_errors_fail_softly(harness, monkeypatch):
    """Resource exhaustion cannot turn startup refresh into an application failure."""
    checker, http, _ = harness

    def unavailable(*args, **kwargs):
        """Represent the runtime refusing to create another thread."""
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", unavailable)
    assert checker.startup("pipeline").refresh_scheduled is False
    result = checker.check()
    assert (result.status, result.error) == ("unavailable", "worker_unavailable")
    assert http.calls == 0
    assert not updates._TRANSPORT_LOCK.locked()
    assert not updates._REFRESH_LOCK.locked()


def test_shared_xdg_cache_and_invalid_relative_override(monkeypatch, tmp_path):
    """All consumers resolve the same per-user location without creating it at import."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    first, second = updates.UpdateChecker(), updates.UpdateChecker()
    assert first.cache_dir == second.cache_dir == tmp_path / "llm-dojo-scoring"
    assert not first.cache_dir.exists()
    monkeypatch.setenv("XDG_CACHE_HOME", "relative-directory")
    assert updates.UpdateChecker().cache_dir.is_absolute()


def test_cache_notices_are_bounded_and_expire(harness):
    """A finite set of active claims cannot grow files indefinitely or permanently suppress newcomers."""
    checker, _, clock = harness
    checker.check()
    for index in range(updates.MAX_NOTICES):
        assert checker.startup(f"consumer-{index}").notice is not None
    assert checker.startup("new-consumer").notice is None
    assert (checker.cache_dir / "updates-v1.json").stat().st_size <= updates.MAX_CACHE_BYTES
    clock[0] += updates.NOTICE_INTERVAL
    checker.check(force=True)
    assert checker.startup("new-consumer").notice is not None
    data = json.loads((checker.cache_dir / "updates-v1.json").read_text())
    assert set(data["notices"]) == {"new-consumer@0.24.0"}


def test_startup_cannot_erase_observation_saved_just_before_lock(harness, monkeypatch):
    """An intervening real write survives startup's earlier cached status snapshot."""
    checker, http, clock = harness
    checker.check()
    original_open = os.open
    intervened = [False]

    def intercept(path, flags, mode=0o777, *, dir_fd=None):
        """Delay the lock-file open until an independent checker has saved newer state."""
        if Path(path).name == "updates-v1.lock" and not intervened[0]:
            intervened[0] = True
            clock[0] += 1
            http.result = response("v0.25.0")
            other = updates.UpdateChecker(checker.cache_dir, transport=http, clock=lambda: clock[0])
            assert other.check(force=True).latest_version == "0.25.0"
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", intercept)
    initial = checker.startup("pipeline")
    assert initial.update.latest_version == "0.24.0"
    assert checker.cached().latest_version == "0.25.0"
    assert "latest 0.25.0" in checker.startup("sandbox").notice


def test_process_exit_never_joins_background_http(harness, tmp_path):
    """A short CLI exits while its fake HTTP worker is still blocked, with no exit handler wait."""
    import numpy

    checker, _, _ = harness
    site = Path(numpy.__file__).resolve().parents[1]
    root = Path(__file__).resolve().parents[1]
    program = '''
"""Exit with a live daemon HTTP worker and no real network use."""
import sys, pathlib, threading
sys.path[:0] = [sys.argv[1], sys.argv[2]]
from llm_dojo_scoring.update_awareness import UpdateChecker, ReleaseResponse
entered = threading.Event()
def transport():
    """Remain blocked beyond the subprocess test timeout unless process exit drops us."""
    entered.set()
    threading.Event().wait(30)
    return ReleaseResponse(500, b"")
checker = UpdateChecker(pathlib.Path(sys.argv[3]), transport=transport)
assert checker.startup("short-cli").refresh_scheduled
assert entered.wait(2)
print("exiting with active HTTP worker")
'''
    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", program,
                             str(root), str(site), str(checker.cache_dir)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "exiting with active HTTP worker"


def test_health_status_reader_is_cache_only_even_when_stale(harness):
    """Repeated health reads return serializable knowledge without writes, claims, or HTTP."""
    checker, http, clock = harness
    assert asdict(checker.cached())["status"] == "unknown"
    assert http.calls == 0
    checker.check()
    cache = checker.cache_dir / "updates-v1.json"
    before, modified = cache.read_bytes(), cache.stat().st_mtime_ns
    clock[0] += updates.CHECK_INTERVAL
    http.result = TimeoutError("status must not call transport")
    for _ in range(3):
        payload = json.loads(json.dumps(asdict(checker.cached())))
        assert (payload["status"], payload["latest_version"], payload["stale"]) == ("update_available", "0.24.0", True)
    assert http.calls == 1
    assert cache.read_bytes() == before
    assert cache.stat().st_mtime_ns == modified


class FakeCRT:
    """Model the documented CRT byte-range contract over real temporary descriptors."""

    LK_NBLCK = 2
    LK_UNLCK = 0

    def __init__(self, *, fail_unlock=False):
        """Track active byte claims and optionally simulate unlock failure."""
        self.active = {}
        self.calls = []
        self.fail_unlock = fail_unlock

    def locking(self, fd, mode, count):
        """Honor current offsets, overlapping contention, and explicit matched unlocks."""
        info = os.fstat(fd)
        offset = os.lseek(fd, 0, os.SEEK_CUR)
        self.calls.append((fd, mode, offset, count))
        assert (offset, count) == (0, 1)
        key = (info.st_dev, info.st_ino, offset, count)
        if mode == self.LK_NBLCK:
            if key in self.active:
                raise PermissionError("CRT EACCES: overlapping region")
            self.active[key] = fd
        elif mode == self.LK_UNLCK:
            if self.fail_unlock:
                raise OSError("CRT unlock failure")
            assert self.active.pop(key) == fd
        else:
            pytest.fail("blocking/retrying CRT mode requested")


@pytest.fixture
def windows_crt(monkeypatch):
    """Inject only the Windows API boundary; filesystem operations remain real."""
    crt = FakeCRT()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "msvcrt", crt)
    # Windows lacks this POSIX flag; reads and lock opens must tolerate that.
    monkeypatch.delattr(os, "O_NONBLOCK", raising=False)
    return crt


def test_windows_adapter_persists_cache_and_notices(harness, windows_crt):
    """Real JSON replacement works through CRT locking without replacing the lock file."""
    checker, http, _ = harness
    assert checker.check().cache_persisted is True
    lock = checker.cache_dir / "updates-v1.lock"
    identity = (lock.stat().st_dev, lock.stat().st_ino)
    assert lock.read_bytes() == b""  # CRT explicitly permits a byte beyond EOF.
    assert checker.startup("pipeline").notice is not None
    assert checker.startup("pipeline").notice is None
    assert checker.startup("sandbox").notice is not None
    assert checker.cached().latest_version == "0.24.0"
    assert http.calls == 1
    assert (lock.stat().st_dev, lock.stat().st_ino) == identity
    assert windows_crt.active == {}
    assert [call[1] for call in windows_crt.calls] == [2, 0, 2, 0, 2, 0, 2, 0]
    for fd, _, _, _ in windows_crt.calls:
        with pytest.raises(OSError):
            os.fstat(fd)


def test_windows_adapter_contention_is_one_immediate_attempt(harness, windows_crt):
    """A real second descriptor collides on the same byte without sleeping or retrying."""
    checker, _, _ = harness
    with checker._lock() as first:
        assert first is True
        first_fd = windows_crt.calls[-1][0]
        with checker._lock() as second:
            assert second is False
        assert [call[1] for call in windows_crt.calls] == [2, 2]
        denied_fd = windows_crt.calls[-1][0]
        with pytest.raises(OSError):
            os.fstat(denied_fd)
        assert os.fstat(first_fd).st_size == 0
    assert [call[1] for call in windows_crt.calls] == [2, 2, 0]
    assert windows_crt.active == {}
    with pytest.raises(OSError):
        os.fstat(first_fd)


def test_windows_unlock_error_still_closes_descriptor(harness, windows_crt):
    """Even CRT unlock errors cannot leak descriptors or break caller startup."""
    checker, _, _ = harness
    windows_crt.fail_unlock = True
    with checker._lock() as locked:
        assert locked is True
        fd = windows_crt.calls[-1][0]
    assert [call[1] for call in windows_crt.calls] == [2, 0]
    with pytest.raises(OSError):
        os.fstat(fd)


@pytest.mark.parametrize("at", [0.0, NOW])
@pytest.mark.parametrize("incoming,current,advance,latest,error,persisted", [
    ("v0.24.0", "v0.25.0", 0, "0.25.0", None, False),
    ("v0.100.0", "v0.25.0", 0, "0.100.0", None, True),
    ("v0.25.0", "v0.25.0", 0, "0.25.0", None, True),
    ("v0.24.0", "v0.25.0", 1, "0.25.0", None, False),
    ("v0.24.0", "failure", 1, "0.23.1", "rate_limited", False),
    ("v0.24.0", "failure", 0, "0.23.1", "rate_limited", False),
    ("failure", "v0.25.0", 0, "0.25.0", "http_error", True),
    ("failure", "v0.25.0", 1, "0.25.0", "http_error", False),
    ("failure", "failure", 0, "0.23.1", "http_error", False),
])
def test_concurrent_attempt_merge_and_returned_knowledge(
        harness, at, incoming, current, advance, latest, error, persisted):
    """Order real processes by pipes; tied clocks must not regress release knowledge."""
    import numpy

    checker, http, clock = harness
    clock[0] = at
    http.result = response("v0.23.1", published_at="1970-01-01T00:00:00Z")
    assert checker.check().cache_persisted
    root = Path(__file__).resolve().parents[1]
    site = Path(numpy.__file__).resolve().parents[1]
    program = '''
"""Pause a real checker at the transport boundary while the parent writes."""
import sys, pathlib, json
from dataclasses import asdict
sys.path[:0] = [sys.argv[1], sys.argv[2]]
from llm_dojo_scoring import update_awareness as u
u.__version__ = "0.23.1"
u.CHECK_TIMEOUT = 30  # Protocol deadlines, not sleeps, control this test.
at, finished = float(sys.argv[4]), float(sys.argv[5])
moments = iter([at, finished])
def transport():
    """Report entry and wait for the independent check and notice writes."""
    print("entered", flush=True)
    assert sys.stdin.readline().strip() == "release"
    if sys.argv[6] == "failure":
        return u.ReleaseResponse(500, b"")
    return u.ReleaseResponse(200, json.dumps({"tag_name":sys.argv[6],
        "draft":False, "prerelease":False,
        "published_at":"1970-01-01T00:00:00Z"}).encode())
checker = u.UpdateChecker(pathlib.Path(sys.argv[3]), transport=transport,
                          clock=lambda: next(moments))
print(json.dumps(asdict(checker.check(force=True))), flush=True)
'''
    child = subprocess.Popen([sys.executable, "-I", "-S", "-B", "-c", program,
                              str(root), str(site), str(checker.cache_dir),
                              str(at), str(at + advance), incoming], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "entered"
        clock[0] += advance
        http.result = (updates.ReleaseResponse(429, b"", "7200") if current == "failure"
                       else response(current, published_at="1970-01-01T00:00:00Z"))
        assert checker.check(force=True).cache_persisted
        if current != "failure":
            assert checker.startup("sandbox").notice is not None
            assert checker.startup("pipeline").notice is not None
        cache = checker.cache_dir / "updates-v1.json"
        before = cache.read_bytes()
        before_data = json.loads(before)
    finally:
        stdout, stderr = child.communicate("release\n", timeout=40)
    assert child.returncode == 0, stdout + stderr
    result = json.loads(stdout)
    after = json.loads(cache.read_bytes())
    assert after["latest"] == latest
    assert result["latest_version"] == latest
    assert result["checked_at"] == after["checked_at"]
    assert result["status"] == ("unavailable" if error else "update_available")
    assert result["error"] == error
    assert result["cache_persisted"] is persisted
    assert result["stale"] is False
    assert after["notices"] == before_data["notices"]
    if persisted:
        assert after["attempted_at"] == at
        assert after["error"] == error
        assert after["retry_at"] == (at + 3600 if error else None)
    else:
        assert cache.read_bytes() == before
    assert checker.cached().latest_version == latest
    if current != "failure":
        # Retain the already claimed pairs even when a higher release wins.
        assert set(after["notices"]) == {"sandbox@0.25.0", "pipeline@0.25.0"}
        if latest == "0.25.0":
            assert checker.startup("sandbox").notice is None
    else:
        assert after["error"] == "rate_limited"
        assert after["retry_at"] == at + advance + 7200
        assert checker.check().source == "cache"
        assert http.calls == 2


@pytest.mark.parametrize("at", [0.0, NOW])
def test_same_time_sequential_failure_recovery_and_newer_rollback(harness, at):
    """Tie protection retains forced errors/recovery and later publisher rollback."""
    checker, http, clock = harness
    clock[0] = at
    http.result = response("v0.25.0", published_at="1970-01-01T00:00:00Z")
    assert checker.check().cache_persisted
    http.result = updates.ReleaseResponse(429, b"", "7200")
    assert checker.check(force=True).error == "rate_limited"
    assert checker.cached().error == "rate_limited"
    http.result = response("v0.25.0", published_at="1970-01-01T00:00:00Z")
    result = checker.check(force=True)
    assert (result.status, result.error, result.cache_persisted) == ("update_available", None, True)
    assert checker.cached().error is None
    clock[0] += 1
    http.result = response("v0.24.0", published_at="1970-01-01T00:00:00Z")
    result = checker.check(force=True)
    assert (result.latest_version, result.cache_persisted) == ("0.24.0", True)
    assert checker.cached().latest_version == "0.24.0"


def test_busy_attempt_leaves_success_and_backoff_untouched(harness):
    """Busy is local availability, never a new persisted failed observation."""
    checker, http, _ = harness
    checker.check()
    for result in (response(), updates.ReleaseResponse(429, b"", "7200")):
        http.result = result
        checker.check(force=True)
        cache = checker.cache_dir / "updates-v1.json"
        before = cache.read_bytes()
        calls = http.calls
        assert updates._TRANSPORT_LOCK.acquire(blocking=False)
        try:
            busy = checker.check(force=True)
        finally:
            updates._TRANSPORT_LOCK.release()
        assert (busy.status, busy.error, busy.cache_persisted) == ("unavailable", "check_busy", False)
        assert busy.latest_version == "0.24.0"
        assert cache.read_bytes() == before
        assert http.calls == calls


def test_documented_startup_example_executes_notice_branch(harness, monkeypatch, capsys):
    """Execute the actual fenced example with fresh globals and a real cached notice."""
    checker, _, _ = harness
    # Seed with the constructor's real clock; the example itself is unmodified.
    updates.UpdateChecker(checker.cache_dir, transport=FakeHTTP()).check()
    monkeypatch.setattr(updates, "_default_cache_dir", lambda: checker.cache_dir)
    doc = Path(__file__).resolve().parents[1] / "docs/UPDATE_AWARENESS.md"
    example = doc.read_text().split("## Thin application startup hook", 1)[1]
    example = example.split("```python\n", 1)[1].split("```", 1)[0]
    namespace = {}
    exec(compile(example, str(doc), "exec"), namespace)
    assert namespace["startup"].refresh_scheduled is False
    assert namespace["startup"].update.latest_version == "0.24.0"
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ("Dojo update available: installed 0.23.1, latest 0.24.0. "
                            + updates.RELEASE_URL + "\n")
