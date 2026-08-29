"""타이포그래피 규칙 회귀 검사 — 「18px 이상은 세리프, 미만은 산세리프」.

눈으로 세다가 선택자가 앞줄에 있는 규칙을 하나 놓쳤다 (`.mains .bandhead` 15px).
규칙을 통째로 파싱해서 걸러야 그런 자리가 안 남는다.
"""
import re
from pathlib import Path

CSS = Path(__file__).resolve().parents[1] / "src/bullet_in/serve/static/style.css"
SERIF_MIN_PX = 18.0


def _rules():
    """(선택자, 크기, 굵기) — 주석을 뺀 뒤 최상위 규칙만 훑는다."""
    css = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)
    for m in re.finditer(r"([^{}@]+)\{([^{}]*)\}", css):
        sel, body = m.group(1).strip().replace("\n", " "), m.group(2)
        size = re.search(r"font-size:\s*([\d.]+)px", body)
        weight = re.search(r"font-weight:\s*(\d+)", body)
        yield (sel, float(size.group(1)) if size else None,
               int(weight.group(1)) if weight else None, body)


def test_serif_is_not_used_below_the_boundary():
    # 한글 세리프는 작은 크기에서 가로획이 가늘어져 흐려진다 (2026-08-30 실물 비교).
    bad = [(s, px) for s, px, _w, body in _rules()
           if "var(--serif)" in body and px is not None and px < SERIF_MIN_PX]
    assert not bad, f"18px 미만에 세리프가 남았다: {bad}"


def test_titles_are_not_heavier_than_800():
    # 900 은 모바일에서 덩어리로 읽힌다 — 제목 상한을 800 으로 둔다.
    heavy = [(s, w) for s, _px, w, _b in _rules() if w is not None and w > 800]
    assert not heavy, f"굵기 800 을 넘는 자리가 있다: {heavy}"


def test_body_paragraph_gap_is_wider_than_the_line_gap():
    # 문단 사이 빈 공간 = margin + (line-height − font-size) · 줄 사이 = 그 뒷항.
    css = CSS.read_text(encoding="utf-8")
    body = re.search(r"\.body\{font-size:(\d+)px;line-height:([\d.]+)\}", css)
    para = re.search(r"\.body p\{margin:0 0 (\d+)px\}", css)
    assert body and para, "본문 · 문단 규칙을 못 찾았다"
    fs, lh, mb = int(body.group(1)), float(body.group(2)), int(para.group(1))
    leading = fs * lh - fs
    assert (mb + leading) / leading >= 2.8, (
        f"문단 사이가 줄 사이의 {(mb + leading) / leading:.2f}배 — 3.0배 근처로 둔다")
