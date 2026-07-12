from __future__ import annotations
from dataclasses import dataclass
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


@dataclass
class Anomaly:
    source_id: str
    today: int
    baseline: float
    direction: str  # "drop" | "spike"


def volume_anomalies(today_counts: dict[str, int],
                     history_counts: list[dict[str, int]],
                     sigma: float = 2.0, min_baseline: float = 3.0) -> list[Anomaly]:
    source_ids = set(today_counts) | {s for h in history_counts for s in h}
    out: list[Anomaly] = []
    for sid in sorted(source_ids):
        hist = [h.get(sid, 0) for h in history_counts]
        if len(hist) < 2:
            continue
        mu = mean(hist)
        if mu < min_baseline:
            continue
        today = today_counts.get(sid, 0)
        if volume_anomaly(today, hist, sigma):
            out.append(Anomaly(sid, today, round(mu, 1),
                               "drop" if today < mu else "spike"))
    return out
