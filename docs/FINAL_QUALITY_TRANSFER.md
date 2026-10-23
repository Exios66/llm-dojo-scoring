# DMR-091 final primary quality proposal

Additive source APIs, requiring a reviewed new Dojo release before consumers
ship. Published v0.22.0 is not claimed to provide these modules.

- `pilot_labels`: exact pipeline inventory matching, compact CUAD normalization,
  MAUD consideration normalization and pilot subclass policy. Producer catalogs
  are explicit inputs; prompt assembly and field selection remain producer-owned.
  CUAD family equivalence calls the existing Dojo engine with the pipeline's
  explicit groups, preserving independence from global task-setting overrides.
- `pilot_summary.pilot_classification_summary`: pilot class/subclass counts and
  three-decimal rates. Every input row counts for class accuracy. A non-None
  subclass flag selects subclass support, including False and flags without GT.
  Nonempty predictions override exact_ok. Per-class historical exact_ok fallback
  can count a missing-label row that strict aggregate classification rejects.
- `field_support`: pilot required-field presence and per-row absolute calibration
  error (three decimals); labeled schema coverage (three decimals); factuality
  means over fields whose n_predicted is truthy (four decimals). Empty lists and
  dicts are requirements in the pilot policy but unlabeled in schema coverage.
  False and numeric zero are labeled requirements in both; predicted False/zero
  fail pilot presence. A nonempty list containing None passes pilot presence.
- `ExtractionScoreResult.audit_support`: additive property exposing eligible
  field support and factuality means. Constructor, to_dict serialization and
  existing overall_verified_precision behavior are unchanged. Each eligible
  field has one vote, irrespective of its number of predicted entities.
- `sandbox_agent_scoring`: literal label equality, contains and reporter-key
  policies preserve the sandbox's exact historical rubrics. Literal blank
  labels retain the sandbox convention; GT-supported pipeline labels use a
  separate nonblank predicate.
  Existing token-set F1/key_presence are not interchangeable with these policies.

No default task/suite formulas, registry names, metric IDs or published defaults
are replaced. These support summaries are not new emitted metrics. Consumers
retain existing score names and row benchmark identities. In particular these
APIs do not equate MAUD sandbox labels with clean MAUD question metrics.

Intentional sandbox runner correction uses existing aggregate_quality_honest:
missing GT no longer becomes zero; no numeric quality score is emitted for an
unscorable batch. Known zero remains scored. Failed rows remain separate errors.
The canonical aggregate rounds to four decimals; old isolated-run means were
unrounded. Non-extraction rows also use this canonical aggregate for their
legacy exact_match headline. The old exact_match report alias remains a
compatibility label, not evidence that extraction rubrics are exact matching.

Existing unknown/unknown -> other matches, loose containment, and reporter key
substrings inside values remain intentional compatibility behavior in this
transfer. New tests use real suites and hand-counted support; no fake scorer is
substituted. Full source and dependent acceptance remains a parent release gate.
