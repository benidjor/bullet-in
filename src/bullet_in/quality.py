from __future__ import annotations
import hashlib
import re
from collections.abc import Iterable
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
    # 기사 표에 남은 마지막 시각 — 판정에 안 쓰고 기록 · 문안에만 쓴다.
    # last_fetched_at 보다 오래됐으면 그 소스는 다른 행으로 흡수되고 있다는 뜻이다
    # (설계 2026-08-20 §3.4). 판정 뒤 run.py 가 채운다.
    stored_fetched_at: datetime | None = None
    # SLO-5 끊김 판정 (스펙 2026-10-02 §2) — evaluate_states 가 채운다.
    state: str | None = None            # ok · quiet · no_response · broken
    miss_streak: int | None = None      # 연속 무응답 횟수
    block_streak: int | None = None     # 그중 끝에서부터 이어진 차단 (전부 430) 횟수
    list_sig: str | None = None         # 마지막으로 응답한 실행의 목록 지문
    list_changed_at: datetime | None = None
    cap_hours: float | None = None
    reason: str = ""                    # 저장하지 않는다 — 알림 문안용


def list_signature(urls: Iterable[str]) -> str:
    """목록 링크 묶음의 지문 — 순서와 중복은 무시한다 (스펙 2026-10-02 §2.3.2).

    같은 기사들의 순서만 바뀐 것은 목록이 바뀐 것으로 보지 않는다."""
    uniq = sorted({u for u in urls if u})
    if not uniq:
        return ""
    return hashlib.sha256("\n".join(uniq).encode()).hexdigest()[:16]


def responded(adapter: str | None, funnel: dict | None,
              errored: bool) -> tuple[bool, str]:
    """이번 실행에 목록이 응답했는가와 무응답 사유 (스펙 2026-10-02 §2.2).

    HTML 은 제목 확인 비율 (titled ÷ deduped) 이 절반 이상이어야 응답이다 —
    제목이 확인되지 않은 링크는 이적 키워드 검사까지 가지 못하고 버려진다."""
    if errored:
        return False, "error"
    if not funnel:
        return False, "no_record"
    if adapter == "html":
        links, titled = int(funnel.get("deduped", 0)), int(funnel.get("titled", 0))
        if links == 0:
            return False, "no_links"
        if titled * 2 < links:
            return False, "title_ratio"
        # 수집 단계 기록이 없으면 목록 서명을 얻지 못했다 (스펙 2026-10-02 §2.2.4)
        if not funnel.get("list_sig"):
            return False, "no_record"
        return True, ""
    if adapter == "x_playwright":
        if int(funnel.get("scraped", 0)) == 0:
            return False, "no_tweets"
        # 수집 단계 기록이 없으면 목록 서명을 얻지 못했다 (스펙 2026-10-02 §2.2.4)
        if not funnel.get("list_sig"):
            return False, "no_record"
        return True, ""
    if adapter == "fmkorea":
        if int(funnel.get("searched", 0)) == 0:
            # 전부 430 이면 상대 사이트의 일시 차단이다 — 회차마다 독립적으로 약 44% 걸리고
            # 저절로 풀린다 (트러블슈팅 2026-10-03). 코드가 섞이거나 없으면 검색 실패로 둔다.
            if set(funnel.get("codes") or {}) == {"430"}:
                return False, "blocked"
            return False, "search_failed"
        if int(funnel.get("listed", 0)) == 0:
            return False, "no_results"
        # 수집 단계 기록이 없으면 목록 서명을 얻지 못했다 (스펙 2026-10-02 §2.2.4)
        if not funnel.get("list_sig"):
            return False, "no_record"
        return True, ""
    if adapter == "rss":
        # 피드가 200 이어도 피드가 아닌 페이지면 항목이 0개다 (설계 2026-10-05 §3.1)
        if int(funnel.get("entries", 0)) == 0:
            return False, "no_entries"
        # 수집 단계 기록이 없으면 목록 서명을 얻지 못했다 (스펙 2026-10-02 §2.2.4)
        if not funnel.get("list_sig"):
            return False, "no_record"
        return True, ""
    return True, ""


# 목록이 이만큼 바뀌지 않으면 「옛 글만 보이는」 고장으로 본다 (스펙 2026-10-02 §2.3.3).
LIST_UNCHANGED_CAP_HOURS = 48.0


def _miss_runs_to_break(r: SourceFreshness, blocked_runs: dict[str, int] | None) -> int:
    """끊김까지 필요한 연속 무응답 수 — 연속 무응답이 모두 차단이면 소스별 기준, 아니면 2."""
    n = (blocked_runs or {}).get(r.source_id)
    if n and r.block_streak and r.block_streak == r.miss_streak:
        return n
    return 2


def evaluate_states(records: list[SourceFreshness],
                    responses: dict[str, tuple[bool, str]],
                    sigs: dict[str, str | None], cap_hours: float,
                    previous: dict[str, dict], now: datetime,
                    blocked_runs: dict[str, int] | None = None,
                    cap_overrides: dict[str, float] | None = None) -> None:
    """소스마다 상태 넷 가운데 하나를 매기고 이어 적을 값을 채운다 (스펙 §2.1 · §2.5).

    무응답 실행은 지문과 바뀐 시각을 직전 값 그대로 잇는다 — 비워 두면 다음 응답
    실행이 빈 값과 비교해 목록이 그대로여도 「바뀜」 으로 판정한다.
    blocked_runs 는 차단 (전부 430) 만 이어질 때 끊김까지 기다릴 소스별 회차 수다
    (스펙 2026-10-02 §8 · 2026-10-03 개정).
    cap_overrides 는 「목록 그대로」 상한의 소스별 값이다 — 팀 페이지 · 기자 한 명의
    타임라인처럼 원문이 조용하면 목록 전체가 멈추는 소스에 둔다 (스펙 §9)."""
    for r in records:
        ok, reason = responses.get(r.source_id, (False, "no_record"))
        prev = previous.get(r.source_id) or {}
        prev_sig, prev_changed = prev.get("list_sig"), prev.get("list_changed_at")
        if ok:
            r.miss_streak = 0
            r.list_sig = sigs.get(r.source_id) or None
            r.list_changed_at = (now if prev_changed is None or r.list_sig != prev_sig
                                 else prev_changed)
        else:
            r.miss_streak = int(prev.get("miss_streak") or 0) + 1
            r.list_sig = prev_sig
            r.list_changed_at = prev_changed or now
        if ok or reason != "blocked":
            r.block_streak = 0
        elif prev.get("block_streak") is None:
            # 칼럼이 생기기 전 행 — 그 무응답도 같은 차단으로 이어 센다. fmkorea 무응답 사유는
            # 228회차 동안 430 뿐이었고, 섞임으로 보면 배포 첫 회차에 알림이 나간다.
            r.block_streak = r.miss_streak
        else:
            r.block_streak = int(prev["block_streak"]) + 1
        r.cap_hours = (cap_overrides or {}).get(r.source_id, cap_hours)
        unchanged = (now - r.list_changed_at).total_seconds() / 3600
        if not ok and r.miss_streak >= _miss_runs_to_break(r, blocked_runs):
            r.state, r.reason = "broken", reason
        elif unchanged > r.cap_hours:
            r.state, r.reason = "broken", "list_unchanged"
        elif not ok:
            r.state, r.reason = "no_response", reason
        elif r.stale:
            r.state, r.reason = "quiet", ""
        else:
            r.state, r.reason = "ok", ""


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


# 무응답 끊김의 재알림 단위 — 3시간 실행 × 16 = 48시간 (스펙 2026-10-02 §4.1.2).
REALERT_RUNS = 16
RUN_INTERVAL_HOURS = 3.0          # DAG 스케줄 0 */3 * * * — 「다음 알림까지」 표시에만 쓴다


def _broken_level(miss_streak, list_changed_at, cap_hours, at,
                  interval_hours: float, runs_per_interval: int,
                  block_streak=None, block_runs: int | None = None) -> tuple[str, int, float]:
    """끊긴 종류 · 재알림 구간 · 다음 구간까지 남은 시간 (시간)."""
    blk = block_streak or 0
    if block_runs and blk and blk == (miss_streak or 0):
        # 차단만 이어지는데 아직 기준 아래라면 무응답으로는 안 끊겼다 — 끊겼다면 목록 그대로 (아래 list)
        if blk >= block_runs:
            done = blk - block_runs
            level = done // runs_per_interval
            return "block", level, ((level + 1) * runs_per_interval - done) * RUN_INTERVAL_HOURS
    elif (miss_streak or 0) >= 2:
        done = miss_streak - 2
        level = done // runs_per_interval
        return "miss", level, ((level + 1) * runs_per_interval - done) * RUN_INTERVAL_HOURS
    over = (at - list_changed_at).total_seconds() / 3600 - (cap_hours or 0.0)
    level = int(over // interval_hours)
    return "list", level, round((level + 1) * interval_hours - over, 1)


def broken_alert_split(records: list[SourceFreshness], previous: dict[str, dict],
                       now: datetime,
                       interval_hours: float = FRESHNESS_REALERT_HOURS,
                       runs_per_interval: int = REALERT_RUNS,
                       blocked_runs: dict[str, int] | None = None
                       ) -> tuple[list[SourceFreshness], list[FreshnessHold]]:
    """끊김 소스를 이번 실행 발송분과 보류분으로 가른다 (스펙 2026-10-02 §4.1.2).

    직전 행과 비교하는 무상태 판정이다. 직전 행이 끊김이 아니었거나, 끊긴 종류가
    바뀌었거나, 상한이 바뀌었거나, 재알림 구간이 올라가면 보낸다."""
    send: list[SourceFreshness] = []
    hold: list[FreshnessHold] = []
    for r in records:
        if r.state != "broken":
            continue
        n = (blocked_runs or {}).get(r.source_id)
        kind, level, to_next = _broken_level(r.miss_streak, r.list_changed_at, r.cap_hours,
                                             now, interval_hours, runs_per_interval,
                                             r.block_streak, n)
        prev = previous.get(r.source_id) or {}
        if (prev.get("state") == "broken" and prev.get("cap_hours") == r.cap_hours
                and prev.get("checked_at") is not None):
            p_kind, p_level, _ = _broken_level(
                prev.get("miss_streak"), prev.get("list_changed_at"), prev.get("cap_hours"),
                prev["checked_at"], interval_hours, runs_per_interval,
                prev.get("block_streak"), n)
            if p_kind == kind and level <= p_level:
                hold.append(FreshnessHold(r.source_id, r.age_hours or 0.0, to_next))
                continue
        send.append(r)
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


# 미등재 구단 탐지 (2026-08-28 사용자 결정) — 자동 등재가 아니라 자동 관측이다.
#
# `club_map.yaml` 은 번역 환각 검출 사전이라 (`enrich.detect_club_injection`) 번역
# 결과에서 뽑아 자동으로 등재하면 모델이 지어낸 이름이 자기 환각을 승인하는 되먹임이
# 생긴다. 그래서 후보만 모아 사람에게 알리고 등재는 사람이 한다.
#
# 구단이 오는 자리는 제목 첫 절의 머리말이다 (「알 힐랄, 마르티넬리 영입 임박」).
# 그 자리에는 사람 이름도 자주 와서 (「아르테타 감독, …」) 선수 · 기자 사전으로 거른다.
# 남는 잡음은 **되풀이되지 않는다** — 실제 구단은 여러 기사에 나오고 문장 조각은 한 번
# 나온다. 그래서 문턱을 두는 것이 필터의 본체다 (2026-08-28 실측: 문턱 3 에서 알 힐랄 7 ·
# 에버튼 3 을 잡고 오탐 0 · 문턱이 없으면 후보가 45종으로 늘어 읽을 수 없다).
_CLUB_HEAD_SPLIT = re.compile(r"[,·:]")
_CLUB_HEAD_MAX = 14


def club_head(title: str) -> str | None:
    """제목 첫 절의 머리말 — 구단이 오는 자리. 없거나 문장 조각이면 None."""
    fc = (title or "").split("…")[0].split("...")[0]
    head = _CLUB_HEAD_SPLIT.split(fc)[0].strip()
    if not head or len(head) > _CLUB_HEAD_MAX:
        return None
    return head


def missing_club_candidates(titles: list[str], clubs, people, journalists,
                            min_count: int = 3) -> list[dict]:
    """구단 목록에 없는 구단 후보 — 되풀이되는 것만 (관측 전용).

    titles 는 대조할 제목 전량, clubs 는 `club_map.yaml` 의 키, people 은 선수 · 스태프
    표기, journalists 는 기자 사전 키다. 아스날로 시작하는 제목은 우리 관점이라 뺀다."""
    counts: dict[str, int] = {}
    example: dict[str, str] = {}
    for t in titles:
        head = club_head(t)
        if not head or head.startswith("아스날") or head.startswith("아스널"):
            continue
        if any(c and c in head for c in clubs):
            continue                      # 이미 등재된 구단
        if any(p and p in head for p in people):
            continue                      # 선수 · 스태프
        if any(j and j in head for j in journalists):
            continue                      # 기자
        counts[head] = counts.get(head, 0) + 1
        example.setdefault(head, t)
    return sorted(({"name": h, "count": n, "example": example[h]}
                   for h, n in counts.items() if n >= min_count),
                  key=lambda c: (-c["count"], c["name"]))
