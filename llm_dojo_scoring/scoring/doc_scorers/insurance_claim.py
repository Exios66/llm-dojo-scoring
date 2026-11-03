"""``insurance_claim``: CMS source-table derivation (tier 2).

``score_claims_extras`` and the canonical ``claim_type`` already run inside the
insurance suite, so this module adds no extras in 0.27.0 (moving them here is
0.28.0 work). Tier 2 derives ``cms_source_table`` from a CMS row's subclass,
because the published ground truth never carries the key; the archive block reads
it from :meth:`InsuranceClaimScorer.derived_fields`.
"""

from __future__ import annotations

from typing import Any

from ...schemas.corpus import DOC_TYPE_SUBCLASSES, cms_source_table
from .base import TypeScorer


class InsuranceClaimScorer(TypeScorer):
    """Insurance claims, with the CMS table derived from the subclass."""

    def derived_fields(self, raw_subclass: Any) -> dict[str, str]:
        """``{"cms_source_table": table}`` for CMS rows, else ``{}``."""
        table = cms_source_table(self.doc_type, raw_subclass)
        return {"cms_source_table": table} if table else {}


SCORER = InsuranceClaimScorer(doc_type="insurance_claim", subclasses=DOC_TYPE_SUBCLASSES["insurance_claim"])
