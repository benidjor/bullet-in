from __future__ import annotations
from statistics import mean, pstdev

def success_rate(total_sources: int, errored: int) -> float:
    if total_sources == 0:
        return 0.0
    return round((total_sources - errored) / total_sources, 3)

def volume_anomaly(today: int, history: list[int], sigma: float = 2.0) -> bool:
    if len(history) < 2:
        return False
    mu, sd = mean(history), pstdev(history)
    if sd == 0:
        return today != mu
    return abs(today - mu) > sigma * sd
