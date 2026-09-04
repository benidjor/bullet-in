"""차트 함수는 순수 함수다 — 값을 넣으면 SVG 문자열이 나오고, 그 구조를 센다.

픽셀을 재지 않는다. 막대 수 · 라벨 · 툴팁 · 클래스만 본다.
"""
from datetime import date

from bullet_in.serve import charts as C


def test_눈금은_보기_좋은_단위로_오른다():
    assert C.nice_ticks(0) == [0]
    assert C.nice_ticks(863) == [0, 500, 1000]
    assert C.nice_ticks(30) == [0, 10, 20, 30]


def test_스파크라인은_값이_없거나_전부_0이면_비운다():
    assert C.sparkline([]) == ""
    assert C.sparkline([0, 0]) == ""
    svg = C.sparkline([1, 3, 2])
    assert "<polyline" in svg and 'class="dot s1"' in svg


def test_누적_막대는_0인_조각을_안_그린다():
    svg = C.stacked_columns(["08/28", "08/29"],
                            [("신규", [94, 666], "s1"), ("재방문", [0, 22], "s2")], unit="명")
    assert svg.count('class="seg s1"') == 2
    assert svg.count('class="seg s2"') == 1
    assert "94명 · 신규" in svg and "0명 · 재방문" in svg     # 툴팁에는 0 도 적는다


def test_누적_막대의_비율_모드는_툴팁에_퍼센트를_적는다():
    svg = C.stacked_columns(["w1"], [("a", [3], "o1"), ("b", [1], "o2")], pct=True)
    assert "(75%)" in svg and "(25%)" in svg


def test_가로_막대는_행마다_라벨과_값을_적는다():
    rows = [{"lab": "홈", "n": 2228}, {"lab": "기사 상세", "n": 763}]
    svg = C.hbars(rows, value="n", label="lab")
    assert svg.count('class="hit"') == 2
    assert ">홈<" in svg and "2,228" in svg


def test_가로_막대는_흐린_행을_따로_표시한다():
    rows = [{"lab": "BBC", "n": 5}, {"lab": "표시 없음", "n": 9}]
    svg = C.hbars(rows, value="n", label="lab", dim_label="표시 없음")
    assert 'class="cat muted"' in svg and "bar s1 dim" in svg


def test_diverging_은_음수를_왼쪽_빨강으로_그린다():
    svg = C.diverging([("등급 0", 4.9, "클릭 10"), ("등급 4", -22.0, "클릭 3")])
    assert 'class="bar pos"' in svg and 'class="bar neg"' in svg
    assert "+4.9pp" in svg and "-22.0pp" in svg


def test_퍼널은_앞_단계_대비_전환율을_적는다():
    svg = C.funnel([("진입", 863), ("카드 클릭", 221)], sides=(("원문 이동", 7),))
    assert "100%" in svg and "25.6% 전환" in svg
    assert "진입의 1%" in svg and 'class="seg dimseg"' in svg


def test_히트맵은_값이_없는_칸을_따로_그리고_숫자를_넣을_수_있다():
    cells = {("a", 0): 100, ("a", 1): 50, ("a", 2): None}
    svg = C.heatmap(["a"], [0, 1, 2], cells, unit="%", show_text=True, scale_exclude_col=0)
    assert svg.count('class="cell none"') == 1
    assert svg.count('class="cell"') == 2
    assert ">50%<" in svg


def test_히트맵의_회차_표시는_삼각형과_설명이다():
    svg = C.heatmap([1], list(range(24)), {(1, h): 0 for h in range(24)}, marks=[0, 3])
    assert svg.count('class="mark"') == 2 and "▲ 회차 시각" in svg


def test_캘린더는_기간_밖_날짜를_안_그린다():
    svg = C.calendar({"2026-06-12": 3}, date(2026, 6, 12), date(2026, 6, 13))
    assert svg.count('class="cell"') == 2
    assert "2026-06-12" in svg and "2026-06-11" not in svg


def test_미터는_찬_정도로_색을_고른다():
    assert 'fill ok' in C.meter(2, 10)
    assert 'fill warn' in C.meter(8, 10)
    assert 'fill bad' in C.meter(10, 10)


def test_덤벨은_로그_눈금과_p50_p95_를_적는다():
    svg = C.dumbbell_log([("BBC", 2.5, 20.0, 40)])
    assert "1일" in svg and "p50 2.5h · p95 20.0h" in svg


def test_표는_접힌_details_다():
    html = C.table(["a", "b"], [(1, 2)])
    assert html.startswith('<details class="tbl">') and "<td>1</td>" in html


def test_라벨의_html_은_이스케이프된다():
    svg = C.hbars([{"lab": "<b>x</b>", "n": 1}], value="n", label="lab")
    assert "<b>" not in svg and "&lt;b&gt;" in svg


def test_선_차트는_밴드와_실패_표시를_그린다():
    svg = C.line_chart(["a", "b", "c"], [("p50", [1, 2, 3])], band=([0, 1, 2], [2, 3, 4]),
                       fails=[(1, "에러 회차 1회")])
    assert 'class="band s1"' in svg and 'class="fail"' in svg
    assert "p10 0 · p90 2" in svg


def test_빈_입력이면_빈_svg_를_돌려주고_예외를_안_낸다():
    for svg in (C.hbars([], value="n", label="lab"),
                C.stacked_columns([], []),
                C.line_chart([], []),
                C.heatmap(["a"], [], {})):
        assert svg.startswith('<svg class="chart"')
        assert "<rect" not in svg and "<path" not in svg and "<polyline" not in svg
