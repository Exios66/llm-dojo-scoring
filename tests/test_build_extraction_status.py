"""``scripts/build_extraction_status.py``: Hub download, argument rules, vocabulary counts.

Network-free: the Hub is replaced by a stubbed opener, and ``build`` runs on
synthetic rows, so neither pyarrow nor the Hub is needed.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest

from conftest import load_script

COMMIT = "ccd040f6a1b6b414bdefd161cdc622b68f6dacf8"
_BASE = "https://huggingface.co"


class _Response(io.BytesIO):
    """A urllib-style response: a readable context manager."""

    def __enter__(self) -> _Response:
        """Return the response itself."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Close the stream."""
        self.close()


class _Hub:
    """A stubbed opener serving a tree listing and the shard bytes."""

    def __init__(self, shards: dict[str, bytes], *, bad_oid: bool = False) -> None:
        """Record the shards (path -> bytes) and the URLs requested."""
        self.shards = shards
        self.bad_oid = bad_oid
        self.urls: list[str] = []
        self.user_agents: list[str] = []

    def __call__(self, request, timeout=None) -> _Response:
        """Answer a tree-listing or a resolve request."""
        url = request.full_url
        self.urls.append(url)
        self.user_agents.append(request.get_header("User-agent") or "")
        tree = f"{_BASE}/api/datasets/Lucius-Morningstar/mailroom-dataset/tree/{COMMIT}/"
        if url.startswith(tree):
            prefix = url[len(tree):] + "/"
            entries = [
                {
                    "type": "file",
                    "path": path,
                    "size": len(data),
                    "lfs": {
                        "oid": "0" * 64 if self.bad_oid else hashlib.sha256(data).hexdigest(),
                        "size": len(data),
                    },
                }
                for path, data in sorted(self.shards.items())
                if path.startswith(prefix) and "/" not in path[len(prefix):]
            ]
            return _Response(json.dumps(entries).encode())
        resolve = f"{_BASE}/datasets/Lucius-Morningstar/mailroom-dataset/resolve/{COMMIT}/"
        assert url.startswith(resolve), url
        return _Response(self.shards[url[len(resolve):]])


_SHARDS = {
    "parquet/ground_truth/train/train-00000-of-00001.parquet": b"train-bytes",
    "parquet/ground_truth/test/test-00000-of-00001.parquet": b"test-bytes",
}


@pytest.fixture(scope="module")
def mod():
    """The build script, loaded by path."""
    return load_script("build_extraction_status")


def test_from_hub_downloads_each_split_at_the_pinned_commit(mod, tmp_path):
    """Shards are discovered with the tree API and fetched from ``/resolve/<commit>/``."""
    hub = _Hub(_SHARDS)
    mod.download_ground_truth(COMMIT, tmp_path, opener=hub)
    assert (tmp_path / "train" / "train-00000-of-00001.parquet").read_bytes() == b"train-bytes"
    assert (tmp_path / "test" / "test-00000-of-00001.parquet").read_bytes() == b"test-bytes"
    resolves = [u for u in hub.urls if "/resolve/" in u]
    assert resolves == [
        f"{_BASE}/datasets/Lucius-Morningstar/mailroom-dataset/resolve/{COMMIT}/{path}"
        for path in _SHARDS
    ]
    assert all(f"/tree/{COMMIT}/parquet/ground_truth/" in u for u in hub.urls if "/tree/" in u)
    assert all(ua and "@" not in ua for ua in hub.user_agents)


def test_from_hub_rejects_a_shard_whose_checksum_differs(mod, tmp_path):
    """A download that does not match the Hub's LFS digest is an error, not data."""
    with pytest.raises(RuntimeError, match="sha256"):
        mod.download_ground_truth(COMMIT, tmp_path, opener=_Hub(_SHARDS, bad_oid=True))


def test_from_hub_fails_loudly_when_a_split_has_no_shard(mod, tmp_path):
    """An empty listing for a split stops the build rather than scoring zero rows."""
    only_train = {k: v for k, v in _SHARDS.items() if "/train/" in k}
    with pytest.raises(RuntimeError, match="test"):
        mod.download_ground_truth(COMMIT, tmp_path, opener=_Hub(only_train))


@pytest.mark.parametrize(
    "argv",
    [
        ["--from-hub", "--commit", "main", "--revision", "v9.3"],
        ["--from-hub", "--commit", "ccd040f", "--revision", "v9.3"],
        ["--from-hub", "--commit", COMMIT.upper(), "--revision", "v9.3"],
        ["--from-hub", "--revision", "v9.3"],
        ["--from-hub", "--commit", COMMIT, "--revision", "v9.3", "--parquet-dir", "x"],
        ["--commit", COMMIT, "--revision", "v9.3"],
    ],
    ids=["branch", "short-sha", "upper-hex", "no-commit", "both-sources", "no-source"],
)
def test_argument_rules_reject_mutable_or_ambiguous_sources(mod, argv, capsys):
    """The pin must be an immutable 40-hex SHA and exactly one source is named."""
    with pytest.raises(SystemExit) as raised:
        mod.main(argv)
    assert raised.value.code == 2
    assert capsys.readouterr().err


def test_main_from_hub_builds_from_the_downloaded_shards(mod, tmp_path, monkeypatch):
    """``--from-hub`` downloads, reads the temp dir, and builds with the given tag and commit."""
    seen: dict[str, object] = {}

    def fake_download(commit, dest, opener=None):
        """Record the call and lay down nothing."""
        seen["commit"] = commit
        seen["dest"] = Path(dest)

    def fake_rows(parquet_dir):
        """Record the directory the rows were read from."""
        seen["rows_dir"] = Path(parquet_dir)
        return []

    monkeypatch.setattr(mod, "download_ground_truth", fake_download)
    monkeypatch.setattr(mod, "_rows", fake_rows)
    monkeypatch.setattr(mod, "OUT_PATH", tmp_path / "status.json")
    assert mod.main(["--from-hub", "--commit", COMMIT, "--revision", "v9.3"]) == 0
    assert seen["commit"] == COMMIT
    assert seen["rows_dir"] == seen["dest"]
    written = json.loads((tmp_path / "status.json").read_text())
    assert (written["revision"], written["commit"]) == ("v9.3", COMMIT)


def _row(doc_type: str, subclass: str, fields: dict) -> dict:
    """A synthetic ground_truth row."""
    return {"expected": doc_type, "expected_subclass": subclass, "gt_fields": json.dumps(fields)}


def test_build_counts_every_vocabulary_value_including_zero_rows(mod):
    """Per class and closed-vocabulary field: rows per scored token, zeros kept."""
    from llm_dojo_scoring.schemas.scored_enums import scored_vocabulary

    rows = [
        _row("insurance_claim", "auto", {"intent": "claim_filing", "claim_type": "auto"}),
        _row("insurance_claim", "auto", {"intent": "claim_filing", "claim_type": "auto"}),
        _row("insurance_claim", "auto", {"intent": "Claim Filing", "claim_type": ""}),
        _row("insurance_claim", "auto", {"intent": "carrier_memo"}),
        _row("correspondence", "email", {"content_topic": "it_systems", "sentiment_label": "Positive"}),
    ]
    out = mod.build(rows, "vtest", COMMIT)
    intent = out["vocabulary"]["insurance_claim"]["intent"]
    assert set(intent["values"]) == set(scored_vocabulary("insurance_claim", "intent"))
    assert intent["values"]["claim_filing"] == 3
    assert intent["values"]["loss_report"] == 0
    assert intent["outside_vocabulary"] == {"carrier_memo": 1}
    assert intent["rows_with_value"] == 4
    assert out["vocabulary"]["insurance_claim"]["claim_type"]["values"]["auto"] == 2
    corr = out["vocabulary"]["correspondence"]
    assert corr["content_topic"]["values"]["it_systems"] == 1
    assert corr["sentiment_label"]["values"] == {"negative": 0, "neutral": 0, "positive": 1}
    assert "record_type" in out["vocabulary"]["corporate_record"]
    assert "contract" not in out["vocabulary"]
