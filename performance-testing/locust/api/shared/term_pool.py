"""Spread Locust create traffic across exported search terms without
pushing any term past PERF_SEED_HIT_MAX (default 2000)."""
from __future__ import annotations

import random

from shared.config import PERF_SEED_HIT_MAX


def claim_create_term(
    terms: list[str],
    usage: dict[str, int],
    seed_hits: dict[str, int] | None = None,
    hit_max: int = PERF_SEED_HIT_MAX,
) -> str:
    """Return a term whose seed hits plus this-process creates stay under hit_max.

    Least-used among terms still under the cap. If every term is already at
    cap (or the list is empty), fall back to least-used across the full list
    so create can still run.
    """
    if not terms:
        return ""
    seed_hits = seed_hits or {}

    def load(term: str) -> int:
        return seed_hits.get(term, 0) + usage.get(term, 0)

    eligible = [term for term in terms if load(term) < hit_max]
    pool = eligible or list(terms)
    min_load = min(load(term) for term in pool)
    least_used = [term for term in pool if load(term) == min_load]
    term = random.choice(least_used)
    usage[term] = usage.get(term, 0) + 1
    return term
