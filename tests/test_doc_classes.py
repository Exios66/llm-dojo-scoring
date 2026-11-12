"""The document-class registry: one hand-edited table, every other table derived.

Pins (1) that each derived table still agrees with ``schemas/doc_classes.py`` when
recomputed from it, (2) that a registry edit reaches every derived table or fails the
import loudly (subprocess mutation tests), and (3) the layering rule that ``schemas/``
never imports ``scoring/``. (The one-off snapshot that proved the refactor changed no
table was retired once the refactor landed; see the PR that introduced the registry.)
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
from conftest import load_script

from llm_dojo_scoring.schemas import doc_classes
from llm_dojo_scoring.schemas.doc_classes import (
    DOC_CLASSES,
    LIVE_DOC_TYPES,
    RETIRED_DOC_TYPES,
    DocClass,
    field_names,
    field_types,
    in_order,
)
from llm_dojo_scoring.schemas.extraction_schemas import (
    extraction_schema,
    iter_extraction_schemas,
    registry_violations,
    schema_coverage,
    scoreable_fields,
)

_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE = _ROOT / "llm_dojo_scoring"

#: The eight classes in registry (taxonomy) order, as the snapshot recorded them.
_EIGHT = (
    "contract",
    "corporate_record",
    "due_diligence",
    "correspondence",
    "compliance_filing",
    "court_opinion",
    "insurance_claim",
    "merger_agreement",
)
_FIVE = ("contract", "merger_agreement", "corporate_record", "correspondence", "insurance_claim")


# ---------------------------------------------------------------------------
# 2. The registry itself
# ---------------------------------------------------------------------------


def test_registry_holds_the_eight_classes_in_taxonomy_order() -> None:
    """All eight classes, keyed by their own key, in the order DEFAULT_FIELD_TYPES always had."""
    assert tuple(DOC_CLASSES) == _EIGHT
    assert all(isinstance(c, DocClass) and c.key == k for k, c in DOC_CLASSES.items())
    assert all(c.fields and all(isinstance(t, str) and t for t in c.fields.values()) for c in DOC_CLASSES.values())


def test_live_and_retired_partition_the_registry() -> None:
    """Live and retired are disjoint, cover every class, and follow the pipeline order."""
    assert LIVE_DOC_TYPES == _FIVE
    assert RETIRED_DOC_TYPES == ("court_opinion", "due_diligence", "compliance_filing")
    assert set(LIVE_DOC_TYPES) | set(RETIRED_DOC_TYPES) == set(DOC_CLASSES)
    assert not set(LIVE_DOC_TYPES) & set(RETIRED_DOC_TYPES)
    assert all(DOC_CLASSES[k].live for k in LIVE_DOC_TYPES)


def test_registry_is_immutable() -> None:
    """The registry and each class's field map reject in-place mutation."""
    with pytest.raises(TypeError):
        DOC_CLASSES["contract"] = DOC_CLASSES["contract"]  # type: ignore[index]
    with pytest.raises(TypeError):
        DOC_CLASSES["contract"].fields["extra"] = "name"  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        DOC_CLASSES["contract"].live = False  # type: ignore[misc]


def test_accessors_return_fresh_values() -> None:
    """``field_types`` is a new dict per call; ``field_names`` is a tuple in field order."""
    first = field_types("contract")
    first["scribble"] = "name"
    first.pop("parties")
    again = field_types("contract")
    assert "scribble" not in again and "parties" in again
    assert field_names("contract") == tuple(DOC_CLASSES["contract"].fields) == tuple(again)
    assert isinstance(field_names("contract"), tuple)


def test_unknown_class_names_the_valid_keys() -> None:
    """A KeyError for an unknown class lists every registered key."""
    for accessor in (field_types, field_names):
        with pytest.raises(KeyError) as err:
            accessor("not_a_class")
        message = str(err.value)
        assert "not_a_class" in message and all(key in message for key in DOC_CLASSES)


def test_monkeypatched_class_is_visible_through_the_accessors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Accessors read ``DOC_CLASSES`` at call time, so an edited entry shows up at once."""
    old = DOC_CLASSES["insurance_claim"]
    new = dataclasses.replace(old, fields={**old.fields, "zz_new_field": "free_text"})
    monkeypatch.setattr(doc_classes, "DOC_CLASSES", MappingProxyType({**DOC_CLASSES, "insurance_claim": new}))
    assert field_types("insurance_claim")["zz_new_field"] == "free_text"
    assert field_names("insurance_claim")[-1] == "zz_new_field"
    assert "zz_new_field" not in field_types("contract")


def test_in_order_puts_hinted_keys_first_and_appends_the_rest() -> None:
    """``in_order`` is the one place a legacy order lives; new classes append at the end."""
    assert in_order(["a", "b", "c"], ()) == ("a", "b", "c")
    assert in_order(("contract", "court_opinion", "insurance_claim"), ("insurance_claim", "contract")) == (
        "insurance_claim",
        "contract",
        "court_opinion",
    )
    assert in_order(["contract"], ("court_opinion", "contract")) == ("contract",)
    with pytest.raises(KeyError, match="typo_class"):
        in_order(["contract"], ("typo_class",))


def test_in_corpus_follows_the_pinned_dataset() -> None:
    """``in_corpus`` is true exactly for the classes the pinned dataset has rows for."""
    from llm_dojo_scoring.schemas.extraction_schemas import _status_data

    with_rows = {
        doc_type
        for doc_type, by_subtype in _status_data()["doc_types"].items()
        if sum(int(part["rows"]) for part in by_subtype.values())
    }
    assert {k for k, c in DOC_CLASSES.items() if c.in_corpus} == with_rows
    assert registry_violations() == []


# ---------------------------------------------------------------------------
# 3. Each derived table agrees with the registry when recomputed from it
# ---------------------------------------------------------------------------


def test_suites_tables_equal_the_registry() -> None:
    """``DEFAULT_FIELD_TYPES`` and ``SPECIALIST_DOC_TYPES`` are the registry, restated by nothing."""
    from llm_dojo_scoring.scoring import suites

    assert list(suites.DEFAULT_FIELD_TYPES) == list(DOC_CLASSES)
    for key in DOC_CLASSES:
        assert suites.DEFAULT_FIELD_TYPES[key] == field_types(key)
        assert list(suites.DEFAULT_FIELD_TYPES[key]) == list(field_names(key))
    assert suites.SPECIALIST_DOC_TYPES == {c.specialist: k for k, c in DOC_CLASSES.items()}
    assert suites.DOC_TYPE_ALIASES == {c.key: c.specialist for c in DOC_CLASSES.values()}


def test_pipeline_rosters_equal_the_registry() -> None:
    """The mailroom live/retired rosters, archive classes and config keys come from the registry."""
    from llm_dojo_scoring import config
    from llm_dojo_scoring.metrics import doc_bundles
    from llm_dojo_scoring.metrics import registry as metric_registry
    from llm_dojo_scoring.pipeline import archive, mailroom
    from llm_dojo_scoring.schemas import extraction_schemas

    assert mailroom.LIVE_DOC_TYPES == doc_classes.LIVE_DOC_TYPES
    assert mailroom.RETIRED_DOC_TYPES == doc_classes.RETIRED_DOC_TYPES
    assert extraction_schemas.MAILROOM_DOC_TYPES == doc_classes.LIVE_DOC_TYPES
    assert archive.LIVE_ARCHIVE_DOC_TYPES == doc_classes.LIVE_DOC_TYPES
    assert mailroom.LIVE_SPECIALISTS == tuple(DOC_CLASSES[k].specialist for k in LIVE_DOC_TYPES)
    assert mailroom.RETIRED_SPECIALISTS == tuple(DOC_CLASSES[k].specialist for k in RETIRED_DOC_TYPES)
    assert set(mailroom.RETIRED_AUDITORS) == {DOC_CLASSES[k].auditor for k in RETIRED_DOC_TYPES}
    assert set(metric_registry.SPECIALIST_AGENTS) == {c.specialist for c in DOC_CLASSES.values()}
    assert metric_registry.LIVE_SPECIALIST_AGENTS == mailroom.LIVE_SPECIALISTS
    assert config.DOC_CLASS_KEYS == list(DOC_CLASSES)
    assert config.LIVE_DOC_CLASS_KEYS == list(LIVE_DOC_TYPES)
    assert config.RETIRED_DOC_CLASS_KEYS == list(RETIRED_DOC_TYPES)
    assert doc_bundles.DOC_TYPES == tuple(DOC_CLASSES)


def test_corpus_tables_equal_the_registry() -> None:
    """``CORPUS_EXTRACTION_FIELDS`` and the corpus class tuples are projections of the registry."""
    from llm_dojo_scoring.schemas import corpus

    assert {k: v for k, v in corpus.CORPUS_EXTRACTION_FIELDS.items()} == {k: field_names(k) for k in DOC_CLASSES}
    assert set(corpus.CORPUS_DOC_TYPES) == {k for k, c in DOC_CLASSES.items() if c.in_corpus}
    assert set(corpus.CORPUS_ABSENT_DOC_TYPES) == {k for k, c in DOC_CLASSES.items() if not c.in_corpus}
    assert set(corpus.NATIVE_DOC_TYPES) == set(DOC_CLASSES)


def test_scoped_field_sets_equal_the_registry() -> None:
    """Extraction scope, adherence fallbacks and the promotion gates cover exactly the live classes."""
    from llm_dojo_scoring.metrics import scorecard_honesty
    from llm_dojo_scoring.pipeline import sandbox_schema_adherence as adherence
    from llm_dojo_scoring.schemas import v10_rows
    from llm_dojo_scoring.scoring import extraction_scope

    assert extraction_scope.LIVE_SCHEMA_FIELDS == {k: frozenset(field_names(k)) for k in LIVE_DOC_TYPES}
    assert set(adherence._FALLBACK_SCHEMA_KEYS) == set(LIVE_DOC_TYPES)
    for key, keys in adherence._FALLBACK_SCHEMA_KEYS.items():
        assert keys == frozenset(field_names(key)) | adherence._PARSE_COMPAT_KEYS.get(key, frozenset())
    assert set(adherence._MODEL_CLASSES) == set(LIVE_DOC_TYPES)
    assert set(scorecard_honesty.SCHEMA_PROMOTION_GATES) == set(LIVE_DOC_TYPES)
    assert v10_rows.V10_GT_CONFIGS == {k: f"gt_{k}" for k in LIVE_DOC_TYPES}


def test_schema_descriptors_equal_the_registry() -> None:
    """The prompt descriptors carry descriptions only: names, order and types are the registry's."""
    from llm_dojo_scoring.schemas import corporate_record_schema, cuad_schema, maud_schema

    assert cuad_schema.CONTRACT_FIELD_TYPES == field_types("contract")
    assert tuple(f.name for f in cuad_schema.CONTRACT_EXTRACTION_FIELDS) == field_names("contract")
    assert maud_schema.MergerAgreementExtraction.field_types == field_types("merger_agreement")
    assert tuple(f.name for f in maud_schema.MergerAgreementExtraction.fields) == field_names("merger_agreement")
    assert corporate_record_schema.CORE_FIELDS == field_names("corporate_record")


def test_build_extraction_status_uses_the_live_classes() -> None:
    """The status builder walks the registry's live classes, in the same order."""
    assert load_script("build_extraction_status").FIVE == LIVE_DOC_TYPES


# ---------------------------------------------------------------------------
# 4. A registry edit reaches every derived table, or fails the import loudly
# ---------------------------------------------------------------------------

_MUTATED_IMPORT = textwrap.dedent(
    """
    import dataclasses, importlib.util, sys, types
    spec = importlib.util.spec_from_file_location("llm_dojo_scoring.schemas.doc_classes", {path!r})
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    old = mod.DOC_CLASSES[{cls!r}]
    new = dataclasses.replace(old, fields={{**old.fields, "zz_new_field": "name"}})
    mod.DOC_CLASSES = types.MappingProxyType({{**mod.DOC_CLASSES, {cls!r}: new}})
    import llm_dojo_scoring
    """
)


def _run_with_edited_registry(cls: str, body: str) -> subprocess.CompletedProcess[str]:
    """Import the package in a fresh interpreter after adding ``zz_new_field`` to ``cls``."""
    header = _MUTATED_IMPORT.format(path=str(_PACKAGE / "schemas" / "doc_classes.py"), cls=cls)
    return subprocess.run(
        [sys.executable, "-c", header + textwrap.dedent(body)],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_new_insurance_field_reaches_every_derived_table() -> None:
    """One edit to ``doc_classes.py`` shows up in every table derived from it, with no other edit."""
    body = """
        from llm_dojo_scoring.scoring import suites, extraction_scope
        from llm_dojo_scoring.schemas import corpus, extraction_schemas, schema_contract
        from llm_dojo_scoring.pipeline import sandbox_schema_adherence as adherence
        cls = "insurance_claim"
        assert suites.DEFAULT_FIELD_TYPES[cls]["zz_new_field"] == "name"
        assert corpus.CORPUS_EXTRACTION_FIELDS[cls][-1] == "zz_new_field"
        assert "zz_new_field" in extraction_scope.LIVE_SCHEMA_FIELDS[cls]
        assert "zz_new_field" in adherence._FALLBACK_SCHEMA_KEYS[cls]
        assert extraction_schemas._live_types(cls)["zz_new_field"] == "name"
        schema = extraction_schemas.extraction_schema(cls)
        assert "zz_new_field" in schema.fields and "zz_new_field" in schema.field_types
        assert schema_contract.contract_empty_payload(cls)["zz_new_field"] is None
        print("OK")
    """
    result = _run_with_edited_registry("insurance_claim", body)
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip().endswith("OK")


@pytest.mark.parametrize("cls", ["contract", "merger_agreement"])
def test_new_field_without_a_prompt_descriptor_fails_the_import(cls: str) -> None:
    """Contract and merger carry hand-written prompt descriptors; a field without one fails loudly."""
    module = {"contract": "cuad_schema", "merger_agreement": "maud_schema"}[cls]
    result = _run_with_edited_registry(cls, f"import llm_dojo_scoring.schemas.{module}\nprint('imported')")
    assert result.returncode != 0
    assert "zz_new_field" in result.stderr
    assert "imported" not in result.stdout


# ---------------------------------------------------------------------------
# 5. scoreable_fields: one rule, shared with schema_coverage
# ---------------------------------------------------------------------------


def test_scoreable_fields_correspondence_is_pinned() -> None:
    """Correspondence scores four fields today: the subtype-derived type plus the semantic trio."""
    assert scoreable_fields("correspondence") == ("communication_type", "intent", "subject_matter", "keywords")


def test_scoreable_fields_insurance_adjuster_in_checklist_out() -> None:
    """A partly-populated field is scored; a field with no GT row is not."""
    fields = scoreable_fields("insurance_claim")
    assert "adjuster" in fields
    assert "claim_checklist" not in fields


def test_scoreable_fields_is_the_scored_status_rule() -> None:
    """Every schema's scoreable fields are exactly those whose status is in ``SCORED_STATUSES``."""
    from llm_dojo_scoring.schemas.extraction_schemas import SCORED_STATUSES

    for schema in iter_extraction_schemas():
        expected = tuple(name for name, spec in schema.fields.items() if spec.status in SCORED_STATUSES)
        assert scoreable_fields(schema.doc_type, schema.subtype) == expected


def test_scoreable_fields_agrees_with_schema_coverage() -> None:
    """A fully labelled row can score exactly ``scoreable_fields``, for every class and subtype."""
    for schema in iter_extraction_schemas():
        row = {name: "x" for name in schema.fields}
        coverage = schema_coverage(schema.doc_type, schema.subtype, row)
        assert tuple(coverage["scorable_fields"]) == scoreable_fields(schema.doc_type, schema.subtype), schema.schema_id
        assert coverage["unlabelled_fields"] == []


def test_scoreable_fields_follows_the_dataset_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """A field that gains GT coverage becomes scoreable with no code change."""
    from llm_dojo_scoring.schemas import extraction_schemas

    data = json.loads(json.dumps(extraction_schemas._status_data()))
    for part in data["doc_types"]["insurance_claim"].values():
        part["fields"]["claim_checklist"] = {"populated": part["rows"]}
    monkeypatch.setattr(extraction_schemas, "_status_data", lambda: data)
    extraction_schemas._cached.cache_clear()
    try:
        assert "claim_checklist" in scoreable_fields("insurance_claim")
    finally:
        monkeypatch.undo()
        extraction_schemas._cached.cache_clear()
    assert "claim_checklist" not in scoreable_fields("insurance_claim")


def test_scoreable_fields_rejects_unknown_class() -> None:
    """The same KeyError as ``extraction_schema`` for a class outside the five."""
    with pytest.raises(KeyError):
        scoreable_fields("court_opinion")
    with pytest.raises(KeyError):
        scoreable_fields("contract", "not_a_subtype")


# ---------------------------------------------------------------------------
# 6. Layering: the registry is a leaf and schemas/ stays below scoring/
# ---------------------------------------------------------------------------

#: ``(file, imported module, imported name)`` triples allowed to reach up into ``scoring/``.
#: ``CMS_ROW_FIELD_TYPES`` is a scorer's per-row type override (``entity_list:cms_doc_ref`` is
#: a scoring-only type), not a class/field table, so it stays in ``scoring.field_scoring``.
_SCORING_EXEMPTIONS: frozenset[tuple[str, str, str]] = frozenset(
    {("extraction_schemas.py", "scoring.field_scoring", "CMS_ROW_FIELD_TYPES")}
)


def _imports(path: Path) -> list[tuple[int, str, list[str]]]:
    """``(line, resolved module, imported names)`` for every import in ``path``, nested ones included."""
    package = ["llm_dojo_scoring", *path.relative_to(_PACKAGE).parts[:-1]]
    found: list[tuple[int, str, list[str]]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name, []) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - (node.level - 1)] if node.level else []
            module = ".".join([*base, *([node.module] if node.module else [])])
            found.append((node.lineno, module, [alias.name for alias in node.names]))
    return found


def _scoring_target(module: str, names: list[str]) -> tuple[str, list[str]] | None:
    """``(relative scoring module, imported names)`` when an import reaches ``scoring/``, else ``None``.

    ``from .. import scoring`` resolves to the package root with ``scoring`` as an imported
    name, so at the root the names decide.
    """
    relative = module.removeprefix("llm_dojo_scoring.")
    if relative == "llm_dojo_scoring":
        hit = [name for name in names if name == "scoring"]
        return ("scoring", hit) if hit else None
    if relative == "scoring" or relative.startswith("scoring."):
        return relative, names
    return None


def test_scoring_target_sees_scoring_imported_through_the_package_root() -> None:
    """Direct, nested and package-root imports of ``scoring`` are all found; other root names are not."""
    assert _scoring_target("llm_dojo_scoring", ["scoring"]) == ("scoring", ["scoring"])
    assert _scoring_target("llm_dojo_scoring", ["config", "scoring"]) == ("scoring", ["scoring"])
    assert _scoring_target("llm_dojo_scoring", ["config"]) is None
    assert _scoring_target("llm_dojo_scoring.scoring", ["x"]) == ("scoring", ["x"])
    assert _scoring_target("llm_dojo_scoring.scoring.field_scoring", []) == ("scoring.field_scoring", [])
    assert _scoring_target("llm_dojo_scoring.schemas.corpus", ["x"]) is None


def test_schemas_never_import_scoring() -> None:
    """No module under ``schemas/`` imports ``scoring/`` (top level or nested), bar the listed exemptions."""
    offenders: list[str] = []
    for path in sorted((_PACKAGE / "schemas").glob("*.py")):
        for line, module, names in _imports(path):
            target = _scoring_target(module, names)
            if target is None:
                continue
            relative, scoring_names = target
            used = scoring_names or [""]
            if all((path.name, relative, name) in _SCORING_EXEMPTIONS for name in used):
                continue
            offenders.append(f"{path.name}:{line} imports {module} {names}")
    assert not offenders, "schemas/ must not import scoring/:\n" + "\n".join(offenders)


def test_scoring_exemptions_are_still_needed() -> None:
    """An exemption nobody uses any more is deleted, not kept as a loophole."""
    used: set[tuple[str, str, str]] = set()
    for path in sorted((_PACKAGE / "schemas").glob("*.py")):
        for _line, module, names in _imports(path):
            used.update((path.name, module.removeprefix("llm_dojo_scoring."), name) for name in names)
    assert _SCORING_EXEMPTIONS <= used


def test_doc_classes_imports_nothing_from_the_package() -> None:
    """The registry is stdlib-only: it is the leaf every other module imports."""
    path = _PACKAGE / "schemas" / "doc_classes.py"
    for line, module, _names in _imports(path):
        top = module.split(".")[0]
        assert top != "llm_dojo_scoring", f"doc_classes.py:{line} imports {module}"
        assert top in sys.stdlib_module_names or top == "__future__", f"doc_classes.py:{line} imports {module}"
    relative = [n for n in ast.walk(ast.parse(path.read_text("utf-8"))) if isinstance(n, ast.ImportFrom) and n.level]
    assert not relative


def test_importing_the_registry_alone_stays_cheap() -> None:
    """Loading the leaf by path pulls no package module, so it is safe to import from anywhere."""
    source = textwrap.dedent(
        f"""
        import importlib.util, sys
        spec = importlib.util.spec_from_file_location("doc_classes_leaf", {str(_PACKAGE / "schemas" / "doc_classes.py")!r})
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        assert not [m for m in sys.modules if m.startswith("llm_dojo_scoring")]
        assert mod.field_names("contract")
        """
    )
    result = subprocess.run([sys.executable, "-c", source], capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr[-1000:]
