from __future__ import annotations
import json
import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from bullet_in import transfer_stage as _stage

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


def outlet_display(row: dict, sources: dict) -> str:
    return (row.get("outlet")
            or sources.get(row.get("source_id"), {}).get("display_name")
            or row.get("source_id") or "")


def tier_label(tier) -> str:
    if tier is None:
        return "tier ?"
    return f"tier {int(tier)}"


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
    if entry:
        name, outlet, registered = entry["name"], entry["outlet"], True
    else:
        name, outlet, registered = j, src.get("outlet"), False
    if j == src.get("journalist_label") or not outlet:
        label = name                       # 통칭 · 소속 미상 → 괄호 생략
    else:
        label = f"{name} ({outlet})"
    return {"name": name, "label": label, "registered": registered}


def facet_counts(articles: list[dict], sources: dict, directory: dict | None = None) -> dict:
    teams = Counter(a.get("team") or "arsenal" for a in articles)
    outlet_ctr = Counter(outlet_display(a, sources) for a in articles)
    outlets = sorted(outlet_ctr.items(), key=lambda kv: (-kv[1], kv[0]))
    tiers = {t: 0 for t in range(5)}
    for a in articles:
        t = a.get("tier")
        if t is not None and 0 <= int(t) <= 4:
            tiers[int(t)] += 1
    stage_counts = {e: 0 for e, _, _ in _stage.SIDEBAR_STAGES}
    other_count = 0
    for a in articles:
        s = a.get("transfer_stage")
        if s in stage_counts:
            stage_counts[s] += 1
        else:
            other_count += 1

    reg_ctr: Counter = Counter()
    more_ctr: Counter = Counter()
    labels: dict[str, str] = {}
    for a in articles:
        e = journalist_entry(a, sources, directory)
        if e is None:
            continue
        (reg_ctr if e["registered"] else more_ctr)[e["name"]] += 1
        labels[e["name"]] = e["label"]

    def _ranked(ctr: Counter) -> list[tuple[str, str, int]]:
        return [(n, labels[n], c)
                for n, c in sorted(ctr.items(), key=lambda kv: (-kv[1], kv[0]))]

    return {"total": len(articles), "team": dict(teams),
            "outlets": outlets, "tiers": tiers, "stage": stage_counts,
            "other": other_count,
            "journalists": {"registered": _ranked(reg_ctr), "more": _ranked(more_ctr)}}

# ---- 운영 뷰 (ops.html) 뷰모델 ----
# 지표 정의 · 데이터 계약: docs/superpowers/specs/2026-07-14-ops-monitoring-view-design.md §5 · §6

TIER_BUCKETS = [(1.0, "Tier 1 — 공식 · 1군 언론"),
                (2.0, "Tier 2 — 2군 · 애그리게이터"),
                (3.0, "Tier 3 — ITK · 루머")]
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


def _decorate(row: dict, sources: dict, now: datetime,
              directory: dict | None = None) -> dict:
    a = dict(row)
    a["_title"] = row.get("title_ko") or row.get("title_original") or ""
    a["_outlet"] = outlet_display(row, sources)
    a["_tier_label"] = tier_label(row.get("tier"))
    pub = row.get("published_at")
    a["_when"] = humanize_when(pub, now) if pub else ""
    a["_published_iso"] = pub.isoformat() if pub else ""
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
    return sorted(articles,
                  key=lambda a: a.get("published_at") or datetime.min,
                  reverse=True)


def render_index(articles: list[dict], sources: dict, now: datetime,
                 directory: dict | None = None) -> str:
    ordered = [_decorate(a, sources, now, directory=directory)
               for a in _sorted_latest(articles)]
    facets = facet_counts(articles, sources, directory=directory)
    return _env().get_template("index.html.j2").render(
        articles=ordered, facets=facets, active="home", root="")


def build_neighbors(ordered: list[dict], idx: int, sources: dict,
                    now: datetime, directory: dict | None = None) -> list[dict]:
    start, end = neighbor_window(len(ordered), idx)
    out = []
    for j in range(start, end):
        d = _decorate(ordered[j], sources, now, directory=directory)
        d["_is_current"] = (j == idx)
        out.append(d)
    return out


def render_article(article: dict, neighbors: list[dict], current_hash: str,
                   sources: dict, now: datetime, facets: dict | None = None) -> str:
    # facets=None이면 빈 구조로 폴백 (하위 호환 유지)
    if facets is None:
        facets = {"team": {}, "outlets": [], "tiers": {t: 0 for t in range(5)},
                  "total": 0, "stage": {}, "other": 0,
                  "journalists": {"registered": [], "more": []}}
    article = dict(article)
    paras = [p for p in (article.get("body_ko") or "").split("\n") if p.strip()]
    article["_body_blocks"] = interleave_body(paras, article.get("_images") or [])
    return _env().get_template("detail.html.j2").render(
        a=article, neighbors=neighbors, active=None, root="../", facets=facets)


def write_site(articles: list[dict], sources: dict, out_dir: str | Path,
               now: datetime | None = None,
               directory: dict | None = None) -> None:
    """인덱스·상세 N개·정적 자산을 out_dir에 일괄 생성한다."""
    now = now or datetime.utcnow()
    out = Path(out_dir)
    (out / "article").mkdir(parents=True, exist_ok=True)

    (out / "index.html").write_text(
        render_index(articles, sources, now, directory=directory), encoding="utf-8")

    ordered = _sorted_latest(articles)
    # 패싯은 전체 기사 기준으로 한 번만 계산해 모든 상세 페이지에 전달
    facets = facet_counts(articles, sources, directory=directory)
    for idx, row in enumerate(ordered):
        a = _decorate(row, sources, now, directory=directory)
        neighbors = build_neighbors(ordered, idx, sources, now, directory=directory)
        html = render_article(a, neighbors, row["content_hash"], sources, now, facets=facets)
        (out / "article" / f"{row['content_hash']}.html").write_text(
            html, encoding="utf-8")

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
