from __future__ import annotations
import json
import logging
import re
import shutil
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from bullet_in import transfer_stage as _stage
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
    미등재 핸들만 aggregator 폴백을 유지한다 (트랙 ③ 설계 ①-A)."""
    src = sources.get(row.get("source_id"), {})
    if row.get("outlet"):
        return row["outlet"]
    if src.get("credibility") == "x_mentions":
        j = (row.get("journalist") or "").strip()
        entry = (directory or {}).get(j.lower())
        if entry and entry.get("outlet"):
            return entry["outlet"]
        fold = (outlet_dir or {}).get(j.lstrip("@").lower())
        if fold:
            return fold
    return (src.get("outlet")
            or src.get("display_name")
            or row.get("source_id") or "")


TIER_ORDER: list[float] = [0.0, 1.0, 1.5, 2.0, 3.0, 4.0]
INITIAL_MAX_TIER = 1.5                      # 초기 노출 상한 (spec §3.2)
TIER_HEADINGS: dict[float, str] = {
    0.0: "Tier 0 · 공식",
    1.0: "Tier 1 · 공신력 최상",
    1.5: "Tier 1.5 · 공신력 상",
    2.0: "Tier 2 · 공신력 중",
    3.0: "Tier 3 · 공신력 하",
    4.0: "Tier 4 · 공신력 최하",
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
    entry = (directory or {}).get(j.lower())
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
        t = registry.outlets.get(key.lower())
        if t is not None:
            return float(t)
    t = sources.get(row.get("source_id"), {}).get("tier")
    return float(t) if t is not None else None


def _journalist_tier(row: dict, entry: dict, registry) -> float | None:
    if entry["registered"] and registry is not None:
        j = (row.get("journalist") or "").strip().lower()
        t = registry.journalists.get(j)
        if t is None:
            t = registry.journalists.get(entry["name"].lower())
        if t is not None:
            return float(t)
    # 비전담 · 조직 · 통칭 → 기사 저장 tier (비전담 기준선) 그룹으로 분류
    t = row.get("tier")
    return float(t) if t is not None else None


def _facet_rows(counts: Counter, labels: dict, tiers: dict) -> dict:
    """tier 그룹 · 더보기 단계로 나눈 facet 뷰모델 (spec §3.1 · §3.2).
    TIER_ORDER 에 없는 tier (설정 오류) 는 미등재로 흘려보낸다."""
    def _item(n, c):
        return {"value": n, "label": labels.get(n, n), "count": c}

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
            label = f"더보기 · Tier {tier_key(t)} · 미등재"
        elif g["items"]:
            label = f"더보기 · Tier {tier_key(t)}"
        else:
            label = "더보기 · 미등재"
        stages.append({"label": label,
                       "groups": [g] if g["items"] else [],
                       "unregistered": tail})
    return {"initial": initial, "stages": stages}


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
    tiers = [{"key": tier_key(t), "label": tier_label(t), "count": seen.get(tier_key(t), 0)}
             for t in TIER_ORDER]

    stage_counts = {e: 0 for e, _, _ in _stage.SIDEBAR_STAGES}
    other_count = 0
    for a in articles:
        s = a.get("transfer_stage")
        if s in stage_counts:
            stage_counts[s] += 1
        else:
            other_count += 1

    return {"total": len(articles), "team": dict(teams),
            "tiers": tiers, "stage": stage_counts, "other": other_count,
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

    return {"generated_at": f"{now:%Y-%m-%d %H:%M} UTC",
            "kpi": _kpi(runs, stale_count, pending_total),
            "runs_chart": runs_chart, "freshness": freshness,
            "volume": volume, "tiers": tiers, "slo": slo}

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
    st = row.get("transfer_stage")
    a["_stage"] = st or ""
    a["_stage_badge"] = _stage.is_displayable(st)
    a["_stage_label"] = _stage.label_for(st)
    a["_stage_class"] = _stage.css_for(st)
    e = journalist_entry(row, sources, directory)
    a["_journalist"] = e["name"] if e else ""   # 카드 data 속성 · 필터 키
    a["_byline"] = e["label"] if e else None    # 표시 라벨 — 기자 (언론사)
    return a


def _sorted_latest(articles: list[dict]) -> list[dict]:
    return sorted(articles, key=_sort_ts, reverse=True)


def render_index(articles: list[dict], sources: dict, now: datetime,
                 directory: dict | None = None, registry=None,
                 outlet_dir: dict | None = None) -> str:
    ordered = [_decorate(a, sources, now, directory=directory, outlet_dir=outlet_dir)
               for a in _sorted_latest(articles)]
    facets = facet_counts(articles, sources, directory=directory, registry=registry,
                          outlet_dir=outlet_dir)
    return _env().get_template("index.html.j2").render(
        articles=ordered, facets=facets, active="home", root="")


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
                   sources: dict, now: datetime, facets: dict | None = None) -> str:
    # facets=None이면 빈 구조로 폴백 (하위 호환 유지)
    if facets is None:
        facets = {"team": {}, "tiers": [], "total": 0, "stage": {}, "other": 0,
                  "outlets": {"initial": [], "stages": []},
                  "journalists": {"initial": [], "stages": []}}
    article = dict(article)
    paras = [p for p in (article.get("body_ko") or "").split("\n") if p.strip()]
    article["_excerpt"] = serving_mode(article.get("source_id"), sources) == "excerpt"
    images = article.get("_images") or []
    if article["_excerpt"]:
        paras, images = excerpt_paras(paras), []
    article["_body_blocks"] = interleave_body(paras, images)
    if article.get("source_id") == "bbc_gossip":
        article["_body_blocks"] = gossip_itemize(
            article["_body_blocks"], roundup_attrib_counts(article.get("body_source")))
    return _env().get_template("detail.html.j2").render(
        a=article, neighbors=neighbors, active=None, root="../", facets=facets)


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

    ordered = _sorted_latest(articles)
    # 패싯은 전체 기사 기준으로 한 번만 계산해 모든 상세 페이지에 전달
    facets = facet_counts(articles, sources, directory=directory, registry=registry,
                          outlet_dir=outlet_dir)
    for idx, row in enumerate(ordered):
        a = _decorate(row, sources, now, directory=directory, outlet_dir=outlet_dir)
        neighbors = build_neighbors(ordered, idx, sources, now, directory=directory,
                                    outlet_dir=outlet_dir)
        html = render_article(a, neighbors, row["content_hash"], sources, now, facets=facets)
        (out / "article" / f"{row['content_hash']}.html").write_text(
            html, encoding="utf-8")

    sweep_orphan_pages(articles, out)

    for asset in ("style.css", "app.js"):
        shutil.copyfile(_STATIC_DIR / asset, out / asset)


def render_ops(view: dict) -> str:
    return _env().get_template("ops.html.j2").render(view=view)


def write_ops(snapshot: dict, sources: dict, out_dir: str | Path,
              anomaly_count: int, now: datetime) -> None:
    """운영 뷰 site/ops.html 생성. 실패 격리는 호출부 (run.py) 책임."""
    view = build_ops_view(snapshot, sources, anomaly_count, now)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "ops.html").write_text(render_ops(view), encoding="utf-8")
