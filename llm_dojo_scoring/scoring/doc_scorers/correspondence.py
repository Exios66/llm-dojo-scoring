"""``correspondence``: tier-2 subclass normalisation only, in 0.27.0.

Topic and sentiment (``score_correspondence_content``) already run inside the
correspondence suite, so returning them again as extras would count them twice;
moving them out of the suite and into this module is 0.28.0 work.
"""

from __future__ import annotations

from ...schemas.corpus import DOC_TYPE_SUBCLASSES
from .base import TypeScorer

SCORER = TypeScorer(doc_type="correspondence", subclasses=DOC_TYPE_SUBCLASSES["correspondence"])
