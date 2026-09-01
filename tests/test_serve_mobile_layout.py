"""좁은 화면 회귀 가드 — 카드 가로 넘침과 이적시장 타이머 레이블.

pytest 는 브라우저를 안 띄우므로 여기서 고정하는 것은 style.css · app.js 가
공유하는 문자열 계약뿐이다. 실제 폭은 브라우저에서 쟀다 (2026-09-02 · 배포본을
393px 뷰포트에 올려 문서 폭 470px → 393px · 카드 455px → 342px).

**이 검사가 못 보는 것** — 실제 렌더 폭, 기기별 글꼴 차이, 상단 바가 접히는 지점,
320px 처럼 더 좁은 화면. 그래서 통과가 「화면이 안 깨진다」 는 증명은 아니다.
"""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src/bullet_in/serve/static"


def test_list_cards_may_shrink_below_their_min_content():
    # 그리드 아이템의 자동 최소 크기는 min-content 다. 카드 메타 줄 (배지 · 매체 ·
    # 공신력 · 시각) 이 한 줄로 버티므로 그 폭이 그대로 카드 폭이 되고, 한 열로
    # 접히는 좁은 화면에서 카드가 칸을 넘어 문서 전체가 가로로 넘쳤다.
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    for sel in ("daylist", "gossiplist"):
        assert re.search(rf"\.{sel}\s*>\s*\*[^{{]*\{{[^}}]*min-width\s*:\s*0", css), (
            f".{sel} > * 에 min-width:0 이 없음 — 좁은 화면에서 카드가 칸보다 "
            "넓어져 화면 전체가 가로로 밀리는 결함"
        )


def test_narrow_screen_keeps_a_label_beside_the_countdown():
    # 레이블을 통째로 감추면 「2:05:12」 만 남아 무엇까지 남은 시간인지 읽히지
    # 않는다 (2026-09-02 사용자 지적). 좁은 화면에서는 문구를 줄여서 남긴다.
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert not re.search(r"\.mktclock\s+\.mkt-label\s*\{[^}]*display\s*:\s*none", css), (
        "좁은 화면에서 타이머 레이블을 감추고 있음 — 숫자만 남는다"
    )
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert re.search(r"matchMedia\(\s*'\(max-width:\s*640px\)'\s*\)", js), (
        "app.js 가 좁은 화면을 판정하지 않음 — 줄인 문구를 고를 근거가 없다"
    )
    assert re.search(r"narrow\s*\?\s*ev\.what", js), (
        "좁은 화면에서 고를 짧은 문구 (「마감」 · 「개장」) 가 없음"
    )
