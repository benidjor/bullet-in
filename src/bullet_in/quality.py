from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
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


@dataclass
class SourceFreshness:
    source_id: str
    last_fetched_at: datetime | None
    threshold_hours: float
    age_hours: float | None   # 워터마크 없으면 None
    stale: bool               # 워터마크 없으면 False (알림 제외)


def evaluate_freshness(watermarks: dict[str, datetime | None], now: datetime,
                       default_hours: float,
                       overrides: dict[str, float] | None = None
                       ) -> list[SourceFreshness]:
    overrides = overrides or {}
    out: list[SourceFreshness] = []
    for sid in sorted(watermarks):
        wm = watermarks[sid]
        thr = float(overrides.get(sid, default_hours))
        if wm is None:
            out.append(SourceFreshness(sid, None, thr, None, False))
            continue
        age = (now - wm).total_seconds() / 3600
        out.append(SourceFreshness(sid, wm, thr, age, age > thr))
    return out


def evaluate_coverage(coverage: dict) -> list[str]:
    """공홈 퍼널 불변식 위반 목록 — 후보 0 = 발견 경로 장애 · Men 소멸 = taxonomy 드리프트.
    accept 0 은 비수기 정상이라 판정하지 않는다 (spec 2026-07-24 §5)."""
    if not coverage:
        return []
    if coverage.get("candidates", 0) == 0:
        return ["no_candidates"]
    if coverage.get("men_tagged", 0) == 0:
        return ["no_men_tag"]
    return []
