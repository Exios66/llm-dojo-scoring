# Update awareness (DMR-095)

This opt-in application API belongs to the independent Dojo source. Consumers
import it after the source feature is reviewed, merged, and released. The
feature is available in Dojo v0.24.0; consumer pins remain operator controlled.
It does not replace the nightly all-feeder drift audit, which checks more
repositories and integration state.

`llm_dojo_scoring.update_awareness.UpdateChecker` centralizes discovery, version
comparison, cache policy, notice limits, and failure semantics. Pure package
imports, construction of a checker, scoring functions, and `dojo-version`
without `--check` never perform update HTTP or start update threads. Do not call
the checker in per-document or per-row scoring loops.

## Explicit operator command

```sh
dojo-version                              # actual loaded code's __version__
dojo-version --json
dojo-version --check                      # daily cache, then bounded HTTP if due
dojo-version --check --force --json       # ignore success/error intervals
dojo-version --check --offline --json     # cache only, no writes or HTTP
python -m llm_dojo_scoring.update_awareness --check --offline --json
```

`--force` and `--offline` are mutually exclusive and require `--check`. Exit 0
means a known update, a fresh equal/older latest release, or an intentionally
disabled checker. Exit 1 means unknown/unavailable knowledge; argparse errors
exit 2. A network error on a forced check is **unavailable**, even if a previous
cache said up to date. Never treat exit 0 as an instruction to upgrade.

JSON contains `status` (`update_available`, `up_to_date`, `unknown`,
`unavailable`, `disabled`), `installed_version`, `latest_version`, `checked_at`
(Unix seconds UTC), `stale`, `source`, `error`, `cache_persisted`, and
`release_url`. `cache_persisted` describes this operation's write, not whether
the cache directory generally works. `up_to_date` means the code is at least as
new as the observed release, not necessarily equal to it. Stale equal/older
release knowledge is `unknown`; stale evidence of a newer release remains an
`update_available` result with `stale: true`. Safe error codes replace exception
text, server bodies, private paths, and credential-bearing URLs.

## Thin application startup hook

```python
import sys

from llm_dojo_scoring.update_awareness import UpdateChecker

checker = UpdateChecker()  # construction is offline
startup = checker.startup("mailroom-pipeline")
if startup.notice:
    print(startup.notice, file=sys.stderr)  # or the application's logger
# Continue immediately. A UI/status endpoint can later read checker.cached().
```

Use stable application IDs such as `mailroom-pipeline`, `mailroom-sandbox`,
`the-mailroom`, `enron-eval`; do not include user, host, matter, or document IDs.
IDs accept ASCII alphanumeric characters, dots, underscores and hyphens (1–64
characters). Invalid IDs return an unknown result without scheduling HTTP.

Startup returns cached state immediately with an optional cached notice. When
due, one daemon **thread in the current process** warms the cache; it never
joins at process exit and creates no service or detached process. Newly fetched
knowledge appears on the next `cached()`/startup read. A short CLI can exit
before the refresh finishes, so its first uncached invocation may display no
notice. Use the explicit check when a result is required in that invocation.
`cached()` never schedules a refresh; a long-running server should call
`startup()` from its existing coarse maintenance timer about once daily if it
wants ongoing refresh, and use `cached()` in status requests. Serialize the cache-only structured
reader directly into pipeline health JSON:

```python
from dataclasses import asdict

health["dojo_update"] = asdict(checker.cached())  # no HTTP, no cache writes
```

No new permanent
timer or background service is supplied by Dojo.

A notice includes the loaded code version, the available version and the fixed
canonical URL. For example:

```text
Dojo update available: installed 0.23.1, latest 0.24.0. https://github.com/Exios66/llm-dojo-scoring/releases/latest
```

Stale/error-backed notices begin `Cached `. One consumer's notice does not
suppress another consumer's notice; markers are keyed by consumer **and**
release, for 24 hours. Persist the marker before returning a notice. If it
cannot be written, suppress the automatic notice to avoid repeated spam;
structured cached status and explicit checks remain available. At most 128
active consumer/release markers are retained; expired markers are pruned on
notice writes. Saturation suppresses additional automatic notices until a
marker expires. Use a fixed ID per application, not an ID per process.

## Discovery and privacy

The sole discovery request is an unauthenticated GET to
`https://api.github.com/repos/Exios66/llm-dojo-scoring/releases/latest`.
[GitHub's official API documentation](https://docs.github.com/en/rest/releases/releases#get-the-latest-release)
describes this public endpoint as the latest full published release, excluding
drafts and prereleases. The checker also validates both boolean flags, a past
publication timestamp and a bounded stable PEP 440 tag. It follows GitHub's
selected latest release rather than scanning all tags for the maximum version.
Pre/dev/local release tags are rejected; installed pre/dev/local versions
compare correctly through the direct `packaging>=23.2` dependency.

The loaded package's `__version__` is authoritative even when a different wheel
has installed distribution metadata, including vendor deployments. No query
parameters, installed version, consumer ID, username, home path, document data,
telemetry, tokens, or authentication headers are sent. A static User-Agent,
Accept, and API version are the only application headers. TLS uses the system
certificate trust configuration. `http.client` does not consult proxy,
`.netrc`, or credential environment variables. Redirects are rejected. Returned
URLs and release prose are ignored; only the fixed canonical release URL is
shown. Cache contents cannot select an endpoint or execute anything.

## Cache, limits and concurrency

Set `LLM_DOJO_UPDATE_CHECK=0` (also `false`, `no`, `off`, case insensitive) to
stop **all** checker HTTP and cache I/O, including `--force`. Set it before
application startup. Offline mode reads existing state without creating files.

One shared `updates-v1.json` lives in absolute `$XDG_CACHE_HOME/llm-dojo-scoring`,
otherwise `~/Library/Caches/llm-dojo-scoring` on macOS or
`~/.cache/llm-dojo-scoring` elsewhere. Relative XDG values are ignored. An
explicit local `cache_dir` can be passed to a checker, primarily for testing.
Success is reused for 24 hours. Failures back off for one hour; numeric HTTP
Retry-After hints are clamped to 1–24 hours. `--force` bypasses these intervals;
`cached()` and offline checks expose cached errors without hiding them as
no-update. Future, nonfinite, malformed, oversized, or unsupported cache state
is ignored and cannot prevent a refresh.

HTTP reads at most 128 KiB plus one sentinel byte. The cache reads/writes at most
32 KiB; reads reject nonregular files and, on POSIX, symlinks. On POSIX, new directories
use mode 0700, new temporary/cache files 0600; Windows inherits the per-user
cache directory's ACLs. Errors on read-only media,
permissions, disk-full and atomic replacement fail softly. Local filesystems
can themselves be slow: the HTTP wait budget is not a hard deadline for local
filesystem syscalls.

Writes use a short nonblocking POSIX `flock`, or Windows CRT `msvcrt.locking`
with `LK_NBLCK` on exactly one byte at offset zero of the same stable lock file,
and an atomic same-directory replacement. The lock file is never renamed,
truncated, or deleted. The CRT permits a byte range beyond EOF, so the lock file
can remain empty. Unlock uses `LK_UNLCK` on that same byte before descriptor
close. Neither adapter sleeps or retries; `LK_LOCK` (which retries) is not used.
The adapter follows the official
[Microsoft CRT documentation](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/locking?view=msvc-170)
and [Python msvcrt documentation](https://docs.python.org/3/library/msvcrt.html#msvcrt.locking). Readers see complete old or new JSON. Refresh
merges reload the cache under lock, retain notification markers recorded during
HTTP and avoid replacing a newer observation with an older request. Timestamp
zero is a real observation. On tied timestamps, a lower
release cannot replace a higher one, and a failure recorded during the request
is retained. A subsequent check that already observed that failure may recover
at the same timestamp. Equal releases may merge; a strictly later attempt can
follow a publisher moving latest back. Explicit results use the merged cache
knowledge when the lock is acquired, while an actual request failure still
reports unavailable. `cache_persisted` is false when a merge is declined.
Lock contention skips that write/notice; it never waits for another writer. No lock
is held across HTTP. Cross-process HTTP deduplication/exactly-once requests are
**not** promised: simultaneous cold starts may duplicate GETs. There is no
background lease. A process crash cannot strand a kernel file lock, but can
leave a small private temporary file; no crash-durability/fsync guarantee is
claimed. On truly unsupported platforms without either adapter, reads and checks still
work but cache persistence and automatic notices are unavailable. Windows can
refuse replacement while another process has the cache file open; that write
fails softly and leaves the previous cache intact. Shared/network filesystems
must implement the relevant OS lock and atomic-replace semantics; hostile user-controlled
parent directories are outside this cache's threat model.

One refresh thread and one active HTTP worker are allowed per process; no task
queue accumulates. Socket operations have a two-second timeout. An explicit
check waits at most three seconds for the HTTP worker, then reports unavailable.
A stuck DNS/system call cannot be cancelled by Python; its daemon worker holds
the one HTTP slot until it returns or the process exits. Later attempts report
`check_busy` without poisoning the cache or spawning more HTTP workers. Short
CLI exit never waits on these daemon threads. The response from a timed-out
worker is discarded; a later successful check must refresh the cache.

## Consumer adoption, after the source release

Keep wrappers thin: one stable consumer ID, startup rendering, and optional
status serialization. Do not copy GitHub discovery/cache code into consumers.
Pin adoption is a separate source-owned release/import unit; no auto-upgrade,
pin rewrite, scoring adjustment, or consumer dependency is part of this API.
Optional consumers should catch `ImportError` at their startup integration seam
and report Dojo unavailable, without failing an otherwise working application.


The pipeline should publish this advisory field through its existing health
HTTP API without changing operational health or scoring outcomes. The-Mailroom
must **not** import Dojo in live display or producer-contract modules: its
`mailroom_ui/pipeline_ops.py` bridge can forward the actual pipeline's
`dojo_update` field from the existing health response into `/api/pipeline` and
its UI status. Do not treat a locally installed optional eval engine as the
pipeline's installed engine. Direct checker use is appropriate only at optional
offline-eval CLI startup, with absent Dojo handled without failing display.
The inspected Corpus EDA runtime has SHA-pinned schema mirrors and no Dojo
runtime import; leave it without a new notice dependency.


Windows boundary tests inject a faithful CRT double around real temporary files
on macOS, checking offset-zero one-byte nonblocking acquisition, contention,
explicit unlock, descriptor cleanup, stable lock-file identity and real cache
persistence/notice claims. Actual Windows kernel/process execution has not been
run in this environment. POSIX concurrent-process tests still use the real OS
locking implementation.
