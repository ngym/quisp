from __future__ import annotations

import math
import random
from typing import Iterable, Sequence

from .experiment_models import DistributionSummary


def _clean(values: Iterable[float]) -> list[float]:
    result: list[float] = []
    for value in values:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(numeric):
            result.append(numeric)
    return result


def reservoir_sample(values: Sequence[float], limit: int = 100000) -> tuple[list[float], str]:
    if len(values) <= limit:
        return list(values), "exact"
    rng = random.Random(0)
    sample = list(values[:limit])
    for index in range(limit, len(values)):
        candidate = rng.randint(0, index)
        if candidate < limit:
            sample[candidate] = values[index]
    return sample, "reservoir"


def percentile(sorted_values: Sequence[float], q: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    weight = position - lower
    return float(sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight)


def summarize_distribution(values: Iterable[float]) -> DistributionSummary:
    cleaned = _clean(values)
    if not cleaned:
        return DistributionSummary(count=0, sample_mode="exact")
    sampled, sample_mode = reservoir_sample(cleaned)
    ordered = sorted(sampled)
    return DistributionSummary(
        count=len(cleaned),
        mean=sum(cleaned) / len(cleaned),
        min=min(cleaned),
        max=max(cleaned),
        p50=percentile(ordered, 0.50),
        p95=percentile(ordered, 0.95),
        p99=percentile(ordered, 0.99),
        sample_mode=sample_mode,
    )
