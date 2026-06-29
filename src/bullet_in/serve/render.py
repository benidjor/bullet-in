from __future__ import annotations
import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

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


def facet_counts(articles: list[dict], sources: dict) -> dict:
    teams = Counter(a.get("team") or "arsenal" for a in articles)
    outlet_ctr = Counter(outlet_display(a, sources) for a in articles)
    outlets = sorted(outlet_ctr.items(), key=lambda kv: (-kv[1], kv[0]))
    tiers = {t: 0 for t in range(5)}
    for a in articles:
        t = a.get("tier")
        if t is not None and 0 <= int(t) <= 4:
            tiers[int(t)] += 1
    return {"total": len(articles), "team": dict(teams),
            "outlets": outlets, "tiers": tiers}

def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(_TPL_DIR),
        autoescape=select_autoescape(default_for_string=True, default=True),
    )


def _decorate(row: dict, sources: dict, now: datetime) -> dict:
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
    u = row.get("url") or ""
    a["url"] = u if re.match(r"^https?://", u) else "#"
    return a


def _sorted_latest(articles: list[dict]) -> list[dict]:
    return sorted(articles,
                  key=lambda a: a.get("published_at") or datetime.min,
                  reverse=True)


def render_index(articles: list[dict], sources: dict, now: datetime) -> str:
    ordered = [_decorate(a, sources, now) for a in _sorted_latest(articles)]
    facets = facet_counts(articles, sources)
    return _env().get_template("index.html.j2").render(
        articles=ordered, facets=facets, active="home", root="")


def build_neighbors(ordered: list[dict], idx: int, sources: dict,
                    now: datetime) -> list[dict]:
    start, end = neighbor_window(len(ordered), idx)
    out = []
    for j in range(start, end):
        d = _decorate(ordered[j], sources, now)
        d["_is_current"] = (j == idx)
        out.append(d)
    return out


def render_article(article: dict, neighbors: list[dict], current_hash: str,
                   sources: dict, now: datetime, facets: dict | None = None) -> str:
    # facets=None이면 빈 구조로 폴백 (하위 호환 유지)
    if facets is None:
        facets = {"team": {}, "outlets": [], "tiers": {t: 0 for t in range(5)}, "total": 0}
    return _env().get_template("detail.html.j2").render(
        a=article, neighbors=neighbors, active=None, root="../", facets=facets)


def write_site(articles: list[dict], sources: dict, out_dir: str | Path,
               now: datetime | None = None) -> None:
    """인덱스·상세 N개·정적 자산을 out_dir에 일괄 생성한다."""
    now = now or datetime.utcnow()
    out = Path(out_dir)
    (out / "article").mkdir(parents=True, exist_ok=True)

    (out / "index.html").write_text(render_index(articles, sources, now),
                                    encoding="utf-8")

    ordered = _sorted_latest(articles)
    # 패싯은 전체 기사 기준으로 한 번만 계산해 모든 상세 페이지에 전달
    facets = facet_counts(articles, sources)
    for idx, row in enumerate(ordered):
        a = _decorate(row, sources, now)
        neighbors = build_neighbors(ordered, idx, sources, now)
        html = render_article(a, neighbors, row["content_hash"], sources, now, facets=facets)
        (out / "article" / f"{row['content_hash']}.html").write_text(
            html, encoding="utf-8")

    for asset in ("style.css", "app.js"):
        shutil.copyfile(_STATIC_DIR / asset, out / asset)
