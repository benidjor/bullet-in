from __future__ import annotations
import json
import logging
import os
import re
import shutil
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from bullet_in import transfer_stage as _stage
from bullet_in.credibility import norm_alias
from bullet_in.enrich import attrib_core, roundup_attrib_counts
from bullet_in.storage.players import MENTION

log = logging.getLogger(__name__)

# 공개 주소 — canonical · og:url 의 절대 URL 기준 (커스텀 도메인 미사용 · 2026-08-23 확정)
SITE_URL = "https://bullet-in.pages.dev"

# 목록 · 선수 페이지는 색인하고 기사 상세는 뺀다 (2026-08-23 확정).
# 상세를 색인시키면 번역문이 원문 대신 검색에 뜬다 — 한 번 색인되면 빼는 데 시간이 걸려
# 공개 전에 정하는 것이 압도적으로 싸다. follow 는 남겨 목록 · 선수 페이지로 크롤이 흐르게 한다.
ARTICLE_ROBOTS = "noindex,follow"

_SITE_DESC = ("아스날 이적 · 팀 소식을 BBC · 스카이스포츠 · 가디언 등 여러 매체에서 모아 "
              "한국어로 정리합니다. 보도마다 공신력 등급과 이적 진행 단계를 함께 표시합니다.")

# GA4 측정 ID — 빈 값이면 계측 스크립트를 아예 넣지 않는다 (로컬 렌더 · 목업에서 계측 0).
# 공개 값이라 숨길 것이 없으나, 속성을 만들기 전에는 채울 수 없어 환경변수로도 받는다.
GA_MEASUREMENT_ID = os.environ.get("GA_MEASUREMENT_ID", "")


def page_meta(title: str, desc: str, path: str = "", *,
              robots: str | None = None, og_type: str = "website",
              image: str | None = None) -> dict:
    """페이지 <head> 의 검색 · 링크 미리보기 메타. path 는 사이트 루트 기준 경로다.

    링크 미리보기는 태그가 있는 것과 커뮤니티 · 메신저가 그것을 어떻게 그리는가가
    다른 층이라, 값을 넣은 뒤 실물로 한 번 확인한다 (2026-08-23 공개 준비)."""
    return {"title": title, "desc": desc, "canonical": f"{SITE_URL}/{path}",
            "robots": robots, "type": og_type, "image": image}


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
    """그 날짜(d)에 실제 발행된 기사 수 — 그날 카드와 줄을 합친 수다.
    묶음이 하루 단위라 그 묶음의 기사가 전부 그날 것이지만, 날짜가 없는 행을
    거르려고 판정은 그대로 둔다."""
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
        # 저장된 언론사명도 사전으로 한 번 접는다 — 같은 매체가 「더 타임스」 · The Times 로
        # 갈려 사이드바에 두 항목이 되던 자리다 (기자명 통일 설계 §4.3).
        # 사전에 없는 표기는 그대로 통과하고 articles.outlet 저장값은 안 건드린다.
        return (outlet_dir or {}).get(norm_alias(row["outlet"]), row["outlet"])
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
# 기자 첫 화면 건수 문턱 (기자 축 설계 §3.2) — 사이드바는 「누가 대단한가」 가 아니라
# 「눌렀을 때 볼 게 있는가」 를 보이는 자리라, 공신력 상한을 내리는 대신 문턱을 둔다.
INITIAL_MIN_COUNT = 2
# 기자 항목을 만들지 않는 소속 (기자 축 설계 §5.1) — 도달 경로는 언론사 facet 의
# 같은 항목이 유지한다. 그 항목이 사라지면 이 결정을 다시 봐야 한다.
NO_SIDEBAR_OUTLETS = {"Goal.com"}
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
# 독자용 7묶음으로 접는다. 저장 enum 은 건드리지 않고 (transfer_stage.py 는 enrich 와
# 공유) 표시 계층에서만 묶는다.
# medical 은 건수가 적어 이적 합의에 합친다 (협상 중 소속에서 이동 — §3) ·
# personal_terms 도 건수가 적어 제안 · 협상에 합친다 (2026-08-13) — 좁힌 정의가
# 자리잡아 서빙 3건까지 줄었고, 남길 자리를 하나 쓰기에는 드물다. 접는 쪽을
# 이적 합의가 아니라 제안 · 협상으로 잡은 것은 개인 합의가 구단 간 합의 **전**이기
# 때문이다 — 이적 합의로 접으면 딜이 성사된 것으로 읽힌다 (실측 반례: 개인 합의까지
# 갔다가 무산된 비니시우스 75ef94fc).
# 순서는 진행이 많이 된 것부터 · collapsed 는 종결이라 맨 뒤.
_DISPLAY_STAGE: dict[str, dict] = {
    "official": {"label": "오피셜", "tone": "red", "filled": True},
    "done": {"label": "이적 완료", "tone": "blue", "filled": False},
    "agreed": {"label": "이적 합의", "tone": "red", "filled": False},
    "medical": {"label": "이적 합의", "tone": "red", "filled": False},
    "personal_terms": {"label": "제안 · 협상", "tone": "green", "filled": False},
    "negotiating": {"label": "제안 · 협상", "tone": "green", "filled": False},
    "interest": {"label": "관심", "tone": "gray", "filled": False},
    "rumour": {"label": "루머", "tone": "gray", "filled": False},
    "collapsed": {"label": "무산", "tone": "ash", "filled": False},
}


def display_stage(enum: str | None) -> dict | None:
    """저장 단계 enum → 표시 배지 {label, tone, filled}. 미표시 (other · None) 는 None."""
    d = _DISPLAY_STAGE.get(enum or "")
    return dict(d) if d else None


# 사이드바 단계 필터 — 표시 7묶음 (라벨, 저장 enum 목록). 이적 합의가 agreed · medical 을,
# 제안 · 협상이 negotiating · personal_terms 를 함께 건다 (위 _DISPLAY_STAGE 주석).
_STAGE_DISPLAY_GROUPS: list[tuple[str, list[str]]] = [
    ("오피셜", ["official"]),
    ("이적 완료", ["done"]),
    ("이적 합의", ["agreed", "medical"]),
    ("제안 · 협상", ["negotiating", "personal_terms"]),
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


# ── 최하 등급 (2026-08-30 사용자 확정) ─────────────────────────────────
# 가십 절의 배정 기준을 「묶음 전원이 최하」 에서 「이 기사가 최하」 로 바꿨다.
# 앞 규칙은 상위 매체가 섞인 이야기 안의 최하를 접힌 채로 남겼는데, 배포본 실측에서
# 그 자리가 368건이었고 화면에서는 관련 보도 토글을 눌러야만 나왔다.
LOWEST_TIER = 4.0

# 가십 절이 처음에 펴 보이는 날짜 수 — 나머지는 「더보기」 뒤로 접는다.
# 7일이면 보이는 카드가 37장이라 절 하나가 화면 둘을 먹는다 (실측 · 3일이면 22장).
GOSSIP_DAYS = 3


def is_lowest(row: dict) -> bool:
    """가십 절로 보낼 기사인가 — 등급 미상은 최하로 보지 않는다."""
    tier = row.get("tier")
    return tier is not None and float(tier) >= LOWEST_TIER


# ── 톱스토리 선정 (spec2 §5) — 히어로 1 + 주요 소식 4.
# 순서: 상위 3등급만 → 아스날 주체 → 공신력 → 영입 단계 → 최신 → 이미지 유무.
# arsenal.com 배제 규칙은 넣지 않는다 (앞 스펙 §16.1 재측정으로 무효 · spec2 §5.1).
_TOP_TIERS = {0.0, 1.0, 1.5}
# 히어로 · 주요 소식에서 뺄 주소 (2026-08-28 사용자 결정) — 모아 주는 계정은 원문이
# 아니라 남의 보도를 옮긴 것이라, 첫 화면의 얼굴로 세우면 출처가 한 겹 멀어진다.
# 등급은 이미 _TOP_TIERS 가 거르므로 여기서는 주소만 본다.
_AGGREGATOR_HOSTS = ("x.com/afcstuff", "twitter.com/afcstuff")


def _is_aggregator_url(url: str) -> bool:
    u = (url or "").lower()
    return any(h in u for h in _AGGREGATOR_HOSTS)
# done 은 종전 체계에서 agreed 로 저장되던 "타 매체 완료 보도" 의 거처라 상위 유지
# (빠뜨리면 완료 당일 보도가 rank 0 으로 추락) · collapsed 가 negotiating 급인 것은
# 결말 카드 문턱을 넘기려던 것인데 그 카드는 2026-09-02 에 없어졌다 · 값은 그대로 둔다
# (1면 정렬과 대표 선정의 마지막 축이 이 표를 계속 쓴다).
_LEAD_STAGE_RANK = {"official": 6, "done": 5, "agreed": 4, "medical": 3,
                    "personal_terms": 2, "negotiating": 1, "collapsed": 1}
_TOP_HORIZON_DAYS = 10


def arsenal_subject(row: dict) -> bool:
    """아스날 주체인가 — 구단 공식이거나 제목이 '아스날' 로 시작하는지 (spec2 §5).

    제목 첫 글자로만 보던 근사에 구단 공식 예외를 더했다 (2026-09-02). 구단 공식은
    아스날이 직접 낸 발표라 제목이 선수 이름으로 시작해도 주체가 아스날인데, 옛 판정은
    그런 기사를 남의 소식으로 보고 1면에서 밀어냈다 — Arsenal.com 의 「가브리엘 제주스,
    FC 바르셀로나로 완전 이적」 이 같은 등급 · 같은 단계의 한 시간 반 앞선 발표에 졌다.

    이 함수를 부르는 곳은 top_story_key 하나다 (선수 페이지의 _arsenal_subject_rank 는
    이름만 비슷한 다른 판정이다)."""
    tier = row.get("tier")
    if tier is not None and float(tier) == 0.0:
        return True
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
        if _is_aggregator_url(a.get("url") or ""):
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


def _journalist_view(j: str, src: dict, directory: dict | None,
                     art_outlet: str | None = None,
                     outlet_dir: dict | None = None) -> dict:
    """이름 하나의 기자 뷰 — 정규화 이름 (필터 · 집계 키) · 표시 라벨 · 등재 여부 · 소속.
    저장값은 소스마다 형태가 다르다 (fmkorea 한글 말머리 · x 핸들 · html 풀네임)
    → 레지스트리 정식명으로 정규화하지 않으면 같은 기자가 facet 에서 갈라진다.

    소속은 「사전 → 그 기사의 매체 (art_outlet) → 그 소스의 매체」 순으로 정한다
    (기자 축 설계 §2.2). fmkorea 처럼 여러 매체를 실어 나르는 소스는 자기 outlet 이
    없어서, 기사가 아는 매체를 안 쓰면 소속이 영영 안 붙는다."""
    entry = (directory or {}).get(norm_alias(j))
    if entry is None and directory:
        # 공동 바이라인 ("A and B") — 등재 기자가 포함돼 있으면 그 기자를 대표로.
        # 정식명 단어 경계 매치만 인정, 복수 등재 시 바이라인 등장 순서 앞선 기자.
        jl = j.lower()
        best_pos = None
        for cand in {e["name"]: e for e in directory.values()
                     if e.get("registered", True)}.values():
            m = re.search(rf"\b{re.escape(cand['name'].lower())}\b", jl)
            if m and (best_pos is None or m.start() < best_pos):
                entry, best_pos = cand, m.start()
    if entry and entry.get("registered", True):
        outlet = entry["outlet"]
        if outlet:
            # 사전 소속도 언론사 사전을 한 번 거친다 (설계 §2.5 나) — 사전이 ChronicleLive
            # 로 적어 둔 매체의 정식명은 Chronicle Live 라 그대로 쓰면 표기가 갈린다.
            outlet = (outlet_dir or {}).get(norm_alias(outlet), outlet)
        # 사전에 소속이 비어 있으면 기사가 아는 매체로 채운다 (설계 §2.4)
        name, outlet, registered = entry["name"], outlet or art_outlet, True
    else:
        # 미등재 — 표기 접기 항목이 있으면 그 표기로 (안건 x · fold_alias_spellings)
        name, registered = (entry["name"] if entry else j), False
        outlet = art_outlet or src.get("outlet")
        # 같은 매체의 나라판 도메인 표기 (ESPN.com.br) 는 매체명으로 접는다 (설계 §4.5)
        # — 저장된 언론사가 이미 둘 다 같은 값이라 항목만 둘로 갈려 있다.
        if outlet and name.lower().startswith(outlet.lower() + "."):
            name = outlet
    if (j == src.get("journalist_label") or name == outlet or name.endswith(")")
            or name.lower() == (src.get("display_name") or "").lower()):
        # 괄호를 생략하는 네 자리 — 통칭 라벨 · 이름과 소속이 같음 · 정식명에 괄호가
        # 이미 있음 (설계 §2.5 가 · 'Bruno Andrade (ESPN)') · **이름이 그 소스의 이름
        # 그대로임** (원문이 저자 자리에 매체 이름을 쓴 자리 · 사용자 확정 2026-08-23).
        # 마지막 자리는 'BBC Sport (BBC)' 가 실물이다 — 같은 목록의 'Arsenal Official' ·
        # 'BBC Gossip' 은 통칭 라벨이라 괄호가 없는데 이것만 붙어 어색했다.
        # 이름은 그대로 남긴다 (원문이 쓴 값이다) — 괄호만 생략한다.
        outlet = None
    return {"name": name, "label": f"{name} ({outlet})" if outlet else name,
            "registered": registered, "outlet": outlet}


def article_authors(row: dict) -> list[str]:
    """저장된 저자 전원 — 값이 없으면 빈 목록 (전환 규칙의 입구).

    비어 있는 동안은 현행 규칙 (단일 journalist) 이 그대로 판정하므로, 소급 전
    배포 구간에 화면이 흔들리지 않는다 (설계 §4.2)."""
    raw = row.get("authors_json")
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [n.strip() for n in parsed if isinstance(n, str) and n.strip()]


def _primary_name(authors: list[str], directory: dict | None) -> str:
    """저자 목록에서 대표 — 첫 등재 기자 · 없으면 첫 저자 (기존 select_journalist 와 같은 순서)."""
    for a in authors:
        if (directory or {}).get(norm_alias(a)):
            return a
    return authors[0] if authors else ""


def article_journalists(row: dict, sources: dict, directory: dict | None,
                        outlet_dir: dict | None = None) -> list[dict]:
    """기사 1건이 도달해야 하는 기자 뷰 전량 — 첫 항목이 대표다.

    공저 기사가 저자 각각의 기자 필터에서 나오게 하는 입구다 (설계 §2.3).
    대표 선정 순서는 건드리지 않는다 — 소스 통칭 라벨 우선 규칙을 우회하면
    'Arsenal Official' 같은 조직 이름이 사이드바 첫 화면으로 올라온다."""
    src = sources.get(row.get("source_id")) or {}
    # 기사가 자기 매체를 알 때만 그 값을 소속으로 쓴다 (기자 축 설계 §2.2).
    # outlet_display 의 소스 폴백까지 타면 fmkorea 같은 통로 소스의 소스명이
    # 기자 소속으로 붙는다 — 그 소스는 매체를 모르는 것이 사실이다.
    art_outlet = (outlet_display(row, sources, directory=directory, outlet_dir=outlet_dir)
                  if row.get("outlet") else None)
    authors = article_authors(row)
    j = (row.get("journalist") or "").strip()
    if not j:
        j = _primary_name(authors, directory)
    elif j != src.get("journalist_label") and authors and j not in authors:
        # 저장값이 여러 이름을 이어 붙인 문자열 — 분해된 목록에서 같은 규칙으로 고른다
        j = _primary_name(authors, directory)
    if not j:
        return []
    out = [_journalist_view(j, src, directory, art_outlet, outlet_dir)]
    if j == src.get("journalist_label"):
        # 통칭 라벨 소스는 개별 저자를 노출하지 않는다는 기존 결정을 지킨다.
        # 라운드업의 저장된 저자는 사람이 아니라 매체 이름이라 (BBC Sport ·
        # Arsenal Media) 공저자로 세면 바이라인이 「BBC Gossip 외 1명」 이 된다.
        return out
    for a in authors:
        view = _journalist_view(a, src, directory, art_outlet, outlet_dir)
        if all(view["name"] != e["name"] for e in out):
            out.append(view)
    return _lead_by_tier(out, directory)


def _lead_by_tier(views: list[dict], directory: dict | None) -> list[dict]:
    """대표를 등급이 가장 높은 저자로 올린다 (사용자 확정 2026-08-27).

    등급 없는 이름이 저장 순서만으로 대표가 되어 사이드바 항목까지 차지하던 자리다
    (실측 17건 · 항목 5종 감소 · 첫 화면 무이동).

    **등급이 없는 저자는 같은 기사에 실린 등재 기자 중 가장 낮은 등급으로 친다**
    (사용자 확정 2026-08-27). 미상을 맨 뒤로 두면 매체 기본값으로 이미 높게 보이던
    이름이 등재된 낮은 등급에 밀려 화면 등급이 내려간다 (실측 1건).
    등급이 같거나 전원 미상이면 순서를 안 흔든다 — 대표가 회차마다 바뀌면 항목도 흔들린다."""
    if len(views) < 2:
        return views

    def listed(v):
        t = (directory or {}).get(norm_alias(v["name"]), {}).get("tier")
        return float(t) if t is not None else None

    graded = [t for t in (listed(v) for v in views) if t is not None]
    if not graded:
        return views
    unknown = max(graded)                       # 미상의 가정 등급

    def rank(v):
        t = listed(v)
        return t if t is not None else unknown

    best = min(views, key=rank)                 # 동점이면 앞선 것이 남는다
    if best is views[0]:
        return views
    return [best] + [v for v in views if v is not best]


def journalist_entry(row: dict, sources: dict, directory: dict | None,
                     outlet_dir: dict | None = None) -> dict | None:
    """기사 1건의 대표 기자 뷰 — 없으면 None."""
    entries = article_journalists(row, sources, directory, outlet_dir)
    return entries[0] if entries else None


def fold_alias_spellings(articles: list[dict], directory: dict | None) -> dict:
    """미등재 이름의 표기 흔들림을 한 항목으로 접은 조회 맵을 돌려준다 (안건 x).

    `norm_alias` 는 등재 기자 조회 키로만 쓰여서, 대소문자만 다른 같은 사람이
    사이드바에서 두 항목으로 갈린다 (실측 'JAMES SHARPE' ↔ 'James Sharpe').
    등재 이름은 directory 가 이미 정식명으로 접으므로 대상이 아니다.
    살아남는 표기는 기사가 많은 쪽 · 동수면 전부 대문자가 아닌 쪽 · 그다음 사전순이다."""
    counts: Counter = Counter()
    for a in articles:
        names = article_authors(a)
        j = (a.get("journalist") or "").strip()
        if j:
            names = [j] + names
        for n in dict.fromkeys(names):
            if not (directory or {}).get(norm_alias(n)):
                counts[n] += 1
    groups: dict[str, list[str]] = {}
    for n in counts:
        groups.setdefault(norm_alias(n), []).append(n)
    out = dict(directory or {})
    for key, names in groups.items():
        if len(names) < 2:
            continue
        win = sorted(names, key=lambda n: (-counts[n], n.isupper(), n))[0]
        out[key] = {"name": win, "outlet": None, "registered": False}
    return out


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
        # 대표가 저장 칸과 다를 수 있어 (2026-08-27 등급 우선 대표) 항목 이름을 먼저 본다 —
        # 저장 칸을 먼저 보면 옛 대표의 등급이 새 대표 항목에 붙는다.
        t = registry.journalists.get(norm_alias(entry["name"]))
        if t is None:
            t = registry.journalists.get(norm_alias(row.get("journalist") or ""))
        if t is not None:
            return float(t)
    # 비전담 · 조직 · 통칭 → 기사 저장 tier (비전담 기준선) 그룹으로 분류
    t = row.get("tier")
    return float(t) if t is not None else None


def _facet_rows(counts: Counter, labels: dict, tiers: dict,
                initial_min: int = 1,
                extra: list[tuple[str, set]] | None = None) -> dict:
    """tier 그룹 · 더보기 단계로 나눈 facet 뷰모델 (spec §3.1 · §3.2).
    TIER_ORDER 에 없는 tier (설정 오류) 는 미등재로 흘려보낸다.

    initial_min — 첫 화면 건수 문턱 (기자 축 설계 §3.2 · 언론사 축은 1 로 그대로).
    extra — 항목을 데려가는 더보기 추가 단계 (같은 설계 §3.3).
            **첫 화면보다 먼저 판정한다** — 여기 걸리는 이름은 공신력 · 건수가 문턱을
            넘어도 첫 화면에 안 둔다 (사용자 확정 2026-08-27).
            앞선 단계가 먼저 가져가므로 단계끼리의 순서도 결과를 가른다.
            **문턱으로 첫 화면에서 빠지는 항목은 이 단계들이 전부 받아야 한다** —
            안 받으면 그 항목은 어느 자리에도 안 실린다."""
    def _item(n, c):
        # data-tier — 공신력 연동 자동 체크의 매칭 키 (spec1 §7.2 · 등급 미상은 빈 값)
        return {"value": n, "label": labels.get(n, n), "count": c,
                "tier": tier_key(tiers.get(n))}

    def _sorted(pairs):
        return [_item(n, c) for n, c in sorted(pairs, key=lambda kv: kv[0].lower())]

    moved: dict[str, str] = {}
    for label, names in extra or []:
        for n in counts:
            if n not in moved and n in names:
                moved[n] = label
    initial_names = {n for n, c in counts.items()
                     if n not in moved and tiers.get(n) in TIER_ORDER
                     and tiers[n] <= INITIAL_MAX_TIER and c >= initial_min}

    def _in_body(n):
        return n not in moved and (tiers.get(n) not in TIER_ORDER
                                   or tiers[n] > INITIAL_MAX_TIER or n in initial_names)

    reg = [(n, c) for n, c in counts.items()
           if tiers.get(n) in TIER_ORDER and _in_body(n)]
    unreg = _sorted([(n, c) for n, c in counts.items()
                     if tiers.get(n) not in TIER_ORDER and _in_body(n)])

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
                       "unregistered": tail, "items": []})
    for label, _ in extra or []:
        picked = [(n, counts[n]) for n, lb in moved.items() if lb == label]
        if picked:
            stages.append({"label": label, "groups": [], "unregistered": [],
                           "items": _sorted(picked)})
    return {"initial": initial, "stages": stages, "total": len(counts)}


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

    # 기자 항목은 **대표로 나온 이름에만** 만든다 (2026-08-27 개정).
    #
    # 2026-08-20 설계 §3.4 는 카드에 실리는 이름 전부에 항목을 만들었다 — 공동 기사에만
    # 나오는 기자가 카드에는 있는데 사이드바 항목이 없던 구멍을 메우려던 것이다.
    # 그런데 쓰는 쪽에서 목록이 너무 길어 한눈에 안 들어왔다 (실측 266종 · 그중 51종이
    # 공저 전용이고 37종은 기사 1건).
    #
    # 공저 전용 이름을 빼도 **그 기사에 도달하지 못하게 되지는 않는다** — 같은 기사의
    # 대표가 항목에 남아 있어 그 필터로 걸린다 (실측 도달 불가 0종).
    # 카드의 data-journalist 는 저자 전원을 그대로 실어, 대표로 고른 이름이 자기가
    # 공저로 참여한 기사까지 함께 걸도록 둔다.
    #
    # 계수는 대표 · 공저를 가리지 않고 그 이름이 걸린 기사 전부를 센다 (필터 동작과 일치).
    j_views: dict = {}                  # 이름 -> 뷰
    j_tier: dict = {}
    j_outlets: dict = {}                # 이름 -> 매체별 기사 수 (설계 §2.3)
    solo: set = set()                   # 단독 기사가 있는 이름
    reached: list[list[str]] = []
    for a in articles:
        entries = article_journalists(a, sources, directory, outlet_dir)
        reached.append([e["name"] for e in entries])
        if not entries:
            continue
        # 공신력은 대표로 나온 기사에서만 정한다 (기존 규칙) — 기사 tier 는 대표 저자와
        # 그 매체가 정한 값이라, 곁들여 실린 이름에 물려주면 그 이름이 첫 화면까지
        # 올라온다. 공저로만 나오는 이름은 등급 없이 자기 단계로 간다 (설계 §3.4).
        j_tier[entries[0]["name"]] = _journalist_tier(a, entries[0], registry)
        j_views[entries[0]["name"]] = entries[0]          # 항목은 대표에만
        for e in entries:
            # 라벨의 매체 · 단독 여부는 저자 전원에서 모은다 — 대표로 뽑힌 이름의
            # 소속이 공저 기사에서만 드러나는 경우가 있다.
            if e["outlet"]:
                j_outlets.setdefault(e["name"], Counter())[e["outlet"]] += 1
            if len(entries) == 1:
                solo.add(e["name"])

    # 이름 하나에 라벨 하나다 (설계 §2.3) — 여러 기사의 매체가 갈리면 가장 많은 기사의
    # 매체를 쓰고 동수면 이름 순으로 앞선 매체를 쓴다. 실측은 0종이지만 데이터가 늘면
    # 생기는 일이라 규칙을 비워 두지 않는다.
    j_labels: dict = {}
    for n in j_views:
        ctr = j_outlets.get(n)
        outlet = min(ctr.items(), key=lambda kv: (-kv[1], kv[0]))[0] if ctr else None
        if outlet in NO_SIDEBAR_OUTLETS:
            continue                    # 항목을 만들지 않는다 (설계 §5.1)
        j_labels[n] = f"{n} ({outlet})" if outlet else n
    j_ctr: Counter = Counter(n for names in reached for n in names if n in j_labels)

    # 더보기 추가 단계 둘 — 단독 없음 → 1건 → 첫 화면 순으로 판정한다 (설계 §3.3 ·
    # 순서는 2026-08-27 에 뒤집혔다: 늘 공동 기사로만 나오는 이름이 문턱을 넘어 첫 화면을
    # 차지하던 자리다 · 실물 6종).
    # 둘에 함께 걸리는 항목이 있어 순서가 결과를 가른다. 1건이라는 사실은 항목 옆
    # 건수로 이미 보이지만 「이 사람은 늘 공동 기사다」 는 단계로만 보인다.
    # 항목이 대표에만 생기게 바뀌면서 (2026-08-27) 이 단계의 뜻도 「공저 전용 이름」 에서
    # 「대표로는 나오지만 단독 기사가 없는 이름」 으로 좁아졌다 — 라벨을 그에 맞춘다.
    j_extra = [("더보기 · 단독 기사가 없는 기자", {n for n in j_labels if n not in solo}),
               ("더보기 · 기사 1건인 기자", {n for n, c in j_ctr.items() if c == 1})]

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
            # 링크 선수 배지 예외는 2026-08-27 에 걷어냈다 — 계수와 카드 숨김이
            # 같은 규칙을 따로 적던 자리가 하나로 줄었다.
            other_count += 1
    # 표시 7묶음 — 라벨 · 저장 enum 목록 (data-value) · 합산 건수 (spec1 §5)
    stage_groups = [{"label": label, "value": ",".join(enums),
                     "count": sum(stage_counts.get(e, 0) for e in enums)}
                    for label, enums in _STAGE_DISPLAY_GROUPS]

    return {"total": len(articles), "team": dict(teams),
            "tiers": tiers, "stage": stage_counts, "stage_groups": stage_groups,
            "other": other_count,
            "outlets": _facet_rows(o_ctr, {}, o_tier),
            "journalists": _facet_rows(j_ctr, j_labels, j_tier,
                                       initial_min=INITIAL_MIN_COUNT, extra=j_extra)}

# 이적시장 창 — 상단 바 타이머의 단일 원천 (2026-08-28 사용자 요청).
#
# 시각은 **현지 (런던) 기준을 오프셋까지 적어 절대 시각으로** 둔다. 「9월 1일 23시」
# 한 줄만 적으면 읽는 쪽 시간대에 따라 여덟 시간이 어긋난다 — 여름은 BST (+01:00),
# 겨울은 GMT (Z) 라 오프셋도 창마다 다르다.
# 계산 (지금이 어느 구간인가 · 얼마 남았나) 은 app.js 가 한다 — 렌더는 세 시간에 한
# 번이라 서버가 계산해 박으면 그사이에 낡는다. 여기는 재료만 둔다.
#
# **목록이 끝나면 타이머는 사라진다** — 다음 시즌 일정은 확정되면 여기에 더한다.
# 여름 개장일 (6월 1일) 은 프리미어리그 통상값을 쓴 가정이다 (사용자가 준 것은 마감
# 시각 셋뿐) — 2027 여름이 오기 전에 확인해서 고친다.
TRANSFER_WINDOWS: list[dict] = [
    {"name": "여름", "open": "2026-06-01T00:00:00+01:00",
     "close": "2026-09-01T23:00:00+01:00"},
    {"name": "겨울", "open": "2027-01-01T00:00:00+00:00",
     "close": "2027-02-01T23:00:00+00:00"},
]


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(_TPL_DIR),
        autoescape=select_autoescape(default_for_string=True, default=True),
    )
    env.globals["stages"] = _stage.SIDEBAR_STAGES
    env.globals["ga_id"] = GA_MEASUREMENT_ID
    env.globals["transfer_windows"] = json.dumps(TRANSFER_WINDOWS, ensure_ascii=False)
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
        # 파일명을 함께 남긴다 — 개수만으로는 "무엇이 사라졌나" 를 사후에 못 묻는다
        # (2026-08-29 회차에서 실제로 막혔다). 한 줄에 몰아 담으면 저널이 자르므로
        # 열 개씩 끊어 여러 줄로 남긴다.
        for i in range(0, len(removed), 10):
            log.info("잔여 페이지 삭제 목록 %d-%d %s",
                     i + 1, min(i + 10, len(removed)), " ".join(removed[i:i + 10]))
    return removed


# 링크 선수 배지 (linked_player_label) 는 2026-08-27 에 걷어냈다.
#
# 2026-08-23 첫인상 정리 (#333) 가 표시를 뗐다가 2026-08-25 (#339) 에
# 거취 어휘 조건을 걸어 되살렸는데, 그 조건이 "어느 선수의 거취인가" 를
# 못 봐서 실측 3건 중 하나가 엉뚱한 이름을 앞세웠다
# ("아스톤 빌라, 하파엘 레앙 영입 타진 및 올리 왓킨스 사과" → "왓킨스 외 1명 관련").
# 이름은 id 순으로 골랐고 기사의 거취 내용은 레앙 쪽이었다.
#
# 배지와 함께 그것이 근거이던 기타 카드 노출 예외도 걷었다 — 배지 없이
# 예외만 남기면 아스날과 무관한 글이 설명 없이 노출되는 #339 이전 상태로
# 돌아간다. SERVING_SELECT_SQL 의 linked_players 도 읽는 곳이 없어 함께 뺐다.

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
    entries = article_journalists(row, sources, directory, outlet_dir)
    # 카드 data 속성 · 필터 키 — 공저는 저자 전원을 실어야 각자의 필터에서 걸린다.
    # 구분자는 파이프 하나다 (app.js 가 나눠 읽는다).
    a["_journalist"] = "|".join(e["name"] for e in entries)
    a["_byline"] = entries[0]["label"] if entries else None   # 표시 라벨 — 기자 (언론사)
    a["_authors"] = [e["name"] for e in entries]              # 상세 페이지 전원 나열
    a["_more_authors"] = max(len(entries) - 1, 0)             # 바이라인 「외 N명」
    # 개편 위계 · 표시 필드 (spec1 §5 · §7.1 · §12 · spec2 §3.1 · §11.1)
    a["_reader_tier"] = reader_tier(row.get("tier"))
    a["_grade"] = grade_class(row.get("tier"))
    a["_dot"] = dot_info(row.get("tier"))
    a["_stage_disp"] = display_stage(st)
    a["_pending"] = title_pending(row)
    a["_datetime"] = published_datetime(row)
    a["_time"] = time_in_group(row)
    a["_show_summary"] = show_summary(row.get("tier"))
    return a


def _sorted_latest(articles: list[dict]) -> list[dict]:
    return sorted(articles, key=_sort_ts, reverse=True)


def story_links(entries: list[dict]) -> dict[str, dict]:
    """사건 묶음 키 (선수 ko_name) → 그 선수 페이지 (안건 π 후속).
    페이지가 만들어진 선수만 담는다 — 없는 선수에게 링크를 달면 죽은 링크가 된다."""
    return {e["ko_name"]: {"slug": e["slug"], "count": e["count"]}
            for e in entries if e.get("ko_name")}


def render_index(articles: list[dict], sources: dict, now: datetime,
                 directory: dict | None = None, registry=None,
                 outlet_dir: dict | None = None,
                 stories: dict | None = None) -> str:
    ordered = [_decorate(a, sources, now, directory=directory, outlet_dir=outlet_dir)
               for a in _sorted_latest(articles)]
    players = load_player_names()
    top = pick_top_stories(ordered, now, players)
    top_hashes = {a["content_hash"] for a in ([top["lead"]] if top["lead"] else []) + top["mains"]}
    rest = [a for a in ordered if a["content_hash"] not in top_hashes]

    # 2026-08-30 사용자 확정 — 최하는 사건 묶음과 상관없이 전부 가십 절로.
    # 앞 규칙 (묶음 전원이 최하일 때만) 은 상위 매체가 섞인 이야기 안의 최하를 접힌
    # 채로 남겨, 배포본 실측 442건 중 368건이 관련 보도 토글 뒤에만 있었다.
    gossip = [a for a in rest if is_lowest(a)]
    clusters = cluster_events([a for a in rest if not is_lowest(a)], players)
    blocks = []
    for c in clusters:
        rep = pick_representative(c["articles"])
        # 대표를 뺀 나머지가 카드 안의 줄이 된다 (2026-09-02). 접지 않으므로 버튼이
        # 없고, 그날 들어온 기사는 카드나 줄 어느 한쪽에 반드시 한 번 나온다.
        same = [a for a in c["articles"] if a["content_hash"] != rep["content_hash"]]
        same.sort(key=_sort_ts, reverse=True)
        blocks.append({"rep": rep, "same": same, "key": c["key"],
                       "stage_group": c.get("stage_group"),
                       "count": len(c["articles"]), "_articles": list(c["articles"])})
    # 2026-08-30 사용자 확정 — 카드가 한 장도 안 선 최근 날짜는 가십에서 꺼내 세운다.
    # 그날 들어온 것이 전부 최하이면 날짜 그룹이 아예 안 생겨 홈이 멈춘 것처럼 보인다.
    # 꺼낸 블록에 다는 lowsolo 는 「한 장이어도 한 열로 펴지 말라」 는 표식이다 (app.js
    # 의 soloWidth) — 한 열로 펴면 최하 한 건이 그날의 헤드라인처럼 보인다.
    band = ([top["lead"]] if top["lead"] else []) + top["mains"]
    carded = {to_kst(_group_ts(a)).date()
              for a in [b["rep"] for b in blocks if b.get("rep")] + band
              if _group_ts(a) is not None}
    picked = pick_empty_day_gossip(gossip, carded, recent_days(ordered), players)
    if picked:
        taken = {a["content_hash"] for a in picked}
        gossip = [g for g in gossip if g["content_hash"] not in taken]
        blocks.extend(
            {"rep": a, "same": [], "count": 1, "_articles": [a],
             "promoted": True, "lowsolo": True, "stage_group": None,
             "key": protagonist(a.get("title_ko") or a.get("title_original") or "",
                                players)}
            for a in picked)

    gossip.sort(key=_sort_ts, reverse=True)   # 가십을 발행 · 수집 시각 내림차순으로 (2-2)
    for g in gossip:
        g["_gwhen"] = gossip_when(g, now)   # 가십 카드는 날짜 · time 정밀도면 시각까지 (6-3)
    if gossip:
        newest_day = to_kst(_sort_ts(gossip[0])[0]).date()
        cut = newest_day - timedelta(days=GOSSIP_DAYS - 1)
        for g in gossip:
            g["_gwk"] = to_kst(_sort_ts(g)[0]).date() < cut
    gossip_hidden = sum(1 for g in gossip if g.get("_gwk"))

    # 머리글 건수 — 「그 절에 실제로 놓인 오늘치」 로 센다 (c안 · 2026-08-30 사용자 확정).
    # 등급으로 세면 꺼내기로 최신 뉴스에 올라간 기사가 「뉴스 0건」 으로 적혀 화면과 어긋난다.
    today = to_kst(now).date()
    def _is_today(a):
        ts = _group_ts(a)
        return ts is not None and to_kst(ts).date() == today
    news_today = len({a["content_hash"] for a in
                      [b["rep"] for b in blocks if b.get("rep")] + band if _is_today(a)})
    gossip_today = sum(1 for g in gossip if _is_today(g))

    # 카드마다 그 선수 페이지로 가는 줄을 단다 (2026-08-28 사용자 확정) — 카드 안의
    # 줄은 이 사건의 다른 보도이고 선수 페이지는 그 선수의 모든 소식이라 축이 다르다.
    for b in blocks:
        b["story"] = None if b.get("band_dup") else (stories or {}).get(b.get("key"))
    # 밴드 (히어로 · 주요 소식) 기사도 목록에 숨김 카드로 내보낸다 — 필터가 기사 단위로
    # 전 기사에 닿도록 (spec2 §6.3). 평소엔 숨김, app.js 가 필터 활성 시에만 노출.
    for a in ordered:
        if a["content_hash"] in top_hashes:
            blocks.append({"rep": a, "same": [], "count": 1, "_articles": [a],
                           "band_dup": True, "key": None, "stage_group": None})
    day_blocks = group_blocks_by_day(blocks, now)

    facets = facet_counts(articles, sources, directory=directory, registry=registry,
                          outlet_dir=outlet_dir)
    return _env().get_template("index.html.j2").render(
        lead=top["lead"], mains=top["mains"], day_blocks=day_blocks,
        gossip=gossip, gossip_hidden=gossip_hidden, gossip_days=GOSSIP_DAYS,
        gossip_shown=len(gossip) - gossip_hidden, gossip_total=len(gossip),
        news_today=news_today, gossip_today=gossip_today,
        facets=facets, active="home", root="",
        meta=page_meta("Bullet-in · 아스날 이적 뉴스", _SITE_DESC,
                       image=(top["lead"] or {}).get("image_url")))


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
        days=days, facets=facets, active="all", root="",
        meta=page_meta("전체 기사 · Bullet-in",
                       "아스날 관련 보도를 묶음 없이 시간순으로 모아 봅니다. "
                       "매체 · 기자 · 이적 단계로 걸러 볼 수 있습니다.", "all.html"))


# ── 사건 묶음 (spec2 §4-7) — 선수 사전 (players 확정 표기) 으로 묶는다 ──────
# 전환어 (spec2 §4.3) — 뒤에 나온 선수가 주인공. 3.1 모델 실측 표현 '불발' 을 포함한다.
#
# 2026-08-28 에 둘을 더했다 (사용자가 화면을 보고 지적).
# 「별개」 — 「가브리엘 마르티넬리와 별개로 훌리안 알바레스 영입 추진」 이 마르티넬리
#   묶음에 들어가 「마르티넬리 더보기」 와 마르티넬리 관련 보도를 달고 있었다.
# 「이어」 — 「모건 로저스 이어 에즈리 콘사 영입 주시」 처럼 앞 선수는 배경이다.
# 서빙 전량에 대 본 결과 바뀌는 기사는 각각 1건 · 2건이고 셋 다 바뀌는 쪽이 맞다
# (「이어」 가 든 제목은 전부 「A 이어 B」 구문이라 오탐 0 · 다른 후보 「무관」 ·
# 「상관없」 · 「외에」 · 「뿐 아니라」 · 「함께」 는 바뀌는 것이 0이라 안 넣었다).
#
# 「방출」 과 「공백」 을 더했다 (2026-08-28 · 사용자가 화면을 보고 지적).
# 「가브리엘 마르티넬리 방출 결정에 내부적 의문 제기…마커스 래시포드 임대 영입설」 이
# 마르티넬리 묶음에 들어가 있었다 — 이 목록의 「떠난」 과 같은 뜻이고 방향만 반대다
# (앞 선수가 나가고 뒤 선수가 그 소식의 주인공).
# 「공백」 은 앞 선수가 비운 자리를 뒤 선수가 메우는 구문이라 같은 갈래다.
# 후보 열 개를 서빙 861건 · 사전 97종에 대 보고 바뀌는 기사를 전수로 읽었다
# (재는 사전은 반드시 load_player_names 여야 한다 — 처음엔 players.status='confirmed'
# 로 뽑아 사전이 달랐고, 그래서 「이탈」 후보의 판정이 뒤집혀 나왔다).
# 넣은 둘이 바꾸는 것은 이 셋이고 전부 옳은 쪽이다.
#   「마르티넬리 방출 결정에 내부적 의문 제기…래시포드 임대 영입설」 마르티넬리 → 래시포드
#   「아스날, 살리바 부상 공백 대비 존 스톤스 영입 고려」            살리바 → 스톤스
#   「윌리엄 살리바 공백 메울 적임자로 낙점된 에즈리 콘사」           살리바 → 콘사
#
# 안 넣은 것들의 이유다.
# 「…」 은 9건이 바뀌는데 그중 넷이 나빠진다 — 「7,500만에 기마랑이스 영입…라이스와
# 화해」 가 라이스로, 「푸빌 영입 제안 거절당해…제주스 이적설」 이 제주스로 간다.
# 「매각」 은 3건 중 둘이 「A 매각 및 B 이적설」 처럼 둘 다 나가는 소식이라 뒤를 고를
# 이유가 없다.
# 「떠나」 · 「내보내」 · 「정리」 · 「빈자리」 · 「대신할」 은 바뀌는 것이 0건이다.
# 「이탈」 은 1건 (「벤 화이트 이탈 우려 속 완-비사카 영입 고려」 화이트 → 완-비사카) 이
# 옳은 쪽이지만, 표본이 하나뿐이라 다음에 같은 낱말이 다른 구문으로 올 때를 못 봤다.
_TRANSITION_WORDS = ["놓친", "대신", "대체", "무산", "불발", "결렬", "실패", "포기", "떠난",
                     "별개", "이어", "방출", "공백"]

# 우리 선수가 아닌 사람인데 성이 겹쳐 제목 매치에 걸리는 이름 (2026-08-28 전수 조사).
#
# 사전은 대부분 성만 담고 (97개 중 87개) 매치는 부분 문자열이라, 같은 성을 쓰는
# 다른 사람이 제목에 나오면 그 기사가 우리 선수의 사건 묶음으로 들어간다.
# 사전의 '긴 이름 우선' 규칙은 그 긴 이름도 사전에 있을 때만 듣는데, 여기 넷은
# 우리 선수가 아니라 사전에 없다.
#
# 제목 문자열만으로 가르는 자동 규칙은 두 가지를 대 봤고 둘 다 더 크게 망가졌다
# — 「성 앞이 붙어 있으면 버린다」 는 「주니오르크루피」 를, 「성 앞말이 우리 이름이
# 아니면 버린다」 는 「수비수 콘사」 · 「유망주 은와네리」 를 함께 버렸다.
# 그래서 사람이 확인한 이름만 담는다 (전체 913건 전수 대조 · 그때는 이 넷이 전부였다).
#
# 「주앙 제주스」 를 더했다 (2026-08-31 · 사용자가 화면을 보고 지적).
# 「베네치아, 주앙 제주스와 구두 합의… 내일 계약 체결 예정」 이 가브리엘 제주스
# 묶음의 관련 보도로 들어가 있었다 — 우리와 무관한 FA 수비수다.
# 명단 표기를 「가브리엘 제주스」 로 바꾸는 쪽도 검토했는데 그러면 「제주스」 만 쓴
# 제목 5건 (「나폴리, 제주스 영입 관심 표명」 등) 을 미탐으로 잃는다.
# 배포본에서 제목에 「제주스」 가 든 20건을 전수로 읽었고 바뀌는 것은 이 1건뿐이다.
#
# **같은 묶음에 남는 것이 하나 더 있다** — 「포르투갈 대표팀 지휘봉 잡은 제주스,
# 전술 변화 예고」 (조르제 제주스 감독). 제목에 성만 있어 이름으로는 못 가린다.
_NOT_OUR_PLAYERS = ("벤 넬슨", "리 딕슨", "깁스-화이트", "겔라두에", "겔라 두에",
                    "주앙 제주스")


def mask_other_people(title: str) -> str:
    """제목에서 남의 이름을 지운다 — 길이는 그대로 둬 전환어 위치 비교를 안 흔든다."""
    for name in _NOT_OUR_PLAYERS:
        if name in title:
            title = title.replace(name, " " * len(name))
    return title


# 동명이인이 잦아 성만으로는 우리 선수라고 볼 수 없는 이름 (2026-08-31).
#
# 「제주스」 하나로 세 사람이 걸렸다 — 가브리엘 제주스 (우리 선수) · 주앙 제주스
# (베네치아로 간 FA 수비수) · 조르제 제주스 (포르투갈 대표팀 감독).
# 앞의 둘은 제목에 이름이 함께 나와 _NOT_OUR_PLAYERS 로 가릴 수 있지만, 감독 건은
# 제목에 성만 있어 지울 이름이 없다.
#
# 명단 표기를 「가브리엘 제주스」 로 바꾸는 쪽은 안 듣는다 — roster_surnames 가 마지막
# 어절을 성으로 자동 파생해 「제주스」 가 되살아나고, 표기를 바꾸면 추출 프롬프트 ·
# 사건 묶음 · 선수 페이지까지 함께 흔들린다.
_AMBIGUOUS_NAMES = {"제주스": "가브리엘 제주스"}


def mask_ambiguous(title: str, body: str) -> str:
    """본문이 풀네임으로 뒷받침할 때만 그 성을 이름으로 인정한다 (길이 보존).

    운영 실측에서 본문 표기가 우리 기사와 남의 기사를 정확히 갈랐다 — 제목이 성만
    쓴 7건 중 우리 기사 4건은 본문에 풀네임이 있었고, 남의 기사 2건은 성만 있었다.

    **본문이 없는 행에는 쓰면 안 된다** — 「본문 없음」 이 「풀네임 없음」 이 되어
    전부 버린다. 지금 부르는 곳 (fmkorea 전재 글) 은 본문이 항상 있다.
    """
    for surname, full in _AMBIGUOUS_NAMES.items():
        if surname in title and full not in (body or ""):
            title = title.replace(surname, " " * len(surname))
    return title


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

# 색인 5그룹 (스펙 §4.1) — (그룹명, 기본 접힘).
# 무산 · 타 클럽행은 되짚기용이라 접어 두고, 접기 · 펼치기는 다섯 그룹 모두에 둔다.
#
# 「진행 중」 을 영입 · 방출로 갈랐다 (2026-08-23 공개 준비 · 사용자 지시).
# 한 묶음일 때는 들어오는 선수와 나가는 선수가 섞여, 어느 쪽을 보러 왔든 목록을
# 통째로 훑어야 했다. 두 그룹의 축 배지는 그대로 둔다 (아래 _NO_BADGE_GROUPS).
# 타 클럽행을 이적 무산 위로 올렸다 (2026-08-28 사용자 지시) — 「어디로 갔나」 는
# 행선지가 있는 소식이고 「무산」 은 남는 것이 없는 자리라, 되짚을 값이 큰 쪽을 먼저 둔다.
TRANSFER_GROUPS: list[tuple[str, bool]] = [
    ("영입 진행 중", False), ("방출 진행 중", False), ("이적 확정", False),
    ("타 클럽행", True), ("이적 무산", True),
]

_TRANSFER_GROUP_OF: dict[str, str] = {
    "in_link": "영입 진행 중", "out_link": "방출 진행 중",
    "in_done": "이적 확정", "out_done": "이적 확정",
    "loan_in": "이적 확정", "loan_out": "이적 확정",
    "link_dropped": "이적 무산", "other_club": "타 클럽행",
}

# 색인에서 축 배지를 생략하는 그룹 (2026-08-11 신설 · 2026-08-23 기준 개정).
#
# 원래 기준은 "값이 하나뿐인 그룹" 이었다 — 배지가 그룹명을 되풀이하거나 (타 클럽행)
# 같은 값을 다른 말로 부르기 때문이다 (이적 무산 그룹의 "링크 소멸").
# 진행 중을 영입 · 방출로 가르면서 그 기준이 두 그룹을 더 삼켰고, 배지가 43개에서
# 9개로 줄었다. 그래서 기준을 "배지가 색을 나르는가" 로 바꿨다.
# 영입 · 방출 배지는 머리와 말이 겹쳐도 초록 · 빨강으로 축을 한 번 더 말한다 —
# 카드 하나만 떼어 봐도 들어오는 쪽인지 나가는 쪽인지 보이게 남긴다.
# 아래 둘은 배지가 회색이라 되풀이만 남으므로 그대로 생략한다.
# 선수 페이지는 그룹 맥락이 없어 어느 쪽이든 배지를 그대로 붙인다.
_NO_BADGE_GROUPS = {"이적 무산", "타 클럽행"}

# 색인에서 현 소속을 배지로 다는 그룹 (2026-08-27 신설).
#
# 「타 클럽행」 은 그룹 머리가 "다른 데로 갔다" 까지만 말하고 어디로 갔는지는 안 말한다.
# 단계 배지를 생략한 자리 (_NO_STAGE_GROUPS) 에 행선지를 넣어 그 빈칸을 메운다.
# 값은 players.club (현 소속) 이고, 타 클럽행이면 그것이 곧 간 곳이다.
# 값이 없으면 배지를 안 단다 — 모르는 것을 빈 배지로 채우지 않는다.
_CLUB_BADGE_GROUPS = {"타 클럽행"}

# 구단 한글 표기 — 저장은 영문 (roster_seed 가 그렇게 쓴다) · 화면은 한글이다.
# 선수 이름을 full_name · ko_name 으로 나눠 두는 것과 같은 결이고, 표기를 DB 에 섞어
# 넣지 않아 시드와 어긋나지 않는다.
# **없는 구단은 저장값을 그대로 띄운다** — 매핑을 빠뜨려도 배지가 사라지지 않는다.
_CLUB_KO: dict[str, str] = {
    "Arsenal": "아스날",
    "Aston Villa": "아스톤 빌라",
    "Atletico Madrid": "아틀레티코 마드리드",
    "Barcelona": "바르셀로나",
    "Bayer Leverkusen": "레버쿠젠",
    "Chelsea": "첼시",
    "Club Brugge": "클뤼프 브뤼허",
    "Crystal Palace": "크리스탈 팰리스",
    "Inter": "인테르",
    "Leeds": "리즈",
    "Leicester": "레스터",
    "Lille": "릴",
    "Manchester City": "맨체스터 시티",
    "Manchester United": "맨체스터 유나이티드",
    "Newcastle": "뉴캐슬",
    "Nottingham Forest": "노팅엄 포레스트",
    "Paris Saint-Germain": "파리 생제르맹",
    "RB Leipzig": "RB 라이프치히",
    "Real Madrid": "레알 마드리드",
    "Sporting CP": "스포르팅 CP",
    "Tottenham": "토트넘",
    "West Ham": "웨스트햄",
}


def club_ko(name: str | None) -> str | None:
    """구단 한글 표기. 매핑에 없으면 저장값 그대로 (빈 값은 None)."""
    return _CLUB_KO.get(name, name) if name else None

# 색인에서 단계 배지를 생략하는 그룹 (2026-08-25 신설).
#
# 그룹 머리와 단계 배지가 서로 다른 질문에 답한다 — 머리는 명단 축 ("그 선수가 어디로
# 갔나") 이고 배지는 아스날 기사에서 계산한 단계 ("아스날이 어디까지 갔나") 다.
# 그래서 "타 클럽행" 아래 "무산" · "관심" 이 함께 뜨고, 둘 다 사실인데 모순으로 읽힌다
# (2026-08-25 실측 12명 중 무산 6 · 관심 4 · 제안 · 협상 1).
# 세 안 (그대로 · 숨김 · "아스날 관심" 처럼 축 밝힘) 을 렌더해 나란히 두고 숨김을 골랐다.
# "이적 무산" 은 대상이 아니다 — 거기서는 머리와 배지가 같은 질문에 같은 답을 한다.
# 선수 페이지는 축 배지가 함께 떠 두 값을 나란히 읽을 수 있으므로 그대로 둔다.
_NO_STAGE_GROUPS = {"타 클럽행"}


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
            {"content_hash": l["content_hash"], "stage": l["stage"],
             "role": l["role"]})
    for p in players:
        p["links"] = links.get(p["id"], [])
    return players


def build_player_entries(articles: list[dict], players: list[dict]) -> list[dict]:
    """선수별 기사 목록 · 진행 단계 사다리 · 현재 단계 (스펙 §5).

    기사 목록은 역할이 언급인 귀속을 뺀 나머지다 (역할 필드 스펙 §3.3).
    단계로 고르던 것을 역할로 바꾼 것인데, 단계는 "이 기사가 그 선수에 대해
    보도하는 진행 단계" 라 "이 기사의 주인공인가" 와 다른 질문이고, 그 대가로
    화면 귀속 807건 중 331건이 남의 기사였다 (2026-08-12 실측).

    **역할이 미기입일 때 옛 단계 규칙으로 판정하던 폴백은 걷어냈다** (2026-08-19).
    값을 만드는 규칙이 모든 행에 주역 · 언급 중 하나를 넣게 된 뒤로 그 갈래가
    운영에서 한 번도 돌지 않았고 (5회 연속 신규 적재분 미기입 0 · 소급 후 2,889쌍
    전부 기입), 값이 빈 채 저장되는 코드 경로도 남아 있지 않다.
    대신 미기입을 막는 자리를 쓰기 쪽으로 옮겼다 (article_players.role NOT NULL) —
    서빙이 미기입을 임의의 한쪽으로 읽으면 화면이 조용히 틀어지기 때문이다.
    주역으로 읽으면 남의 기사가 뜨고 언급으로 읽으면 본인 기사가 사라진다.
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
                  if l["content_hash"] in by_hash and l["role"] != MENTION]
        if not paired:
            continue
        paired.sort(key=lambda t: _sort_ts(t[0]))          # 오래된 것부터 (사다리 입력)
        timeline = [{"row": r, "stage": s} for r, s in paired]
        # 대표 선정의 이름 대조는 성 (ko_name) 으로 한다 — 기사 제목이 성만 쓰는 일이 잦다
        ko = p.get("ko_name")
        ladder = stage_ladder(timeline, ko)
        slug = player_slug(p.get("surname") or "", p["id"], dupes)
        if folded[p["id"]] in dupes:
            # 정상 폴백이라 INFO 다 — 렌더마다 (하루 여덟 번) 같은 줄이 나오므로
            # WARNING 으로 두면 회차 로그를 훑을 때 사고처럼 읽힌다.
            log.info("동성 복수 — slug 를 id 로 떨어뜨림: %s → %s",
                     p["full_name"], slug)
        out.append({**p,
                    "name": (p.get("ko_full_name") or p.get("ko_name")
                             or p["full_name"]),
                    "slug": slug,
                    "articles": [r for r, _ in reversed(paired)],
                    "ladder": ladder,
                    "ended": ended_marker(timeline, ko, p.get("transfer_status")),
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


def ended_marker(entries: list[dict], name: str | None = None,
                 transfer_status: str | None = None) -> dict | None:
    """무산 (collapsed) 종결 표시 (단계 재정의 스펙 §8) — 사다리 축 밖의 한 줄.
    대표 선정 규칙은 사다리와 동일 (그 선수를 다룬 기사 우선 · 공신력 · 늦은 기사).

    current_stage 와 같은 명단 뒷받침을 요구한다 — 이 줄은 사다리 맨 위에 꽂혀
    "이 사가는 끝났다" 를 먼저 말하므로, 명단이 부정하는 종결을 그리면 같은 페이지의
    머리 배지와 정면으로 어긋난다 (실측: 영입을 마친 기마랑이스 페이지에 이적 완료
    열흘 전 가십 한 건으로 만든 무산 줄, 아직 진행 중인 콘사 페이지에 같은 줄).
    가드가 빠진 것은 이 함수와 current_stage 의 가드가 서로 다른 PR 에서 들어왔기
    때문이고, 판정 기준은 _TERMINAL_BACKING 하나로 맞춘다."""
    b = [e for e in entries if e.get("stage") == "collapsed"]
    if not b or transfer_status not in _TERMINAL_BACKING["collapsed"]:
        return None
    rep = min(reversed(b), key=_rep_key(name))
    return {"row": rep["row"], "stage": rep["stage"], "count": len(b)}


# 선수 카드 사진 — 밖에서 새로 긁지 않고 우리가 이미 저장한 기사 이미지를 쓴다
# (2026-08-28 사용자 확정). 트랜스퍼마르크트 같은 곳을 받아 저장하면 초상 · 저작권
# 판단이 새로 생기는데, 기사 사진은 이미 카드에 쓰고 있어 새로 지는 위험이 없다.
_PHOTO_SKIP_SOURCES = {"bbc_gossip"}   # 가십은 소스 고정 배너라 선수와 무관하다


def assign_player_photos(entries: list[dict]) -> None:
    """선수마다 카드 사진 하나를 고른다 (`_photo` 를 넣는다 · 없으면 None).

    `players.photo_url` 이 박혀 있으면 그것이 이긴다 — 자동 선택은 그 선수의 가장
    최근 기사 사진이라 새 기사가 들어올 때마다 갈아탄다 (30일에 177회 · 선수당 3.2회
    실측). 얼굴이 어긋난 선수만 손으로 박고, 박은 뒤로는 안 바뀐다.
    박는 곳은 `python -m bullet_in.set_player_photo` 하나다.

    자동 선택의 후보는 그 선수 페이지에 실리는 기사뿐이다 — entries 의 articles 는
    이미 주역 귀속만 남아 있어 (player_entries), 언급으로 스쳐 간 기사는 후보가 아니다.
    가십 소스는 뺀다 — 배너가 고정이라 안 빼면 여러 선수가 같은 「GOSSIP」 글자판을
    단다 (실측 8명).
    같은 사진이 둘에게 걸리면 앞 선수만 쓰고 뒤 선수는 다음 후보로 내린다 — 둘이
    함께 찍힌 사진이 서로 다른 카드에 걸리면 어느 쪽도 못 믿는다 (실측 3장 · 7명).
    손으로 박은 사진도 이 자리를 차지한다 — 자동 선택이 같은 장을 또 집으면 박은
    뜻이 없어진다.
    최근 보도가 있는 선수부터 골라 새 사진이 활발한 쪽으로 가게 한다."""
    taken: set[str] = set()
    auto: list[dict] = []
    for e in entries:
        pinned = (e.get("photo_url") or "").strip()
        e["_photo"] = pinned or None
        if pinned:
            taken.add(pinned)
        else:
            auto.append(e)
    for e in sorted(auto, key=lambda x: x["last_ts"], reverse=True):
        for a in e.get("articles") or []:            # 최신순 · 색인만 만드는 호출은 비어 있다
            img = (a.get("image_url") or "").strip()
            if not img or img in taken or a.get("source_id") in _PHOTO_SKIP_SOURCES:
                continue
            taken.add(img)
            e["_photo"] = img
            break


def render_players(entries: list[dict], now: datetime) -> str:
    """선수 색인 (스펙 §4) — 5그룹 · 그룹 안 최근 보도순 · 이름순 전환 단추.

    2026-08-23 에 성 가나다순으로 바꿨다가 2026-08-28 에 최근 보도순으로 되돌렸다
    (사용자 확정). 이름순은 찾으려는 선수를 빨리 집게 해 주지만, 오늘 움직인 소식이
    목록 한가운데로 내려간다 (실측: 기사 141건짜리 알바레스가 28명 중 16번째).
    두 차례를 다 살리려고 기본은 최근 보도순으로 두고 전환 단추를 둔다 — 정렬 키는
    카드의 data 속성에 실어 app.js 가 자리만 바꾼다."""
    assign_player_photos(entries)
    groups = []
    for name, collapsed in TRANSFER_GROUPS:
        members = [e for e in entries if transfer_group(e["transfer_status"]) == name]
        members.sort(key=lambda e: e["last_ts"], reverse=True)
        for e in members:
            e["_badge"] = (None if name in _NO_BADGE_GROUPS
                           else transfer_badge(e["transfer_status"]))
            e["_stage"] = (None if name in _NO_STAGE_GROUPS
                           else display_stage(e["stage"]))
            e["_club"] = (club_ko(e.get("club"))
                          if name in _CLUB_BADGE_GROUPS else None)
            e["_last"] = fmt_date(to_kst(e["last_ts"]))
            # 전환 단추가 쓰는 두 정렬 키 — 이름순 키는 되돌리기 전과 같은 성 (ko_name).
            e["_lastkey"] = e["last_ts"].isoformat()
            e["_namekey"] = e.get("ko_name") or e["name"]
        groups.append({"name": name, "collapsed": collapsed, "members": members})
    return _env().get_template("players.html.j2").render(
        groups=groups, active="players", root="", solo=True,
        meta=page_meta("선수 · Bullet-in",
                       "아스날 이적설이 붙은 선수별로 관련 보도를 모아 "
                       "어디까지 진행됐는지 정리했습니다.", "players.html"))


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
        active="players", root="../", solo=True,
        meta=page_meta(f"{entry['name']} · Bullet-in",
                       f"{entry['name']} 관련 아스날 이적 보도 {entry['count']}건을 "
                       "진행 단계별로 모았습니다.",
                       f"player/{entry['slug']}.html", og_type="profile"))


def protagonist(title: str, players: list[str]) -> str | None:
    """사건 주인공 선수 (spec2 §4.3) — 전환어 뒤 선수를 우선, 없으면 첫 등장 선수.

    성이 겹치는 남의 이름은 먼저 지운다 (`_NOT_OUR_PLAYERS`) — 안 지우면 그 기사가
    우리 선수의 사건 묶음에 들어간다 (실측: 「벤 넬슨」 기사가 리스 넬슨 묶음에)."""
    title = mask_other_people(title or "")
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
    """같은 날 · 같은 선수 · 같은 표시 단계 기사를 한 묶음으로 (2026-09-02 개정).

    그전에는 선수 이름 하나로만 묶고 날짜 경계가 없었다. 그러면 6월 기사와 오늘
    기사가 한 묶음이 되고, 카드는 대표 하나만 서서 그날 들어온 것이 화면에서
    사라진다 (실측 2026-08-28 — 기사 16건에 카드 1장 · 날짜 그룹이 아예 없는 날도
    나흘 있었다).

    단계는 표시 묶음 (_STAGE_GROUP_OF) 을 쓴다 — 화면에 같은 배지가 붙은 것끼리
    묶여야 카드 안이 한 이야기로 읽힌다. 메디컬은 이적 합의로, 개인 합의는
    제안 · 협상으로 접힌다.

    묶지 않는 것은 셋이다 — 주인공을 못 찾은 기사 · 기준 시각이 없는 기사 ·
    단계가 기타이거나 빈 기사. 셋 다 낱개 카드가 된다.

    입력 등장 순서를 보존한다 (호출부가 최신순으로 정렬해 전달)."""
    groups: dict = {}
    order: list = []
    singles: list = []
    for a in articles:
        name = protagonist(a.get("title_ko") or a.get("title_original") or "", players)
        ts = _group_ts(a)
        stage_group = _STAGE_GROUP_OF.get(a.get("transfer_stage") or "")
        if name is None or ts is None or stage_group is None:
            singles.append({"key": name, "day": to_kst(ts).date() if ts else None,
                            "stage_group": stage_group, "articles": [a]})
            continue
        key = (to_kst(ts).date(), name, stage_group)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(a)
    return [{"key": k[1], "day": k[0], "stage_group": k[2], "articles": groups[k]}
            for k in order] + singles


def _arsenal_subject_rank(a: dict) -> int:
    """아스날 주어 순위 (spec2 §6.1 3번) — 제목 시작 3 · 본문 언급 2 · 없음 1."""
    if (a.get("title_ko") or "").lstrip().startswith("아스날"):
        return 3
    return 2 if "아스날" in (a.get("body_ko") or "") else 1


def _has_body(a: dict) -> int:
    """본문이 있는 기사인가 (1) 트윗 · 제목뿐인 행인가 (0).

    트윗은 한두 문장이라 같은 소식의 원문 기사보다 대표로 세울 값이 낮다. 그런데
    시각만 보면 집계 계정이 원문보다 몇 분 늦게 올리는 것이 흔해 트윗이 이긴다
    (실측: 넬슨 계약 해지에서 afcstuff 트윗 00:33 이 The Athletic 원문 00:31 을
    눌렀다)."""
    lvl = a.get("body_level")
    return 1 if lvl is not None and int(lvl) > 0 else 0


def pick_representative(articles: list[dict]) -> dict | None:
    """묶음 대표 — 구단 공식 → 최하 제외 → 아스날 주어 → 공신력 → 본문 → 최신 → 단계.

    2026-09-02 에 공신력을 넷째로 올렸다. 그전에는 날짜와 시각이 공신력보다 앞이라
    사실상 「가장 최신」 이 대표였다. 그렇게 둔 근거는 「옛 기사가 본문을 갖고 있다고
    최신 소식을 밀어내던 것」 인데, 묶음이 하루 안에서만 만들어지면서 한 묶음의
    기사가 모두 같은 날이 되어 그 위험이 사라졌다.

    날짜 축도 같은 이유로 뺐다 — 비교할 것이 없다.
    이 함수를 부르는 곳은 render_index 하나다 (선수 페이지 사다리는 _rep_key 를 쓴다)."""
    if not articles:
        return None
    has_higher = any(a.get("tier") is not None and float(a["tier"]) < 4.0 for a in articles)

    def key(a):
        tier = a.get("tier")
        tv = float(tier) if tier is not None else 99.0
        official = 1 if tv == 0.0 else 0
        not_lowest = 0 if (has_higher and tv >= 4.0) else 1
        return (official, not_lowest, _arsenal_subject_rank(a), -tv,
                _has_body(a), _sort_ts(a)[0],
                _LEAD_STAGE_RANK.get(a.get("transfer_stage") or "", 0))

    return max(articles, key=key)


# ── 카드가 한 장도 안 선 날 가십에서 꺼내기 (2026-08-30) ────────────────
# 두 값 모두 pick_empty_day_gossip 이 쓴다. 접힌 기사를 꺼내던 promote_recent 가
# 여기서 함께 쓰다가 2026-09-02 에 없어졌다 (하루 단위 묶음이라 접힘이 안 생긴다).
#
# 한 선수당 장수를 제한하는 이유는 「같은 기사가 두 번 나와서」 가 아니다. 이 코드는
# 중복인지 아닌지를 보지 않는다 — 제목에서 뽑은 선수 이름 (protagonist) 만 보고
# 같은 이야기로 묶는다. 제한이 없으면 한 선수가 그날 카드를 거의 다 가져간다
# (2026-08-27 실측 — 꺼낼 수 있는 18장 중 14장이 세 선수 것이었다).
PROMOTE_DAYS = 3
PROMOTE_PER_PLAYER_DAY = 3

# 공신력 중 (tier 2) 에는 매체가 여덟이라 (Sky Sports · ESPN · The Times ·
# The Telegraph · arseblog · Globo · UOL · O Jogo) 같은 등급끼리 자주 겹친다.
# 그때는 Sky Sports 를 먼저 세운다 (2026-08-27 사용자 결정).
MID_TIER = 2.0
MID_TIER_PREFERRED_OUTLET = "Sky Sports"


def _mid_tier_rank(row: dict) -> int:
    """공신력 중 안에서의 매체 순서 — Sky Sports 가 0, 나머지가 1.
    다른 등급은 전부 1이라 그 등급 안에서는 아무것도 안 바꾼다."""
    tier = row.get("tier")
    if tier is None or float(tier) != MID_TIER:
        return 1
    return 0 if (row.get("_outlet") or row.get("outlet")) == MID_TIER_PREFERRED_OUTLET else 1


def _stage_visible(row: dict) -> bool:
    """카드가 화면에 남는 단계인가 — 기타 · 미상은 app.js 의 isOther 가 숨긴다."""
    stage = row.get("transfer_stage")
    return bool(stage) and stage != "other"


def pick_empty_day_gossip(lowest: list[dict], carded: set, window: set,
                          players: list[str],
                          cap: int = PROMOTE_PER_PLAYER_DAY) -> list[dict]:
    """카드가 한 장도 안 선 최근 날짜에 세울 가십 기사 (2026-08-30).

    가십 절은 본문 90% 지점이라, 그날 들어온 것이 전부 최하면 홈 첫 화면이 어제에
    멈춘 것처럼 보인다 (배포본 실측 — 90개 날짜 중 43개가 카드 0장).
    그 날짜에만 가십에서 꺼내 날짜 그룹을 세운다.

    **꺼낸 기사는 호출부가 가십 목록에서 빼 준다.** 양쪽에 두면 필터를 걸었을 때
    같은 기사가 두 번 보인다 — `dupcard` 는 필터가 걸리면 오히려 드러나는 장치라
    (app.js 의 `active && m`) 최신 뉴스 쪽 카드와 겹친다.
    """
    by_day: dict = {}
    for a in lowest:
        ts = _group_ts(a)
        if ts is None or not _stage_visible(a):
            continue
        day = to_kst(ts).date()
        if day in carded or day not in window:
            continue
        by_day.setdefault(day, []).append(a)
    picks = []
    for _, arts in sorted(by_day.items(), reverse=True):
        arts.sort(key=_sort_ts, reverse=True)
        per: Counter = Counter()
        for a in arts:
            # 주인공 미상은 서로 다른 이야기라 한 묶음으로 세지 않는다
            key = protagonist(a.get("title_ko") or a.get("title_original") or "",
                              players) or a["content_hash"]
            if per[key] >= cap:
                continue
            per[key] += 1
            picks.append(a)
    return picks


def recent_days(articles: list[dict], n: int = PROMOTE_DAYS) -> set:
    """따로 세울 날짜 — 기사가 있는 최신 n개 날짜 (홈이 펼치는 날짜 그룹 수와 같다).
    카드가 아니라 기사에서 뽑는다 — 따로 세운 결과가 이 범위를 다시 흔들면 안 된다."""
    days = set()
    for a in articles:
        ts = _group_ts(a)
        if ts is not None:
            days.add(to_kst(ts).date())
    return set(sorted(days, reverse=True)[:n])


def render_about() -> str:
    """소개 페이지 (spec1 §10) — 사이드바 없는 프로즈 페이지."""
    return _env().get_template("about.html.j2").render(
        active="about", root="", about_page=True,
        meta=page_meta("소개 · Bullet-in",
                       "Bullet-in 이 어떤 소식을 어떻게 모으고, 공신력 등급을 "
                       "무엇으로 매기는지 정리한 페이지입니다.", "about.html"))


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
        chips=chips or [],
        meta=page_meta(f"{article['_title']} · Bullet-in",
                       (article.get("summary_ko") or article["_title"]),
                       f"article/{current_hash}.html",
                       robots=ARTICLE_ROBOTS, og_type="article",
                       image=article.get("image_url")))


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

    # 미등재 이름의 표기 흔들림 접기 (안건 x) — 전 기사를 봐야 정할 수 있어 여기서 한 번
    # 만들고, 이미 directory 를 받는 모든 자리 (계수 · 카드 · 상세) 가 같은 맵을 쓴다.
    directory = fold_alias_spellings(articles, directory)

    # 선수 페이지 목록을 인덱스보다 먼저 만든다 — 홈에서 꺼낸 카드가 그 선수 페이지로
    # 이어지려면 어떤 선수에게 페이지가 생기는지 먼저 알아야 한다 (안건 π 후속).
    entries = build_player_entries(articles, load_page_players())

    (out / "index.html").write_text(
        render_index(articles, sources, now, directory=directory, registry=registry,
                     outlet_dir=outlet_dir, stories=story_links(entries)),
        encoding="utf-8")
    (out / "all.html").write_text(
        render_all(articles, sources, now, directory=directory, registry=registry,
                   outlet_dir=outlet_dir),
        encoding="utf-8")
    (out / "about.html").write_text(render_about(), encoding="utf-8")

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


def render_ops(view: dict) -> str:
    """수집 현황 화면. 뷰모델은 serve/ops_view 가 만들고 여기서는 템플릿만 부른다."""
    return _env().get_template("ops.html.j2").render(view=view, missing_note=view["missing_note"])


def render_behavior(metrics: dict, *, players=(), articles=(), sources=None) -> str:
    """행동 지표 화면. 뷰모델은 serve/behavior_view 가 만들고 여기서는 템플릿만 부른다."""
    from bullet_in.serve.behavior_view import build_behavior_view
    view = build_behavior_view(metrics, players=players, articles=articles, sources=sources)
    return _env().get_template("behavior.html.j2").render(
        view=view, missing_note=view["missing_note"])


def write_behavior(metrics_path: str | Path, out_dir: str | Path, *,
                   players=(), articles=(), sources=None) -> bool:
    """집계 파일이 있으면 site/behavior.html 을 그린다.

    집계는 회차가 아니라 `warehouse_load` 태스크가 만든다. 파일이 없다는 것은 아직
    한 번도 안 돌았거나 그쪽이 실패했다는 뜻이고, 둘 다 회차를 멈출 이유는 아니다.
    선수 · 기사 · 소스는 화면이 슬러그 · 해시를 이름으로 바꾸는 데만 쓴다.
    """
    src = Path(metrics_path)
    if not src.exists():
        return False
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "behavior.html").write_text(
        render_behavior(json.loads(src.read_text(encoding="utf-8")),
                        players=players, articles=articles, sources=sources),
        encoding="utf-8")
    return True


def write_ops(snapshot: dict, sources: dict, out_dir: str | Path,
              anomaly_count: int, now: datetime,
              unmatched: list[dict] | None = None,
              gate_path: str | Path | None = None) -> None:
    """수집 현황 site/ops.html 생성. 실패 격리는 호출부 (run.py) 책임.

    gate_path 는 직전 회차 게이트의 `dbt/target/run_results.json` 이다 — 회차의 gate
    태스크가 publish 뒤에 돌아 이번 회차 것은 아직 없다 (스펙 2026-09-05 §2). 없으면
    SLO-3 · 4 가 「게이트 결과 없음」 으로 그려진다.
    """
    from bullet_in.dbt_gate import gate_tally
    from bullet_in.serve.ops_view import build_ops_view
    gate = gate_tally(Path(gate_path)) if gate_path else None
    view = build_ops_view(snapshot, sources, anomaly_count, now, gate=gate, unmatched=unmatched)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "ops.html").write_text(render_ops(view), encoding="utf-8")
