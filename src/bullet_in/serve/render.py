from __future__ import annotations
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

_TPL_DIR = Path(__file__).parent / "templates"

def render_page(articles: list[dict]) -> str:
    ordered = sorted(articles, key=lambda a: a.get("confidence_score") or 0.0, reverse=True)
    env = Environment(loader=FileSystemLoader(_TPL_DIR),
                      autoescape=select_autoescape(["html"]))
    return env.get_template("index.html.j2").render(articles=ordered)

def write_page(articles: list[dict], out_path: str | Path) -> None:
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(render_page(articles), encoding="utf-8")
