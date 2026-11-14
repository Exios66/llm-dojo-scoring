# ADR: how piece 3 of unlabelled-value grounding is split into PRs

**Status:** Accepted
**Date:** 2026-11-14
**Deciders:** repository owner
**Tracker:** Exios66/llm-dojo-scoring#146
**Design:** `docs/superpowers/specs/2026-11-14-unlabelled-value-grounding-design.md`, §6.4 and §11

## Context

Pieces 1 (#147) and 2 (#148) are open as stacked draft PRs. Piece 3 is the rest of the
design:

- **Agreement:** each agent's agreement with human spot-checks. The gating number is the precision of the agent's `valid` verdicts, by Wilson lower bound. Overall agreement and κ are reported next to it.
- **Trust gate:** decides, as of each confirmation's time, whether an agent's confirmations count. It also produces serialisable snapshots and lists the labels to re-review when an agent drops below the bar.
- **Spot-check sampling:** a deterministic sample of each agent's confirmations to send to people.
- **`GroundingSettings`:** the tunable thresholds.

As one PR this would be about 1,000 changed lines over four concerns, and one of them (`config.py`) is a shared module that consumers import. The owner asked for work stacked in reviewable chunks, not one large PR.

Forces:

- Each PR must be green and useful on its own, with its tests and docs.
- `config.py` is on the consumer surface (`get_settings`, `configure`). A change there should be small and easy to see.
- The trust gate depends on the agreement statistics. Sampling depends on neither.
- Review cost grows faster than size. The review rules size rounds by lines and risk.

## Decision

Split piece 3 into four stacked PRs, each based on the one before:

| PR | Branch suffix | Scope | Depends on |
|:--|:--|:--|:--|
| 3a | `-grounding-3a` | `GroundingSettings` in `config.py`: the `grounding:` YAML block, `configure(grounding__…)`, validation of ranges; this ADR | piece 2 |
| 3b | `-grounding-3b` | `grounding/agreement.py`: pairing human and agent latest verdicts, `ReviewerAgreement`, `reviewer_agreement` (valid precision and its Wilson bound, agreement, κ, per-field), the five `grounding_reviewer_*` metrics and their T1 metadata | 3a (window default) |
| 3c | `-grounding-3c` | `grounding/trust.py`: `GateSnapshot`, `TrustGate.history`, `TrustGate.trusted_snapshot_id` (the piece-2 `TrustLookup`), the regression guard | 3b |
| 3d | `-grounding-3d` | `select_spot_checks` in `agreement.py`, an end-to-end test (audit → candidates → ledger → gate → labels), and the contract doc's final pass | 3c |

Every PR follows the house flow: local gates, one combined adversarial round (reduced at the owner's request to limit usage), a fresh pre-PR review, and a draft PR.

## Options considered

### Option A: one piece-3 PR

| Dimension | Assessment |
|:--|:--|
| Complexity | Low to set up, high to review (about 1,000 lines, four concerns) |
| Cost | One review cycle, but long, and its findings span modules |
| Adaptability | Poor: a change to the trust rule re-opens the settings and the sampling too |

**Pros:** fewer branches, and one rebase chain to keep up to date.
**Cons:** this is what the owner asked to avoid. A config change hides inside a large diff.

### Option B: two PRs (statistics, then gate and sampling)

| Dimension | Assessment |
|:--|:--|
| Complexity | Medium |
| Cost | Two cycles |
| Adaptability | Better, but the settings change still rides along with the statistics |

**Pros:** a natural seam between measuring and deciding.
**Cons:** sampling and the end-to-end test are bundled with the gate, which is the riskiest logic.

### Option C: four PRs, as decided

| Dimension | Assessment |
|:--|:--|
| Complexity | Medium: four branches, rebases down the stack |
| Cost | Four short cycles, each of about 150 to 350 lines |
| Adaptability | Best: each concern can change, or stop, alone |

**Pros:** the shared-module change is isolated. The gate gets a focused review. Sampling and the end-to-end test land last, against final names.
**Cons:** more PR overhead, and a fix low in the stack must be merged upward.

## Trade-off analysis

Option C costs more PRs, but each review sees one idea. The two riskiest changes are the
public `config.py` and the trust decision; each gets its own reviewer. Settings land
first because every later PR reads its defaults, so nothing hard-codes a threshold that
a later PR would move. Sampling is independent of the gate, but it lands last so that
the end-to-end test can exercise the whole chain once.

## Consequences

- **Easier:** reviewing, reverting or re-tuning one concern; seeing exactly what changes on the consumer surface (3a only adds a `grounding` section).
- **Harder:** keeping four branches in step. A fix to 3a must be merged up through 3b to 3d. Merge order is fixed: 3a, then 3b, then 3c, then 3d, all after #147 and #148, all for 0.31.0.
- **Revisit:**
  - whether `agreement.py` should hold sampling (§11) or a separate `spot_checks.py`, if sampling grows;
  - whether the release PR squashes the stack.

## Action items

1. [ ] 3a: `GroundingSettings` and this ADR.
2. [ ] 3b: agreement statistics and metrics.
3. [ ] 3c: trust gate and snapshots.
4. [ ] 3d: spot-check sampling, end-to-end test, and the final contract doc.
5. [ ] Update tracker #146 as each PR opens.
