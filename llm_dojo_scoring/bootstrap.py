"""Bootstrap confidence intervals and small-sample delta testing.

Ported from ``src/bootstrap.py`` (llm-entity-extraction). Deterministic given
a seed, offline, and dependency-free (stdlib ``random`` only — no numpy/scipy
requirement in the scoring path).
"""

from __future__ import annotations

import math
import random
from typing import Any, Optional

DEFAULT_N_BOOT = 2000
DEFAULT_ALPHA = 0.05
DEFAULT_SEED = 42


def _clean(values: list[Any]) -> list[float]:
    """Coerce a per-document score list to floats, dropping None, non-numeric
    and non-finite values (one NaN used to turn the whole CI into NaN)."""
    out: list[float] = []
    for v in values:
        if v is None:
            continue
        if isinstance(v, bool):
            out.append(1.0 if v else 0.0)
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            out.append(f)
    return out


def _resample_means(values: list[float], n_boot: int, rng: random.Random) -> list[float]:
    n = len(values)
    return [
        sum(values[i] for i in (rng.randrange(n) for _ in range(n))) / n
        for _ in range(n_boot)
    ]


def _percentile_indices(n_boot: int, alpha: float) -> tuple[int, int]:
    """Symmetric nearest-rank indices for the (alpha/2, 1-alpha/2) quantiles.

    The old ``round()`` form used banker's rounding, which put the two tails
    at different distances from the ends for small ``n_boot``."""
    lo = max(0, math.ceil((alpha / 2) * n_boot) - 1)
    return lo, max(lo, n_boot - 1 - lo)


def bootstrap_ci(
    values: list[Any],
    *,
    n_boot: int = DEFAULT_N_BOOT,
    alpha: float = DEFAULT_ALPHA,
    seed: int = DEFAULT_SEED,
) -> Optional[dict[str, Any]]:
    """Percentile-bootstrap 95% CI over per-document scores.

    Returns ``{"lo", "hi", "half", "n", "seed", "n_boot", "method"}`` (half =
    half-width in score points, 0-1 scale) or ``None`` when fewer than 2
    usable values (no CI on a single document).
    """
    values = _clean(values)
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    means = _resample_means(values, n_boot, rng)
    means.sort()
    lo_idx, hi_idx = _percentile_indices(n_boot, alpha)
    lo = round(means[lo_idx], 4)
    hi = round(means[hi_idx], 4)
    return {
        "lo": lo,
        "hi": hi,
        "half": round((hi - lo) / 2, 4),
        "n": len(values),
        "seed": seed,
        "n_boot": n_boot,
        "method": "percentile-bootstrap",
    }


def delta_significance(
    values_a: list[Any],
    values_b: list[Any],
    *,
    n_boot: int = DEFAULT_N_BOOT,
    alpha: float = DEFAULT_ALPHA,
    seed: int = DEFAULT_SEED,
    paired: bool = False,
) -> Optional[dict[str, Any]]:
    """Bootstrap on the mean difference (B - A).

    ``paired=True`` is for two systems scored on the SAME documents in the
    same order (the usual model/prompt A/B): it resamples documents jointly,
    so per-document difficulty cancels. The default two-sample form treats
    the lists as independent samples. For paired resampling both sides must
    have the same length and rows with a missing value on either side are
    dropped together.

    Returns ``{"delta", "ci_lo", "ci_hi", "significant", "n_a", "n_b",
    "seed", "n_boot", "method"}`` — ``significant`` is True when the 95% CI
    on the difference excludes zero. ``None`` when either side has fewer than
    2 usable values (the delta is then unmeasurable, not "insignificant").
    """
    if paired:
        values_a, values_b = list(values_a), list(values_b)
        if len(values_a) != len(values_b):
            raise ValueError("paired delta needs equal-length score lists")
        pairs = [
            (ca[0], cb[0])
            for ca, cb in ((_clean([x]), _clean([y])) for x, y in zip(values_a, values_b))
            if ca and cb
        ]
        a = [x for x, _ in pairs]
        b = [y for _, y in pairs]
    else:
        a = _clean(values_a)
        b = _clean(values_b)
    if len(a) < 2 or len(b) < 2:
        return None
    rng = random.Random(seed)
    mean_a = sum(a) / len(a)
    mean_b = sum(b) / len(b)

    def _sample_mean(values: list[float]) -> float:
        n = len(values)
        return sum(values[rng.randrange(n)] for _ in range(n)) / n

    if paired:
        d = [y - x for x, y in zip(a, b)]
        diffs = sorted(_resample_means(d, n_boot, rng))
    else:
        diffs = sorted(_sample_mean(b) - _sample_mean(a) for _ in range(n_boot))
    lo_idx, hi_idx = _percentile_indices(n_boot, alpha)
    lo = diffs[lo_idx]
    hi = diffs[hi_idx]
    return {
        "delta": round(mean_b - mean_a, 4),
        "ci_lo": round(lo, 4),
        "ci_hi": round(hi, 4),
        "significant": lo > 0 or hi < 0,
        "n_a": len(a),
        "n_b": len(b),
        "seed": seed,
        "n_boot": n_boot,
        "method": "paired-percentile-bootstrap" if paired else "two-sample-percentile-bootstrap",
    }


def wilson_ci(p: float, n: int, z: float = 1.96) -> Optional[dict[str, Any]]:
    """Wilson score interval for an aggregate proportion.

    Used when only the aggregate rate ``p`` and support ``n`` are available
    (e.g. rows of an Excel results workbook) rather than per-document scores.
    Returns ``{"lo", "hi", "half", "n", "p", "z"}`` or ``None`` when ``n < 1``.
    """
    if n < 1 or p is None:
        return None
    p = float(p)
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    margin = z * ((p * (1 - p) / n + z2 / (4 * n * n)) ** 0.5) / denom
    lo = max(0.0, centre - margin)
    hi = min(1.0, centre + margin)
    return {
        "lo": round(lo, 4),
        "hi": round(hi, 4),
        "half": round((hi - lo) / 2, 4),
        "n": int(n),
        "p": round(p, 4),
        "z": z,
    }


__all__ = ["bootstrap_ci", "delta_significance", "wilson_ci",
           "DEFAULT_N_BOOT", "DEFAULT_ALPHA", "DEFAULT_SEED"]
