import json
import subprocess

from conftest import load_script

TAXONOMY = """\
version: 1
doc_classes:
  - key: correspondence
    schema: CorrespondenceExtraction
    specialist: correspondence_specialist
    field_types:
      sender: name
      intent: label
  - key: contract
    schema: ContractExtraction
    specialist: contracts_specialist
    field_types:
      parties: entity_list:name
"""


def _write(tmp_path):
    path = tmp_path / "taxonomy.yaml"
    path.write_bytes(TAXONOMY.encode())
    return path


def test_blob_sha1_equals_git_hash_object(tmp_path):
    gen = load_script("gen_taxonomy_fixture")
    path = _write(tmp_path)
    expected = subprocess.run(
        ["git", "hash-object", str(path)], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert gen.build_fixture(path)["authority_blob_sha1"] == expected


def test_field_types_round_trip_and_roster_order(tmp_path):
    gen = load_script("gen_taxonomy_fixture")
    fixture = gen.build_fixture(_write(tmp_path))
    assert fixture["live_doc_types"] == ["correspondence", "contract"]
    corr = fixture["doc_classes"]["correspondence"]
    assert corr["field_types"] == {"sender": "name", "intent": "label"}
    assert corr["specialist"] == "correspondence_specialist"
    assert corr["schema"] == "CorrespondenceExtraction"


def test_check_ignores_captured_at_only(tmp_path):
    gen = load_script("gen_taxonomy_fixture")
    tax, out = _write(tmp_path), tmp_path / "fixture.json"
    assert gen.main(["--taxonomy", str(tax), "--out", str(out)]) == 0
    data = json.loads(out.read_text())
    data["captured_at"] = "1999-01-01"
    out.write_text(json.dumps(data))
    assert gen.main(["--taxonomy", str(tax), "--out", str(out), "--check"]) == 0
    data["doc_classes"]["correspondence"]["field_types"]["intent"] = "name"
    out.write_text(json.dumps(data))
    assert gen.main(["--taxonomy", str(tax), "--out", str(out), "--check"]) == 1
