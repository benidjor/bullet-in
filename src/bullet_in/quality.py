from __future__ import annotations
import re
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
        if thr <= 0:
            continue   # 감시 제외 (freshness_hours: 0) — 이벤트 구동 소스 (스펙 2026-08-07 §3.2)
        if wm is None:
            out.append(SourceFreshness(sid, None, thr, None, False))
            continue
        age = (now - wm).total_seconds() / 3600
        out.append(SourceFreshness(sid, wm, thr, age, age > thr))
    return out


# 재알림 고정 간격 (h) — 임계와 독립이다. 임계의 배수로 두면 임계가 큰 저빈도 소스에서
# 재알림이 영영 안 온다 (x_ornstein 임계 120h 의 3배 = 15일 > 실제 경과 12.6일).
FRESHNESS_REALERT_HOURS = 48.0


@dataclass
class FreshnessHold:
    """stale 이지만 이번 회차에 안 알리는 소스 — 로그로 사유를 남기는 데 쓴다."""
    source_id: str
    age_hours: float
    hours_to_next: float


def _realert_level(age_hours: float, threshold_hours: float,
                   interval_hours: float) -> int:
    """임계를 넘은 뒤 몇 번째 간격 구간에 있는가 — 임계 안이면 -1."""
    if age_hours <= threshold_hours:
        return -1
    return int((age_hours - threshold_hours) // interval_hours)


def freshness_alert_split(records: list[SourceFreshness],
                          previous: dict[str, dict],
                          interval_hours: float = FRESHNESS_REALERT_HOURS
                          ) -> tuple[list[SourceFreshness], list[FreshnessHold]]:
    """stale 소스를 이번 회차 발송분과 보류분으로 가른다 (스펙 2026-08-14 §4.2).

    임계를 넘은 회차에 한 번 알리고, 그 뒤 경과가 interval_hours 씩 늘 때마다 다시
    알린다. 발송 사실을 따로 저장하지 않고 previous (직전 회차의 source_freshness 행 ·
    source_id → age_hours · threshold_hours) 와 비교하는 무상태 전이 판정이다 —
    candidate_cliffs 와 같은 방식.
    직전 행이 없거나 (첫 회차) 그때 임계가 지금과 다르면 비교 기준이 없어 알린다.
    임계를 고친 회차는 새 규칙으로 처음 판정하는 회차이므로 옛 판정을 '이미 알렸다' 의
    근거로 쓸 수 없다."""
    send: list[SourceFreshness] = []
    hold: list[FreshnessHold] = []
    for r in records:
        if not r.stale:
            continue
        prev = previous.get(r.source_id)
        level = _realert_level(r.age_hours, r.threshold_hours, interval_hours)
        prev_level = -1
        if (prev is not None and prev.get("age_hours") is not None
                and float(prev["threshold_hours"]) == r.threshold_hours):
            prev_level = _realert_level(float(prev["age_hours"]),
                                        r.threshold_hours, interval_hours)
        if level > prev_level:
            send.append(r)
        else:
            next_age = r.threshold_hours + (level + 1) * interval_hours
            hold.append(FreshnessHold(r.source_id, r.age_hours,
                                      round(next_age - r.age_hours, 1)))
    return send, hold


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


def candidate_cliffs(today: dict[str, int], previous: dict[str, int]) -> list[str]:
    """직전 회차에 후보가 있었는데 이번에 0 이 된 소스 (차단 알림 스펙 §3.1).

    상태 (후보 == 0) 가 아니라 전이만 잡는다 — 상태로 잡으면 이미 죽어 있는 소스가
    매 회차 발화한다 (실측 16회차에서 arsenal_official 은 16회 전부 후보 0).
    직전 회차에 후보가 있었다는 사실 자체가 '직전까지 살아 있었다' 의 증거라
    추가 이력 조건을 두지 않는다."""
    return sorted(sid for sid, n in previous.items()
                  if n > 0 and today.get(sid, 0) == 0)


# 이적성 제목 패턴 — 96h 창 47건 실측에서 오탐 0 (스펙 2026-08-07 §3.3)
# 공홈 어댑터의 제목 채택 조건도 이 상수를 쓴다 (공홈 수집 개정 스펙 2026-08-12 §3.2)
# — 수집 조건과 "놓쳤다" 고 부르는 알림 조건을 하나로 묶기 위해서다.
# 소유를 여기 두는 것은 이 모듈이 표준 라이브러리만 쓰기 때문이다 (반대 방향 참조 금지).
TRANSFER_TITLE_RE = re.compile(r"\b(joins|signs|transfer|loan)\b", re.IGNORECASE)


def filter_miss_suspects(rejects: list[dict], now: datetime,
                         recent_hours: float = 6.0) -> list[dict]:
    """Men + News 비채택 기사 중 이적 관련 제목 + 최근 발행만 추린다 (관측 전용).

    6시간 창은 3시간 회차 기준 기사당 최대 2회 발화로 도배를 막는 무상태 설계.
    발행 시각이 없거나 파싱 불가면 최근 여부를 알 수 없어 제외한다."""
    out: list[dict] = []
    for r in rejects:
        pub = r.get("published")
        if not pub:
            continue
        try:
            dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            if (now - dt).total_seconds() > recent_hours * 3600:
                continue
        except (ValueError, TypeError):
            # TypeError: naive datetime (오프셋 없는 published) 를 aware now 와 뺄 때
            # (2026-08-07 재현 — run.py 관측 루프 전멸로 이어짐)
            continue
        if TRANSFER_TITLE_RE.search(r.get("title") or ""):
            out.append(r)
    return out


# 명단 이적 축 낡음 관측 (스펙 2026-08-10) — 단계 집합은 article_players.stage 어휘.
# 완결 직후 후속 보도는 같은 완결 단계 귀속을 계속 만들므로 (메아리), 완료 축
# 선수의 방아쇠에는 초기 단계만 남긴다 (스펙 §2.1).
ROSTER_EARLY_STAGES = frozenset({"rumour", "interest", "negotiating",
                                 "personal_terms"})
ROSTER_ADVANCED_STAGES = frozenset({"agreed", "medical", "official"})
# 딜 종결 어휘 (기사 단계 재정의 스펙 2026-08-10 §4 의 PLAYERS_CLAUSE 동기화분).
# 링크 선수에게만 방아쇠다 — 축이 없는 선수에게 붙는 종결 단계는 지난 창 회고
# 보도라 갱신할 것이 없다.
ROSTER_CLOSING_STAGES = frozenset({"done", "collapsed"})
ROSTER_PROGRESS_STAGES = ROSTER_EARLY_STAGES | ROSTER_ADVANCED_STAGES
ROSTER_COMPLETION_STAGES = ROSTER_ADVANCED_STAGES | ROSTER_CLOSING_STAGES


def _roster_trigger(transfer_status: str) -> tuple[str, frozenset[str]] | None:
    if transfer_status == "none":
        return "start", ROSTER_PROGRESS_STAGES
    if transfer_status in ("in_done", "out_done"):
        return "start", ROSTER_EARLY_STAGES
    if transfer_status in ("in_link", "out_link"):
        return "finish", ROSTER_COMPLETION_STAGES
    return None


def roster_axis_staleness(cycle_pairs: list[dict],
                          recent_counts: dict[tuple[int, str], int],
                          min_recent: int = 2) -> list[dict]:
    """이번 회차 귀속과 명단 이적 축 값의 어긋남 의심 목록 (관측 전용 · 스펙 §2 · §3).

    cycle_pairs 는 확정 선수의 이번 회차 (player_id · ko_name · transfer_status ·
    stage) 목록, recent_counts 는 {(player_id, stage): 최근 7일 귀속 건수}.
    방아쇠 단계 집합 밖의 귀속은 세지 않고, 최근 누적이 min_recent 미만이면
    단발 오추출 · 단발 루머로 보고 거른다 (무상태 도배 방지의 두 번째 축)."""
    by_player: dict[int, dict] = {}
    for p in cycle_pairs:
        trig = _roster_trigger(p["transfer_status"])
        if trig is None or p["stage"] not in trig[1]:
            continue
        case = by_player.setdefault(p["player_id"], {
            "player_id": p["player_id"], "ko_name": p["ko_name"],
            "transfer_status": p["transfer_status"], "kind": trig[0],
            "new_stages": {}})
        case["new_stages"][p["stage"]] = case["new_stages"].get(p["stage"], 0) + 1
    out = []
    for pid, case in by_player.items():
        stages = _roster_trigger(case["transfer_status"])[1]
        total = sum(n for (p, s), n in recent_counts.items()
                    if p == pid and s in stages)
        if total >= min_recent:
            out.append({**case, "recent_total": total})
    return sorted(out, key=lambda c: c["ko_name"] or "")
