"""Voicing cost estimates (characters x per-character price)."""
from __future__ import annotations

from dataclasses import dataclass

from .script import Script, spoken_text


@dataclass
class CostEstimate:
    characters: int
    cost: float
    per_recording: dict[str, int]


def estimate(scripts: list[Script], provider: str, prices: dict[str, float]) -> CostEstimate:
    """`prices` maps provider name to price per character."""
    if provider not in prices:
        raise KeyError(provider)
    per = {s.id: sum(len(spoken_text(p)) for p in s.passages) for s in scripts}
    total = sum(per.values())
    return CostEstimate(characters=total, cost=total * prices[provider], per_recording=per)
