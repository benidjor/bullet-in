"""모바일 화면 (640px 이하 · 세로) 회귀 가드 — 카드 가로 넘침과 이적시장 타이머 표기.

pytest 는 브라우저를 안 띄우므로 여기서 고정하는 것은 style.css · app.js 가
공유하는 문자열 계약뿐이다. 실제 폭은 브라우저에서 쟀다 (2026-09-02 · 배포본을
393px 뷰포트에 올려 문서 폭 470px → 393px · 카드 455px → 342px).

**이 검사가 못 보는 것** — 실제 렌더 폭, 기기별 글꼴 차이, 상단 바가 접히는 지점,
320px 처럼 더 좁은 화면, D 표기 계산의 실행 결과. 그래서 통과가 「화면이 안 깨진다」
는 증명은 아니다.
"""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src/bullet_in/serve/static"


def test_list_cards_may_shrink_below_their_min_content():
    # 그리드 아이템의 자동 최소 크기는 min-content 다. 카드 메타 줄 (배지 · 매체 ·
    # 공신력 · 시각) 이 한 줄로 버티므로 그 폭이 그대로 카드 폭이 되고, 한 열로
    # 접히는 모바일 화면에서 카드가 칸을 넘어 문서 전체가 가로로 넘쳤다.
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    for sel in ("daylist", "gossiplist"):
        assert re.search(rf"\.{sel}\s*>\s*\*[^{{]*\{{[^}}]*min-width\s*:\s*0", css), (
            f".{sel} > * 에 min-width:0 이 없음 — 모바일 화면에서 카드가 칸보다 "
            "넓어져 화면 전체가 가로로 밀리는 결함"
        )


def test_narrow_screen_keeps_a_label_beside_the_countdown():
    # 레이블을 통째로 감추면 「2:05:12」 만 남아 무엇까지 남은 시간인지 읽히지 않는다
    # (2026-09-02 사용자 지적). 모바일 화면에서는 문구를 줄여서 남긴다.
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert not re.search(r"\.mktclock\s+\.mkt-label\s*\{[^}]*display\s*:\s*none", css), (
        "모바일 화면에서 타이머 레이블을 감추고 있음 — 숫자만 남는다"
    )
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert re.search(r"matchMedia\(\s*'\(max-width:\s*640px\)'\s*\)", js), (
        "app.js 가 모바일 화면을 판정하지 않음 — 줄인 문구를 고를 근거가 없다"
    )
    for word in ("이적 마감", "이적 시장"):
        assert f"'{word}'" in js, f"모바일 화면 문구 「{word}」 가 없음"
    assert "D-${" in js, "모바일 화면에서 남은 날짜를 D 표기로 적는 자리가 없음"


def test_dday_counts_calendar_days_in_kst():
    # D-N 은 남은 시간이 아니라 달력 날짜다. 남은 시간을 24 로 나누면 하루씩 어긋난다
    # — 마감이 9월 2일 07:00 이고 지금이 9월 1일 20:00 이면 남은 시간은 11시간인데
    # 달력으로는 D-1 이다. 기준 시간대는 화면 표기와 같은 KST 여야 한다.
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "KST_MS = 9 * 3600000" in js, "D 계산의 기준 시간대가 KST 로 고정돼 있지 않음"
    assert re.search(r"ddayKst\s*=\s*\(at,\s*now\)", js), (
        "달력 날짜로 D-N 을 세는 함수가 없음 — 남은 시간을 24 로 나누면 하루씩 어긋난다"
    )
    # 마지막 하루는 D-DAY 대신 시계 — 「하루 넘게 남았을 때만 D 표기」 라는 경계다.
    assert re.search(r"narrow\s*&&\s*left\s*>=\s*86400000", js), (
        "마지막 하루를 시계로 넘기는 경계가 없음 — D-0 이 화면에 뜬다"
    )
def test_list_cards_share_the_left_edge_with_the_band():
    # 카드의 좌우 패딩은 상위 두 등급 배경 음영 안에서 글자를 띄우려고 둔 것인데,
    # 배경이 없는 카드까지 12px 씩 밀려 히어로 · 절 머리와 세로선이 어긋났다
    # (2026-09-02 사용자 지적 · 실측 393px 에서 밴드 16px 대 목록 28px).
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert re.search(r"\.daylist\s+\.item\{[^}]*padding-left\s*:\s*0", css), (
        "모바일 화면에서 카드 좌우 패딩을 걷는 규칙이 없음 — 목록이 밴드보다 안쪽에 선다"
    )
    # 음영을 칠하는 쪽이 페이지마다 다르다 — 둘 다 넓혀야 글자만 제자리에 선다.
    # 넓히는 값은 .shell 의 좌우 패딩 (16px) 보다 작아야 띠가 화면 끝에서 떨어진다.
    for sel in (r"\.block\.g0", r"\.daylist\.flatlist\s+\.item\.g0"):
        assert re.search(sel + r"[^{]*\{[^}]*margin-left\s*:\s*-8px", css), (
            f"{sel} 의 배경을 8px 넓히는 규칙이 없음 — 음영이 글자에 붙는다"
        )
