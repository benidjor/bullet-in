from __future__ import annotations
import json
import logging
import os
import re
import shutil
import yaml
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from bullet_in import transfer_stage as _stage
from bullet_in.credibility import norm_alias
from bullet_in.enrich import attrib_core, roundup_attrib_counts

log = logging.getLogger(__name__)

_TPL_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"


def humanize_when(dt: datetime, now: datetime) -> str:
    delta = now - dt
    secs = delta.total_seconds()
    if secs < 60:
        return "방금 전"
    mins = int(secs // 60)
    if mins < 60:
        return f"{mins}분 전"
    hours = mins // 60
    if hours < 24:
        return f"{hours}시간 전"
    days = hours // 24
    if days <= 7:
        return f"{days}일 전"
    return dt.strftime("%Y-%m-%d")


def fmt_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _fmt_day_only(dt: datetime, now: datetime) -> str:
    """day 정밀도 표시 — 상대 시각 대신 날짜만 (실제보다 정밀한 척 금지)."""
    if dt.year == now.year:
        return f"{dt.month}월 {dt.day}일"
    return f"{dt.year}년 {dt.month}월 {dt.day}일"


_KST = timedelta(hours=9)
_WEEKDAY_KO = "월화수목금토일"


def to_kst(dt: datetime) -> datetime:
    """저장 UTC (naive) → 한국 시간 (naive). 표시 · 날짜 경계에 공통으로 쓴다 (spec1 §12)."""
    return dt + _KST


def _group_ts(row: dict) -> datetime | None:
    """날짜 묶기 · 시각 표시의 기준 시각 — published_at, 없으면 수집 시각 폴백 (spec1 §12)."""
    return row.get("published_at") or row.get("fetched_at")


def _day_label(d, today) -> str:
    delta = (today - d).days
    if delta == 0:
        return "오늘"
    if delta == 1:
        return "어제"
    return f"{d.month}월 {d.day}일 ({_WEEKDAY_KO[d.weekday()]})"


def group_by_day(articles: list[dict], now: datetime) -> list[dict]:
    """KST 날짜로 묶는다 (spec1 §6.2). 최신 날짜부터 · 그룹 안은 입력 순서 유지.
    라벨은 오늘 · 어제 · '7월 18일 (토)'. 기준 시각이 없는 행은 제외한다."""
    today = to_kst(now).date()
    buckets: dict = {}
    for a in articles:
        ts = _group_ts(a)
        if ts is not None:
            buckets.setdefault(to_kst(ts).date(), []).append(a)
    return [{"label": _day_label(d, today), "date": d, "articles": buckets[d]}
            for d in sorted(buckets, reverse=True)]


def _same_day_reports(day_blocks: list[dict], d) -> int:
    """그 날짜(d)에 실제 발행된 기사 수 (spec2 §4.1 개정).
    묶음은 날짜 경계가 없어 여러 날 기사를 품으므로, 대표 날짜와 같은 날 기사만 센다."""
    return sum(1 for b in day_blocks for a in b.get("_articles", [])
               if _group_ts(a) is not None and to_kst(_group_ts(a)).date() == d)


def group_blocks_by_day(blocks: list[dict], now: datetime) -> list[dict]:
    """사건 블록을 대표 기사의 KST 날짜로 묶는다 (spec2 §4.1).
    건수는 '묶음 N개 · 보도 M건' — 그 날짜에 배치된 묶음 수와 그 날짜에 발행된 기사 수."""
    today = to_kst(now).date()
    buckets: dict = {}
    for b in blocks:
        ts = _group_ts(b["rep"]) if b.get("rep") else None
        if ts is not None:
            buckets.setdefault(to_kst(ts).date(), []).append(b)
    out = []
    for d in sorted(buckets, reverse=True):
        day_blocks = sorted(buckets[d], key=lambda b: _sort_ts(b["rep"]), reverse=True)
        # 밴드 재출현 카드 (band_dup) 는 평소 숨김 — 헤더 건수에서 제외
        counted = [b for b in day_blocks if not b.get("band_dup")]
        out.append({"label": _day_label(d, today), "date": d, "blocks": day_blocks,
                    "n": len(counted),
                    "reports": _same_day_reports(counted, d),
                    "all_dup": not counted})
    return out


def time_in_group(row: dict) -> str:
    """날짜 그룹 안 항목의 시각 표시 (spec1 §6.2 · §12). day 정밀도는 지어내지 않고 빈 문자열."""
    if row.get("published_precision") == "day":
        return ""
    ts = _group_ts(row)
    return to_kst(ts).strftime("%H:%M") if ts else ""


def published_datetime(row: dict) -> str:
    """상세 발행 표시 (spec1 §12) — time 정밀도는 KST 날짜 + HH:MM, day 정밀도는 날짜만.
    published_at 이 없으면 빈 문자열 (없는 시각을 지어내지 않는다)."""
    pub = row.get("published_at")
    if not pub:
        return ""
    kst = to_kst(pub)
    if row.get("published_precision") == "time":
        return kst.strftime("%Y-%m-%d %H:%M")
    return kst.strftime("%Y-%m-%d")


def title_pending(row: dict) -> bool:
    """재번역 큐 대기 — title_ko 가 비어 title_original 로 폴백 중인지 (spec2 §11.1)."""
    return not row.get("title_ko") and bool(row.get("title_original"))


def gossip_when(row: dict, now: datetime) -> str:
    """가십 카드 시각 (spec2 §7 · 6-3) — 가십은 날짜 묶음이 없어 카드마다 날짜가 있어야
    순서를 알 수 있다. KST 날짜만 보여 준다 (오늘 · 어제 · 'M월 D일 (요일)').
    상세한 발행 시각은 카드 메타 줄을 줄바꿈시켜 간격을 깨므로 상세 페이지 발행 칸에만 둔다."""
    ts = _group_ts(row)
    if not ts:
        return ""
    return _day_label(to_kst(ts).date(), to_kst(now).date())


def _sort_ts(row: dict) -> tuple[datetime, datetime]:
    """정렬 키. day 정밀도는 fetched_at 을 발행일 [00:00, 23:59:59] 로 클램프해 보간."""
    pub = row.get("published_at") or datetime.min
    fet = row.get("fetched_at") or datetime.min
    if row.get("published_precision") == "day" and pub is not datetime.min:
        start = pub.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1) - timedelta(seconds=1)
        return (min(max(fet, start), end), fet)
    return (pub, fet)


def outlet_display(row: dict, sources: dict, directory: dict | None = None,
                   outlet_dir: dict | None = None) -> str:
    """facet 키 · 카드 칩이 공유하는 언론사 표시명.
    소스 outlet 폴백이 없으면 display_name (BBC Sport) 이 키가 되는데
    이 문자열은 credibility.yaml 에 없어 tier 조회가 실패한다 (spec §3.4).
    X 2순위 항목은 인용 기자 소속 (등재) · 조직 계정 정식명으로 표기하고
    미등재 핸들만 aggregator 폴백을 유지한다 (트랙 ③ 설계 ①-A).
    고정 tier X 소스 (x_ornstein · self_source) 도 같은 매핑을 탄다 — medium 조건 (PR #137 후속)."""
    src = sources.get(row.get("source_id"), {})
    if row.get("outlet"):
        return row["outlet"]
    if src.get("credibility") == "x_mentions" or src.get("medium") == "x":
        j = (row.get("journalist") or "").strip()
        entry = (directory or {}).get(norm_alias(j))
        if entry and entry.get("outlet"):
            return entry["outlet"]
        fold = (outlet_dir or {}).get(norm_alias(j.lstrip("@")))
        if fold:
            return fold
    return (src.get("outlet")
            or src.get("display_name")
            or row.get("source_id") or "")


TIER_ORDER: list[float] = [0.0, 1.0, 1.5, 2.0, 3.0, 4.0]
INITIAL_MAX_TIER = 1.5                      # 초기 노출 상한 (spec §3.2)
# 소스 · 기자 facet 그룹 견출 — 독자 라벨만 (내부 Tier 문자열 금지 · spec1 §7.1)
TIER_HEADINGS: dict[float, str] = {
    0.0: "구단 공식", 1.0: "공신력 최상", 1.5: "공신력 상",
    2.0: "공신력 중", 3.0: "공신력 하", 4.0: "공신력 최하",
}


def tier_key(tier) -> str:
    """data-tier · facet data-value · URL ?tier= 가 공유하는 표기.
    app.js 가 문자열 동등 비교를 하므로 포매터는 여기 하나만 둔다."""
    if tier is None:
        return ""
    return f"{float(tier):g}"               # 1.0 -> "1" · 1.5 -> "1.5"


def tier_label(tier) -> str:
    if tier is None:
        return "Tier ?"
    return f"Tier {tier_key(tier)}"


# ── 표시 단계 매핑 (spec1 §5 · 단계 재정의 스펙 2026-08-10 §3.1) — 저장 enum 9종을
# 독자용 8묶음으로 접는다. 저장 enum 은 건드리지 않고 (transfer_stage.py 는 enrich 와
# 공유) 표시 계층에서만 묶는다.
# medical 은 건수가 적어 이적 합의에 합친다 (협상 중 소속에서 이동 — §3) ·
# 순서는 진행이 많이 된 것부터 · collapsed 는 종결이라 맨 뒤.
_DISPLAY_STAGE: dict[str, dict] = {
    "official": {"label": "오피셜", "tone": "red", "filled": True},
    "done": {"label": "이적 완료", "tone": "blue", "filled": False},
    "agreed": {"label": "이적 합의", "tone": "red", "filled": False},
    "medical": {"label": "이적 합의", "tone": "red", "filled": False},
    "personal_terms": {"label": "개인 합의", "tone": "yellow", "filled": False},
    "negotiating": {"label": "협상 중", "tone": "green", "filled": False},
    "interest": {"label": "관심", "tone": "gray", "filled": False},
    "rumour": {"label": "루머", "tone": "gray", "filled": False},
    "collapsed": {"label": "무산", "tone": "ash", "filled": False},
}


def display_stage(enum: str | None) -> dict | None:
    """저장 단계 enum → 표시 배지 {label, tone, filled}. 미표시 (other · None) 는 None."""
    d = _DISPLAY_STAGE.get(enum or "")
    return dict(d) if d else None


# 사이드바 단계 필터 — 표시 8묶음 (라벨, 저장 enum 목록). 이적 합의가 agreed · medical 을
# 함께 건다 (단계 재정의 스펙 2026-08-10 §3 — 메디컬의 소속을 협상 중에서 이동).
_STAGE_DISPLAY_GROUPS: list[tuple[str, list[str]]] = [
    ("오피셜", ["official"]),
    ("이적 완료", ["done"]),
    ("이적 합의", ["agreed", "medical"]),
    ("개인 합의", ["personal_terms"]),
    ("협상 중", ["negotiating"]),
    ("관심", ["interest"]),
    ("루머", ["rumour"]),
    ("무산", ["collapsed"]),
]


# ── 독자 등급 라벨 (spec1 §7.1) — 내부 tier 숫자를 절대 노출하지 않는다.
_READER_TIER: dict[float, str] = {
    0.0: "구단 공식", 1.0: "공신력 최상", 1.5: "공신력 상",
    2.0: "공신력 중", 3.0: "공신력 하", 4.0: "공신력 최하",
}


def reader_tier(tier: float | None) -> str:
    """저장 tier → 독자 표기. 미상은 빈 문자열."""
    return _READER_TIER.get(float(tier), "") if tier is not None else ""


# ── 위계 표현 채널 (spec2 §3.1) — 등급 클래스 · 출처 점 · 요약 유무.
_GRADE_CLASS: dict[float, str] = {
    0.0: "g0", 1.0: "g1", 1.5: "g15", 2.0: "g2", 3.0: "g3", 4.0: "g4",
}


def grade_class(tier: float | None) -> str:
    """등급 CSS 클래스 (제목 급수 · 색 · 배경). 미상은 빈 문자열."""
    return _GRADE_CLASS.get(float(tier), "") if tier is not None else ""


def dot_info(tier: float | None) -> dict:
    """출처 점 (spec2 §3.1) — 구단 공식 = 레드 채움 · 최상 · 상 = 채움 · 나머지 = 빈 원."""
    if tier is None:
        return {"fill": False, "color": "var(--mut)"}
    t = float(tier)
    if t == 0.0:
        return {"fill": True, "color": "var(--red)"}
    if t in (1.0, 1.5):
        return {"fill": True, "color": "var(--mut)"}
    return {"fill": False, "color": "var(--mut)"}


def show_summary(tier: float | None) -> bool:
    """요약문 표시 대상 (spec2 §3.1) — 하 · 최하 (tier 3 · 4) 는 마크업에서 뺀다."""
    return tier is not None and float(tier) < 3.0


# ── 톱스토리 선정 (spec2 §5) — 히어로 1 + 주요 소식 4.
# 순서: 상위 3등급만 → 아스날 주체 → 공신력 → 영입 단계 → 최신 → 이미지 유무.
# arsenal.com 배제 규칙은 넣지 않는다 (앞 스펙 §16.1 재측정으로 무효 · spec2 §5.1).
_TOP_TIERS = {0.0, 1.0, 1.5}
# done 은 종전 체계에서 agreed 로 저장되던 "타 매체 완료 보도" 의 거처라 상위 유지
# (빠뜨리면 완료 당일 보도가 rank 0 으로 추락) · collapsed 는 결말 카드 문턱
# (ending_card 의 >= 1) 을 넘도록 negotiating 급 (단계 재정의 2026-08-10 반영).
_LEAD_STAGE_RANK = {"official": 6, "done": 5, "agreed": 4, "medical": 3,
                    "personal_terms": 2, "negotiating": 1, "collapsed": 1}
_TOP_HORIZON_DAYS = 10


def arsenal_subject(row: dict) -> bool:
    """제목이 '아스날' 로 시작하는지 — 아스날 주체 근사 (spec2 §5 · team 플래그로는 못 가림)."""
    return (row.get("title_ko") or "").lstrip().startswith("아스날")


def top_story_key(row: dict) -> tuple:
    """정렬 키 (내림차순 = 우선). 이미지 유무는 신뢰도를 밀지 않게 최하위 (spec2 §5.1)."""
    tier = row.get("tier")
    return (
        1 if arsenal_subject(row) else 0,
        -float(tier) if tier is not None else -99.0,
        _LEAD_STAGE_RANK.get(row.get("transfer_stage") or "", 0),
        _sort_ts(row)[0],
        1 if row.get("image_url") else 0,
    )


def pick_top_stories(articles: list[dict], now: datetime,
                     players: list[str] | None = None) -> dict:
    """{'lead': row|None, 'mains': [row..≤4]}. 상위 3등급 · 최근 10일 후보만 (spec1 §6.1 · spec2 §5).
    players 를 주면 히어로 + 주요 소식이 서로 다른 사건이도록 사건 key 로 dedup 한다."""
    cands = []
    for a in articles:
        tier = a.get("tier")
        if tier is None or float(tier) not in _TOP_TIERS:
            continue
        ts = _group_ts(a)
        if ts is None or (now - ts).days > _TOP_HORIZON_DAYS:
            continue
        cands.append(a)
    cands.sort(key=top_story_key, reverse=True)
    if players:
        seen: set = set()
        deduped = []
        for a in cands:
            ev = protagonist(a.get("title_ko") or "", players) or a["content_hash"]
            if ev in seen:
                continue
            seen.add(ev)
            deduped.append(a)
        cands = deduped
    # 히어로는 선정 순위 그대로, 주요 소식은 화면에서 최신 먼저 (Image #6)
    mains = sorted(cands[1:5], key=_sort_ts, reverse=True)
    return {"lead": cands[0] if cands else None, "mains": mains}


def neighbor_window(n: int, idx: int, size: int = 5) -> tuple[int, int]:
    if n <= size:
        return (0, n)
    start = idx - size // 2
    if start < 0:
        start = 0
    end = start + size
    if end > n:
        end = n
        start = end - size
    return (start, end)


def journalist_entry(row: dict, sources: dict, directory: dict | None) -> dict | None:
    """기사 1건의 기자 뷰 — 정규화 이름 (필터 · 집계 키) · 표시 라벨 · 등재 여부.
    저장값은 소스마다 형태가 다르다 (fmkorea 한글 말머리 · x 핸들 · html 풀네임)
    → 레지스트리 정식명으로 정규화하지 않으면 같은 기자가 facet 에서 갈라진다."""
    j = (row.get("journalist") or "").strip()
    if not j:
        return None
    src = sources.get(row.get("source_id")) or {}
    entry = (directory or {}).get(norm_alias(j))
    if entry is None and directory:
        # 공동 바이라인 ("A and B") — 등재 기자가 포함돼 있으면 그 기자를 대표로.
        # 정식명 단어 경계 매치만 인정, 복수 등재 시 바이라인 등장 순서 앞선 기자.
        jl = j.lower()
        best_pos = None
        for cand in {e["name"]: e for e in directory.values()}.values():
            m = re.search(rf"\b{re.escape(cand['name'].lower())}\b", jl)
            if m and (best_pos is None or m.start() < best_pos):
                entry, best_pos = cand, m.start()
    if entry:
        name, outlet, registered = entry["name"], entry["outlet"], True
    else:
        name, outlet, registered = j, src.get("outlet"), False
        # 조직 바이라인 (BBC Sport 등) → outlet 정식명으로 접기 (통칭 라벨은 제외)
        if (outlet and j != src.get("journalist_label")
                and j.lower() in {(src.get("display_name") or "").lower(),
                                  outlet.lower()}):
            name = outlet
    if j == src.get("journalist_label") or not outlet or name == outlet:
        label = name                       # 통칭 · 소속 미상 · 조직 → 괄호 생략
    else:
        label = f"{name} ({outlet})"
    return {"name": name, "label": label, "registered": registered}


def _outlet_tier(key: str, row: dict, sources: dict, registry) -> float | None:
    """등재 tier 우선, 없으면 소스 설정 tier (spec §3.4)."""
    if registry is not None:
        t = registry.outlets.get(norm_alias(key))
        if t is not None:
            return float(t)
    t = sources.get(row.get("source_id"), {}).get("tier")
    return float(t) if t is not None else None


def _journalist_tier(row: dict, entry: dict, registry) -> float | None:
    if entry["registered"] and registry is not None:
        j = norm_alias(row.get("journalist") or "")
        t = registry.journalists.get(j)
        if t is None:
            t = registry.journalists.get(norm_alias(entry["name"]))
        if t is not None:
            return float(t)
    # 비전담 · 조직 · 통칭 → 기사 저장 tier (비전담 기준선) 그룹으로 분류
    t = row.get("tier")
    return float(t) if t is not None else None


def _facet_rows(counts: Counter, labels: dict, tiers: dict) -> dict:
    """tier 그룹 · 더보기 단계로 나눈 facet 뷰모델 (spec §3.1 · §3.2).
    TIER_ORDER 에 없는 tier (설정 오류) 는 미등재로 흘려보낸다."""
    def _item(n, c):
        # data-tier — 공신력 연동 자동 체크의 매칭 키 (spec1 §7.2 · 등급 미상은 빈 값)
        return {"value": n, "label": labels.get(n, n), "count": c,
                "tier": tier_key(tiers.get(n))}

    def _sorted(pairs):
        return [_item(n, c) for n, c in sorted(pairs, key=lambda kv: kv[0].lower())]

    reg = [(n, c) for n, c in counts.items() if tiers.get(n) in TIER_ORDER]
    unreg = _sorted([(n, c) for n, c in counts.items() if tiers.get(n) not in TIER_ORDER])

    groups = {t: {"key": tier_key(t), "heading": TIER_HEADINGS[t],
                  "items": _sorted([x for x in reg if tiers[x[0]] == t])}
              for t in TIER_ORDER}

    initial = [groups[t] for t in TIER_ORDER
               if t <= INITIAL_MAX_TIER and groups[t]["items"]]

    rest = [t for t in TIER_ORDER if t > INITIAL_MAX_TIER]
    stages = []
    for t in rest:
        g = groups[t]
        is_last = (t == rest[-1])
        tail = unreg if is_last else []
        if not g["items"] and not tail:
            continue                        # 빈 tier 는 단계에서 건너뛴다
        if g["items"] and tail:
            label = f"더보기 · {reader_tier(t)} · 미등재"
        elif g["items"]:
            label = f"더보기 · {reader_tier(t)}"
        else:
            label = "더보기 · 미등재"
        stages.append({"label": label,
                       "groups": [g] if g["items"] else [],
                       "unregistered": tail})
    return {"initial": initial, "stages": stages}


def filter_stage(row: dict) -> str | None:
    """카드 · 사이드바 건수가 공유하는 필터 단계 키.
    가십 루머 롤업은 저장 계층 규칙 (rule_stage) 으로 이동 — 방향 축 스펙 §5."""
    return row.get("transfer_stage")


def in_stage_filter(stage: str | None, direction: str | None) -> bool:
    """단계 필터 (계수 · 목록) 대상인지 — 방향 in · out 한정 (단계 재정의 스펙 §8).

    무산 (collapsed) 은 예외로 방향을 보지 않는다 (§8 개정 2026-08-11): 무산은
    정의상 아스날 관련 딜의 종결에만 붙는 관점 값이라 "타 구단 딜 제외" 라는
    한정의 취지가 이미 분류 단계에서 충족돼 있고, 방향까지 걸면 잔류 확정 ·
    재계약 체결 (실측상 방향 none) 이 자기 필터에서 빠져 배지와 필터 결과가
    어긋난다. app.js 의 같은 판정과 규칙을 맞춘다."""
    return stage == "collapsed" or direction in ("in", "out")


def facet_counts(articles: list[dict], sources: dict, directory: dict | None = None,
                 registry=None, outlet_dir: dict | None = None) -> dict:
    teams = Counter(a.get("team") or "arsenal" for a in articles)

    o_ctr: Counter = Counter()
    o_tier: dict = {}
    for a in articles:
        key = outlet_display(a, sources, directory=directory, outlet_dir=outlet_dir)
        o_ctr[key] += 1
        o_tier[key] = _outlet_tier(key, a, sources, registry)

    j_ctr: Counter = Counter()
    j_labels: dict = {}
    j_tier: dict = {}
    for a in articles:
        e = journalist_entry(a, sources, directory)
        if e is None:
            continue
        j_ctr[e["name"]] += 1
        j_labels[e["name"]] = e["label"]
        j_tier[e["name"]] = _journalist_tier(a, e, registry)

    seen = Counter(tier_key(a.get("tier")) for a in articles if a.get("tier") is not None)
    # 사이드바 공신력 — 독자 라벨만 노출 (내부 Tier 문자열 금지 · spec1 §7.1)
    tiers = [{"key": tier_key(t), "reader": reader_tier(t), "count": seen.get(tier_key(t), 0)}
             for t in TIER_ORDER]

    # 단계 필터 계수는 방향 in · out (아스날 주체) 한정이다 (단계 재정의 스펙 §8).
    # 타 구단 딜 (none) 은 분류 · 배지를 유지한 채 필터 분모에서만 빠지고,
    # 전체 목록 · 팀 facet · 사건 묶음 · 선수 필터로는 계속 도달된다.
    # 기타 (other · 미분류) 계수는 방향과 무관하다 — 기타 토글의 분모는 그대로다.
    stage_counts = {e: 0 for e, _, _ in _stage.SIDEBAR_STAGES}
    other_count = 0
    for a in articles:
        s = filter_stage(a)
        if s in stage_counts:
            if in_stage_filter(s, a.get("transfer_direction")):
                stage_counts[s] += 1
        else:
            other_count += 1
    # 표시 8묶음 — 라벨 · 저장 enum 목록 (data-value) · 합산 건수 (spec1 §5)
    stage_groups = [{"label": label, "value": ",".join(enums),
                     "count": sum(stage_counts.get(e, 0) for e in enums)}
                    for label, enums in _STAGE_DISPLAY_GROUPS]

    return {"total": len(articles), "team": dict(teams),
            "tiers": tiers, "stage": stage_counts, "stage_groups": stage_groups,
            "other": other_count,
            "outlets": _facet_rows(o_ctr, {}, o_tier),
            "journalists": _facet_rows(j_ctr, j_labels, j_tier)}

# ---- 운영 뷰 (ops.html) 뷰모델 ----
# 지표 정의 · 데이터 계약: docs/superpowers/specs/2026-07-14-ops-monitoring-view-design.md §5 · §6

TIER_BUCKETS = [(1.0, "Tier 1 — 공식 · 공신력 최상"),
                (2.0, "Tier 2 — 공신력 중"),
                (3.0, "Tier 3 — 공신력 하")]
ETC_TIER_LABEL = "기타 (0 · 1.5 · 4)"


def spark_points(values: list[float], width: int = 84, height: int = 18) -> str:
    if not values:
        return ""
    vmin, vmax = min(values), max(values)
    span = max(vmax - vmin, 1)                      # 전부 동일값 → 분모 1 (평평한 선)
    n = len(values)
    pts = []
    for i, v in enumerate(values):
        x = 0 if n == 1 else i * width / (n - 1)
        y = (height - 2) - (v - vmin) / span * (height - 4)
        pts.append(f"{x:.0f},{y:.0f}")
    return " ".join(pts)


def _kpi(runs: list[dict], stale_count: int | None, pending_total: int) -> dict:
    if not runs:
        return {"new": "—", "dup": "—", "err": "—", "success": "—",
                "stale": "—", "pending": str(pending_total)}
    top = runs[0]
    return {"new": str(top["new_count"]), "dup": str(top["dup_count"]),
            "err": str(top["error_count"]),
            "success": f"{top['success_rate'] * 100:.0f}%",
            "stale": "—" if stale_count is None else str(stale_count),
            "pending": str(pending_total)}


def build_ops_view(snapshot: dict, sources: dict, anomaly_count: int,
                   now: datetime) -> dict:
    runs = snapshot["runs"]                          # 최신순
    chrono = list(reversed(runs))                    # 차트는 과거 → 최신

    max_new = max((r["new_count"] for r in chrono), default=0) or 1
    runs_chart = [{
        "h": round(r["new_count"] / max_new * 100),
        "err": r["error_count"] > 0,
        "label": (f"{r['started_at']:%m-%d %H:%M} UTC · 신규 {r['new_count']}"
                  f" · 중복 {r['dup_count']} · 에러 {r['error_count']}"),
    } for r in chrono]

    fresh_rows = snapshot["freshness"]               # checked_at 오름차순
    latest_run = fresh_rows[-1]["run_id"] if fresh_rows else None
    latest = {r["source_id"]: r for r in fresh_rows if r["run_id"] == latest_run}
    history: dict[str, list[float]] = {}
    for r in fresh_rows:                              # 부재 회차 없음 = 진짜 결측 (§6.1)
        if r["age_hours"] is not None:
            history.setdefault(r["source_id"], []).append(float(r["age_hours"]))
    freshness = []
    for sid, row in sorted(latest.items()):
        disp = sources.get(sid, {}).get("display_name") or sid
        if row["age_hours"] is None:
            freshness.append({"display": disp, "last": "이력 없음", "age": "—",
                              "thr": f"{row['threshold_hours']:.0f}h",
                              "points": "", "status": "none"})
            continue
        freshness.append({
            "display": disp,
            "last": f"{row['last_fetched_at']:%m-%d %H:%M}",
            "age": f"{row['age_hours']:.1f}h",
            "thr": f"{row['threshold_hours']:.0f}h",
            "points": spark_points(history.get(sid, [])),
            "status": "stale" if row["stale"] else "fresh",   # 저장값 그대로 (§6.2)
        })
    stale_count = (sum(1 for r in latest.values() if r["stale"])
                   if latest else None)

    trend = runs[:12]                                 # 신선도 추세와 같은 12회 창
    totals = {sid: sum(r["source_counts"].get(sid, 0) for r in trend)  # 부재 = 0 (§6.1)
              for sid in sources}
    max_total = max(totals.values(), default=0) or 1
    pending = snapshot["pending"]
    volume = [{
        "display": sources.get(sid, {}).get("display_name") or sid,
        "total": total,
        "bar_pct": round(total / max_total * 100),
        "translate": pending.get(sid, {}).get("translate", 0),
        "stage": pending.get(sid, {}).get("stage", 0),
    } for sid, total in sorted(totals.items(), key=lambda kv: -kv[1])]
    pending_total = sum(p["translate"] + p["stage"] for p in pending.values())

    tier_counts = snapshot["tier_counts"]
    total_articles = sum(tier_counts.values()) or 1
    known = {t for t, _ in TIER_BUCKETS}
    tiers = [{"label": label, "count": tier_counts.get(t, 0),
              "pct": round(tier_counts.get(t, 0) / total_articles * 100)}
             for t, label in TIER_BUCKETS]
    etc = sum(n for t, n in tier_counts.items() if t not in known)
    tiers.append({"label": ETC_TIER_LABEL, "count": etc,
                  "pct": round(etc / total_articles * 100)})

    if runs:
        avg_sr = sum(r["success_rate"] for r in runs) / len(runs)
        avg_dur = sum(r["duration_sec"] for r in runs) / len(runs)
        fetch_vals = [r["fetch_duration_sec"] for r in runs
                      if r.get("fetch_duration_sec") is not None]  # NULL 이력 제외 (§6)
        avg_fetch = sum(fetch_vals) / len(fetch_vals) if fetch_vals else None
        slo = [
            {"slo_id": "SLO-2", "definition": "최근 30회 평균 success_rate",
             "value": f"{avg_sr * 100:.1f}%",
             "status": "ok" if avg_sr >= 0.9 else "bad"},
            {"slo_id": "SLO-5", "definition": "수집 끊긴 소스 수 (최신 run)",
             "value": "—" if stale_count is None else str(stale_count),
             "status": "info" if stale_count is None else ("ok" if not stale_count else "bad")},
            {"slo_id": "SLO-6", "definition": "현재 회차 이상 감지 소스 수",
             "value": str(anomaly_count),
             "status": "ok" if anomaly_count == 0 else "bad"},
            {"slo_id": "duration", "definition": "최근 30회 평균 소요 시간",
             "value": f"{avg_dur:.0f}s", "status": "info"},
            {"slo_id": "fetch_duration", "definition": "최근 30회 평균 fetch 시간",
             "value": "—" if avg_fetch is None else f"{avg_fetch:.0f}s",
             "status": "info"},
        ]
    else:
        slo = []

    # snapshot.get — 옛 스냅샷 (키 없음) 으로도 렌더가 죽지 않게 한다
    high = snapshot.get("high_retention") or []

    return {"generated_at": f"{now:%Y-%m-%d %H:%M} UTC",
            "kpi": _kpi(runs, stale_count, pending_total),
            "runs_chart": runs_chart, "freshness": freshness,
            "volume": volume, "tiers": tiers, "slo": slo,
            "high_retention": [{"content_hash": r["content_hash"],
                                "outlet": r["outlet"] or "—",
                                "retention": f"{r['retention']:.2f}",
                                "href": f"article/{r['content_hash']}.html"}
                               for r in high],
            "high_retention_count": len(high)}

def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(_TPL_DIR),
        autoescape=select_autoescape(default_for_string=True, default=True),
    )
    env.globals["stages"] = _stage.SIDEBAR_STAGES
    env.filters["md_bold"] = _md_bold
    return env


def _norm_img(url: str) -> str:
    """CDN 리사이즈 변형 (쿼리스트링) 을 무시한 이미지 동일성 비교 키."""
    return url.split("?", 1)[0]


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _md_bold(text: str) -> Markup:
    """이스케이프 후 **굵게**만 <strong>으로 — 경량 마크다운 인라인 변환."""
    return Markup(_BOLD_RE.sub(r"<strong>\1</strong>", str(escape(text))))


def _para_block(p: str) -> dict:
    """경량 마크다운 블록 분류: '### '=소제목, '> '=인용, 그 외 문단."""
    if p.startswith("### "):
        return {"type": "h3", "text": p[4:].strip()}
    if p.startswith("> "):
        return {"type": "quote", "text": p[2:].strip()}
    return {"type": "p", "text": p}


def interleave_body(paras: list[str], images: list[str], every: int = 2) -> list[dict]:
    """번역 문단과 인라인 이미지의 교차 블록 시퀀스.
    every 문단마다 이미지 1장, 이미지 소진 후엔 문단만, 남는 이미지는 버린다."""
    blocks, qi = [], 0
    for i, p in enumerate(paras, 1):
        blocks.append(_para_block(p))
        if qi < len(images) and i % every == 0:
            blocks.append({"type": "img", "url": images[qi]})
            qi += 1
    return blocks


def serving_mode(source_id: str | None, sources: dict) -> str:
    """소스별 상세 페이지 서빙 범위 (spec §2.3). config 미지정 · 미상 값은 안전한 기본값 excerpt."""
    mode = (sources.get(source_id) or {}).get("serving")
    return mode if mode in ("full", "excerpt") else "excerpt"


# 라운드업 문단 끝 괄호 표지 — 출처 여부는 원문 표지 집합 (roundup_attrib_counts) 으로 판정
_TRAIL_PAREN_RE = re.compile(r"\s*\(([^()]{2,60})\)\s*$")


def gossip_itemize(blocks: list[dict], attrib_counts: dict[str, int]) -> list[dict]:
    """가십 라운드업 본문의 출처 병기 문단을 item 블록 (본문 + 출처 배지) 으로 변환.
    문단 끝 괄호의 출처명 (core) 이 원문 '(출처) , external' 표지 집합에 있을 때만 변환 —
    라운드업 뒤쪽 일정 섹션의 경기장 · 시각 괄호는 원문에 표지가 없어 그대로 남는다."""
    if not attrib_counts:
        return blocks
    out = []
    for b in blocks:
        m = _TRAIL_PAREN_RE.search(b["text"]) if b.get("type") == "p" else None
        if m and attrib_core(m.group(1)) in attrib_counts:
            out.append({"type": "item", "text": b["text"][:m.start()].strip(),
                        "source": m.group(1).strip()})
        else:
            out.append(b)
    return out


def excerpt_paras(paras: list[str], limit: int = 300, max_paras: int = 2) -> list[str]:
    """발췌 모드 본문 — 첫 1~2문단, 누적 limit 자 도달 시 중단 (문단 중간은 자르지 않음)."""
    out, total = [], 0
    for p in paras[:max_paras]:
        out.append(p)
        total += len(p)
        if total >= limit:
            break
    return out


def sweep_orphan_pages(articles: list[dict], out_dir: str | Path) -> list[str]:
    """DB 에서 빠진 기사의 잔여 페이지 파일을 삭제한다 (spec §2.6). 삭제한 파일명 목록 반환.

    렌더 대상 0건은 DB 조회 실패와 구분할 수 없으므로 삭제를 건너뛴다 (오삭제 방어).
    """
    art_dir = Path(out_dir) / "article"
    if not articles:
        log.warning("잔여 페이지 정리 건너뜀 — 렌더 대상 0건 (DB 조회 실패 가능성)")
        return []
    valid = {a["content_hash"] for a in articles}
    removed = sorted(f.name for f in art_dir.glob("*.html") if f.stem not in valid)
    for name in removed:
        (art_dir / name).unlink()
    if removed:
        log.info("잔여 페이지 %d건 삭제 (DB 에서 빠진 기사)", len(removed))
    return removed


def linked_player_label(names: str | None, title: str) -> str | None:
    """링크 선수 배지 문구 — 연결된 선수 이름으로 이 글이 왜 여기 있는지 밝힌다.

    이름을 쓰는 이유 (2026-08-02 확정): 일반 문구 "아스날 링크 선수" 는 감독 사임
    같은 글에 붙었을 때 무엇을 가리키는지 알려 주지 못한다.
    제목에 아스날이 이미 있으면 설명할 게 없어 배지를 달지 않는다
    (변형 표기 "아스널" · 영문 제목 Arsenal 포함 — 2026-08-01 오폭 실측).
    여럿이면 첫 이름만 적고 나머지는 인원으로 접는다 — 카드 머리가 길어지지 않게."""
    if not names:
        return None
    if "아스날" in title or "아스널" in title or "arsenal" in title.lower():
        return None
    people = [n for n in names.split("|") if n]
    if not people:
        return None
    if len(people) == 1:
        return f"{people[0]} 관련"
    return f"{people[0]} 외 {len(people) - 1}명 관련"


def _decorate(row: dict, sources: dict, now: datetime,
              directory: dict | None = None, outlet_dir: dict | None = None) -> dict:
    a = dict(row)
    a["_title"] = row.get("title_ko") or row.get("title_original") or ""
    a["_outlet"] = outlet_display(row, sources, directory=directory, outlet_dir=outlet_dir)
    a["_tier_label"] = tier_label(row.get("tier"))
    a["_tier_key"] = tier_key(row.get("tier"))
    pub = row.get("published_at")
    if pub and row.get("published_precision") == "day":
        a["_when"] = _fmt_day_only(pub, now)
    else:
        a["_when"] = humanize_when(pub, now) if pub else ""
    a["_published_iso"] = _sort_ts(row)[0].isoformat() if pub else ""
    a["_date"] = fmt_date(pub) if pub else ""
    iu = row.get("image_url")
    a["image_url"] = iu if iu and re.match(r"^https?://[^\s'\"()]+$", iu) else None
    try:
        parsed = json.loads(row.get("images_json") or "[]")
    except (TypeError, ValueError):
        parsed = []
    imgs = [u for u in parsed
            if isinstance(u, str) and re.match(r"^https?://[^\s'\"()]+$", u)]
    if a["image_url"]:
        hero = _norm_img(a["image_url"])
        imgs = [u for u in imgs if _norm_img(u) != hero]
    elif imgs:
        a["image_url"] = imgs[0]  # og:image 부재 → 인라인 1번을 히어로·카드 썸네일로 승격
        imgs = imgs[1:]
    # body_images: false 소스 (가십 라운드업 등) 는 썸네일만 쓰고 본문 인라인 이미지 제외
    if sources.get(row.get("source_id"), {}).get("body_images", True) is False:
        imgs = []
    a["_images"] = imgs
    u = row.get("url") or ""
    a["url"] = u if re.match(r"^https?://", u) else "#"
    st = filter_stage(row)
    a["_stage"] = st or ""
    # 단계 필터의 in · out 한정 (스펙 §8) 판정 키 — 카드 data-dir 로 나간다
    a["_dir"] = row.get("transfer_direction") or ""
    a["_stage_badge"] = _stage.is_displayable(st)
    a["_stage_label"] = _stage.label_for(st)
    a["_stage_class"] = _stage.css_for(st)
    e = journalist_entry(row, sources, directory)
    a["_journalist"] = e["name"] if e else ""   # 카드 data 속성 · 필터 키
    a["_byline"] = e["label"] if e else None    # 표시 라벨 — 기자 (언론사)
    # 개편 위계 · 표시 필드 (spec1 §5 · §7.1 · §12 · spec2 §3.1 · §11.1)
    a["_reader_tier"] = reader_tier(row.get("tier"))
    a["_grade"] = grade_class(row.get("tier"))
    a["_dot"] = dot_info(row.get("tier"))
    a["_stage_disp"] = display_stage(st)
    a["_pending"] = title_pending(row)
    a["_datetime"] = published_datetime(row)
    a["_time"] = time_in_group(row)
    a["_show_summary"] = show_summary(row.get("tier"))
    a["_ctx"] = linked_player_label(row.get("linked_players"), a["_title"])
    return a


def _sorted_latest(articles: list[dict]) -> list[dict]:
    return sorted(articles, key=_sort_ts, reverse=True)


def render_index(articles: list[dict], sources: dict, now: datetime,
                 directory: dict | None = None, registry=None,
                 outlet_dir: dict | None = None) -> str:
    ordered = [_decorate(a, sources, now, directory=directory, outlet_dir=outlet_dir)
               for a in _sorted_latest(articles)]
    players, clubs = load_player_names(), load_clubs()
    top = pick_top_stories(ordered, now, players)
    top_hashes = {a["content_hash"] for a in ([top["lead"]] if top["lead"] else []) + top["mains"]}
    rest = [a for a in ordered if a["content_hash"] not in top_hashes]

    clusters = cluster_events(rest, players)
    # 가십 — 대표만 보이되, 비대표도 숨김 카드 (_dup) 로 내보내 필터가 기사 단위로 닿게 한다
    gossip, gossip_reps = [], 0
    for c in clusters:
        if not is_gossip_cluster(c):
            continue
        rep = pick_representative(c["articles"])
        gossip_reps += 1
        for a in c["articles"]:
            if a is not rep:
                a["_dup"] = True
            gossip.append(a)
    gossip.sort(key=_sort_ts, reverse=True)   # 가십을 발행 · 수집 시각 내림차순으로 (2-2)
    for g in gossip:
        g["_gwhen"] = gossip_when(g, now)   # 가십 카드는 날짜 · time 정밀도면 시각까지 (6-3)
    if gossip:
        newest_day = to_kst(_sort_ts(gossip[0])[0]).date()
        cut = newest_day - timedelta(days=6)   # 최신 날짜 포함 7개 캘린더 날짜
        for g in gossip:
            g["_gwk"] = to_kst(_sort_ts(g)[0]).date() < cut
    gossip_hidden = sum(1 for g in gossip if g.get("_gwk") and not g.get("_dup"))
    blocks = []
    for c in clusters:
        if is_gossip_cluster(c):
            continue
        rep = pick_representative(c["articles"])
        ending = ending_card(c, clubs)
        # 대표가 이미 다른 구단 결말 기사면 결말 카드를 따로 세우지 않는다 (중복 방지)
        if ending and _is_other_club_report(rep, c["key"], clubs):
            ending = None
        branches = branch_views(related_reports(c, rep, ending, clubs), ending)
        blocks.append({"rep": rep, "ending": ending, "branches": branches,
                       "rel_count": sum(len(br["articles"]) for br in branches),
                       "count": len(c["articles"]), "_articles": c["articles"]})
    # 밴드 (히어로 · 주요 소식) 기사도 목록에 숨김 카드로 내보낸다 — 필터가 기사 단위로
    # 전 기사에 닿도록 (spec2 §6.3). 평소엔 숨김, app.js 가 필터 활성 시에만 노출.
    for a in ordered:
        if a["content_hash"] in top_hashes:
            blocks.append({"rep": a, "ending": None, "branches": [], "rel_count": 0,
                           "count": 1, "_articles": [a], "band_dup": True})
    day_blocks = group_blocks_by_day(blocks, now)

    facets = facet_counts(articles, sources, directory=directory, registry=registry,
                          outlet_dir=outlet_dir)
    return _env().get_template("index.html.j2").render(
        lead=top["lead"], mains=top["mains"], day_blocks=day_blocks,
        gossip=gossip, gossip_n=gossip_reps, gossip_hidden=gossip_hidden,
        facets=facets, active="home", root="")


def render_all(articles: list[dict], sources: dict, now: datetime,
               directory: dict | None = None, registry=None,
               outlet_dir: dict | None = None) -> str:
    """전체 기사 평면 페이지 — 사건 묶음 없이 날짜 그룹 + 시간순 낱개 카드 (spec §3)."""
    ordered = [_decorate(a, sources, now, directory=directory, outlet_dir=outlet_dir)
               for a in _sorted_latest(articles)]
    days = group_by_day(ordered, now)
    facets = facet_counts(articles, sources, directory=directory, registry=registry,
                          outlet_dir=outlet_dir)
    return _env().get_template("all.html.j2").render(
        days=days, facets=facets, active="all", root="")


# ── 사건 묶음 (spec2 §4-7) — 선수 사전 (players 확정 표기) 으로 묶는다 ──────
# 전환어 (spec2 §4.3) — 뒤에 나온 선수가 주인공. 3.1 모델 실측 표현 '불발' 을 포함한다.
_TRANSITION_WORDS = ["놓친", "대신", "대체", "무산", "불발", "결렬", "실패", "포기", "떠난"]


def load_player_names(engine=None) -> list[str]:
    """서빙 사건 사전 — players 확정 ko_name (DB 단일 원천 · 스펙 §5 · §8).
    긴 이름을 앞에 둬 부분 매치를 막는다 (기존 규칙 유지).
    engine 미지정 시 MARIADB_URL 로 생성한다 — write_site 호출부 (run.py · 런북) 는
    이미 그 env 로 돌므로 시그니처 연쇄 변경 없이 전환된다."""
    from sqlalchemy import create_engine
    from bullet_in.storage.players import PlayerStore
    engine = engine or create_engine(os.environ["MARIADB_URL"])
    names = PlayerStore(engine).serving_names()
    if not names:
        import logging
        logging.getLogger(__name__).warning(
            "players 서빙 사전이 비어 있음 — migrate_roster 미실행이면 사건 묶음이 꺼진 채 렌더된다")
    return sorted(names, key=len, reverse=True)


# ── 선수 페이지 (스펙 §4 · §5) ─────────────────────────────────────────
# 선수 단위 이적 축 배지 — players 스펙 §3.1 의 화면 배지 열을 그대로 옮긴다.
# 기사 단위 transfer_direction 은 이 화면에서 쓰지 않는다 (스펙 §4.2).
_TRANSFER_BADGE: dict[str, tuple[str, str]] = {
    "in_link": ("영입 링크", "t-inlink"),
    "out_link": ("방출 링크", "t-outlink"),
    "in_done": ("영입 완료", "t-indone"),
    "out_done": ("방출 완료", "t-outdone"),
    "loan_in": ("임대 영입", "t-loanin"),
    "loan_out": ("임대 이적", "t-loanout"),
    "link_dropped": ("링크 소멸", "t-dropped"),
    "other_club": ("타 클럽행", "t-otherclub"),
}

# 색인 4그룹 (스펙 §4.1) — (그룹명, 기본 접힘).
# 무산 · 타 클럽행은 되짚기용이라 접어 두고, 접기 · 펼치기는 네 그룹 모두에 둔다.
TRANSFER_GROUPS: list[tuple[str, bool]] = [
    ("진행 중", False), ("이적 확정", False),
    ("이적 무산", True), ("타 클럽행", True),
]

_TRANSFER_GROUP_OF: dict[str, str] = {
    "in_link": "진행 중", "out_link": "진행 중",
    "in_done": "이적 확정", "out_done": "이적 확정",
    "loan_in": "이적 확정", "loan_out": "이적 확정",
    "link_dropped": "이적 무산", "other_club": "타 클럽행",
}

# 값이 하나뿐인 그룹 — 색인에서 축 배지가 그룹명을 되풀이하거나 (타 클럽행) 같은 값을
# 다른 말로 부른다 (이적 무산 그룹의 "링크 소멸"). 그룹 안에서 가릴 것이 없으므로
# 색인에서는 배지를 생략한다 (2026-08-11). 선수 페이지는 그룹 맥락이 없어 그대로 붙인다.
_SOLE_VALUE_GROUPS = {g for g, n in Counter(_TRANSFER_GROUP_OF.values()).items() if n == 1}


def transfer_badge(status: str | None) -> dict | None:
    """선수 이적 축 배지 {label, cls}. 축이 없으면 (none) 배지를 달지 않는다."""
    d = _TRANSFER_BADGE.get(status or "")
    return {"label": d[0], "cls": d[1]} if d else None


def transfer_group(status: str | None) -> str | None:
    """색인 그룹명. 여덟 값이 4그룹으로 빠짐없이 갈리고, 그 밖의 값은 None 이다."""
    return _TRANSFER_GROUP_OF.get(status or "")


def player_slug(surname: str, player_id: int, dupes: set[str]) -> str:
    """선수 페이지 slug — 소문자 영문 성. 동성 복수면 surname-id 로 떨어뜨린다."""
    base = re.sub(r"[^a-z0-9]", "", (surname or "").lower()) or "player"
    return f"{base}-{player_id}" if base in dupes else base


def load_page_players(engine=None) -> list[dict]:
    """선수 페이지 대상 + 귀속 (스펙 §3.1) — DB 단일 원천.
    engine 미지정 시 MARIADB_URL 로 생성한다 — write_site 호출부 (run.py · 런북) 는
    이미 그 env 로 돌므로 시그니처 연쇄 변경 없이 전환된다 (load_player_names 선례)."""
    from sqlalchemy import create_engine
    from bullet_in.storage.players import PlayerStore
    store = PlayerStore(engine or create_engine(os.environ["MARIADB_URL"]))
    players = store.page_players()
    links: dict[int, list[dict]] = {}
    for l in store.page_player_links():
        links.setdefault(l["player_id"], []).append(
            {"content_hash": l["content_hash"], "stage": l["stage"]})
    for p in players:
        p["links"] = links.get(p["id"], [])
    return players


def build_player_entries(articles: list[dict], players: list[dict]) -> list[dict]:
    """선수별 기사 목록 · 진행 단계 사다리 · 현재 단계 (스펙 §5).

    기사 목록은 단계가 other 인 귀속을 뺀 나머지다.
    이름만 스친 기사가 그 선수의 이적 기사인 것처럼 쌓이던 것을 막기 위한 것이며,
    머리 건수도 같은 집합에서 나오므로 "머리 = 목록" 등식은 그대로다 (스펙 §5.3).
    서빙 목록에 없는 기사는 링크에서 빠지고, 그 결과 남는 기사가 0건인 선수는
    빈 페이지가 되지 않도록 결과에서 제외한다."""
    by_hash = {a["content_hash"]: a for a in articles}
    folded = {p["id"]: re.sub(r"[^a-z0-9]", "", (p.get("surname") or "").lower())
              for p in players}
    counts = Counter(folded.values())
    dupes = {s for s, n in counts.items() if n > 1}
    out = []
    for p in players:
        paired = [(by_hash[l["content_hash"]], l["stage"]) for l in p["links"]
                  if l["content_hash"] in by_hash and l["stage"] != _stage.OTHER]
        if not paired:
            continue
        paired.sort(key=lambda t: _sort_ts(t[0]))          # 오래된 것부터 (사다리 입력)
        timeline = [{"row": r, "stage": s} for r, s in paired]
        # 대표 선정의 이름 대조는 성 (ko_name) 으로 한다 — 기사 제목이 성만 쓰는 일이 잦다
        ko = p.get("ko_name")
        ladder = stage_ladder(timeline, ko)
        slug = player_slug(p.get("surname") or "", p["id"], dupes)
        if folded[p["id"]] in dupes:
            log.warning("동성 복수 — slug 를 id 로 떨어뜨림: %s → %s",
                        p["full_name"], slug)
        out.append({**p,
                    "name": (p.get("ko_full_name") or p.get("ko_name")
                             or p["full_name"]),
                    "slug": slug,
                    "articles": [r for r, _ in reversed(paired)],
                    "ladder": ladder,
                    "ended": ended_marker(timeline, ko),
                    # 카드 배지를 선수 축으로 바꾸는 재료 (아래 render_player)
                    "_stage_by_hash": {r["content_hash"]: s for r, s in paired},
                    "stage": current_stage(timeline, p.get("transfer_status")),
                    "count": len(paired),
                    "last_ts": _sort_ts(paired[-1][0])[0]})
    return out


_STAGE_GROUP_OF = {e: label for label, enums in _STAGE_DISPLAY_GROUPS for e in enums}


def _rep_key(name: str | None):
    """사다리 · 종결 줄의 대표 선정 키 — 그 선수를 다룬 기사가 먼저, 그다음 공신력.

    제목에 이름이 없는 기사가 대표가 되면 그 선수와 무관한 줄이 사다리에 올라온다
    (실측: 뇌르고르 사다리 세 줄이 전부 기마랑이스 기사였다 — 오귀속 기사의 공신력이
    본인 기사보다 높았다). 귀속 자체를 좁히는 것은 추출 몫이고, 여기서는 같은 묶음
    안에서 대표를 고를 때만 쓴다."""
    def key(e):
        title = e["row"].get("title_ko") or e["row"].get("title_original") or ""
        return (0 if name and name in title else 1, _ladder_cred(e))
    return key


def stage_ladder(entries: list[dict], name: str | None = None) -> list[dict]:
    """진행 단계 사다리 (사다리 스펙 §4.2) — 표시 묶음 6종마다 대표 기사 하나.

    입력은 오래된 것부터 정렬된 [{"row", "stage"}], 출력은 오피셜이 앞이다.
    대표는 공신력 높은 순 (tier 작을수록 높음 · 미상은 최하 — pick_representative
    의 99.0 선례) 이고, 동률이면 전 묶음 공통으로 가장 늦은 기사를 뽑는다
    (§4.2 개정 2026-08-07) — 줄의 날짜가 그 단계의 최신 보도를 가리켜야 이른
    기사끼리 날짜가 뒤섞여 보이는 위화감이 줄고, 공홈의 마지막 공지 = 현재 상태
    규칙도 같은 식으로 흡수된다. count 는 묶음 전체 건수 (대표 포함) 라
    머리 · 사이드바 건수와 셈법이 같다. other · 빈 값은 줄도 건수도 없다."""
    buckets: dict[str, list[dict]] = {}
    for e in entries:
        if not _stage.is_displayable(e.get("stage")):
            continue
        buckets.setdefault(_STAGE_GROUP_OF[e["stage"]], []).append(e)

    out = []
    for label, enums in _STAGE_DISPLAY_GROUPS:
        if "collapsed" in enums:
            # collapsed 는 진행 단계가 아니라 사다리 축에 넣지 않는다 — 종결 표시는
            # ended_marker() 가 따로 만든다 (단계 재정의 스펙 §8). 판정은 표시 라벨이
            # 아니라 enum 으로 — ended_marker 와 기준을 하나로 맞춘다.
            continue
        b = buckets.get(label)
        if not b:
            continue
        # 뒤집어 넣어 동률에서 늦은 기사가 이기게 한다 (min 은 안정 선택 — 첫 최소값).
        rep = min(reversed(b), key=_rep_key(name))
        out.append({"row": rep["row"], "stage": rep["stage"], "count": len(b)})
    return out


def _ladder_cred(e):
    t = e["row"].get("tier")
    return float(t) if t is not None else 99.0


# 종결 단계와 그것을 뒷받침해야 하는 명단 축 값.
# 오피셜은 종결에 넣지 않는다: 공홈은 합의 때 · 확정 때 각각 올라와 종결을 뜻하지
# 않고, 사다리 첫 줄 (오피셜) 을 현재 상태로 읽으면 실측 다섯 명이 전부 틀렸다 (§6.2).
_COMPLETED = {"in_done", "out_done", "loan_in", "loan_out"}
_TERMINAL_BACKING = {
    "official": _COMPLETED,
    "done": _COMPLETED,
    "collapsed": {"link_dropped", "other_club"},
}


def current_stage(entries: list[dict], transfer_status: str | None = None) -> str | None:
    """머리 · 색인 카드에 붙는 현재 단계 (사다리 스펙 §6.2 개정 2026-08-11).

    원래는 시간축 최신값만 썼는데, 딜이 끝난 뒤에도 그 선수를 배경으로만 언급한
    기사가 뒤에 오면 그 기사의 단계가 현재 상태를 덮어썼다 (실측: 재계약으로 끝난
    비니시우스가 '협상 중' 으로 표시). 그래서 종결 단계 (이적 완료 · 무산) 가 있으면
    가장 늦은 종결을 현재 상태로 삼는다.

    단, 종결은 **명단 축이 뒷받침할 때만** 쓴다. 명단 축은 사람이 확정한 현재 상태라
    모델이 낸 기사 단계보다 믿을 만하고, 두 배지가 서로 모순되지 않아야 한다.
    이 가드가 없으면 상류 오분류 한 건이 배지를 영구히 지배한다 — 실측에서 영입을
    마친 업슨이 무산으로, 아직 이적하지 않은 코네 · 알바레스가 무산으로 뒤집혔다.
    뒷받침이 없으면 종전대로 시간축 최신값을 쓴다.

    이적을 마친 선수에게 공홈 발표가 있으면 그것을 먼저 쓴다 — 구단 공식 발표가
    가장 강한 신호이고, 완료 기사 유무에 따라 어떤 선수는 오피셜 · 어떤 선수는
    이적 완료로 갈리던 것을 없앤다 (실측 9명 중 6명이 공홈 발표 보유).
    진행 중인 선수의 공홈 합의 공지가 현재 상태를 가로채던 옛 문제는 명단 축
    뒷받침 조건이 막는다 (§6.2 의 다섯 명 실측).
    입력은 오래된 것부터 정렬된 [{"row", "stage"}] 다."""
    def denied(stage: str | None) -> bool:
        backing = _TERMINAL_BACKING.get(stage or "")
        return bool(backing) and transfer_status not in backing

    if transfer_status in _COMPLETED and any(e.get("stage") == "official" for e in entries):
        return "official"
    for e in reversed(entries):
        backing = _TERMINAL_BACKING.get(e.get("stage") or "")
        if backing and transfer_status in backing:
            return e["stage"]
    # 명단이 부정하는 종결은 최신값 경로에서도 뺀다 — 두 배지가 모순되면 안 된다
    # (영입 완료 선수 옆에 무산, 링크 소멸 선수 옆에 협상 중이 붙던 자리).
    return next((e["stage"] for e in reversed(entries)
                 if _stage.is_displayable(e.get("stage")) and not denied(e.get("stage"))),
                None)


def ended_marker(entries: list[dict], name: str | None = None) -> dict | None:
    """무산 (collapsed) 종결 표시 (단계 재정의 스펙 §8) — 사다리 축 밖의 한 줄.
    대표 선정 규칙은 사다리와 동일 (그 선수를 다룬 기사 우선 · 공신력 · 늦은 기사)."""
    b = [e for e in entries if e.get("stage") == "collapsed"]
    if not b:
        return None
    rep = min(reversed(b), key=_rep_key(name))
    return {"row": rep["row"], "stage": rep["stage"], "count": len(b)}


def render_players(entries: list[dict], now: datetime) -> str:
    """선수 색인 (스펙 §4) — 4그룹 · 그룹 안 최근 보도일 내림차순."""
    groups = []
    for name, collapsed in TRANSFER_GROUPS:
        members = [e for e in entries if transfer_group(e["transfer_status"]) == name]
        members.sort(key=lambda e: e["last_ts"], reverse=True)
        for e in members:
            e["_badge"] = (None if name in _SOLE_VALUE_GROUPS
                           else transfer_badge(e["transfer_status"]))
            e["_stage"] = display_stage(e["stage"])
            e["_last"] = fmt_date(to_kst(e["last_ts"]))
        groups.append({"name": name, "collapsed": collapsed, "members": members})
    return _env().get_template("players.html.j2").render(
        groups=groups, active="players", root="", solo=True)


def render_player(entry: dict, sources: dict, now: datetime,
                  directory: dict | None = None,
                  outlet_dir: dict | None = None) -> str:
    """선수 페이지 (스펙 §5) — 머리 · 진행 단계 사다리 · 귀속 기사 전량."""
    decorated = {}
    by_stage = entry.get("_stage_by_hash") or {}
    for a in entry["articles"]:
        d = _decorate(a, sources, now, directory=directory, outlet_dir=outlet_dir)
        # _decorate 의 _date 는 UTC 라 사다리 · 카드가 머리와 다른 날짜로 보일 수
        # 있다 — 선수 페이지 지역 범위로만 KST 로 보정한다.
        d["_kdate"] = fmt_date(to_kst(_sort_ts(a)[0]))
        # 카드 배지도 선수 축으로 바꾼다 (2026-08-11). 기사 축을 그대로 쓰면 아스날과
        # 무관한 딜의 단계가 그 선수의 카드에 붙는다 — 아스날 건이 관심에서 멈춘
        # 스톤스의 카드에 인터 밀란과의 "이적 합의" 가 뜨던 자리다.
        # 같은 페이지의 사다리도 선수 축이라 두 표시가 이제 같은 축을 쓴다.
        ps = by_stage.get(a["content_hash"])
        d["_stage"] = ps or ""
        d["_stage_disp"] = display_stage(ps)
        decorated[a["content_hash"]] = d
    nodes = [{"a": decorated[n["row"]["content_hash"]],
              "badge": display_stage(n["stage"]), "count": n["count"]}
             for n in entry["ladder"]]
    ended = entry.get("ended")
    if ended:
        # 무산 종결 줄 — 같은 tlnode 마크업에 end 플래그만 얹어 단일 루프로 그린다.
        # 맨 위에 둔다 (개정 2026-08-11): 사다리는 위가 가장 진행된 단계라, 끝난 사가의
        # 종결을 아래에 두면 아직 진행 중인 것처럼 읽힌다 (실측 · 비니시우스 페이지).
        nodes.insert(0, {"a": decorated[ended["row"]["content_hash"]],
                         "badge": display_stage(ended["stage"]),
                         "count": ended["count"], "end": True})
    return _env().get_template("player.html.j2").render(
        e=entry, badge=transfer_badge(entry["transfer_status"]),
        stage=display_stage(entry["stage"]), nodes=nodes,
        articles=[decorated[a["content_hash"]] for a in entry["articles"]],
        last=fmt_date(to_kst(entry["last_ts"])),
        active="players", root="../", solo=True)


def load_clubs(path: str = "config/club_map.yaml") -> dict:
    """구단 검출 사전 (결말 · 행선지 칩) — club_map 의 한글 구단명."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return data.get("clubs") or {}


def _first_clause(title: str) -> str:
    """제목 첫 절 — '…' 앞까지 (spec2 §6.2 · 뒤에 덧붙인 다른 사건 배제)."""
    for sep in ("…", "..."):
        i = title.find(sep)
        if i >= 0:
            return title[:i].strip()
    return title.strip()


def club_in_title(first_clause: str, club_map: dict) -> str | None:
    """첫 절에 등장하는 비-아스날 구단 (한글 키 부분 매치 · 긴 키 우선)."""
    for club in sorted(club_map or {}, key=len, reverse=True):
        if club in first_clause:
            return club
    return None


def protagonist(title: str, players: list[str]) -> str | None:
    """사건 주인공 선수 (spec2 §4.3) — 전환어 뒤 선수를 우선, 없으면 첫 등장 선수."""
    title = title or ""
    found = sorted((title.find(p), p) for p in players if p in title)
    if not found:
        return None
    trans = [title.find(w) for w in _TRANSITION_WORDS if w in title]
    if trans:
        after = [(pos, p) for pos, p in found if pos > min(trans)]
        if after:
            return min(after)[1]
    return found[0][1]


def cluster_events(articles: list[dict], players: list[str]) -> list[dict]:
    """주인공 기준 사건 묶음 (spec2 §4) — 날짜 경계 없음 · 주인공 미상은 단독 묶음.
    입력 등장 순서를 보존한다 (호출부가 최신순으로 정렬해 전달)."""
    groups: dict = {}
    order: list = []
    singles: list = []
    for a in articles:
        key = protagonist(a.get("title_ko") or a.get("title_original") or "", players)
        if key is None:
            singles.append({"key": None, "articles": [a]})
        else:
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(a)
    return [{"key": k, "articles": groups[k]} for k in order] + singles


def _arsenal_subject_rank(a: dict) -> int:
    """아스날 주어 순위 (spec2 §6.1 3번) — 제목 시작 3 · 본문 언급 2 · 없음 1."""
    if (a.get("title_ko") or "").lstrip().startswith("아스날"):
        return 3
    return 2 if "아스날" in (a.get("body_ko") or "") else 1


def pick_representative(articles: list[dict]) -> dict | None:
    """묶음 대표 (spec2 §6.1) — 구단 공식 → 최하 제외 → 아스날 주어 → 최신 → 공신력 → 단계."""
    if not articles:
        return None
    has_higher = any(a.get("tier") is not None and float(a["tier"]) < 4.0 for a in articles)

    def key(a):
        tier = a.get("tier")
        tv = float(tier) if tier is not None else 99.0
        official = 1 if tv == 0.0 else 0
        not_lowest = 0 if (has_higher and tv >= 4.0) else 1
        return (official, not_lowest, _arsenal_subject_rank(a), _sort_ts(a)[0],
                -tv, _LEAD_STAGE_RANK.get(a.get("transfer_stage") or "", 0))

    return max(articles, key=key)


# 아스날 인바운드 신호 (spec2 §6.2) — 현 소속이 제목 앞머리에 와도 아스날로 오는 사건.
# '아스날 이적 의사' 는 '아스날 이적' 에, '아스날로 이적' 은 '아스날로' 에 걸린다.
_ARSENAL_INBOUND = ("아스날 이적", "아스날 합류", "아스날행", "아스날로")


def _is_other_club_report(a: dict, key: str | None, club_map: dict) -> str | None:
    """다른 구단 관점 기사면 그 구단명, 아니면 None (제목 비-아스날 시작 + 첫 절 비아스날 구단).
    첫 절에 아스날 인바운드 신호가 있으면 현 소속이 앞머리에 와도 다른 구단행이 아니다."""
    title = a.get("title_ko") or ""
    if title.lstrip().startswith("아스날"):
        return None
    fc = _first_clause(title)
    if any(sig in fc for sig in _ARSENAL_INBOUND):
        return None
    if key and key not in fc:
        return None
    return club_in_title(fc, club_map)


def ending_card(cluster: dict, club_map: dict) -> dict | None:
    """결말 카드 (spec2 §6.2) — 다른 구단이 데려간 사건 · 단계 협상 중 이상."""
    for a in cluster["articles"]:
        club = _is_other_club_report(a, cluster["key"], club_map)
        if club and _LEAD_STAGE_RANK.get(a.get("transfer_stage") or "", 0) >= 1:
            return {"article": a, "club": club}
    return None


def related_reports(cluster: dict, rep: dict | None, ending: dict | None,
                    club_map: dict) -> dict:
    """관련 보도 갈래 (spec2 §6.3) — 아스날 관점 / 다른 구단 관점 · 각 갈래 시간순 (최신 먼저)."""
    excluded = set()
    if rep:
        excluded.add(rep["content_hash"])
    if ending:
        excluded.add(ending["article"]["content_hash"])
    arsenal_side, other_side = [], []
    for a in cluster["articles"]:
        if a["content_hash"] in excluded:
            continue
        if _is_other_club_report(a, cluster["key"], club_map):
            other_side.append(a)
        else:
            arsenal_side.append(a)
    arsenal_side.sort(key=_sort_ts, reverse=True)
    other_side.sort(key=_sort_ts, reverse=True)
    return {"arsenal": arsenal_side, "other": other_side}


def branch_views(related: dict, ending: dict | None) -> list[dict]:
    """관련 보도 갈래를 이름표와 함께 정렬 (spec2 §6.3).
    결말 있으면 다른 구단 갈래를 위로 · 갈래가 하나면 이름표 생략."""
    ars, oth = related["arsenal"], related["other"]
    if ending:
        club = ending["club"]
        branches = ([{"label": f"{club}행 관련", "articles": oth}] if oth else []) + \
                   ([{"label": "아스날 쪽 보도", "articles": ars}] if ars else [])
    else:
        branches = ([{"label": "아스날 쪽 보도", "articles": ars}] if ars else []) + \
                   ([{"label": "영입 경쟁", "articles": oth}] if oth else [])
    if len(branches) == 1:
        branches[0]["label"] = ""
    return branches


def is_gossip_cluster(cluster: dict) -> bool:
    """가십 묶음 (spec2 §7.1) — 묶음의 모든 기사가 최하 등급일 때만."""
    arts = cluster["articles"]
    return bool(arts) and all(
        a.get("tier") is not None and float(a["tier"]) >= 4.0 for a in arts)


def render_about() -> str:
    """소개 페이지 (spec1 §10) — 사이드바 없는 프로즈 페이지."""
    return _env().get_template("about.html.j2").render(
        active="about", root="", about_page=True)


def build_neighbors(ordered: list[dict], idx: int, sources: dict,
                    now: datetime, directory: dict | None = None,
                    outlet_dir: dict | None = None) -> list[dict]:
    start, end = neighbor_window(len(ordered), idx)
    out = []
    for j in range(start, end):
        d = _decorate(ordered[j], sources, now, directory=directory, outlet_dir=outlet_dir)
        d["_is_current"] = (j == idx)
        out.append(d)
    return out


def render_article(article: dict, neighbors: list[dict], current_hash: str,
                   sources: dict, now: datetime, facets: dict | None = None,
                   chips: list[dict] | None = None) -> str:
    # facets=None이면 빈 구조로 폴백 (하위 호환 유지)
    if facets is None:
        facets = {"team": {}, "tiers": [], "total": 0, "stage": {}, "stage_groups": [],
                  "other": 0, "outlets": {"initial": [], "stages": []},
                  "journalists": {"initial": [], "stages": []}}
    article = dict(article)
    paras = [p for p in (article.get("body_ko") or "").split("\n") if p.strip()]
    article["_excerpt"] = serving_mode(article.get("source_id"), sources) == "excerpt"
    article["_meta_only"] = not (article.get("body_ko") or "").strip()
    images = article.get("_images") or []
    if article["_excerpt"]:
        paras, images = excerpt_paras(paras), []
    article["_body_blocks"] = interleave_body(paras, images)
    if article.get("source_id") == "bbc_gossip":
        article["_body_blocks"] = gossip_itemize(
            article["_body_blocks"], roundup_attrib_counts(article.get("body_source")))
    return _env().get_template("detail.html.j2").render(
        a=article, neighbors=neighbors, active=None, root="../", facets=facets,
        chips=chips or [])


def player_chips(entries: list[dict]) -> dict[str, list[dict]]:
    """기사 → 그 기사에 걸린 선수 칩 (스펙 §6). 페이지가 만들어진 선수만 담는다
    — 페이지 없는 선수에게 칩을 달면 죽은 링크가 된다."""
    out: dict[str, list[dict]] = {}
    for e in entries:
        for a in e["articles"]:
            out.setdefault(a["content_hash"], []).append(
                {"name": e["name"], "slug": e["slug"]})
    return out


def write_player_pages(entries: list[dict], sources: dict, out_dir: str | Path,
                       now: datetime, directory: dict | None = None,
                       outlet_dir: dict | None = None) -> None:
    """선수 색인 · 선수 페이지 생성과 고아 정리.

    대상 0건이면 삭제를 건너뛴다 — DB 조회 실패와 구분할 수 없어, 조회가 비면
    기존 선수 페이지를 전부 지우게 된다 (draft 리뷰에서 잡힌 결함 · 스펙 §5.4)."""
    out = Path(out_dir)
    (out / "player").mkdir(parents=True, exist_ok=True)
    (out / "players.html").write_text(render_players(entries, now), encoding="utf-8")
    keep = set()
    for e in entries:
        keep.add(f"{e['slug']}.html")
        (out / "player" / f"{e['slug']}.html").write_text(
            render_player(e, sources, now, directory=directory, outlet_dir=outlet_dir),
            encoding="utf-8")
    if not entries:
        log.warning("선수 페이지 정리 건너뜀 — 대상 0건 (DB 조회 실패 가능성)")
        return
    removed = [p for p in (out / "player").glob("*.html") if p.name not in keep]
    for p in removed:
        p.unlink()
    if removed:
        log.info("선수 페이지 %d건 삭제 (대상에서 빠진 선수)", len(removed))


def write_site(articles: list[dict], sources: dict, out_dir: str | Path,
               now: datetime | None = None,
               directory: dict | None = None, registry=None,
               outlet_dir: dict | None = None) -> None:
    """인덱스·상세 N개·정적 자산을 out_dir에 일괄 생성한다."""
    now = now or datetime.utcnow()
    out = Path(out_dir)
    (out / "article").mkdir(parents=True, exist_ok=True)

    (out / "index.html").write_text(
        render_index(articles, sources, now, directory=directory, registry=registry,
                     outlet_dir=outlet_dir),
        encoding="utf-8")
    (out / "all.html").write_text(
        render_all(articles, sources, now, directory=directory, registry=registry,
                   outlet_dir=outlet_dir),
        encoding="utf-8")
    (out / "about.html").write_text(render_about(), encoding="utf-8")

    entries = build_player_entries(articles, load_page_players())
    write_player_pages(entries, sources, out, now, directory=directory,
                       outlet_dir=outlet_dir)

    ordered = _sorted_latest(articles)
    # 패싯은 전체 기사 기준으로 한 번만 계산해 모든 상세 페이지에 전달
    facets = facet_counts(articles, sources, directory=directory, registry=registry,
                          outlet_dir=outlet_dir)
    chips_map = player_chips(entries)
    for idx, row in enumerate(ordered):
        a = _decorate(row, sources, now, directory=directory, outlet_dir=outlet_dir)
        neighbors = build_neighbors(ordered, idx, sources, now, directory=directory,
                                    outlet_dir=outlet_dir)
        html = render_article(a, neighbors, row["content_hash"], sources, now,
                              facets=facets, chips=chips_map.get(row["content_hash"]))
        (out / "article" / f"{row['content_hash']}.html").write_text(
            html, encoding="utf-8")

    sweep_orphan_pages(articles, out)

    for asset in ("style.css", "app.js"):
        shutil.copyfile(_STATIC_DIR / asset, out / asset)
    shutil.copytree(_STATIC_DIR / "fonts", out / "fonts", dirs_exist_ok=True)


def unmatched_articles(articles: list[dict], linked: set[str]) -> list[dict]:
    """단계가 있는데 귀속 선수가 0명인 기사 (스펙 §9) — 추출 누락 감시.

    선수 페이지가 article_players 를 유일한 원천으로 쓰므로 추출이 실패한 기사는
    어느 선수 페이지에도 나타나지 않고 조용히 사라진다. 그것을 볼 수 있는 자리다."""
    out = []
    for a in _sorted_latest(articles):
        if not _stage.is_displayable(filter_stage(a)):
            continue
        if a["content_hash"] in linked:
            continue
        out.append({"title": a.get("title_ko") or a.get("title_original") or "",
                    "source": a.get("source_id") or "",
                    "date": fmt_date(to_kst(_sort_ts(a)[0]))})
    return out


def render_ops(view: dict, unmatched: list[dict] | None = None) -> str:
    return _env().get_template("ops.html.j2").render(view=view, unmatched=unmatched)


def write_ops(snapshot: dict, sources: dict, out_dir: str | Path,
              anomaly_count: int, now: datetime,
              unmatched: list[dict] | None = None) -> None:
    """운영 뷰 site/ops.html 생성. 실패 격리는 호출부 (run.py) 책임."""
    view = build_ops_view(snapshot, sources, anomaly_count, now)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "ops.html").write_text(render_ops(view, unmatched=unmatched),
                                  encoding="utf-8")
