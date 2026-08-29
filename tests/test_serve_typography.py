"""타이포그래피 규칙 회귀 검사.

**세리프는 크기 하나로 못 자른다 — 굵기와 함께 본다** (2026-08-30 실물 사다리).
14.5px 세리프도 굵기 700 이면 읽히고, 900 이면 획이 뭉치며, 600 이하면 무너진다.
처음엔 「18px 이상만 세리프」 로 잡았는데 굵기를 변수에 안 넣은 거친 규칙이었다.

**이 검사가 안 보는 것** — 글자 색 (`--mut` · `--dim` 으로 흐려진 자리),
배경 대비, 상속으로 세리프가 흘러가는 자리 (규칙만 파싱하고 DOM 은 안 본다),
실제 기기 렌더링. 그래서 통과가 「읽힌다」 는 증명은 아니다.

눈으로 세다가 선택자가 앞줄에 있는 규칙을 하나 놓쳤다 (`.mains .bandhead` 15px).
규칙을 통째로 파싱해야 그런 자리가 안 남는다.
"""
import re
from pathlib import Path

CSS = Path(__file__).resolve().parents[1] / "src/bullet_in/serve/static/style.css"
SERIF_MIN_PX = 14.0        # 이 아래는 굵기와 무관하게 세리프를 안 쓴다
SERIF_BOLD_BELOW_PX = 18.0  # 18px 미만 세리프는 굵기 700 이상일 때만
SERIF_MIN_WEIGHT = 700


def _rules():
    """(선택자, 크기, 굵기) — 주석을 뺀 뒤 최상위 규칙만 훑는다."""
    css = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)
    for m in re.finditer(r"([^{}@]+)\{([^{}]*)\}", css):
        sel, body = m.group(1).strip().replace("\n", " "), m.group(2)
        size = re.search(r"font-size:\s*([\d.]+)px", body)
        weight = re.search(r"font-weight:\s*(\d+)", body)
        yield (sel, float(size.group(1)) if size else None,
               int(weight.group(1)) if weight else None, body)


def test_serif_is_never_used_at_tiny_sizes():
    # 14px 아래는 굵기를 올려도 한글 세리프의 가로획이 버티지 못한다.
    bad = [(s, px) for s, px, _w, body in _rules()
           if "var(--serif)" in body and px is not None and px < SERIF_MIN_PX]
    assert not bad, f"{SERIF_MIN_PX:g}px 미만에 세리프가 남았다: {bad}"


def test_small_serif_carries_enough_weight():
    # 14 ~ 18px 구간의 세리프는 굵기 700 이상이어야 획이 선다.
    # 굵기를 안 적은 자리는 상속이라 판정할 수 없어 함께 잡는다 — 명시하게 만든다.
    bad = [(s, px, w) for s, px, w, body in _rules()
           if "var(--serif)" in body and px is not None
           and SERIF_MIN_PX <= px < SERIF_BOLD_BELOW_PX
           and (w is None or w < SERIF_MIN_WEIGHT)]
    assert not bad, f"작은 세리프에 굵기가 모자라거나 안 적혔다: {bad}"


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
