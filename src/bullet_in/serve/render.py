from __future__ import annotations
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

def render_page(articles: list[dict]) -> str:
    ordered = sorted(articles, key=lambda a: a.get("confidence_score") or 0.0, reverse=True)
    env = Environment(loader=FileSystemLoader(_TPL_DIR),
                      autoescape=select_autoescape(default_for_string=True, default=True))
    return env.get_template("index.html.j2").render(articles=ordered)

def write_page(articles: list[dict], out_path: str | Path) -> None:
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(render_page(articles), encoding="utf-8")
