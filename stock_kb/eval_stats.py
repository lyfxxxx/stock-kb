from __future__ import annotations

import math
import random
from typing import Sequence


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score 95% interval for a binomial proportion."""
    if n <= 0:
        return (0.0, 0.0)
    successes = max(0, min(int(successes), int(n)))
    p = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    margin = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n) / denom
    lo = max(0.0, center - margin)
    hi = min(1.0, center + margin)
    return (round(lo, 3), round(hi, 3))


def bootstrap_ci(
    scores: Sequence[float],
    n_resample: int = 10000,
    alpha: float = 0.05,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile bootstrap CI for the mean of a score list."""
    if not scores:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(scores)
    means: list[float] = []
    for _ in range(n_resample):
        total = 0.0
        for _i in range(n):
            total += scores[rng.randrange(n)]
        means.append(total / n)
    means.sort()
    lo_i = int(alpha / 2.0 * n_resample)
    hi_i = min(n_resample - 1, int((1.0 - alpha / 2.0) * n_resample))
    return (round(means[lo_i], 3), round(means[hi_i], 3))
