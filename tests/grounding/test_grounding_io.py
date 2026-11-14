"""Local JSONL read and write for grounding records."""

from __future__ import annotations

import pytest

from llm_dojo_scoring.grounding.io import read_jsonl, write_jsonl
from llm_dojo_scoring.grounding.ledger import Confirmation


def test_round_trip_records_and_mappings(tmp_path):
    """Records are written through as_dict, mappings as they are, and read back in order."""
    path = tmp_path / "out.jsonl"
    confirmation = Confirmation("c1", "valid", "human", "human:a", 1.0)
    assert write_jsonl([confirmation, {"x": "é"}], path) == 2
    rows = read_jsonl(path)
    assert rows[0]["schema_version"] == 1 and rows[0]["candidate_id"] == "c1"
    assert rows[1] == {"x": "é"}
    assert Confirmation.from_dict(rows[0]) == confirmation


def test_append_grows_the_file(tmp_path):
    """append=True adds lines after the existing ones."""
    path = tmp_path / "ledger.jsonl"
    write_jsonl([{"n": 1}], path)
    write_jsonl([{"n": 2}], path, append=True)
    assert [row["n"] for row in read_jsonl(path)] == [1, 2]


def test_failed_write_leaves_file_unchanged(tmp_path):
    """An unserialisable record raises before anything is written."""
    path = tmp_path / "out.jsonl"
    write_jsonl([{"n": 1}], path)
    with pytest.raises(TypeError):
        write_jsonl([{"n": 2}, {"bad": object()}], path)
    with pytest.raises(TypeError):
        write_jsonl([{"n": 2}, {"bad": object()}], path, append=True)
    with pytest.raises(TypeError, match="not a mapping"):
        write_jsonl([[1, 2]], path)
    assert read_jsonl(path) == [{"n": 1}]
    assert [p.name for p in tmp_path.iterdir()] == ["out.jsonl"]


def test_bad_lines_name_their_line_number(tmp_path):
    """Invalid JSON or a non-object line raises ValueError with the line number; blanks are skipped."""
    path = tmp_path / "bad.jsonl"
    path.write_text('{"a": 1}\n\n{oops\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r":3: not valid JSON"):
        read_jsonl(path)
    path.write_text('{"a": 1}\n[1]\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r":2: expected a JSON object"):
        read_jsonl(path)


def test_append_after_torn_line_starts_a_new_line(tmp_path):
    """A torn last line is closed before appending, so the new record stays readable."""
    path = tmp_path / "ledger.jsonl"
    path.write_text('{"n": 1}\n{"n": 2', encoding="utf-8")
    write_jsonl([{"n": 3}], path, append=True)
    assert path.read_text(encoding="utf-8").splitlines() == ['{"n": 1}', '{"n": 2', '{"n": 3}']


def test_nan_is_refused(tmp_path):
    """NaN is not JSON: writing it raises and the file is untouched."""
    path = tmp_path / "out.jsonl"
    with pytest.raises(ValueError):
        write_jsonl([{"x": float("nan")}], path)
    assert not path.exists()


def test_new_files_are_owner_only(tmp_path):
    """A file created by either path is readable by its owner only."""
    replaced, appended = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    write_jsonl([{"n": 1}], replaced)
    write_jsonl([{"n": 1}], appended, append=True)
    assert {p.stat().st_mode & 0o777 for p in (replaced, appended)} == {0o600}


def test_replace_keeps_permissions(tmp_path):
    """Replacing a file keeps its mode."""
    path = tmp_path / "out.jsonl"
    path.write_text("", encoding="utf-8")
    path.chmod(0o644)
    write_jsonl([{"n": 1}], path)
    assert path.stat().st_mode & 0o777 == 0o644
