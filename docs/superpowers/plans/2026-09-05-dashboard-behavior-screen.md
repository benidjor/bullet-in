# 대시보드 개편 PR 1 — 행동 지표 화면 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 행동 지표 화면 (`behavior.html`) 을 목업 v2.8 대로 다시 만든다.
gold 표 셋과 집계 다섯을 새로 만들고, 차트를 순수 함수 모듈로 옮기고, 템플릿을 새로 쓴다.

**Architecture:** `warehouse.py` 가 silver `ga4_events_flat` 에서 gold 표 셋 (`fact_session` · `fact_user_daily` · `dim_user`) 을 통째로 다시 만들고, 집계 다섯이 그 위에서 돌아 `state/behavior_metrics.json` 한 파일로 떨어진다.
회차의 `publish` 는 그 파일과 MariaDB 의 선수 · 기사 행만 읽어 `serve/behavior_view.py` 가 뷰모델을 만들고 `serve/charts.py` 가 SVG 를 그린다.
템플릿 `behavior.html.j2` 는 공통 조각 `_dash.html.j2` 를 상속한다.

**Tech Stack:** Python 3.11 · pyarrow · PyIceberg (SqlCatalog 로 로컬 테스트) · Jinja2 · markupsafe · pytest.

**Spec:** `docs/superpowers/specs/2026-09-05-dashboard-redesign-design.md` (§3.1 데이터 경로 · §3.2 차트 · §3.3 템플릿 · §3.6 계측 · §4 빈 구간 · §5 검증).

## Global Constraints

- 사람을 세는 키는 `user_pseudo_id` 하나다. `bi_cid` 는 어디에도 쓰지 않는다 (스펙 §3.1).
- 공개일 (`LAUNCH_DATE` = 2026-08-29) 은 총량 · 시계열에 넣고 평균 · 비율 · 분포에서 뺀다. 히트맵과 축은 `excl` · `incl` 두 벌을 낸다.
- 색은 SVG 속성에 적지 않고 CSS 클래스 (`s1` 에서 `s5` · `o1` 에서 `o6` · `dimseg` · `dimbar` · `pos` · `neg`) 로만 건다 (스펙 §3.2).
- 화면은 JSON 파일 `state/behavior_metrics.json` 하나만 읽는다. 렌더가 Iceberg 에 붙지 않는다.
- JSON 에 키가 없는 절은 「다음 적재 뒤에 채워진다」 한 줄로 그리고 렌더는 실패하지 않는다 (스펙 §4).
- 테스트 이름은 기존 파일의 관례대로 한국어 함수명이다 (`test_클릭_수_곁에_표본_수가_함께_나온다`).
- 파이썬 환경 · 워크트리 · 브랜치 규율은 메모리 `standing-session-rules` §1 에서 §3 그대로다. `uv run --project <워크트리> --extra dev pytest`.
- `docs/` 문서는 서식 훅 (`.claude/hooks/check-doc-format.py`) 을 통과해야 한다.
- 커밋 메시지는 `docs/conventions/2026-06-11-commit-pr-convention.md` 를 따른다. type 은 `feat` · `test` · `docs` · `refactor`, scope 는 `warehouse` · `serve` · `dashboard`.
- 테스트 기준선은 1,704 (2026-09-05 `uv run pytest -q --co`).

## 파일 구조

| 파일 | 책임 | 태스크 |
| --- | --- | --- |
| `src/bullet_in/serve/charts.py` (신설) | 순수 SVG 차트 함수 12종과 작은 헬퍼 | 1 |
| `tests/test_charts.py` (신설) | 차트의 구조 단언 | 1 |
| `src/bullet_in/warehouse.py` | gold 표 셋의 행 생성 · `build_gold` 확장 · 집계 다섯 · `build_metrics` · `show --from --to` | 2 · 3 |
| `tests/test_warehouse.py` | gold 행 · 집계 테스트 (기존 파일 끝에 덧붙인다) | 2 · 3 |
| `src/bullet_in/serve/behavior_view.py` (신설) | 집계 JSON 과 선수 · 기사 행을 절 단위 뷰모델로 | 4 |
| `src/bullet_in/serve/templates/_dash.html.j2` (신설) | 상단 · 스타일 · JS 뼈대 | 4 |
| `src/bullet_in/serve/templates/_dash_macros.html.j2` (신설) | 절 · 인사이트 매크로 | 4 |
| `src/bullet_in/serve/templates/behavior.html.j2` | 재작성 · `_dash.html.j2` 상속 | 4 |
| `src/bullet_in/serve/render.py` | `render_behavior` · `write_behavior` 가 뷰모델을 거치게 | 4 |
| `src/bullet_in/run.py` | `publish` 가 선수 · 기사 · 소스를 `write_behavior` 에 넘김 | 4 |
| `tests/test_behavior_view.py` | 재작성 | 4 |
| `docs/troubleshooting/2026-09-04-three-charts-that-pointed-at-the-wrong-layer.md` | §3 정정 | 5 |

---

### Task 0: 워크트리 준비와 기준선

**Files:**
- 없음 (환경만)

- [ ] **Step 1: 워크트리 확인**

워크트리 `.claude/worktrees/dashboard` (브랜치 `worktree-dashboard`) 는 스펙 PR 이 판 것이다.
없으면 저장소 루트에서 만든다.

```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in
git fetch origin
git worktree list | grep dashboard || git worktree add -b worktree-dashboard .claude/worktrees/dashboard origin/main
cp .env .claude/worktrees/dashboard/.env
```

- [ ] **Step 2: 파이썬 환경**

```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/dashboard
uv venv --python 3.11 --project .
uv sync --project . --extra dev
```

- [ ] **Step 3: 기준선 수집 수**

```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/dashboard
uv run --project . --extra dev pytest -q --co 2>/dev/null | tail -1
```

Expected: `1704 tests collected`. 다르면 셸이 워크트리 밖에 서 있는 것이다 (규율 §3).

---

### Task 1: 차트 모듈 `serve/charts.py`

**Files:**
- Create: `src/bullet_in/serve/charts.py`
- Test: `tests/test_charts.py`

**Interfaces:**
- Produces: 아래 함수 전부. 뒤 태스크 (4) 가 `from bullet_in.serve import charts as C` 로 쓴다.
  - `fmt(n) -> str` · `tip(lines) -> str` · `nice_ticks(mx, n=4) -> list[float]` · `svg(w, h, body) -> str`
  - `sparkline(vals, w=96, h=24) -> str`
  - `line_chart(labels, series, *, w=520, h=190, unit="", annotate=(), events=(), area=True, ref=None, fails=(), band=None) -> str`
  - `stacked_columns(labels, series, *, w=520, h=200, unit="", pct=False, step=None) -> str` (series 원소 = `(이름, 값 목록, css 클래스)`)
  - `legend(items) -> str` (items 원소 = `(이름, css 클래스)`)
  - `hbars(rows, *, value, label, w=440, unit="", note=None, dim_label=None, text_value=None, cls="s1", right=70) -> str`
  - `diverging(rows, *, w=520, unit="pp") -> str` (rows 원소 = `(라벨, 값, 부연)`)
  - `funnel(steps, *, w=520, sides=()) -> str` (steps · sides 원소 = `(라벨, 사용자 수)`)
  - `heatmap(rows, cols, cells, *, w=640, cell=None, unit="명", marks=(), rowlab=..., collab=..., show_text=False, scale_exclude_col=None) -> str`
  - `calendar(day_vals, start, end, *, w=640, unit="건") -> str`
  - `meter(v, mx, w=110, h=8) -> str` · `dumbbell_log(rows, *, w=560, unit="h") -> str`
  - `table(head, rows, cls="tbl") -> str` · `tile(label, value, sub="", spark="") -> str`

- [ ] **Step 1: 실패하는 테스트**

`tests/test_charts.py`:

```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --project . --extra dev pytest tests/test_charts.py -q`
Expected: `ModuleNotFoundError: No module named 'bullet_in.serve.charts'`

- [ ] **Step 3: 구현**

`src/bullet_in/serve/charts.py` 전문.
목업 생성기 (2026-09-04 · 세션 스크래치패드 `build_mockup2.py`) 의 함수를 이름 그대로 옮긴 것이다.

```python
"""대시보드 두 화면의 인라인 SVG 차트.

순수 함수다 — 파이썬 값을 받아 SVG 문자열을 돌려주고 파일 · DB · 시각을 안 본다.
색은 SVG 속성에 안 적고 CSS 클래스 (`s1` … `s5` · `o1` … `o6`) 로만 건다.
presentation attribute 에는 `var()` 가 안 통해 색이 통째로 죽기 때문이다
(2026-09-04 목업에서 밟았다 · 스펙 §3.2).

원본은 2026-09-04 목업 생성기이고 이름과 인자를 그대로 옮겼다.
"""
from __future__ import annotations

import html
import math
from datetime import date, timedelta

E = html.escape


def fmt(n) -> str:
    """정수는 천 단위 쉼표, 소수는 둘째 자리까지."""
    if isinstance(n, float) and not n.is_integer():
        return f"{n:,.2f}"
    return f"{int(round(n)):,}"


def tip(lines) -> str:
    """툴팁 본문. 줄바꿈을 그대로 두고 (JS 가 줄로 가른다) HTML 만 이스케이프한다."""
    return E("\n".join(lines))


def nice_ticks(mx, n=4) -> list:
    """0 부터 mx 를 덮는 1 · 2 · 5 단위 눈금."""
    if mx <= 0:
        return [0]
    raw = mx / n
    mag = 10 ** math.floor(math.log10(raw))
    st = raw / mag
    st = (1 if st <= 1 else 2 if st <= 2 else 5 if st <= 5 else 10) * mag
    top = math.ceil(mx / st) * st
    return [round(i * st, 6) for i in range(int(round(top / st)) + 1)]


def svg(w, h, body) -> str:
    return (f'<svg class="chart" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'role="img">{body}</svg>')


# ---------- 기본 도형 -------------------------------------------------------

def sparkline(vals, w=96, h=24) -> str:
    if not vals or max(vals) == 0:
        return ""
    mx = max(vals)
    n = len(vals)
    pts = [(2 + i * (w - 4) / max(n - 1, 1), h - 2 - v / mx * (h - 4))
           for i, v in enumerate(vals)]
    d = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = (f"M{pts[0][0]:.1f},{h - 2} L{d.replace(' ', ' L')} "
            f"L{pts[-1][0]:.1f},{h - 2} Z")
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'aria-hidden="true"><path class="area s1" d="{area}"/>'
            f'<polyline class="ln s1" points="{d}"/>'
            f'<circle class="dot s1" cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="3"/></svg>')


def axes_frame(L, T, pw, ph, ticks, Y, labels, X, step=None) -> str:
    out = []
    for t in ticks:
        out.append(f'<line class="grid" x1="{L}" x2="{L + pw}" y1="{Y(t):.1f}" y2="{Y(t):.1f}"/>'
                   f'<text class="tick" x="{L - 6}" y="{Y(t) + 3.5:.1f}" text-anchor="end">{fmt(t)}</text>')
    out.append(f'<line class="axis" x1="{L}" x2="{L + pw}" y1="{T + ph}" y2="{T + ph}"/>')
    n = len(labels)
    step = step or max(1, math.ceil(n / 8))
    for i, lab in enumerate(labels):
        if i % step == 0 or i == n - 1:
            out.append(f'<text class="tick" x="{X(i):.1f}" y="{T + ph + 16}" '
                       f'text-anchor="middle">{E(lab)}</text>')
    return "".join(out)


def line_chart(labels, series, *, w=520, h=190, unit="", annotate=(), events=(),
               area=True, ref=None, fails=(), band=None) -> str:
    """series 원소 = (이름, 값 목록). band = (하한 목록, 상한 목록). fails = (index, 라벨)."""
    L, R, T, B = 44, 14, 16, 30
    pw, ph = w - L - R, h - T - B
    n = len(labels)
    mx = max(max(v) for _, v in series)
    if band:
        mx = max(mx, max(band[1]))
    if ref is not None:
        mx = max(mx, ref)
    ticks = nice_ticks(mx)
    top = ticks[-1] or 1
    X = lambda i: L + i * pw / max(n - 1, 1)                     # noqa: E731
    Y = lambda v: T + ph - v / top * ph                          # noqa: E731
    out = [axes_frame(L, T, pw, ph, ticks, Y, labels, X)]
    if ref is not None:
        out.append(f'<line class="ref" x1="{L}" x2="{L + pw}" y1="{Y(ref):.1f}" y2="{Y(ref):.1f}"/>'
                   f'<text class="evlab" x="{L + pw}" y="{Y(ref) - 4:.1f}" text-anchor="end">기대 {fmt(ref)}</text>')
    for k, (i, lab) in enumerate(events):
        ey = T + ph - 6 - 12 * k if fails else T + 10 + 12 * k
        out.append(f'<line class="event" x1="{X(i):.1f}" x2="{X(i):.1f}" y1="{T}" y2="{T + ph}"/>'
                   f'<text class="evlab" x="{X(i) + 4:.1f}" y="{ey}">{E(lab)}</text>')
    if band:
        lo, hi = band
        up = " ".join(f"L{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(hi))
        dn = " ".join(f"L{X(i):.1f},{Y(v):.1f}" for i, v in reversed(list(enumerate(lo))))
        out.append(f'<path class="band s1" d="M{X(0):.1f},{Y(hi[0]):.1f} {up} {dn} Z"/>')
    for si, (name, vals) in enumerate(series):
        pts = [(X(i), Y(v)) for i, v in enumerate(vals)]
        d = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        cls = f"s{si + 1}"
        if area and len(series) == 1 and not band:
            out.append(f'<path class="area {cls}" d="M{pts[0][0]:.1f},{T + ph} '
                       f'L{d.replace(" ", " L")} L{pts[-1][0]:.1f},{T + ph} Z"/>')
        out.append(f'<polyline class="ln {cls}" points="{d}"/>')
        for i in annotate:
            x, y = pts[i]
            out.append(f'<circle class="dot {cls}" cx="{x:.1f}" cy="{y:.1f}" r="4"/>'
                       f'<text class="dlab" x="{x + (8 if i < n - 1 else -8):.1f}" '
                       f'y="{y - 8 if y > T + 16 else y + 16:.1f}" '
                       f'text-anchor="{"start" if i < n - 1 else "end"}">{fmt(vals[i])}{unit}</text>')
    for fi, flab in fails:
        out.append(f'<text class="fail" x="{X(fi):.1f}" y="{T + 9}" text-anchor="middle" '
                   f'data-tip="{tip([labels[fi], flab])}">✕</text>')
    slot = pw / max(n - 1, 1)
    for i, lab in enumerate(labels):
        x0 = L + max(0, X(i) - L - slot / 2)
        wd = slot if 0 < i < n - 1 else slot / 2
        lines = [lab] + [f"{fmt(v[i])}{unit} · {nm}" for nm, v in series]
        if band:
            lines.append(f"p10 {fmt(band[0][i])} · p90 {fmt(band[1][i])}")
        out.append(f'<line class="xh" x1="{X(i):.1f}" x2="{X(i):.1f}" y1="{T}" y2="{T + ph}"/>'
                   f'<rect class="hit" x="{x0:.1f}" y="{T}" width="{max(wd, 6):.1f}" height="{ph}" '
                   f'data-tip="{tip(lines)}" tabindex="0"/>')
    return svg(w, h, "".join(out))


def stacked_columns(labels, series, *, w=520, h=200, unit="", pct=False, step=None) -> str:
    """series 원소 = (이름, 값 목록, css 클래스). 조각 사이 2px · 막대 폭 24px 이하."""
    L, R, T, B = 44, 14, 12, 30
    pw, ph = w - L - R, h - T - B
    n = len(labels)
    tot = [sum(s[1][i] for s in series) for i in range(n)]
    mx = 100 if pct else max(tot)
    ticks = nice_ticks(mx)
    top = ticks[-1] or 1
    slot = pw / n
    bw = min(24, slot * 0.7)
    X = lambda i: L + slot * i + slot / 2                        # noqa: E731
    Y = lambda v: T + ph - v / top * ph                          # noqa: E731
    out = [axes_frame(L, T, pw, ph, ticks, Y, labels, X, step)]
    for i in range(n):
        acc = 0
        lines = [labels[i]]
        for name, vals, cls in series:
            v = vals[i]
            vv = (v / tot[i] * 100 if tot[i] else 0) if pct else v
            if vv > 0:
                y1, y0 = Y(acc + vv), Y(acc)
                out.append(f'<rect class="seg {cls}" x="{X(i) - bw / 2:.1f}" y="{y1:.1f}" '
                           f'width="{bw:.1f}" height="{max(y0 - y1 - 2, 0):.1f}" rx="2"/>')
            lines.append(f"{fmt(v)}{unit}{f' ({vv:.0f}%)' if pct else ''} · {name}")
            acc += vv
        out.append(f'<rect class="hit" x="{X(i) - slot / 2:.1f}" y="{T}" width="{slot:.1f}" '
                   f'height="{ph}" data-tip="{tip(lines)}" tabindex="0"/>')
    return svg(w, h, "".join(out))


def legend(items) -> str:
    return ('<p class="legend">'
            + "".join(f'<span class="key {cls}"></span>{E(name)}' for name, cls in items)
            + "</p>")


def hbars(rows, *, value, label, w=440, unit="", note=None, dim_label=None,
          text_value=None, cls="s1", right=70) -> str:
    """rows 는 dict 목록. value · label 은 그 키. 행에 `cls` 키가 있으면 그 색을 쓴다."""
    L, R, T = 150, right, 6
    bh, gap = 16, 8
    h = T + len(rows) * (bh + gap) + 4
    mx = max((r[value] or 0) for r in rows) or 1
    pw = w - L - R
    out = []
    for i, r in enumerate(rows):
        y = T + i * (bh + gap)
        v = r[value] or 0
        bw = max(v / mx * pw, 0)
        dim = dim_label is not None and r[label] == dim_label
        out.append(f'<text class="cat{" muted" if dim else ""}" x="{L - 8}" y="{y + bh - 4}" '
                   f'text-anchor="end">{E(str(r[label]))}</text>')
        if bw > 0:
            out.append(f'<path class="bar {r.get("cls", cls)}{" dim" if dim else ""}" '
                       f'd="M{L},{y} h{max(bw - 4, 0):.1f} a4,4 0 0 1 4,4 v{bh - 8} '
                       f'a4,4 0 0 1 -4,4 H{L} Z"/>')
        tv = text_value(r) if text_value else f"{fmt(v)}{unit}"
        out.append(f'<text class="val" x="{L + bw + 6:.1f}" y="{y + bh - 4}">{E(tv)}</text>')
        lines = [str(r[label]), f"{fmt(v)}{unit}"] + ([note(r)] if note else [])
        out.append(f'<rect class="hit" x="0" y="{y - gap / 2}" width="{w}" height="{bh + gap}" '
                   f'data-tip="{tip(lines)}" tabindex="0"/>')
    return svg(w, h, "".join(out))


def diverging(rows, *, w=520, unit="pp") -> str:
    """rows 원소 = (라벨, 값, 부연). 0 을 가운데 두고 + 는 오른쪽 파랑, − 는 왼쪽 빨강."""
    L, R, T = 120, 60, 6
    bh, gap = 16, 8
    h = T + len(rows) * (bh + gap) + 20
    mx = max(abs(v) for _, v, _ in rows) or 1
    pw = w - L - R
    cx = L + pw / 2
    sc = (pw / 2 - 48) / mx
    out = [f'<line class="axis" x1="{cx:.1f}" x2="{cx:.1f}" y1="{T}" y2="{T + len(rows) * (bh + gap)}"/>']
    for i, (lab, v, note) in enumerate(rows):
        y = T + i * (bh + gap)
        bw = abs(v) * sc
        out.append(f'<text class="cat" x="{L - 8}" y="{y + bh - 4}" text-anchor="end">{E(lab)}</text>')
        if v >= 0:
            out.append(f'<path class="bar pos" d="M{cx},{y} h{max(bw - 4, 0):.1f} a4,4 0 0 1 4,4 '
                       f'v{bh - 8} a4,4 0 0 1 -4,4 H{cx} Z"/>')
        else:
            out.append(f'<path class="bar neg" d="M{cx},{y} h-{max(bw - 4, 0):.1f} a4,4 0 0 0 -4,4 '
                       f'v{bh - 8} a4,4 0 0 0 4,4 H{cx} Z"/>')
        tx = cx + bw + 6 if v >= 0 else cx - bw - 6
        anc = "start" if v >= 0 else "end"
        if v < 0 and tx < L + 4:
            tx, anc = cx + 6, "start"
        out.append(f'<text class="val" x="{tx:.1f}" y="{y + bh - 4}" text-anchor="{anc}">{v:+.1f}{unit}</text>')
        out.append(f'<rect class="hit" x="0" y="{y - gap / 2}" width="{w}" height="{bh + gap}" '
                   f'data-tip="{tip([lab, f"{v:+.1f}{unit}", note])}" tabindex="0"/>')
    out.append(f'<text class="tick" x="{cx:.1f}" y="{h - 4}" text-anchor="middle">0 · 클릭 비중 − 기사 비중</text>')
    return svg(w, h, "".join(out))


def funnel(steps, *, w=520, sides=()) -> str:
    """steps · sides 원소 = (라벨, 사용자 수). 폭은 첫 단계 대비, 전환율은 앞 단계 대비."""
    T = 6
    bh, gap = (38, 12) if w > 700 else (34, 10)
    h = T + (len(steps) + len(sides)) * (bh + gap) + 4
    mx = steps[0][1] or 1
    pw = w - 260
    out = []
    for i, (lab, n) in enumerate(steps):
        y = T + i * (bh + gap)
        bw = max(n / mx * pw, 6)
        x = 160 + (pw - bw) / 2
        conv = f"{n / (steps[i - 1][1] or 1) * 100:.1f}% 전환" if i else "100%"
        wide = bw > 90
        out.append(f'<text class="cat" x="152" y="{y + bh / 2 + 4}" text-anchor="end">{E(lab)}</text>'
                   f'<rect class="seg s1" x="{x:.1f}" y="{y}" width="{bw:.1f}" height="{bh}" rx="4"/>'
                   f'<text class="{"seglab" if wide else "val"}" x="{x + bw / 2 if wide else x + bw + 6:.1f}" '
                   f'y="{y + bh / 2 + 4}" text-anchor="{"middle" if wide else "start"}">{fmt(n)}명</text>'
                   f'<text class="val" x="{160 + pw + 8}" y="{y + bh / 2 + 4}">{conv}</text>'
                   f'<rect class="hit" x="0" y="{y}" width="{w}" height="{bh + gap}" '
                   f'data-tip="{tip([lab, f"{fmt(n)}명", conv])}" tabindex="0"/>')
    for k, (lab, n) in enumerate(sides):
        y = T + (len(steps) + k) * (bh + gap)
        bw = max(n / mx * pw, 6)
        x = 160 + (pw - bw) / 2
        out.append(f'<text class="cat muted" x="152" y="{y + bh / 2 + 4}" text-anchor="end">{E(lab)}</text>'
                   f'<rect class="seg dimseg" x="{x:.1f}" y="{y}" width="{bw:.1f}" height="{bh}" rx="4"/>'
                   f'<text class="val" x="{x + bw + 6:.1f}" y="{y + bh / 2 + 4}">{fmt(n)}명 · 진입의 {n / mx * 100:.0f}%</text>'
                   f'<rect class="hit" x="0" y="{y}" width="{w}" height="{bh + gap}" '
                   f'data-tip="{tip([lab, f"{fmt(n)}명"])}" tabindex="0"/>')
    return svg(w, h, "".join(out))


def heatmap(rows, cols, cells, *, w=640, cell=None, unit="명", marks=(),
            rowlab=lambda r: r, collab=lambda c: c, show_text=False,
            scale_exclude_col=None) -> str:
    """cells = {(row, col): 값 | None}. None 은 「아직 없는 칸」 이라 따로 그린다."""
    L, T, R = 96, 22, 8
    cw = cell or (w - L - R) / len(cols)
    ch = 20 if not show_text else 24
    h = T + len(rows) * (ch + 2) + (30 if marks else 8)
    vals = [v for (r, c), v in cells.items() if v is not None and c != scale_exclude_col]
    mx = max(vals) if vals else 1
    out = []
    for j, c in enumerate(cols):
        if j % max(1, len(cols) // 12) == 0:
            out.append(f'<text class="tick" x="{L + j * cw + cw / 2:.1f}" y="{T - 8}" '
                       f'text-anchor="middle">{E(str(collab(c)))}</text>')
    for i, r in enumerate(rows):
        out.append(f'<text class="cat" x="{L - 8}" y="{T + i * (ch + 2) + ch - 6}" '
                   f'text-anchor="end">{E(str(rowlab(r)))}</text>')
        for j, c in enumerate(cols):
            v = cells.get((r, c))
            x = L + j * cw
            y = T + i * (ch + 2)
            if v is None:
                out.append(f'<rect class="cell none" x="{x:.1f}" y="{y}" width="{cw - 2:.1f}" height="{ch}" rx="2"/>')
                continue
            t = 0 if v == 0 else 0.12 + 0.88 * min(v / mx, 1) ** 0.6
            if c == scale_exclude_col:
                t = 1
            shown = v if isinstance(v, str) else fmt(v)
            out.append(f'<rect class="cell" x="{x:.1f}" y="{y}" width="{cw - 2:.1f}" height="{ch}" rx="2" '
                       f'style="fill-opacity:{t:.2f}" '
                       f'data-tip="{tip([f"{rowlab(r)} · {collab(c)}", f"{shown}{unit}"])}" tabindex="0"/>')
            if show_text:
                out.append(f'<text class="celltxt{" onink" if t > 0.55 else ""}" x="{x + (cw - 2) / 2:.1f}" '
                           f'y="{y + ch - 8}" text-anchor="middle">{E(str(shown))}{unit if unit == "%" else ""}</text>')
    for m in marks:
        x = L + m * cw + cw / 2
        y = T + len(rows) * (ch + 2) + 4
        out.append(f'<path class="mark" d="M{x - 4:.1f},{y + 8} L{x:.1f},{y} L{x + 4:.1f},{y + 8} Z"/>')
    if marks:
        out.append(f'<text class="tick" x="{L}" y="{T + len(rows) * (ch + 2) + 24}">▲ 회차 시각 (KST)</text>')
    return svg(w, h, "".join(out))


def calendar(day_vals, start, end, *, w=640, unit="건") -> str:
    """세로 = 월요일부터 일요일, 가로 = ISO 주. day_vals = {iso 날짜: 값}."""
    d0 = start - timedelta(start.isoweekday() - 1)
    weeks = []
    d = d0
    while d <= end:
        weeks.append(d)
        d += timedelta(7)
    L, T = 34, 22
    cw = min(20, (w - L - 8) / len(weeks))
    ch = cw
    h = T + 7 * (ch + 2) + 8
    mx = max(day_vals.values(), default=0) or 1
    out = []
    for j, wk in enumerate(weeks):
        if wk.day <= 7 or j == 0:
            out.append(f'<text class="tick" x="{L + j * (cw + 2):.1f}" y="{T - 8}">{wk.month}월</text>')
    for i, wd in enumerate(["월", "", "수", "", "금", "", "일"]):
        if wd:
            out.append(f'<text class="tick" x="{L - 6}" y="{T + i * (ch + 2) + ch - 5}" text-anchor="end">{wd}</text>')
    for j, wk in enumerate(weeks):
        for i in range(7):
            d = wk + timedelta(i)
            if d < start or d > end:
                continue
            v = day_vals.get(d.isoformat(), 0)
            t = 0 if v == 0 else 0.12 + 0.88 * (v / mx) ** 0.6
            out.append(f'<rect class="cell" x="{L + j * (cw + 2):.1f}" y="{T + i * (ch + 2)}" '
                       f'width="{cw:.1f}" height="{ch:.1f}" rx="3" style="fill-opacity:{t:.2f}" '
                       f'data-tip="{tip([d.isoformat(), f"{fmt(v)}{unit}"])}" tabindex="0"/>')
    return svg(w, h, "".join(out))


def meter(v, mx, w=110, h=8) -> str:
    t = min(v / mx, 1) if mx else 0
    cls = "bad" if t >= 1 else "warn" if t >= 0.75 else "ok"
    return (f'<svg class="meter" viewBox="0 0 {w} {h}" width="{w}" height="{h}" aria-hidden="true">'
            f'<rect class="track" x="0" y="0" width="{w}" height="{h}" rx="4"/>'
            f'<rect class="fill {cls}" x="0" y="0" width="{max(t * w, 3):.1f}" height="{h}" rx="4"/></svg>')


def dumbbell_log(rows, *, w=560, unit="h") -> str:
    """rows 원소 = (라벨, p50, p95, n). 단위는 시간, 축은 로그."""
    L, R, T = 150, 40, 22
    bh, gap = 14, 12
    h = T + len(rows) * (bh + gap) + 24
    lo, hi = 0.5, max(r[2] for r in rows) * 1.2
    pw = w - L - R
    X = lambda v: (L + (math.log10(max(v, lo)) - math.log10(lo))   # noqa: E731
                   / (math.log10(hi) - math.log10(lo)) * pw)
    out = []
    for tv, tl in ((1, "1시간"), (6, "6시간"), (24, "1일"), (168, "1주"), (720, "30일")):
        if lo <= tv <= hi:
            out.append(f'<line class="grid" x1="{X(tv):.1f}" x2="{X(tv):.1f}" y1="{T}" '
                       f'y2="{T + len(rows) * (bh + gap)}"/>'
                       f'<text class="tick" x="{X(tv):.1f}" y="{T - 8}" text-anchor="middle">{tl}</text>')
    for i, (lab, p50, p95, n) in enumerate(rows):
        y = T + i * (bh + gap) + bh / 2
        out.append(f'<text class="cat" x="{L - 8}" y="{y + 4}" text-anchor="end">{E(lab)}</text>'
                   f'<line class="dline" x1="{X(p50):.1f}" x2="{X(p95):.1f}" y1="{y}" y2="{y}"/>'
                   f'<circle class="dot s1" cx="{X(p50):.1f}" cy="{y}" r="5"/>'
                   f'<circle class="dot s1 hollow" cx="{X(p95):.1f}" cy="{y}" r="5"/>'
                   f'<text class="val" x="{X(p95) + 9:.1f}" y="{y + 4}">n={n}</text>'
                   f'<rect class="hit" x="0" y="{y - bh / 2 - gap / 2}" width="{w}" height="{bh + gap}" '
                   f'data-tip="{tip([lab, f"p50 {p50:.1f}{unit} · p95 {p95:.1f}{unit}", f"기사 {n}건"])}" tabindex="0"/>')
    out.append(f'<text class="tick" x="{L}" y="{h - 4}">● p50 · ○ p95 · 로그 축</text>')
    return svg(w, h, "".join(out))


def table(head, rows, cls="tbl") -> str:
    return (f'<details class="{cls}"><summary>표로 보기</summary><table><thead><tr>'
            + "".join(f"<th>{E(str(h))}</th>" for h in head)
            + "</tr></thead><tbody>"
            + "".join("<tr>" + "".join(f"<td>{E(str(c))}</td>" for c in r) + "</tr>" for r in rows)
            + "</tbody></table></details>")


def tile(label, value, sub="", spark="") -> str:
    return (f'<div class="tile"><div class="tl">{E(label)}</div><div class="tv">{value}</div>'
            f'<div class="ts">{sub}</div>{spark}</div>')
```

- [ ] **Step 4: 통과 확인**

Run: `uv run --project . --extra dev pytest tests/test_charts.py -q`
Expected: `16 passed`

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/serve/charts.py tests/test_charts.py
git commit -m "feat(serve): 대시보드 SVG 차트 함수 12종을 순수 함수 모듈로 (안건 2φ · PR 1)"
```

커밋 본문에는 「목업 생성기에서 옮겼고 색은 CSS 클래스로만 건다」 와 `Refs:` · co-author 트레일러를 넣는다 (컨벤션 §1).

---

### Task 2: gold 표 셋 — `fact_session` · `fact_user_daily` · `dim_user`

**Files:**
- Modify: `src/bullet_in/warehouse.py` (`FACT_COLUMNS` 정의 뒤 · `build_gold` 안)
- Test: `tests/test_warehouse.py` (파일 끝에 덧붙인다)

**Interfaces:**
- Consumes: `flatten_rows` 가 만든 silver 행 (dict · 키는 `FLAT_BASE_TYPES` · `NESTED_COLUMNS` · 계측 파라미터 이름 그대로). `KST` · `LAUNCH_DATE` · `_typed_schema` · `ensure_table` · `to_arrow` 는 이미 있다.
- Produces:
  - 상수 `SESSION_TABLE = "fact_session"` · `USER_DAILY_TABLE = "fact_user_daily"` · `DIM_USER_TABLE = "dim_user"` 와 각 `*_COLUMNS` 튜플.
  - `path_of(location: str | None) -> str` — 주소에서 경로만.
  - `session_rows(flat: list[dict]) -> list[dict]` · `user_daily_rows(flat) -> list[dict]` · `dim_user_rows(flat) -> list[dict]`.
  - `build_gold(catalog, now)` 가 표 다섯을 갈아 끼운다 (기존 둘 + 새 셋).

- [ ] **Step 1: 실패하는 테스트**

`tests/test_warehouse.py` 끝에 덧붙인다.
픽스처 `_event` · `_p` 는 같은 파일 위쪽 (253행 · 266행) 의 것이다.
컬럼 이름은 지어내지 않는다 — `session_engaged` · `ga_session_id` · `engagement_time_msec` · `n_tier` · `n_journalist` 는 계측 (`app.js`) 과 GA4 가 실제로 보내는 파라미터 이름이고 `device_category` · `traffic_source` 는 `NESTED_COLUMNS` 의 키다.

```python
# --- 행동 기록 · gold 표 셋 (세션 · 사용자 × 날짜 · 사용자) ----------------------

# 2026-09-01 12:00 KST (03:00 UTC) 부터 1시간 간격. event_timestamp 는 마이크로초.
_T0 = 1_788_231_600_000_000


def _ev(name, user="u1", sid="s1", hours=0, page=None, params=(), **extra):
    """gold 테스트용 평탄화 입력. 세션 · 참여 · 경로를 계측 이름 그대로 싣는다."""
    ps = [_p("ga_session_id", string_value=sid)] + list(params)
    if page:
        ps.append(_p("page_location", string_value=f"https://bullet-in.pages.dev{page}"))
    return _event(name=name, ts=_T0 + hours * 3_600_000_000, params=ps,
                  user_pseudo_id=user, **extra)


def _flat(*events):
    return warehouse.flatten_rows(list(events))


def test_세션은_사용자와_세션_id_쌍으로_하나다():
    rows = warehouse.session_rows(_flat(
        _ev("session_start"), _ev("page_view", page="/"), _ev("bi_card_click"),
        _ev("session_start", user="u2", sid="s1")))         # 다른 사용자의 같은 id
    assert len(rows) == 2
    s = next(r for r in rows if r["user_pseudo_id"] == "u1")
    assert s["ga_session_id"] == "s1"
    assert s["n_page_views"] == 1 and s["n_card_clicks"] == 1


def test_세션의_시작_시각은_가장_이른_이벤트이고_KST_로_요일과_시각을_적는다():
    rows = warehouse.session_rows(_flat(
        _ev("page_view", hours=2), _ev("session_start", hours=0)))
    s = rows[0]
    assert s["session_date_kst"] == "2026-09-01"
    assert s["start_hour_kst"] == 12 and s["weekday_kst"] == 2     # 화요일 정오


def test_세션의_참여_여부는_한_이벤트라도_참여면_참이다():
    rows = warehouse.session_rows(_flat(
        _ev("page_view"), _ev("user_engagement", params=[_p("session_engaged", string_value="1")])))
    assert rows[0]["engaged"] is True


def test_세션의_체류_시간은_밀리초_합이다():
    rows = warehouse.session_rows(_flat(
        _ev("user_engagement", params=[_p("engagement_time_msec", int_value=1500)]),
        _ev("scroll", params=[_p("engagement_time_msec", int_value=500)])))
    assert rows[0]["engagement_msec"] == 2000


def test_세션_행은_정한_컬럼만_가진다():
    rows = warehouse.session_rows(_flat(_ev("page_view")))
    assert set(rows[0]) == set(warehouse.SESSION_COLUMNS)


def test_사용자_날짜_행은_첫날을_신규로_표시한다():
    rows = warehouse.user_daily_rows(_flat(
        _ev("page_view", hours=0), _ev("page_view", hours=24)))
    by = {r["date_kst"]: r for r in rows}
    assert by["2026-09-01"]["is_new"] is True
    assert by["2026-09-02"]["is_new"] is False


def test_사용자_날짜_행은_기사와_선수_페이지뷰를_가른다():
    rows = warehouse.user_daily_rows(_flat(
        _ev("page_view", page="/article/abc"), _ev("page_view", page="/player/saka"),
        _ev("page_view", page="/players"), _ev("bi_entry")))
    r = rows[0]
    assert r["n_article_views"] == 1 and r["n_player_views"] == 1
    assert r["n_entries"] == 1


def test_신뢰도_필터는_등급이나_기자_조건이_있을_때만_센다():
    yes = warehouse.user_daily_rows(_flat(
        _ev("bi_filter_apply", params=[_p("n_tier", int_value=1)])))
    no = warehouse.user_daily_rows(_flat(
        _ev("bi_filter_apply", params=[_p("n_stage", int_value=2), _p("n_tier", int_value=0)])))
    assert yes[0]["used_trust_filter"] is True
    assert no[0]["used_trust_filter"] is False


def test_사용자_날짜_행의_기기는_그날_가장_많은_것이다():
    rows = warehouse.user_daily_rows(_flat(
        _ev("page_view", device={"category": "desktop"}),
        _ev("page_view", device={"category": "mobile"}),
        _ev("scroll", device={"category": "mobile"})))
    assert rows[0]["device_category"] == "mobile"


def test_사용자_행은_첫_방문의_기기와_유입을_적는다():
    rows = warehouse.dim_user_rows(_flat(
        _ev("page_view", hours=5, device={"category": "desktop"}),
        _ev("session_start", hours=0, device={"category": "mobile"},
            traffic_source={"source": "m.fmkorea.com", "medium": "referral", "name": "x"}),
        _ev("bi_card_click", hours=30)))
    u = rows[0]
    assert u["first_date_kst"] == "2026-09-01"
    assert u["first_device"] == "mobile" and u["first_source"] == "m.fmkorea.com"
    assert u["n_active_days"] == 2 and u["n_card_clicks"] == 1


def test_gold_표_셋도_평탄화본에서_다시_세운다(local_catalog, fake_ga4):
    fake_ga4["days"] = {"20260901": 2}
    now = _t(2026, 9, 2, 3)
    warehouse.load_ga4_events(local_catalog, now)
    warehouse.load_ga4_flat(local_catalog, now)
    warehouse.build_gold(local_catalog, now)
    for name in (warehouse.SESSION_TABLE, warehouse.USER_DAILY_TABLE, warehouse.DIM_USER_TABLE):
        t = local_catalog.load_table(f"{warehouse.BEHAVIOR_NS}.{name}")
        assert name in warehouse._existing_tables(local_catalog, warehouse.BEHAVIOR_NS)
        assert t.scan().to_arrow().num_rows >= 0


def test_경로만_남기고_호스트와_질의문자열은_버린다():
    assert warehouse.path_of("https://bullet-in.pages.dev/?stage=official") == "/"
    assert warehouse.path_of("https://x.test/player/saka?utm=1") == "/player/saka"
    assert warehouse.path_of(None) == ""
```

`fake_ga4` 는 `ga_session_id` 를 안 싣는다.
그래서 마지막 통합 테스트는 표가 만들어지는지 (행 수 0 이어도) 만 본다.
행의 내용은 위의 단위 테스트가 본다.

- [ ] **Step 2: 실패 확인**

Run: `uv run --project . --extra dev pytest tests/test_warehouse.py -q -k "세션 or 사용자 or 신뢰도 or gold_표 or 경로"`
Expected: `AttributeError: module 'bullet_in.warehouse' has no attribute 'session_rows'` 등

- [ ] **Step 3: 구현**

`warehouse.py` 의 `dim_date_rows` 바로 뒤에 넣는다.
`from urllib.parse import urlsplit` 은 파일 위 import 에 더한다.

```python
# --- 행동 기록 · gold 표 셋 (스펙 2026-09-05 §3.1) --------------------------------
#
# 사람을 세는 키는 `user_pseudo_id` 하나다. `bi_cid` 는 자동 수집 이벤트에 없어서
# 둘을 섞으면 한 사람이 두 사람으로 센다 (트러블슈팅 2026-09-04 두 키).

SESSION_TABLE = "fact_session"
USER_DAILY_TABLE = "fact_user_daily"
DIM_USER_TABLE = "dim_user"

SESSION_COLUMNS = ("user_pseudo_id", "ga_session_id", "session_date_kst", "started_at",
                   "start_hour_kst", "weekday_kst", "engaged", "device_category",
                   "traffic_source", "traffic_medium", "n_page_views", "n_card_clicks",
                   "n_filter_applies", "n_origin_exits", "engagement_msec")
_SESSION_TYPES = {"started_at": pa.timestamp("us", tz="UTC"),
                  "start_hour_kst": pa.int32(), "weekday_kst": pa.int32(),
                  "engaged": pa.bool_(), "n_page_views": pa.int32(),
                  "n_card_clicks": pa.int32(), "n_filter_applies": pa.int32(),
                  "n_origin_exits": pa.int32(), "engagement_msec": pa.int64()}

USER_DAILY_COLUMNS = ("user_pseudo_id", "date_kst", "is_new", "n_sessions", "n_entries",
                      "n_card_clicks", "n_article_views", "n_player_views",
                      "n_origin_exits", "used_trust_filter", "device_category")
_USER_DAILY_TYPES = {"is_new": pa.bool_(), "n_sessions": pa.int32(), "n_entries": pa.int32(),
                     "n_card_clicks": pa.int32(), "n_article_views": pa.int32(),
                     "n_player_views": pa.int32(), "n_origin_exits": pa.int32(),
                     "used_trust_filter": pa.bool_()}

DIM_USER_COLUMNS = ("user_pseudo_id", "first_date_kst", "first_device", "first_source",
                    "first_medium", "n_active_days", "n_card_clicks")
_DIM_USER_TYPES = {"n_active_days": pa.int32(), "n_card_clicks": pa.int32()}


def path_of(location: str | None) -> str:
    """주소에서 경로만. 호스트 · 질의문자열이 달라도 같은 경로면 같은 페이지다."""
    if not location:
        return ""
    return urlsplit(location).path or "/"


def _truthy(value) -> bool:
    return value in (1, "1", True, "true")


def _int(value) -> int:
    """파라미터는 문자열로 온다 (`_param_value`). 비었거나 숫자가 아니면 0."""
    if value in (None, ""):
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _event_at(row: dict) -> datetime | None:
    at = row.get("event_at")
    if at is None and row.get("event_timestamp"):
        at = datetime.fromtimestamp(int(row["event_timestamp"]) / 1_000_000,
                                    tz=timezone.utc)
    if at is not None and at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at


def session_rows(flat: list[dict]) -> list[dict]:
    """(사용자, GA4 세션 id) 마다 한 행. 시작 시각은 가장 이른 이벤트다.

    `ga_session_id` 만으로 묶지 않는다 — 사용자가 달라도 같은 값이 겹칠 수 있다 (런북 §3).
    """
    groups: dict[tuple, dict] = {}
    for r in flat:
        user, sid = r.get("user_pseudo_id"), r.get("ga_session_id")
        if not user or not sid:
            continue
        g = groups.setdefault((user, sid), {
            "user_pseudo_id": user, "ga_session_id": sid, "started_at": None,
            "engaged": False, "device_category": None, "traffic_source": None,
            "traffic_medium": None, "n_page_views": 0, "n_card_clicks": 0,
            "n_filter_applies": 0, "n_origin_exits": 0, "engagement_msec": 0})
        at = _event_at(r)
        if at is not None and (g["started_at"] is None or at < g["started_at"]):
            g["started_at"] = at
            g["device_category"] = r.get("device_category")
            g["traffic_source"] = r.get("traffic_source")
            g["traffic_medium"] = r.get("traffic_medium")
        if _truthy(r.get("session_engaged")):
            g["engaged"] = True
        name = r.get("event_name")
        if name == "page_view":
            g["n_page_views"] += 1
        elif name == "bi_card_click":
            g["n_card_clicks"] += 1
        elif name == "bi_filter_apply":
            g["n_filter_applies"] += 1
        elif name == "bi_origin_exit":
            g["n_origin_exits"] += 1
        g["engagement_msec"] += _int(r.get("engagement_time_msec"))
    out = []
    for g in groups.values():
        if g["started_at"] is None:
            continue
        k = g["started_at"].astimezone(KST)
        g["session_date_kst"] = k.date().isoformat()
        g["start_hour_kst"] = k.hour
        g["weekday_kst"] = k.isoweekday()
        out.append({c: g.get(c) for c in SESSION_COLUMNS})
    return sorted(out, key=lambda x: (x["started_at"], x["user_pseudo_id"]))


def _first_dates(flat: list[dict]) -> dict[str, str]:
    first: dict[str, str] = {}
    for r in flat:
        user, day = r.get("user_pseudo_id"), r.get("event_date_kst")
        if user and day and (user not in first or day < first[user]):
            first[user] = day
    return first


def user_daily_rows(flat: list[dict]) -> list[dict]:
    """(사용자, KST 날짜) 마다 한 행. 첫 방문일은 평탄화본 전량에서 정한다."""
    first = _first_dates(flat)
    groups: dict[tuple, dict] = {}
    for r in flat:
        user, day = r.get("user_pseudo_id"), r.get("event_date_kst")
        if not user or not day:
            continue
        g = groups.setdefault((user, day), {
            "sessions": set(), "n_entries": 0, "n_card_clicks": 0, "n_article_views": 0,
            "n_player_views": 0, "n_origin_exits": 0, "used_trust_filter": False,
            "devices": Counter()})
        if r.get("ga_session_id"):
            g["sessions"].add(r["ga_session_id"])
        name = r.get("event_name")
        if name == "bi_entry":
            g["n_entries"] += 1
        elif name == "bi_card_click":
            g["n_card_clicks"] += 1
        elif name == "bi_origin_exit":
            g["n_origin_exits"] += 1
        elif name == "page_view":
            path = path_of(r.get("page_location"))
            if path.startswith("/article/"):
                g["n_article_views"] += 1
            elif path.startswith("/player/"):
                g["n_player_views"] += 1
        elif name == "bi_filter_apply" and (_int(r.get("n_tier")) or _int(r.get("n_journalist"))):
            g["used_trust_filter"] = True
        if r.get("device_category"):
            g["devices"][r["device_category"]] += 1
    out = []
    for (user, day), g in sorted(groups.items()):
        out.append({"user_pseudo_id": user, "date_kst": day, "is_new": first[user] == day,
                    "n_sessions": len(g["sessions"]), "n_entries": g["n_entries"],
                    "n_card_clicks": g["n_card_clicks"],
                    "n_article_views": g["n_article_views"],
                    "n_player_views": g["n_player_views"],
                    "n_origin_exits": g["n_origin_exits"],
                    "used_trust_filter": g["used_trust_filter"],
                    "device_category": (g["devices"].most_common(1)[0][0]
                                        if g["devices"] else None)})
    return out


def dim_user_rows(flat: list[dict]) -> list[dict]:
    """사용자마다 한 행. 첫 방문의 기기 · 유입은 가장 이른 이벤트의 것이다."""
    users: dict[str, dict] = {}
    for r in flat:
        user, day = r.get("user_pseudo_id"), r.get("event_date_kst")
        if not user or not day:
            continue
        g = users.setdefault(user, {"first_date_kst": day, "first_at": None,
                                    "first_device": None, "first_source": None,
                                    "first_medium": None, "days": set(), "n_card_clicks": 0})
        g["days"].add(day)
        if day < g["first_date_kst"]:
            g["first_date_kst"] = day
        at = _event_at(r)
        if at is not None and (g["first_at"] is None or at < g["first_at"]):
            g["first_at"] = at
            g["first_device"] = r.get("device_category")
            g["first_source"] = r.get("traffic_source")
            g["first_medium"] = r.get("traffic_medium")
        if r.get("event_name") == "bi_card_click":
            g["n_card_clicks"] += 1
    return [{"user_pseudo_id": user, "first_date_kst": g["first_date_kst"],
             "first_device": g["first_device"], "first_source": g["first_source"],
             "first_medium": g["first_medium"], "n_active_days": len(g["days"]),
             "n_card_clicks": g["n_card_clicks"]}
            for user, g in sorted(users.items())]
```

`build_gold` 의 `for name, rows, names, types in (...)` 튜플에 셋을 더한다.

```python
    facts = fact_rows(flat)
    dims = dim_date_rows(r.get("event_date_kst") for r in flat)
    sessions = session_rows(flat)
    user_days = user_daily_rows(flat)
    users = dim_user_rows(flat)

    for name, rows, names, types in (
            (FACT_TABLE, facts, FACT_COLUMNS, _FACT_TYPES),
            (DIM_DATE_TABLE, dims, tuple(_DIM_DATE_TYPES), _DIM_DATE_TYPES),
            (SESSION_TABLE, sessions, SESSION_COLUMNS, _SESSION_TYPES),
            (USER_DAILY_TABLE, user_days, USER_DAILY_COLUMNS, _USER_DAILY_TYPES),
            (DIM_USER_TABLE, users, DIM_USER_COLUMNS, _DIM_USER_TYPES)):
```

독스트링의 「팩트와 날짜 디멘션」 을 「팩트 · 날짜 · 세션 · 사용자 × 날짜 · 사용자 표 다섯」 으로 고친다.

- [ ] **Step 4: 통과 확인**

Run: `uv run --project . --extra dev pytest tests/test_warehouse.py -q`
Expected: 기존 100 + 새 12 = `112 passed`

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/warehouse.py tests/test_warehouse.py
git commit -m "feat(warehouse): 행동 로그 gold 에 세션 · 사용자 × 날짜 · 사용자 표 셋 (안건 2φ · PR 1)"
```

---

### Task 3: 집계 다섯 · `build_metrics` · 기준값 재현 명령

**Files:**
- Modify: `src/bullet_in/warehouse.py` (`aggregate` 뒤 · `write_metrics` · `run_show` · `__main__`)
- Test: `tests/test_warehouse.py` (끝에 덧붙인다)

**Interfaces:**
- Consumes: 태스크 2 의 세 표 행 (dict 목록 · 컬럼 이름은 `*_COLUMNS`) · 기존 `fact_rows` 결과 (`FACT_COLUMNS`) · silver 의 `page_view` 행 (`user_pseudo_id` · `event_date_kst` · `page_location`).
- Produces (태스크 4 가 JSON 으로 읽는다):
  - `aggregate(facts, articles, *, exclude_launch=True)` — 기존 함수에 키워드 하나.
  - `agg_daily(user_daily, sessions, facts, *, start=None, end=None) -> dict` — 키 `days` (날짜별 dict: `date` · `dau` · `new` · `ret` · `sessions` · `engaged` · `clicks` · `dev` · `surf`) · `users` · `sessions` · `engaged` · `clickers` · `device` (`[{"k", "users"}]`) · `traffic` (`[{"source", "medium", "users"}]`).
  - `agg_funnel(user_daily, *, start=None, end=None) -> dict` — `steps` (넷 · `{"label", "users"}`) · `sides` (둘) · `article_page_users` · `all_users`.
  - `agg_heatmap(sessions, *, start=None, end=None, exclude_launch=True) -> list[dict]` — 168 칸 `{"wd", "h", "v"}`.
  - `agg_retention(users, user_daily, *, end=None, cohorts=14, horizon=7) -> list[dict]` — `{"first", "n", "ret": [7]}`.
  - `agg_pages(page_views, sessions, facts, *, start=None, end=None) -> dict` — `paths` · `engagement` · `engagement_p50` · `players` · `list` · `top_hashes`.
  - `build_metrics(catalog, now, *, start=None, end=None) -> dict` — JSON 전체 (`totals` · `dates` · `axes` · `axes_incl` · `window` · `daily` · `weekly` · `funnel` · `heat` · `retention` · `pages` · `generated_at`).
  - `baseline_lines(metrics) -> list[str]` — 런북 §9 표의 일곱 줄.
  - CLI `python -m bullet_in.warehouse show --from 2026-08-28 --to 2026-09-03`.

- [ ] **Step 1: 실패하는 테스트**

`tests/test_warehouse.py` 끝에 덧붙인다.

```python
# --- 행동 기록 · 집계 다섯 ---------------------------------------------------------

def _ud(user, day, **kw):
    row = {"user_pseudo_id": user, "date_kst": day, "is_new": False, "n_sessions": 1,
           "n_entries": 1, "n_card_clicks": 0, "n_article_views": 0, "n_player_views": 0,
           "n_origin_exits": 0, "used_trust_filter": False, "device_category": "mobile"}
    row.update(kw)
    return row


def _ss(user, day, hour=12, wd=2, **kw):
    row = {"user_pseudo_id": user, "ga_session_id": f"{user}-{day}-{hour}",
           "session_date_kst": day, "started_at": None, "start_hour_kst": hour,
           "weekday_kst": wd, "engaged": False, "device_category": "mobile",
           "traffic_source": "m.fmkorea.com", "traffic_medium": "referral",
           "n_page_views": 1, "n_card_clicks": 0, "n_filter_applies": 0,
           "n_origin_exits": 0, "engagement_msec": 5000}
    row.update(kw)
    return row


def _du(user, first, **kw):
    row = {"user_pseudo_id": user, "first_date_kst": first, "first_device": "mobile",
           "first_source": "m.fmkorea.com", "first_medium": "referral",
           "n_active_days": 1, "n_card_clicks": 0}
    row.update(kw)
    return row


def test_일별_집계는_신규와_재방문을_가르고_기기별_사용자를_센다():
    got = warehouse.agg_daily(
        [_ud("u1", "2026-08-30", is_new=True, n_card_clicks=2),
         _ud("u2", "2026-08-30", device_category="desktop"),
         _ud("u1", "2026-08-31")],
        [_ss("u1", "2026-08-30", engaged=True), _ss("u2", "2026-08-30"), _ss("u1", "2026-08-31")],
        [_fact(day="2026-08-30", card_surface="item"), _fact(day="2026-08-30", card_surface="pcard")])
    d0 = got["days"][0]
    assert d0 == {"date": "2026-08-30", "dau": 2, "new": 1, "ret": 1, "sessions": 2,
                  "engaged": 1, "clicks": 2, "dev": {"mobile": 1, "desktop": 1},
                  "surf": {"item": 1, "pcard": 1}}
    assert got["users"] == 2 and got["sessions"] == 3 and got["engaged"] == 1
    assert got["clickers"] == 1
    assert got["device"] == [{"k": "mobile", "users": 1}, {"k": "desktop", "users": 1}]
    assert got["traffic"][0] == {"source": "m.fmkorea.com", "medium": "referral", "users": 2}


def test_일별_집계는_창_밖의_날을_뺀다():
    got = warehouse.agg_daily([_ud("u1", "2026-08-01"), _ud("u1", "2026-08-30")], [], [],
                              start="2026-08-28", end="2026-09-03")
    assert [d["date"] for d in got["days"]] == ["2026-08-30"]


def test_퍼널은_앞_단계의_부분집합이고_재방문은_클릭한_사람만_센다():
    rows = [_ud("a", "2026-08-30", n_card_clicks=2), _ud("a", "2026-08-31"),
            _ud("b", "2026-08-30", n_card_clicks=1),
            _ud("c", "2026-08-30"), _ud("c", "2026-08-31"),        # 다시 왔지만 안 눌렀다
            _ud("d", "2026-08-30", n_entries=0, n_article_views=1)]  # 진입 없이 기사로 바로
    got = warehouse.agg_funnel(rows)
    assert [s["users"] for s in got["steps"]] == [3, 2, 1, 1]
    assert [s["label"] for s in got["steps"]][0] == "진입"
    assert got["article_page_users"] == 1 and got["all_users"] == 4


def test_퍼널의_곁가지는_신뢰도_필터와_원문_이동이다():
    rows = [_ud("a", "2026-08-30", used_trust_filter=True), _ud("b", "2026-08-30", n_origin_exits=2)]
    got = warehouse.agg_funnel(rows)
    assert [s["users"] for s in got["sides"]] == [1, 1]
    assert got["sides"][1]["label"] == "원문 매체로 이동"


def test_히트맵은_요일_시각마다_고유_사용자를_세고_공개일을_뺀다():
    sessions = [_ss("u1", "2026-08-30", hour=21, wd=7), _ss("u1", "2026-08-30", hour=21, wd=7),
                _ss("u2", "2026-08-30", hour=21, wd=7), _ss("u9", "2026-08-29", hour=0, wd=6)]
    cells = {(c["wd"], c["h"]): c["v"] for c in warehouse.agg_heatmap(sessions)}
    assert len(cells) == 168
    assert cells[(7, 21)] == 2 and cells[(6, 0)] == 0
    incl = {(c["wd"], c["h"]): c["v"] for c in warehouse.agg_heatmap(sessions, exclude_launch=False)}
    assert incl[(6, 0)] == 1


def test_리텐션은_코호트마다_n일_뒤에_온_수를_적고_아직_안_온_날은_None():
    users = [_du("a", "2026-08-30"), _du("b", "2026-08-30"), _du("c", "2026-08-31")]
    daily = [_ud("a", "2026-08-30"), _ud("b", "2026-08-30"), _ud("a", "2026-08-31"),
             _ud("c", "2026-08-31"), _ud("a", "2026-09-01")]
    got = warehouse.agg_retention(users, daily, end="2026-09-01")
    assert got[0] == {"first": "2026-08-30", "n": 2, "ret": [2, 1, 1, None, None, None, None]}
    assert got[1]["ret"][:2] == [1, 0]


def test_리텐션은_최근_코호트_수만큼만_남긴다():
    users = [_du(f"u{i}", f"2026-08-{10 + i:02d}") for i in range(20)]
    daily = [_ud(f"u{i}", f"2026-08-{10 + i:02d}") for i in range(20)]
    got = warehouse.agg_retention(users, daily, cohorts=14)
    assert len(got) == 14 and got[0]["first"] == "2026-08-16"


def test_페이지_집계는_경로를_이름으로_묶고_선수_슬러그를_센다():
    pv = [{"user_pseudo_id": "a", "event_date_kst": "2026-08-30", "page_location": "https://bullet-in.pages.dev/"},
          {"user_pseudo_id": "a", "event_date_kst": "2026-08-30", "page_location": "https://bullet-in.pages.dev/?stage=official"},
          {"user_pseudo_id": "b", "event_date_kst": "2026-08-30", "page_location": "https://bullet-in.pages.dev/article/abc"},
          {"user_pseudo_id": "b", "event_date_kst": "2026-08-30", "page_location": "https://bullet-in.pages.dev/player/alvarez"},
          {"user_pseudo_id": "c", "event_date_kst": "2026-08-30", "page_location": "https://bullet-in.pages.dev/player/alvarez.html"},
          {"user_pseudo_id": "c", "event_date_kst": "2026-08-30", "page_location": "https://bullet-in.pages.dev/players"}]
    got = warehouse.agg_pages(pv, [_ss("a", "2026-08-30", engagement_msec=12000)],
                              [_fact(day="2026-08-30", card_hash="h1"), _fact(day="2026-08-30", card_hash="h1")])
    paths = {p["label"]: p["n"] for p in got["paths"]}
    assert paths == {"홈": 2, "기사 상세": 1, "선수 페이지": 2, "선수 목록": 1}
    assert got["players"] == [{"slug": "alvarez", "pv": 2, "users": 2}]
    assert got["list"] == {"pv": 1, "users": 1}
    assert got["top_hashes"] == [{"hash": "h1", "clicks": 2}]
    assert got["engagement"][1] == {"bin": "10에서 30초", "n": 1} and got["engagement_p50"] == 12


def test_축_집계는_공개일_포함_한_벌도_낼_수_있다():
    facts = [_fact(day="2026-08-29"), _fact(day="2026-08-30")]
    assert warehouse.aggregate(facts, [])["totals"]["counted"] == 1
    assert warehouse.aggregate(facts, [], exclude_launch=False)["totals"]["counted"] == 2


def test_기준값_일곱_줄은_런북_9절의_순서다():
    metrics = {
        "daily": {"days": [{"date": "2026-08-29", "dau": 688, "new": 666}], "users": 890,
                  "sessions": 1502, "engaged": 918, "clickers": 221,
                  "device": [{"k": "mobile", "users": 585}],
                  "traffic": [{"source": "m.fmkorea.com", "medium": "referral", "users": 421},
                              {"source": "fmkorea.com", "medium": "referral", "users": 205}]},
        "funnel": {"steps": [{"label": "진입", "users": 863}, {"label": "카드 클릭", "users": 221},
                             {"label": "2건 이상 클릭", "users": 97}, {"label": "재방문 (2일 이상 방문)", "users": 71}],
                   "sides": [{"label": "신뢰도 · 기자 필터 사용", "users": 53}, {"label": "원문 매체로 이동", "users": 7}],
                   "article_page_users": 254, "all_users": 890},
        "pages": {"players": [{"slug": "alvarez", "pv": 108, "users": 50}], "list": {"pv": 71, "users": 32}}}
    metrics["weekly"] = metrics["daily"]
    lines = warehouse.baseline_lines(metrics)
    assert lines[0] == "사용자 7일 · 세션 · 참여 세션 비율 | 890 · 1,502 · 61%"
    assert lines[1] == "공개일 DAU · 신규 | 688 · 666"
    assert lines[2] == "퍼널 | 863 → 221 → 97 → 71"
    assert lines[3] == "신뢰도 · 기자 필터 사용자 · 원문 이동 | 53 · 7"
    assert lines[4] == "기사 상세를 본 사용자 | 254"
    assert lines[5] == "선수 페이지 뷰 · 목록 뷰 | 108 · 71"
    assert lines[6] == "모바일 비율 · fmkorea 참조 비율 | 66% · 70%"


def test_집계_파일에_새_키_전부가_실린다(local_catalog, fake_ga4, tmp_path, monkeypatch):
    import json as _json

    monkeypatch.setattr(warehouse, "METRICS_PATH", tmp_path / "m.json")
    fake_ga4["days"] = {"20260901": 2}
    now = _t(2026, 9, 2, 3)
    warehouse.load_ga4_events(local_catalog, now)
    warehouse.load_ga4_flat(local_catalog, now)
    warehouse.build_gold(local_catalog, now)
    got = warehouse.write_metrics(local_catalog, now)
    saved = _json.loads((tmp_path / "m.json").read_text(encoding="utf-8"))
    for key in ("totals", "axes", "axes_incl", "window", "daily", "weekly", "funnel", "heat",
                "retention", "pages", "generated_at"):
        assert key in saved, key
    assert set(saved["heat"]) == {"excl", "incl"}
    assert got["window"]["end"] is None or len(got["window"]["end"]) == 10
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --project . --extra dev pytest tests/test_warehouse.py -q -k "일별 or 퍼널 or 히트맵 or 리텐션 or 페이지_집계 or 축_집계 or 기준값 or 새_키"`
Expected: `AttributeError` (`agg_daily` 없음) 과 `TypeError` (`exclude_launch` 인자 없음)

- [ ] **Step 3: 구현**

먼저 `aggregate` 시그니처와 첫 줄.

```python
def aggregate(facts: list[dict], articles: list[dict], *, exclude_launch: bool = True) -> dict:
    """축별 클릭 수 · 기사 수 · 기사당 클릭.

    공개일 (2026-08-29) 을 뺀다 — 그 하루가 표본의 58% 라 평균을 왜곡한다.
    뺀 사실과 뺀 양을 `totals` 에 함께 실어 화면이 그대로 적을 수 있게 한다.
    화면의 「포함」 토글이 쓸 한 벌은 `exclude_launch=False` 로 낸다.
    """
    launch = LAUNCH_DATE.isoformat()
    counted = [f for f in facts if not exclude_launch or f.get("event_date_kst") != launch]
```

나머지는 그대로다.
그 아래에 집계 다섯을 넣는다.

```python
# --- 행동 기록 · 집계 다섯 (스펙 2026-09-05 §3.1) ---------------------------------
#
# 전부 dict 목록을 받는 순수 함수다. 창 (`start` · `end`) 은 KST 날짜 문자열이고
# 둘 다 닫힌 구간이다. 검증은 08-28 에서 09-03 을 넣어 런북 §9 를 재현한다.

EMPTY_DEVICE = "(없음)"
FUNNEL_LABELS = ("진입", "카드 클릭", "2건 이상 클릭", "재방문 (2일 이상 방문)")
FUNNEL_SIDES = ("신뢰도 · 기자 필터 사용", "원문 매체로 이동")
ENGAGEMENT_BINS = (("0에서 10초", 0, 10), ("10에서 30초", 10, 30), ("30초에서 1분", 30, 60),
                   ("1에서 3분", 60, 180), ("3분 넘게", 180, float("inf")))
_PAGE_LABELS = {"/": "홈", "/all": "전체 기사", "/players": "선수 목록", "/about": "소개"}
_PLAYER_PATH = re.compile(r"^/player/([^/]+?)(?:\.html)?$")


def _in_window(day: str | None, start: str | None, end: str | None) -> bool:
    return bool(day) and (start is None or day >= start) and (end is None or day <= end)


def agg_daily(user_daily: list[dict], sessions: list[dict], facts: list[dict], *,
              start: str | None = None, end: str | None = None) -> dict:
    """날짜별 DAU · 신규 · 재방문 · 세션 · 참여 세션 · 클릭 · 기기 · 화면과 창 전체의 총량."""
    days: dict[str, dict] = {}
    users, clickers = set(), set()
    by_device: dict[str, set] = {}
    by_traffic: dict[tuple, set] = {}

    def bucket(day):
        return days.setdefault(day, {"date": day, "dau": 0, "new": 0, "ret": 0, "sessions": 0,
                                     "engaged": 0, "clicks": 0, "dev": Counter(),
                                     "surf": Counter()})

    for r in user_daily:
        if not _in_window(r["date_kst"], start, end):
            continue
        b = bucket(r["date_kst"])
        b["dau"] += 1
        b["new" if r["is_new"] else "ret"] += 1
        b["clicks"] += r["n_card_clicks"]
        device = r.get("device_category") or EMPTY_DEVICE
        b["dev"][device] += 1
        users.add(r["user_pseudo_id"])
        by_device.setdefault(device, set()).add(r["user_pseudo_id"])
        if r["n_card_clicks"] > 0:
            clickers.add(r["user_pseudo_id"])
    n_sessions = n_engaged = 0
    for s in sessions:
        if not _in_window(s["session_date_kst"], start, end):
            continue
        b = bucket(s["session_date_kst"])
        b["sessions"] += 1
        n_sessions += 1
        if s["engaged"]:
            b["engaged"] += 1
            n_engaged += 1
        key = (s.get("traffic_source") or "(direct)", s.get("traffic_medium") or "(none)")
        by_traffic.setdefault(key, set()).add(s["user_pseudo_id"])
    for f in facts:
        day = f.get("event_date_kst")
        if _in_window(day, start, end) and day in days:
            days[day]["surf"][f.get("card_surface") or EMPTY_LABEL] += 1

    rows = []
    for day in sorted(days):
        b = days[day]
        rows.append({**b, "dev": dict(b["dev"]), "surf": dict(b["surf"])})
    return {"days": rows, "users": len(users), "sessions": n_sessions, "engaged": n_engaged,
            "clickers": len(clickers),
            "device": sorted([{"k": k, "users": len(v)} for k, v in by_device.items()],
                             key=lambda x: -x["users"]),
            "traffic": sorted([{"source": s, "medium": m, "users": len(v)}
                               for (s, m), v in by_traffic.items()],
                              key=lambda x: -x["users"])[:10]}


def agg_funnel(user_daily: list[dict], *, start: str | None = None,
               end: str | None = None) -> dict:
    """진입 → 카드 클릭 → 2건 이상 → 재방문. 곁가지는 신뢰도 필터 · 원문 이동 (런북 §4)."""
    per: dict[str, dict] = {}
    for r in user_daily:
        if not _in_window(r["date_kst"], start, end):
            continue
        p = per.setdefault(r["user_pseudo_id"], {"entries": 0, "clicks": 0, "days": set(),
                                                 "trust": False, "origin": 0, "article": 0})
        p["entries"] += r["n_entries"]
        p["clicks"] += r["n_card_clicks"]
        p["days"].add(r["date_kst"])
        p["trust"] = p["trust"] or bool(r["used_trust_filter"])
        p["origin"] += r["n_origin_exits"]
        p["article"] += r["n_article_views"]
    entry = {u for u, p in per.items() if p["entries"] > 0}
    click1 = {u for u, p in per.items() if p["clicks"] >= 1}
    click2 = {u for u, p in per.items() if p["clicks"] >= 2}
    returned = {u for u, p in per.items() if len(p["days"]) >= 2} & click1
    counts = (len(entry), len(click1), len(click2), len(returned))
    sides = (sum(1 for p in per.values() if p["trust"]),
             sum(1 for p in per.values() if p["origin"] > 0))
    return {"steps": [{"label": lab, "users": n} for lab, n in zip(FUNNEL_LABELS, counts)],
            "sides": [{"label": lab, "users": n} for lab, n in zip(FUNNEL_SIDES, sides)],
            "article_page_users": sum(1 for p in per.values() if p["article"] > 0),
            "all_users": len(per)}


def agg_heatmap(sessions: list[dict], *, start: str | None = None, end: str | None = None,
                exclude_launch: bool = True) -> list[dict]:
    """요일 (1 = 월) × 시각 (KST) 마다 세션을 시작한 고유 사용자 수. 168 칸 전부 낸다."""
    launch = LAUNCH_DATE.isoformat()
    cells: dict[tuple, set] = {}
    for s in sessions:
        day = s["session_date_kst"]
        if not _in_window(day, start, end) or (exclude_launch and day == launch):
            continue
        cells.setdefault((s["weekday_kst"], s["start_hour_kst"]), set()).add(s["user_pseudo_id"])
    return [{"wd": wd, "h": h, "v": len(cells.get((wd, h), ()))}
            for wd in range(1, 8) for h in range(24)]


def agg_retention(users: list[dict], user_daily: list[dict], *, end: str | None = None,
                  cohorts: int = 14, horizon: int = 7) -> list[dict]:
    """첫 방문일 코호트마다 k 일 뒤에 온 사람 수. 아직 안 온 날은 None 이다 (런북 §5)."""
    active: dict[str, set] = {}
    for r in user_daily:
        active.setdefault(r["user_pseudo_id"], set()).add(r["date_kst"])
    cohort: dict[str, set] = {}
    for u in users:
        cohort.setdefault(u["first_date_kst"], set()).add(u["user_pseudo_id"])
    last = end or max((d for ds in active.values() for d in ds), default=None)
    if last is None:
        return []
    out = []
    for first in sorted(d for d in cohort if d <= last)[-cohorts:]:
        base = cohort[first]
        f = date.fromisoformat(first)
        row = []
        for k in range(horizon):
            dk = (f + timedelta(k)).isoformat()
            row.append(None if dk > last
                       else sum(1 for u in base if dk in active.get(u, ())))
        out.append({"first": first, "n": len(base), "ret": row})
    return out


def _page_label(path: str) -> str:
    if path in _PAGE_LABELS:
        return _PAGE_LABELS[path]
    if path.startswith("/article/"):
        return "기사 상세"
    if path.startswith("/player/"):
        return "선수 페이지"
    return path or "(없음)"


def agg_pages(page_views: list[dict], sessions: list[dict], facts: list[dict], *,
              start: str | None = None, end: str | None = None) -> dict:
    """경로별 뷰 · 세션 체류 구간 · 선수 슬러그별 뷰 · 상위 기사 해시."""
    paths: Counter = Counter()
    slug_pv: Counter = Counter()
    slug_users: dict[str, set] = {}
    list_pv, list_users = 0, set()
    for r in page_views:
        if not _in_window(r.get("event_date_kst"), start, end):
            continue
        path = path_of(r.get("page_location"))
        paths[_page_label(path)] += 1
        m = _PLAYER_PATH.match(path)
        if m:
            slug_pv[m.group(1)] += 1
            slug_users.setdefault(m.group(1), set()).add(r["user_pseudo_id"])
        elif path in ("/players", "/players.html"):
            list_pv += 1
            list_users.add(r["user_pseudo_id"])
    secs = sorted((s["engagement_msec"] or 0) / 1000 for s in sessions
                  if _in_window(s["session_date_kst"], start, end))
    top = Counter(f["card_hash"] for f in facts
                  if _in_window(f.get("event_date_kst"), start, end) and f.get("card_hash"))
    return {"paths": [{"label": k, "n": n} for k, n in paths.most_common(8)],
            "engagement": [{"bin": lab, "n": sum(1 for v in secs if lo <= v < hi)}
                           for lab, lo, hi in ENGAGEMENT_BINS],
            "engagement_p50": round(secs[len(secs) // 2]) if secs else 0,
            "players": [{"slug": s, "pv": n, "users": len(slug_users[s])}
                        for s, n in slug_pv.most_common()],
            "list": {"pv": list_pv, "users": len(list_users)},
            "top_hashes": [{"hash": h, "clicks": n} for h, n in top.most_common(12)]}
```

그다음 `write_metrics` 를 `build_metrics` 와 둘로 가른다 (기존 `write_metrics` 본문을 대체한다).

```python
def _scan_rows(catalog, name: str, columns: tuple | None = None) -> list[dict] | None:
    """behavior 표 하나를 dict 목록으로. 없으면 None (빈 표와 구분한다)."""
    from pyiceberg.exceptions import NoSuchTableError

    try:
        table = catalog.load_table(f"{BEHAVIOR_NS}.{name}")
    except NoSuchTableError:
        return None
    scan = table.scan(selected_fields=columns) if columns else table.scan()
    return scan.to_arrow().to_pylist()


def build_metrics(catalog, now: datetime, *, start: str | None = None,
                  end: str | None = None) -> dict:
    """화면이 읽는 JSON 전체. 창을 안 주면 마지막 날짜까지 28일이다."""
    facts = _scan_rows(catalog, FACT_TABLE)
    if facts is None:
        return {}
    articles = _latest_articles(catalog)
    users = _scan_rows(catalog, DIM_USER_TABLE) or []
    user_daily = _scan_rows(catalog, USER_DAILY_TABLE) or []
    sessions = _scan_rows(catalog, SESSION_TABLE) or []
    flat = _scan_rows(catalog, GA4_FLAT_TABLE,
                      ("event_name", "user_pseudo_id", "event_date_kst", "page_location")) or []
    page_views = [r for r in flat if r.get("event_name") == "page_view"]

    last = end or max((r["date_kst"] for r in user_daily), default=None)
    first = start or ((date.fromisoformat(last) - timedelta(27)).isoformat() if last else None)

    metrics = aggregate(facts, articles)
    metrics["axes_incl"] = aggregate(facts, articles, exclude_launch=False)["axes"]
    metrics["window"] = {"start": first, "end": last}
    metrics["daily"] = agg_daily(user_daily, sessions, facts, start=first, end=last)
    week = (date.fromisoformat(last) - timedelta(6)).isoformat() if last else None
    metrics["weekly"] = agg_daily(user_daily, sessions, facts,
                                  start=max(week, first) if week and first else week, end=last)
    metrics["funnel"] = agg_funnel(user_daily, start=first, end=last)
    metrics["heat"] = {"excl": agg_heatmap(sessions, end=last),
                       "incl": agg_heatmap(sessions, end=last, exclude_launch=False)}
    metrics["retention"] = agg_retention(users, user_daily, end=last)
    metrics["pages"] = agg_pages(page_views, sessions, facts, start=first, end=last)
    metrics["generated_at"] = now.isoformat()
    return metrics


def write_metrics(catalog, now: datetime) -> dict:
    """집계 JSON 을 파일로 떨어뜨린다. 팩트가 없으면 빈 dict 이고 파일도 안 쓴다."""
    metrics = build_metrics(catalog, now)
    if not metrics:
        log.info("%s — 팩트가 아직 없다", METRICS_PATH)
        return {}
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(json.dumps(metrics, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    log.info("%s — 클릭 %d건 (공개일 %d건 제외) · 사용자 %d명 기준 집계",
             METRICS_PATH, metrics["totals"]["counted"], metrics["totals"]["launch_day"],
             metrics["daily"]["users"])
    return metrics


def baseline_lines(metrics: dict) -> list[str]:
    """런북 2026-09-04 §9 표와 같은 순서 · 같은 꼴의 일곱 줄.

    총량은 `weekly` (창의 마지막 7일) 에서, 공개일 한 줄은 `daily` 에서 읽는다.
    검증 창 08-28 에서 09-03 은 7일이라 둘이 같다.
    """
    d, f, p = metrics["weekly"], metrics["funnel"], metrics["pages"]
    launch = next((x for x in metrics["daily"]["days"]
                   if x["date"] == LAUNCH_DATE.isoformat()), None)
    users = d["users"] or 1
    engaged = round(d["engaged"] / d["sessions"] * 100) if d["sessions"] else 0
    mobile = next((x["users"] for x in d["device"] if x["k"] == "mobile"), 0)
    fmkorea = sum(x["users"] for x in d["traffic"] if "fmkorea" in (x["source"] or ""))
    return [
        f"사용자 7일 · 세션 · 참여 세션 비율 | {d['users']:,} · {d['sessions']:,} · {engaged}%",
        f"공개일 DAU · 신규 | {launch['dau'] if launch else '-'} · {launch['new'] if launch else '-'}",
        "퍼널 | " + " → ".join(str(s["users"]) for s in f["steps"]),
        f"신뢰도 · 기자 필터 사용자 · 원문 이동 | {f['sides'][0]['users']} · {f['sides'][1]['users']}",
        f"기사 상세를 본 사용자 | {f['article_page_users']}",
        f"선수 페이지 뷰 · 목록 뷰 | {sum(x['pv'] for x in p['players'])} · {p['list']['pv']}",
        f"모바일 비율 · fmkorea 참조 비율 | {round(mobile / users * 100)}% · {round(fmkorea / users * 100)}%",
    ]
```

마지막으로 CLI.
`run_show` 에 창 인자를 더하고 `__main__` 의 `show` 파서에 옵션 둘을 붙인다.

```python
def run_show(start: str | None = None, end: str | None = None) -> None:
    """쌓인 테이블의 행 수 · 파일 수 · 남은 스냅샷 수를 보여 준다.

    창을 주면 그 창의 기준값 일곱 줄 (런북 2026-09-04 §9) 을 대신 찍는다 —
    코드 PR 이 런북 값을 그대로 재현하는지 보는 자리다.
    """
    catalog = load_catalog()
    if start or end:
        metrics = build_metrics(catalog, datetime.now(timezone.utc), start=start, end=end)
        for line in baseline_lines(metrics):
            print(line)
        return
    for ns in (NAMESPACE, BEHAVIOR_NS):
        ...   # 기존 본문 그대로
```

```python
    show = sub.add_parser("show", help="쌓인 것 보기 · --from --to 를 주면 기준값 일곱 줄")
    show.add_argument("--from", dest="start", help="KST 날짜 · 닫힌 구간")
    show.add_argument("--to", dest="end", help="KST 날짜 · 닫힌 구간")
    ...
    else:
        run_show(args.start, args.end)
```

- [ ] **Step 4: 통과 확인**

Run: `uv run --project . --extra dev pytest tests/test_warehouse.py -q`
Expected: `123 passed` (112 + 11)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/warehouse.py tests/test_warehouse.py
git commit -m "feat(warehouse): 행동 지표 집계 다섯과 기준값 재현 명령 (안건 2φ · PR 1)"
```

---

### Task 4: 뷰모델 `serve/behavior_view.py` · 템플릿 둘 · 렌더 연결

이 태스크는 넷으로 쪼개 커밋한다 (4a 뷰모델 · 4b 템플릿 · 4c 렌더 · run.py 연결 · 4d 옛 테스트 정리).
넷이 끝나야 화면이 나오므로 리뷰는 한 번에 받는다.

**Files:**
- Create: `src/bullet_in/serve/behavior_view.py`
- Create: `src/bullet_in/serve/templates/_dash.html.j2`
- Create: `src/bullet_in/serve/templates/_dash_macros.html.j2`
- Modify: `src/bullet_in/serve/templates/behavior.html.j2` (전문 교체)
- Modify: `src/bullet_in/serve/render.py:2158-2199` (`BEHAVIOR_AXES` · `render_behavior` · `write_behavior`)
- Modify: `src/bullet_in/run.py:654-658` (`write_behavior` 호출)
- Test: `tests/test_behavior_view.py` (전문 교체)

**Interfaces:**
- Consumes: 태스크 1 의 `charts` 함수 전부 · 태스크 3 의 JSON 키 (`weekly` · `daily` · `funnel` · `heat` · `retention` · `pages` · `axes` · `axes_incl` · `window` · `generated_at`) · `render.py` 의 `SITE_URL` · `player_slug` · `_TRANSFER_GROUP_OF` · `to_kst` · `transfer_stage.SIDEBAR_STAGES` · `PlayerStore.page_players()` 의 행 (`id` · `surname` · `ko_name` · `transfer_status`) · 서빙 행 (`content_hash` · `title_ko` · `tier` · `transfer_stage` · `source_id`) · `sources` (`{source_id: {"display_name": ...}}`).
- Produces:
  - `build_behavior_view(metrics: dict, *, players=(), articles=(), sources=None) -> dict` — 키 `generated_at` · `window` · `overview` · `tiles` · `sections` · `missing_any`.
  - `sections` 원소는 절 dict 이거나 `{"pair": [절, 절]}` 이다. 절 dict 의 키 = `id` · `title` · `sub` · `question` (문장 목록) · `toggle` · `body` (Markup) · `body_incl` (Markup | None) · `insights` · `insights_incl` (각 `(문장, [부연])` 목록) · `missing`.
  - `render_behavior(metrics, *, players=(), articles=(), sources=None) -> str` · `write_behavior(metrics_path, out_dir, *, players=(), articles=(), sources=None) -> bool`.

#### 4a. 뷰모델

- [ ] **Step 1: 실패하는 테스트**

`tests/test_behavior_view.py` 를 아래로 통째로 바꾼다.
옛 테스트 열 개는 옛 템플릿 (표 넷) 을 재던 것이라 같이 사라진다.
픽스처 값은 2026-09-04 목업 데이터 (런북 §9) 에서 가져왔다.

```python
"""행동 지표 화면 — 절 열여덟 가운데 아홉이 목업 v2.8 의 id 로 그려지는지.

픽스처 값은 2026-09-04 19:24 KST 추출 (런북 §9) 에서 가져왔다. 지어낸 수가 아니다.
"""
import json

from markupsafe import Markup

from bullet_in.serve.behavior_view import build_behavior_view
from bullet_in.serve.render import render_behavior, write_behavior

DAYS = [
    {"date": "2026-08-28", "dau": 94, "new": 94, "ret": 0, "sessions": 94, "engaged": 52,
     "clicks": 43, "dev": {"mobile": 56, "desktop": 39}, "surf": {"item": 31, "mitem": 8, "pcard": 1, "relitem": 3}},
    {"date": "2026-08-29", "dau": 688, "new": 666, "ret": 22, "sessions": 878, "engaged": 538,
     "clicks": 306, "dev": {"mobile": 458, "desktop": 220, "tablet": 10}, "surf": {"item": 200, "mitem": 61, "pcard": 18}},
    {"date": "2026-08-30", "dau": 114, "new": 50, "ret": 64, "sessions": 181, "engaged": 101,
     "clicks": 65, "dev": {"mobile": 71, "desktop": 43}, "surf": {"item": 60, "pcard": 1}},
]
METRICS = {
    "generated_at": "2026-09-04T10:24:00+00:00",
    "totals": {"all": 621, "launch_day": 306, "counted": 315},
    "dates": {"from": "2026-08-24", "to": "2026-09-03"},
    "window": {"start": "2026-08-28", "end": "2026-08-30"},
    "axes": {"card_tier": [{"value": "0", "n_clicks": 30, "n_articles": 60, "per_article": 0.5},
                           {"value": "4", "n_clicks": 67, "n_articles": 448, "per_article": 0.15},
                           {"value": "(없음)", "n_clicks": 52, "n_articles": 0, "per_article": None}],
             "card_stage": [{"value": "rumour", "n_clicks": 40, "n_articles": 300, "per_article": 0.13},
                            {"value": "official", "n_clicks": 30, "n_articles": 50, "per_article": 0.6}],
             "card_outlet": [{"value": "The Athletic", "n_clicks": 31, "n_articles": 0, "per_article": None},
                             {"value": "(없음)", "n_clicks": 52, "n_articles": 0, "per_article": None}],
             "card_surface": [{"value": "item", "n_clicks": 207, "n_articles": 0, "per_article": None}]},
    "axes_incl": {"card_tier": [{"value": "0", "n_clicks": 50, "n_articles": 60, "per_article": 0.83},
                                {"value": "4", "n_clicks": 120, "n_articles": 448, "per_article": 0.27}],
                  "card_stage": [{"value": "rumour", "n_clicks": 90, "n_articles": 300, "per_article": 0.3}],
                  "card_outlet": [{"value": "(없음)", "n_clicks": 144, "n_articles": 0, "per_article": None}],
                  "card_surface": []},
    "weekly": {"days": DAYS, "users": 890, "sessions": 1502, "engaged": 918, "clickers": 221,
               "device": [{"k": "mobile", "users": 585}, {"k": "desktop", "users": 296}],
               "traffic": [{"source": "m.fmkorea.com", "medium": "referral", "users": 421},
                           {"source": "(direct)", "medium": "(none)", "users": 240}]},
    "daily": {"days": DAYS, "users": 890, "sessions": 1502, "engaged": 918, "clickers": 221,
              "device": [{"k": "mobile", "users": 585}, {"k": "desktop", "users": 296}],
              "traffic": [{"source": "m.fmkorea.com", "medium": "referral", "users": 421},
                          {"source": "(direct)", "medium": "(none)", "users": 240}]},
    "funnel": {"steps": [{"label": "진입", "users": 863}, {"label": "카드 클릭", "users": 221},
                         {"label": "2건 이상 클릭", "users": 97}, {"label": "재방문 (2일 이상 방문)", "users": 71}],
               "sides": [{"label": "신뢰도 · 기자 필터 사용", "users": 53}, {"label": "원문 매체로 이동", "users": 7}],
               "article_page_users": 254, "all_users": 890},
    "heat": {"excl": [{"wd": wd, "h": h, "v": (71 if (wd, h) == (5, 23) else 0)} for wd in range(1, 8) for h in range(24)],
             "incl": [{"wd": wd, "h": h, "v": (590 if (wd, h) == (6, 0) else 0)} for wd in range(1, 8) for h in range(24)]},
    "retention": [{"first": "2026-08-28", "n": 94, "ret": [94, 22, 9, 6, 6, 5, 2]},
                  {"first": "2026-08-29", "n": 666, "ret": [666, 55, 30, 25, 20, 18, None]}],
    "pages": {"paths": [{"label": "홈", "n": 2228}, {"label": "기사 상세", "n": 763}],
              "engagement": [{"bin": "0에서 10초", "n": 479}, {"bin": "10에서 30초", "n": 326}],
              "engagement_p50": 9,
              "players": [{"slug": "alvarez", "pv": 20, "users": 11}, {"slug": "jesus", "pv": 13, "users": 1}],
              "list": {"pv": 71, "users": 32},
              "top_hashes": [{"hash": "h1", "clicks": 40}, {"hash": "h404", "clicks": 3}]},
}
PLAYERS = [{"id": 1, "surname": "Alvarez", "ko_name": "알바레스", "transfer_status": "in_link"},
           {"id": 2, "surname": "Jesus", "ko_name": "제주스", "transfer_status": "out_link"}]
ARTICLES = [{"content_hash": "h1", "title_ko": "마르티넬리, 바이에른행 협상", "tier": 3.0,
             "transfer_stage": "negotiating", "source_id": "afcstuff"}]
SOURCES = {"afcstuff": {"display_name": "X (afcstuff)"}}


def _view(metrics=METRICS):
    return build_behavior_view(metrics, players=PLAYERS, articles=ARTICLES, sources=SOURCES)


def _html(metrics=METRICS):
    return render_behavior(metrics, players=PLAYERS, articles=ARTICLES, sources=SOURCES)


def test_절_아홉이_목업의_id_로_나온다():
    html = _html()
    for sec in ("sec-dau", "sec-engagement-funnel", "sec-activity-heatmap",
                "sec-engagement-by-dimension", "sec-retention", "sec-clicks-by-surface",
                "sec-pages-sessions", "sec-top-articles", "sec-player-pages"):
        assert f'id="{sec}"' in html, sec


def test_타일_여섯은_지난_7일_총량에서_만든다():
    tiles = _view()["tiles"]
    assert [t["label"] for t in tiles] == ["Users · 7일", "DAU · 최근", "Sessions / User",
                                            "Engaged Session Rate", "Click-through Rate",
                                            "Stickiness · DAU/WAU"]
    assert tiles[0]["value"] == "890" and tiles[1]["value"] == "114"
    assert tiles[2]["value"] == "1.69" and tiles[3]["value"] == "61%"
    assert tiles[4]["value"] == "25%"
    assert "하한선" in tiles[0]["sub"]


def test_퍼널의_끝은_재방문이고_곁가지는_흐리게():
    html = _html()
    assert "재방문 (2일 이상 방문)" in html and "73.2% 전환" in html
    assert 'class="seg dimseg"' in html


def test_공개일_토글이_있는_절은_두_벌을_다_내린다():
    secs = {s["id"]: s for s in _flat_sections(_view())}
    heat = secs["sec-activity-heatmap"]
    assert heat["toggle"] is True and heat["body_incl"] is not None
    assert "71명" in heat["body"] and "590명" in heat["body_incl"]
    dim = secs["sec-engagement-by-dimension"]
    assert dim["toggle"] is True and "+" in dim["body"]


def test_관심_지수는_클릭_비중에서_기사_비중을_뺀_값이다():
    # 등급 0 = 클릭 30/97 (31%) − 기사 60/508 (12%) = +19.1pp · 「(없음)」 은 뺀다
    secs = {s["id"]: s for s in _flat_sections(_view())}
    assert "+19.1pp" in secs["sec-engagement-by-dimension"]["body"]


def test_리텐션은_비율_숫자를_적은_히트맵이고_아직_안_온_칸은_비운다():
    secs = {s["id"]: s for s in _flat_sections(_view())}
    body = secs["sec-retention"]["body"]
    assert ">23%<" in body                      # 22 / 94
    assert 'class="cell none"' in body           # 공개일 코호트의 D+6
    assert "08/29 · 666명" in body


def test_리텐션과_화면별_클릭은_나란히_놓인다():
    view = _view()
    pair = next(s for s in view["sections"] if "pair" in s)
    assert [s["id"] for s in pair["pair"]] == ["sec-retention", "sec-clicks-by-surface"]


def test_상위_기사는_실제_기사_링크이고_마트에_없는_해시는_뺀다():
    html = _html()
    assert 'href="https://bullet-in.pages.dev/article/h1"' in html
    assert "마르티넬리" in html and "X (afcstuff)" in html and "협상 중" in html
    assert "h404" not in html


def test_선수_페이지는_슬러그를_명단에_붙여_이적_상태를_적는다():
    html = _html()
    assert "알바레스 · 영입 진행 중" in html and "제주스 · 방출 진행 중" in html
    assert "20뷰 · 11명" in html
    assert "선수 목록 페이지는 71뷰 32명" in html


def test_집계에_없는_절은_다음_적재_뒤라고_적고_실패하지_않는다():
    old = {k: METRICS[k] for k in ("generated_at", "totals", "dates", "axes")}
    html = render_behavior(old)
    assert html.count("다음 적재 뒤에 채워진다") >= 8
    assert 'id="sec-engagement-by-dimension"' in html         # axes 만으로 그릴 수 있는 절
    assert "The Athletic" in html


def test_인사이트의_숫자는_값에서_온다():
    secs = {s["id"]: s for s in _flat_sections(_view())}
    dau = secs["sec-dau"]["insights"]
    assert any("688명 가운데 666명" in main for main, _ in dau)
    assert any("모바일이 66%" in main for main, _ in dau)


def test_설명문은_문장마다_줄을_가른다():
    html = _html()
    assert html.count('<span class="l">') >= 18


def test_검색엔진에_안_실리게_막고_수집_현황으로_가는_링크가_있다():
    html = _html()
    assert 'name="robots" content="noindex,nofollow"' in html
    assert 'href="ops.html"' in html


def test_집계_시각을_한국_시간으로_보여_준다():
    html = _html()
    assert "2026-09-04 19:24 KST" in html


def test_집계_파일이_없으면_페이지를_안_그린다(tmp_path):
    assert write_behavior(tmp_path / "없다.json", tmp_path) is False


def test_집계_파일이_있으면_페이지를_그린다(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps(METRICS, ensure_ascii=False), encoding="utf-8")
    assert write_behavior(p, tmp_path, players=PLAYERS, articles=ARTICLES, sources=SOURCES) is True
    out = (tmp_path / "behavior.html").read_text(encoding="utf-8")
    assert 'id="sec-dau"' in out and isinstance(Markup(""), str)


def _flat_sections(view):
    for s in view["sections"]:
        if "pair" in s:
            yield from s["pair"]
        else:
            yield s
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --project . --extra dev pytest tests/test_behavior_view.py -q`
Expected: `ModuleNotFoundError: No module named 'bullet_in.serve.behavior_view'`

- [ ] **Step 3: 뷰모델 구현**

`src/bullet_in/serve/behavior_view.py` 전문.

```python
"""행동 지표 화면의 뷰모델 — 집계 JSON 을 절 단위의 값 · SVG 로 바꾼다.

화면 (`behavior.html.j2`) 은 이 모듈이 돌려주는 dict 만 본다.
집계 JSON 에 아직 없는 키 (머지 직후 첫 회차 · 스펙 §4) 는 그 절만 「다음 적재 뒤」 로
그리고 나머지 절은 정상으로 그린다. 절 순서와 `id` 는 목업 v2.8 그대로다.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from markupsafe import Markup

from bullet_in.serve import charts as C
from bullet_in.serve.render import SITE_URL, _TRANSFER_GROUP_OF, player_slug, to_kst
from bullet_in.transfer_stage import SIDEBAR_STAGES

STAGE_KO = {key: ko for key, ko, _ in SIDEBAR_STAGES}
STAGE_ORDER = ("rumour", "interest", "negotiating", "agreed", "personal_terms", "medical",
               "official", "done", "collapsed")
TIER_ORDER = ("0", "1", "1.5", "2", "3", "4")
TIER_KO = {"0": "0 구단 공식", "1": "1 최상", "1.5": "1.5", "2": "2", "3": "3", "4": "4 타블로이드"}
DEVICE_KO = {"mobile": "모바일", "desktop": "데스크톱", "tablet": "태블릿"}
SURFACE_KO = {"item": "기사 목록", "mitem": "주요 소식", "pcard": "선수 카드"}
WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")
CYCLE_HOURS = (0, 3, 6, 9, 12, 15, 18, 21)
EMPTY = "(없음)"
NO_OUTLET = "표시 없음 (선수 카드 · 주요 소식)"
STATUS_CLS = {"영입 진행 중": "s1", "방출 진행 중": "s2", "이적 확정": "s3",
              "타 클럽행": "s4", "이적 무산": "s5"}
GROUP_ORDER = ("영입 진행 중", "이적 확정", "이적 무산", "타 클럽행", "방출 진행 중")
MISSING_NOTE = "다음 적재 뒤에 채워진다."


def _md(iso: str) -> str:
    """2026-08-29 → 08/29"""
    return iso[5:].replace("-", "/")


def _pct(n, d) -> int:
    return round(n / d * 100) if d else 0


def _sents(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def _section(id_, title, sub, question, body, insights=(), *, toggle=False,
             body_incl=None, insights_incl=()):
    return {"id": id_, "title": title, "sub": sub, "question": _sents(question),
            "toggle": toggle, "body": Markup(body),
            "body_incl": Markup(body_incl) if body_incl is not None else None,
            "insights": list(insights), "insights_incl": list(insights_incl),
            "missing": False}


def _missing(id_, title, sub, question=""):
    return {"id": id_, "title": title, "sub": sub, "question": _sents(question),
            "toggle": False, "body": None, "body_incl": None, "insights": [],
            "insights_incl": [], "missing": True}


def _fig(cap, body):
    return f'<figure><figcaption>{C.E(cap)}</figcaption>{body}</figure>'


def _two(*figs):
    return '<div class="two">' + "".join(figs) + "</div>"


# --- 타일 ---------------------------------------------------------------------

def _tiles(weekly: dict | None) -> list[dict]:
    if not weekly or not weekly.get("days"):
        return []
    days = weekly["days"][-7:]
    dau = [d["dau"] for d in days]
    users = weekly["users"] or 1
    sessions = weekly["sessions"] or 1
    span = f"{_md(days[0]['date'])} 에서 {_md(days[-1]['date'])}"
    avg = sum(dau) / len(dau)
    return [
        {"label": "Users · 7일", "value": C.fmt(weekly["users"]),
         "sub": f"{span} · 광고 차단 방문 제외 · 하한선", "spark": Markup(C.sparkline(dau))},
        {"label": "DAU · 최근", "value": C.fmt(dau[-1]),
         "sub": f"{_md(days[-1]['date'])} · 지난 7일 평균 {avg:.0f}", "spark": Markup(C.sparkline(dau))},
        {"label": "Sessions / User", "value": f"{weekly['sessions'] / users:.2f}",
         "sub": f"세션 {C.fmt(weekly['sessions'])} · 사용자 {C.fmt(weekly['users'])}", "spark": ""},
        {"label": "Engaged Session Rate", "value": f"{_pct(weekly['engaged'], sessions)}%",
         "sub": "GA4 참여 세션 (10초 · 2페이지 · 전환)",
         "spark": Markup(C.sparkline([_pct(d["engaged"], d["sessions"]) for d in days]))},
        {"label": "Click-through Rate", "value": f"{_pct(weekly['clickers'], users)}%",
         "sub": f"카드를 누른 사용자 {C.fmt(weekly['clickers'])} / {C.fmt(weekly['users'])}", "spark": ""},
        {"label": "Stickiness · DAU/WAU", "value": f"{_pct(avg, users)}%",
         "sub": "일 평균 DAU ÷ 7일 사용자", "spark": ""},
    ]


# --- 절 -----------------------------------------------------------------------

def _dau(daily: dict | None):
    title, sub = "DAU", "Daily Active Users"
    q = ("하루에 몇 명이 왔는지를 신규와 재방문으로 나누어 본다. "
         "어떤 기기로 들어왔는지 (모바일 · 데스크톱 · 태블릿) 도 같은 축으로 본다.")
    if not daily or not daily.get("days"):
        return _missing("sec-dau", title, sub, q)
    days = daily["days"]
    labels = [_md(d["date"]) for d in days]
    users_chart = C.stacked_columns(labels, [("신규", [d["new"] for d in days], "s1"),
                                             ("재방문", [d["ret"] for d in days], "s2")], unit="명")
    dev_chart = C.stacked_columns(labels, [(DEVICE_KO[k], [d["dev"].get(k, 0) for d in days], cls)
                                           for k, cls in (("mobile", "s1"), ("desktop", "s2"),
                                                          ("tablet", "s3"))], unit="명")
    body = (_two(_fig("신규 · 재방문 (명)", users_chart + C.legend([("신규 사용자", "s1"), ("재방문 사용자", "s2")])),
                 _fig("기기별 DAU (명)", dev_chart + C.legend([("모바일", "s1"), ("데스크톱", "s2"), ("태블릿", "s3")])))
            + C.table(["날짜", "DAU", "신규", "재방문", "세션", "참여 세션", "카드 클릭"],
                      [(d["date"], d["dau"], d["new"], d["ret"], d["sessions"], d["engaged"], d["clicks"])
                       for d in days]))
    ins = []
    launch = next((d for d in days if d["date"] == "2026-08-29"), None)
    if launch:
        ins.append((f"공개 첫날 {C.fmt(launch['dau'])}명 가운데 {C.fmt(launch['new'])}명이 처음 온 사람이다.", []))
    last = days[-1]
    ins.append((f"{_md(last['date'])} 은 {C.fmt(last['dau'])}명이고 그 가운데 재방문이 {C.fmt(last['ret'])}명이다.", []))
    mobile = next((x["users"] for x in daily["device"] if x["k"] == "mobile"), 0)
    ins.append((f"모바일이 {_pct(mobile, daily['users'])}% 라 모바일 화면이 곧 기본 화면이다.", []))
    return _section("sec-dau", title, sub, q, body, ins)


def _funnel(funnel: dict | None):
    title, sub = "Engagement Funnel", "진입 → 카드 클릭 → 반복 클릭 → 재방문"
    q = ("들어온 사용자가 카드를 누르고 여러 건을 읽고 다시 와서 읽는 습관을 들이기까지를 단계로 나누어 본다. "
         "수는 사용자 수로 세고 신뢰도 필터를 쓴 것과 원문으로 나간 것은 단계가 아니라 곁가지로 둔다.")
    if not funnel:
        return _missing("sec-engagement-funnel", title, sub, q)
    steps = [(s["label"], s["users"]) for s in funnel["steps"]]
    sides = [(s["label"], s["users"]) for s in funnel["sides"]]
    body = C.funnel(steps, sides=sides, w=980)
    n = [s["users"] for s in funnel["steps"]]
    ins = [("마지막 단계를 「다시 와서 읽는 사용자」 로 두었다.", ["이 서비스의 목표가 매일 들르는 습관이기 때문이다."]),
           (f"진입한 {C.fmt(n[0])}명 가운데 {C.fmt(n[1])}명이 카드를 눌렀고 {C.fmt(n[2])}명이 두 건 이상 눌렀으며 "
            f"카드를 누른 사람 가운데 {C.fmt(n[3])}명이 이틀 이상 왔다.", []),
           (f"신뢰도 · 기자 필터를 쓴 {C.fmt(sides[0][1])}명은 이 서비스의 차별점을 실제로 써 본 사람이다.", []),
           (f"원문으로 나간 사람은 {C.fmt(sides[1][1])}명이다.", ["요약과 번역이 원문을 대신한다는 뜻이다."])]
    ap = funnel.get("article_page_users", 0)
    if ap > n[1]:
        ins.append((f"기사 상세 페이지를 본 사용자는 {C.fmt(ap)}명으로 카드를 누른 {C.fmt(n[1])}명보다 많다.",
                    ["커뮤니티 글에 걸린 링크가 홈이 아니라 기사 페이지 주소여서 홈을 거치지 않고 기사로 바로 들어온 방문이 있기 때문이다."]))
    return _section("sec-engagement-funnel", title, sub, q, body, ins)


def _heat_cells(cells):
    return {(c["wd"], c["h"]): c["v"] for c in cells}


def _heatmap(heat: dict | None):
    title, sub = "Activity Heatmap", "요일 × 시간대 · KST"
    q = "요일과 시간대별로 사용자가 언제 읽는지 본다. 회차 시각 ▲ 과 읽는 시각이 맞물리는지 함께 확인한다."
    if not heat or not heat.get("excl"):
        return _missing("sec-activity-heatmap", title, sub, q)

    def draw(cells):
        return C.heatmap(list(range(1, 8)), list(range(24)), _heat_cells(cells), w=980,
                         marks=list(CYCLE_HOURS), rowlab=lambda r: WEEKDAYS[r - 1],
                         collab=lambda c: f"{c:02d}시")

    def peak(cells):
        top = max(cells, key=lambda c: c["v"])
        return WEEKDAYS[top["wd"] - 1], top["h"], top["v"]

    wd, h, v = peak(heat["excl"])
    ins = [("공개일 (08-29) 을 뺀 값이다.", ["그 하루를 넣으면 그 한 칸이 눈금을 다 차지한다."]),
           (f"가장 몰린 칸은 {wd} {h:02d}시 {C.fmt(v)}명이다.", [])]
    wd2, h2, v2 = peak(heat["incl"])
    ins2 = [(f"공개일을 넣으면 {wd2} {h2:02d}시 한 칸 ({C.fmt(v2)}명) 이 눈금을 다 차지한다.",
             ["그래서 이 화면은 기본값을 제외로 둔다."])]
    return _section("sec-activity-heatmap", title, sub, q, draw(heat["excl"]), ins, toggle=True,
                    body_incl=draw(heat["incl"]), insights_incl=ins2)


def _index_rows(axis_rows, order, ko):
    """over / under index — 클릭 비중 − 기사 비중 (pp). 「(없음)」 과 기사 0 인 값은 뺀다."""
    rows = [r for r in axis_rows if r["value"] != EMPTY and r.get("n_articles")]
    tc = sum(r["n_clicks"] for r in rows) or 1
    ta = sum(r["n_articles"] for r in rows) or 1
    by = {r["value"]: r for r in rows}
    out = []
    for v in order:
        r = by.get(v)
        if not r:
            continue
        pc, pa_ = r["n_clicks"] / tc * 100, r["n_articles"] / ta * 100
        out.append((ko.get(v, v), pc - pa_, f"클릭 {r['n_clicks']} ({pc:.0f}%) · 기사 {r['n_articles']} ({pa_:.0f}%)"))
    return out


def _outlet_rows(axis_rows):
    return [{"lab": NO_OUTLET if r["value"] == EMPTY else r["value"], "n": r["n_clicks"]}
            for r in axis_rows][:12]


def _traffic_rows(daily):
    def lab(r):
        s = r["source"] or "(direct)"
        if s == "m.fmkorea.com":
            return "fmkorea (모바일)"
        if s == "fmkorea.com":
            return "fmkorea (PC)"
        if s == "(direct)":
            return "직접 유입"
        return f"{s} · {r['medium']}"
    return [{"lab": lab(r), "n": r["users"]} for r in (daily or {}).get("traffic", [])[:7]]


def _dimension(axes: dict | None, axes_incl: dict | None, daily: dict | None, totals: dict | None):
    title, sub = "Engagement by Dimension", "over / under index"
    q = ("관심이 어느 등급과 어느 단계에 쏠리는지 본다. "
         "클릭 비중에서 기사 비중을 뺀 값이라 0 보다 크면 기사 수에 비해 더 눌린 것이다.")
    if not axes:
        return _missing("sec-engagement-by-dimension", title, sub, q)
    counted = (totals or {}).get("counted", 0)
    all_ = (totals or {}).get("all", 0)
    traffic = _traffic_rows(daily)

    def draw(ax, label, n):
        tier = _index_rows(ax.get("card_tier", []), TIER_ORDER, TIER_KO)
        stage = _index_rows(ax.get("card_stage", []), STAGE_ORDER, STAGE_KO)
        figs = [_fig(f"기자 등급 (0 에서 4) · {label} {C.fmt(n)}건", C.diverging(tier) if tier else "<p class=\"q\">아직 없다.</p>"),
                _fig(f"이적 단계 (루머 → 완료) · {label}", C.diverging(stage) if stage else "<p class=\"q\">아직 없다.</p>"),
                _fig(f"매체 · 클릭 수 · {label}", C.hbars(_outlet_rows(ax.get("card_outlet", [])), value="n", label="lab", dim_label=NO_OUTLET)
                     if ax.get("card_outlet") else "<p class=\"q\">아직 없다.</p>")]
        if traffic:
            figs.append(_fig("유입 경로 · 사용자 수", C.hbars(traffic, value="n", label="lab", unit="명")))
        return _two(*figs), tier

    body, tier = draw(axes, "공개일 제외", counted)
    ins = []
    if tier:
        hi, lo = max(tier, key=lambda t: t[1]), min(tier, key=lambda t: t[1])
        ins.append((f"등급 {hi[0]} 이 {hi[1]:+.1f}pp 로 가장 크고 등급 {lo[0]} 가 {lo[1]:+.1f}pp 로 가장 작다.", []))
    ins.append(("매체의 「표시 없음」 은 선수 카드와 주요 소식 카드처럼 매체 이름을 싣지 않는 카드의 클릭이다.", []))
    if traffic and daily and daily.get("users"):
        fm = sum(r["users"] for r in daily["traffic"] if "fmkorea" in (r["source"] or ""))
        ins.append((f"유입은 fmkorea 참조가 {_pct(fm, daily['users'])}% 다.", []))
    body_incl, _ = draw(axes_incl or {}, "공개일 포함", all_)
    return _section("sec-engagement-by-dimension", title, sub, q, body, ins, toggle=True,
                    body_incl=body_incl if axes_incl else None,
                    insights_incl=[("공개일을 넣으면 홈 상단의 주요 소식 카드가 많이 눌려 「표시 없음」 이 커진다.", [])])


def _retention(ret: list | None):
    title, sub = "Retention", "코호트 × D+n"
    q = "처음 온 날짜마다 n 일 뒤에 다시 온 비율 (%) 을 본다. D+0 은 정의상 100 이라 색 눈금에서 뺐다."
    if not ret:
        return _missing("sec-retention", title, sub, q)
    cells = {}
    for r in ret:
        for k, v in enumerate(r["ret"]):
            cells[(r["first"], k)] = None if v is None else round(v / (r["n"] or 1) * 100)
    n_of = {r["first"]: r["n"] for r in ret}
    body = C.heatmap([r["first"] for r in ret], list(range(7)), cells, unit="%", w=560,
                     rowlab=lambda r: f"{_md(r)} · {C.fmt(n_of[r])}명", collab=lambda c: f"D+{c}",
                     show_text=True, scale_exclude_col=0)
    first = ret[0]
    d1 = cells.get((first["first"], 1))
    ins = [(f"{_md(first['first'])} 코호트 ({C.fmt(first['n'])}명) 는 D+1 이 {d1 if d1 is not None else '-'}% 다.", []),
           ("재방문을 붙잡는 장치 (알림 · 구독) 가 없다는 것이 지금의 한계다.", [])]
    return _section("sec-retention", title, sub, q, body, ins)


def _surfaces(daily: dict | None):
    title, sub = "Clicks by Surface", "화면별 카드 클릭 추이"
    q = "어느 자리의 카드가 눌리는지 날짜마다 본다. 기사 목록 · 주요 소식 · 선수 카드를 갈라 보고 나머지는 기타로 묶는다."
    if not daily or not daily.get("days"):
        return _missing("sec-clicks-by-surface", title, sub, q)
    days = daily["days"]
    labels = [_md(d["date"]) for d in days]
    other = [sum(v for k, v in d["surf"].items() if k not in SURFACE_KO) for d in days]
    series = [(SURFACE_KO[k], [d["surf"].get(k, 0) for d in days], cls)
              for k, cls in (("item", "s1"), ("mitem", "s2"), ("pcard", "s3"))] + [("기타", other, "dimseg")]
    body = (C.stacked_columns(labels, series, unit="건", w=640, h=210)
            + C.legend([("기사 목록", "s1"), ("주요 소식", "s2"), ("선수 카드", "s3"), ("기타 (관련 보도 · 타임라인)", "dimseg")]))
    mitem = sum(d["surf"].get("mitem", 0) for d in days)
    ins = [(f"주요 소식 카드는 이 기간에 {C.fmt(mitem)}건 눌렸다.", [])]
    return _section("sec-clicks-by-surface", title, sub, q, body, ins)


def _pages(pages: dict | None):
    title, sub = "Pages & Sessions", "페이지뷰 · 세션 체류 시간"
    q = "어떤 페이지가 읽히고 세션이 얼마나 머무는지 본다."
    if not pages:
        return _missing("sec-pages-sessions", title, sub, q)
    paths = [{"lab": p["label"], "n": p["n"]} for p in pages["paths"][:8]]
    body = _two(_fig("페이지뷰", C.hbars(paths, value="n", label="lab") if paths else "<p class=\"q\">아직 없다.</p>"),
                _fig("세션 체류 시간 분포", C.hbars(pages["engagement"], value="n", label="bin", unit=" 세션")))
    long = pages["engagement"][-1]["n"] if pages["engagement"] else 0
    ins = [(f"세션 체류 중앙값은 {C.fmt(pages['engagement_p50'])}초다.", [f"3분 넘게 머문 세션은 {C.fmt(long)}개다."])]
    return _section("sec-pages-sessions", title, sub, q, body, ins)


def _tier_key(t) -> str:
    s = str(t)
    return s[:-2] if s.endswith(".0") else s


def _top_articles(pages: dict | None, articles, sources):
    title, sub = "Top Articles", "가장 많이 눌린 기사 10"
    q = "어떤 기사가 가장 많이 눌렸는지 등급 · 단계 · 소스와 함께 본다."
    if not pages:
        return _missing("sec-top-articles", title, sub, q)
    by_hash = {a["content_hash"]: a for a in articles if a.get("content_hash")}
    rows = [(h["hash"], h["clicks"], by_hash[h["hash"]]) for h in pages["top_hashes"] if h["hash"] in by_hash][:10]
    src = sources or {}
    cells = "".join(
        f'<tr><td>{i + 1}</td><td><a class="alink" href="{SITE_URL}/article/{h}" target="_blank" rel="noopener">'
        f'{C.E((a.get("title_ko") or "")[:44])}</a></td><td>{_tier_key(a.get("tier"))}</td>'
        f'<td>{C.E(STAGE_KO.get(a.get("transfer_stage"), a.get("transfer_stage") or ""))}</td>'
        f'<td>{C.E(src.get(a.get("source_id"), {}).get("display_name") or a.get("source_id") or "")}</td>'
        f'<td class="num">{n}</td></tr>'
        for i, (h, n, a) in enumerate(rows))
    body = ('<table class="fresh"><thead><tr><th>#</th><th>기사</th><th>등급</th><th>단계</th><th>소스</th>'
            '<th class="num">클릭</th></tr></thead><tbody>' + cells + "</tbody></table>")
    ins = [("제목을 누르면 실제 기사 페이지가 새 창으로 열린다.", [])]
    if rows:
        ins.insert(0, (f"가장 많이 눌린 기사는 {C.fmt(rows[0][1])}번이다.", []))
    return _section("sec-top-articles", title, sub, q, body, ins)


def _player_rows(pages, players):
    surnames = [re.sub(r"[^a-z0-9]", "", (p.get("surname") or "").lower()) or "player" for p in players]
    dupes = {s for s in surnames if surnames.count(s) > 1}
    by_slug = {player_slug(p.get("surname") or "", p["id"], dupes): p for p in players}
    rows = []
    for r in pages["players"]:
        p = by_slug.get(r["slug"])
        group = _TRANSFER_GROUP_OF.get((p or {}).get("transfer_status") or "", "")
        name = (p or {}).get("ko_name") or r["slug"]
        rows.append({"lab": f"{name} · {group}" if group else name, "pv": r["pv"], "users": r["users"],
                     "group": group, "cls": STATUS_CLS.get(group, "dimbar")})
    return rows, by_slug


def _player_pages(pages: dict | None, players):
    title, sub = "Player Pages", "선수 페이지 조회 · 이적 상태별"
    q = ("선수 페이지가 얼마나 읽히고 어느 이적 상태의 선수가 관심을 끄는지 본다. "
         "상태는 선수 명단의 이적 상태 (영입 진행 중 · 이적 확정 · 이적 무산 · 타 클럽행 · 방출 진행 중) 그대로다.")
    if not pages:
        return _missing("sec-player-pages", title, sub, q)
    rows, by_slug = _player_rows(pages, list(players))
    per_group = {g: 0 for g in GROUP_ORDER}
    for r in rows:
        if r["group"] in per_group:
            per_group[r["group"]] += r["pv"]
    site_n = {g: 0 for g in GROUP_ORDER}
    for p in by_slug.values():
        g = _TRANSFER_GROUP_OF.get(p.get("transfer_status") or "", "")
        if g in site_n:
            site_n[g] += 1
    group_rows = [{"lab": g, "pv": per_group[g], "n": site_n[g],
                   "per": per_group[g] / max(site_n[g], 1), "cls": STATUS_CLS[g]} for g in GROUP_ORDER]
    top = rows[:12]
    body = (_two(_fig("선수별 페이지뷰 상위 12",
                      C.hbars(top, value="pv", label="lab", unit="뷰",
                              text_value=lambda r: f"{r['pv']}뷰 · {r['users']}명") if top else "<p class=\"q\">아직 없다.</p>"),
                 _fig("이적 상태별 페이지뷰 · 선수 수 · 선수당 뷰",
                      C.hbars(group_rows, value="pv", label="lab", right=190,
                              text_value=lambda r: f"{r['pv']}뷰 · 선수 {r['n']}명 · 선수당 {r['per']:.1f}")))
            + C.legend([(g, STATUS_CLS[g]) for g in GROUP_ORDER]))
    total = sum(r["pv"] for r in rows)
    ins = [(f"선수 목록 페이지는 {C.fmt(pages['list']['pv'])}뷰 {C.fmt(pages['list']['users'])}명이고 "
            f"개별 선수 페이지는 모두 합쳐 {C.fmt(total)}뷰다.", [])]
    if top:
        ins.append((f"{top[0]['lab']} 가 {top[0]['pv']}뷰 {top[0]['users']}명으로 가장 많다.", []))
    return _section("sec-player-pages", title, sub, q, body, ins)


# --- 조립 ---------------------------------------------------------------------

def _overview(window: dict | None):
    span = (f"{window['start']} 부터 {window['end']} 까지" if window and window.get("start")
            else "집계 창은 다음 적재 뒤에 정해진다")
    return [
        ("데이터 흐름", "GA4 → BigQuery 내보내기 → Iceberg (bronze · silver · gold) → 집계 파일 → 이 화면.",
         [("bronze", "GA4 원본 이벤트 (behavior.ga4_events)."),
          ("silver", "이벤트를 평탄화한 표 (ga4_events_flat)."),
          ("gold", "카드 클릭 팩트 · 세션 · 사용자 × 날짜 · 사용자 표와 날짜 디멘션.")]),
        ("기간", f"{span}."),
        ("갱신", "화면은 회차마다 (3시간) 다시 그리지만 GA4 내보내기가 다음 날 오전에 도착하므로 숫자는 하루에 한 번 바뀐다."),
        ("집계 기준", "사용자는 GA4 익명 id 로 센다.",
         [("하한선", "광고 차단을 쓰는 방문은 잡히지 않으므로 모든 수는 실제보다 작다."),
          ("공개일", "08-29 하루가 표본의 대부분이라 평균 · 비율 · 분포에서는 뺀다. Activity Heatmap 과 Engagement by Dimension 은 제목 옆 버튼으로 포함 · 제외를 바꿀 수 있다.")]),
    ]


def _generated_at(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return to_kst(dt.replace(tzinfo=None)).strftime("%Y-%m-%d %H:%M KST")


def build_behavior_view(metrics: dict, *, players=(), articles=(), sources=None) -> dict:
    """집계 JSON 을 화면이 그릴 dict 로. 없는 키는 그 절만 「다음 적재 뒤」 다."""
    daily = metrics.get("daily")
    pages = metrics.get("pages")
    sections = [
        _dau(daily),
        _funnel(metrics.get("funnel")),
        _heatmap(metrics.get("heat")),
        _dimension(metrics.get("axes"), metrics.get("axes_incl"), daily, metrics.get("totals")),
        {"pair": [_retention(metrics.get("retention")), _surfaces(daily)]},
        _pages(pages),
        _top_articles(pages, list(articles), sources),
        _player_pages(pages, players),
    ]
    flat = [s for item in sections for s in (item["pair"] if "pair" in item else [item])]
    return {"generated_at": _generated_at(metrics.get("generated_at")),
            "window": metrics.get("window") or {},
            "overview": _overview(metrics.get("window")),
            "tiles": _tiles(metrics.get("weekly")),
            "sections": sections,
            "missing_any": any(s["missing"] for s in flat),
            "missing_note": MISSING_NOTE}
```

- [ ] **Step 4: 부분 통과 확인**

Run: `uv run --project . --extra dev pytest tests/test_behavior_view.py -q -k "타일 or 관심_지수 or 리텐션 or 인사이트"`
Expected: 뷰모델만 재는 테스트 넷이 PASS (`render_behavior` 를 부르는 것은 아직 FAIL).

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/serve/behavior_view.py tests/test_behavior_view.py
git commit -m "feat(serve): 행동 지표 화면의 뷰모델 — 절 아홉과 타일 여섯 (안건 2φ · PR 1)"
```

#### 4b. 템플릿 — 공통 조각 `_dash.html.j2` 와 `behavior.html.j2`

- [ ] **Step 1: 공통 조각**

`src/bullet_in/serve/templates/_dash.html.j2` 전문.
스타일과 JS 는 목업 v2.8 의 것이고, 탭만 페이지 링크로 바꿨다 (스펙 §3.3).

```jinja
{#- 대시보드 두 화면 (behavior · ops) 의 공통 뼈대 — 상단 고정 · 목차 · 툴팁 · 공개일 토글.
    스타일 · JS 는 2026-09-04 목업 v2.8 그대로이고 탭은 페이지 링크다 (스펙 2026-09-05 §3.3).
    자식은 {% block title %} · {% block page %} (behavior | ops) · {% block meta %} · {% block content %} 를 채우고
    절은 _dash_macros.html.j2 의 매크로로 그린다. -#}
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{% block title %}bullet-in 대시보드{% endblock %}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@500;600&display=swap">
<style>
:root{color-scheme:light;
 --blue:#1D5FA8;--red:#DA020E;--green:#1D7A42;--yellow:#A8710A;
 --s1:#1D5FA8;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--neg:#DA020E;
 --ink:#16130f;--mut:#6f6960;--dim:#8d877d;--paper:#fbfaf7;--sunk:#f2efe9;--hair:#ddd8ce;--rule:#16130f;
 --o1:#86b6ef;--o2:#6b98cd;--o3:#517bad;--o4:#375f8d;--o5:#1f446f;--o6:#052b52;
 --serif:"Noto Serif KR",ui-serif,Georgia,"Apple SD Gothic Neo",serif;
 --sans:"Pretendard",-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Segoe UI",Roboto,sans-serif}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;
 --blue:#5C9CE6;--red:#FF4F57;--green:#54C97C;--yellow:#E0A83C;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--neg:#e66767;
 --ink:#efeae2;--mut:#a49d94;--dim:#8d867c;--paper:#131211;--sunk:#1d1b19;--hair:#332f2b;--rule:#efeae2;
 --o1:#2a4d78;--o2:#345f95;--o3:#4074b3;--o4:#4d89cd;--o5:#5C9CE6;--o6:#8fbdf0}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);font-size:14px;line-height:1.55}
.wrap{max-width:1040px;margin:0 auto;padding:28px 24px 64px}
header{display:flex;align-items:baseline;justify-content:space-between;gap:16px;flex-wrap:wrap;padding-bottom:6px}
h1{font-family:var(--serif);font-weight:600;font-size:22px;margin:0;letter-spacing:-.01em}
.meta{color:var(--mut);font-size:12.5px}
.tabs{display:flex;gap:4px;margin:8px 0 6px}
.tabs a{font:inherit;font-size:13.5px;padding:7px 14px;border:1px solid var(--hair);background:var(--sunk);color:var(--mut);border-radius:6px;text-decoration:none}
.tabs a[aria-current="page"]{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.tabs a:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
.top{position:sticky;top:0;z-index:5;background:var(--paper);padding-top:4px;margin:-4px 0 12px;border-bottom:1px solid var(--hair)}
.toc{font-size:12.5px;padding:0 0 8px}
.toc ol{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:2px 4px}
.toc li a{display:inline-block;padding:3px 9px;color:var(--mut);text-decoration:none;border-radius:999px;border:1px solid transparent}
.toc li a:hover,.toc li a:focus-visible{color:var(--ink);border-color:var(--hair)}
.toc li a.cur{color:var(--ink);background:var(--sunk);border-color:var(--hair)}
.tiles{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin:0 0 8px}
.tile{border:1px solid var(--hair);border-radius:8px;padding:11px 12px 9px;background:var(--paper);display:grid;gap:2px;align-content:start}
.tl{font-size:11px;letter-spacing:.02em;color:var(--mut)}
.tv{font-size:26px;font-weight:600;line-height:1.1;letter-spacing:-.02em}
.ts{font-size:11px;color:var(--dim);min-height:2.6em}
.spark{display:block;margin-top:4px}
.ln{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.ln.s1{stroke:var(--s1)}.ln.s2{stroke:var(--s2)}.ln.s3{stroke:var(--s3)}
.area{fill-opacity:.1}.area.s1{fill:var(--s1)}.band{fill:var(--s1);fill-opacity:.14}
.dot{stroke:var(--paper);stroke-width:2}.dot.s1{fill:var(--s1)}.dot.hollow{fill:var(--paper);stroke:var(--s1);stroke-width:2}
.dline{stroke:var(--s1);stroke-width:2;opacity:.5}
.sec{margin:26px 0 0;padding-top:18px;border-top:1px solid var(--hair)}
.sec h2{font-family:var(--serif);font-weight:600;font-size:17px;margin:0 0 2px}
.sec h2 small{font-family:var(--sans);font-weight:400;font-size:12.5px;color:var(--mut);margin-left:8px}
.q{margin:0 0 12px;color:var(--mut);font-size:13px;max-width:90ch}
.q .l{display:block}
.ins{margin:10px 0 0;padding:0;list-style:none;color:var(--mut);font-size:12.5px;max-width:90ch}
.ins li{position:relative;padding-left:16px;margin:2px 0}
.ins li::before{content:"·";position:absolute;left:3px;color:var(--dim);font-weight:700}
.ins .sub{list-style:none;margin:2px 0 4px;padding-left:14px}
.ins .sub li{color:var(--dim);padding-left:16px}
.ins .sub li::before{content:"→";left:0;font-weight:400}
.ov{display:grid;gap:12px;margin:10px 0 18px;padding:14px 16px;border:1px solid var(--hair);border-radius:8px;background:var(--sunk)}
.ov-item{display:grid;gap:3px}
.ov-lab{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--dim);font-weight:600}
.ov-txt{font-size:13px;color:var(--ink)}
.ov-sub{margin:2px 0 0;padding-left:18px;font-size:12.5px;color:var(--mut)}.ov-sub li{margin:3px 0}.ov-sub b{color:var(--ink);font-weight:600}
.alink{color:inherit;text-decoration:none;border-bottom:1px solid var(--hair)}.alink:hover{color:var(--blue);border-color:var(--blue)}
section.sec{scroll-margin-top:150px}
.two-sec{display:grid;grid-template-columns:1fr 1fr;gap:0 28px;margin:26px 0 0;padding-top:18px;border-top:1px solid var(--hair)}
.two-sec .sec{margin:0;padding-top:0;border-top:none;min-width:0}
.sec-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap}
.vtoggle{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--mut)}
.vtoggle button{font:inherit;font-size:12px;padding:2px 9px;border:1px solid var(--hair);background:var(--paper);color:var(--mut);border-radius:6px;cursor:pointer}
.vtoggle button[aria-pressed="true"]{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.missing{color:var(--dim);font-size:13px;margin:0}
.two{display:grid;grid-template-columns:1fr 1fr;gap:18px 24px}
figure{margin:0;min-width:0}
figcaption{font-size:12.5px;color:var(--mut);margin-bottom:4px}
.chart{max-width:100%;height:auto;display:block;overflow:visible;font-family:var(--sans)}
.chart text{fill:var(--ink);font-size:11px}
.chart .tick{fill:var(--dim);font-size:10.5px;font-variant-numeric:tabular-nums}
.chart .cat{fill:var(--ink);font-size:11.5px}.chart .cat.muted{fill:var(--dim)}
.chart .val{fill:var(--mut);font-size:11px;font-variant-numeric:tabular-nums}
.chart .dlab{fill:var(--ink);font-size:11px;font-weight:600;paint-order:stroke;stroke:var(--paper);stroke-width:3px}
.chart .grid,.chart .axis{stroke:var(--hair);stroke-width:1}
.chart .event{stroke:var(--mut);stroke-width:1;opacity:.6}.chart .ref{stroke:var(--mut);stroke-width:1;opacity:.5}
.chart .evlab{fill:var(--mut);font-size:10.5px}
.chart .fail{fill:var(--red);font-size:11px;font-weight:700;cursor:default}
.chart .bar.s1{fill:var(--s1)}.chart .bar.s2{fill:var(--s2)}.chart .bar.s3{fill:var(--s3)}.chart .bar.s4{fill:var(--s4)}.chart .bar.s5{fill:var(--s5)}.chart .bar.dimbar{fill:var(--dim);fill-opacity:.55}.chart .bar.dim{fill:var(--dim);fill-opacity:.55}
.chart .bar.pos{fill:var(--s1)}.chart .bar.neg{fill:var(--neg)}
.chart .cell{fill:var(--blue);stroke:none}.chart .cell.none{fill:var(--sunk)}
.chart .cell:hover,.chart .cell:focus{stroke:var(--ink);stroke-width:1.5;outline:none}
.chart .celltxt{fill:var(--ink);font-size:10.5px;font-variant-numeric:tabular-nums;pointer-events:none}.chart .celltxt.onink{fill:#fff}
.chart .mark{fill:var(--mut)}
.chart .seg{stroke:none}.chart .seg.s1{fill:var(--s1)}.chart .seg.s2{fill:var(--s2)}.chart .seg.s3{fill:var(--s3)}.chart .seg.dimseg{fill:var(--dim);fill-opacity:.5}
.chart .seg.o1{fill:var(--o1)}.chart .seg.o2{fill:var(--o2)}.chart .seg.o3{fill:var(--o3)}.chart .seg.o4{fill:var(--o4)}.chart .seg.o5{fill:var(--o5)}.chart .seg.o6{fill:var(--o6)}
.chart .seglab{fill:#fff;font-size:11px;font-weight:600;pointer-events:none}
.chart .hit{fill:transparent;cursor:crosshair;outline:none}
.chart .hit:hover+.xh,.chart .hit:focus+.xh{opacity:1}
.chart .xh{stroke:var(--ink);stroke-width:1;opacity:0;pointer-events:none}
.legend{font-size:12px;color:var(--mut);margin:6px 0 0;display:flex;flex-wrap:wrap;gap:4px 14px;align-items:center}
.key{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-2px;margin-right:5px}
.key.s1{background:var(--s1)}.key.s2{background:var(--s2)}.key.s3{background:var(--s3)}.key.s4{background:var(--s4)}.key.s5{background:var(--s5)}.key.dimbar{background:var(--dim);opacity:.55}.key.dimseg{background:var(--dim);opacity:.5}
.key.o1{background:var(--o1)}.key.o2{background:var(--o2)}.key.o3{background:var(--o3)}.key.o4{background:var(--o4)}.key.o5{background:var(--o5)}.key.o6{background:var(--o6)}
.meter{vertical-align:middle}.meter .track{fill:var(--sunk)}.meter .fill.ok{fill:var(--s1)}.meter .fill.warn{fill:var(--yellow)}.meter .fill.bad{fill:var(--red)}
.tbl{margin-top:10px;font-size:12.5px}.tbl summary{cursor:pointer;color:var(--mut)}
.tbl table,.fresh{border-collapse:collapse;width:100%;margin-top:8px;font-size:12.5px}
.tbl th,.tbl td,.fresh th,.fresh td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--hair);font-variant-numeric:tabular-nums}
.tbl th,.fresh th{color:var(--mut);font-weight:500;font-size:11.5px}
.num{text-align:right}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11.5px;border:1px solid var(--hair)}.pill.ok{color:var(--green)}.pill.bad{color:var(--red)}
#tip{position:fixed;pointer-events:none;background:var(--ink);color:var(--paper);padding:6px 9px;border-radius:6px;font-size:12px;line-height:1.4;white-space:pre;opacity:0;transition:opacity .08s;z-index:9;max-width:340px}
#tip b{font-size:13px}
[hidden]{display:none!important}
@media (max-width:760px){.tiles{grid-template-columns:repeat(2,1fr)}.two,.two-sec{grid-template-columns:1fr}}
@media (prefers-reduced-motion:reduce){#tip{transition:none}}
</style>
</head>
<body>
<div class="wrap">
<div class="top">
<header><h1>Bullet-in 대시보드</h1><div class="meta">{% block meta %}{% endblock %}</div></header>
<nav class="tabs" aria-label="화면">
  <a href="behavior.html"{% if self.page() | trim == "behavior" %} aria-current="page"{% endif %}>행동 지표</a>
  <a href="ops.html"{% if self.page() | trim == "ops" %} aria-current="page"{% endif %}>수집 현황</a>
</nav>
<nav class="toc" aria-label="절 목차"><ol id="toc"></ol></nav>
</div>
{% block content %}{% endblock %}
</div>
<div id="tip" role="status" aria-live="polite"></div>
<script>
(function(){
 var tip=document.getElementById('tip');
 function show(el,x,y){var t=el.getAttribute('data-tip');if(!t)return;var ls=t.split('\n');tip.textContent='';
   var b=document.createElement('b');b.textContent=ls[1]||'';var h=document.createElement('div');h.textContent=ls[0];tip.appendChild(b);tip.appendChild(h);
   for(var i=2;i<ls.length;i++){var d=document.createElement('div');d.textContent=ls[i];tip.appendChild(d);}
   tip.style.opacity=1;place(x,y);}
 function place(x,y){var w=tip.offsetWidth,hh=tip.offsetHeight;var px=x+14,py=y+14;if(px+w>innerWidth-8)px=x-w-14;if(py+hh>innerHeight-8)py=y-hh-14;tip.style.left=px+'px';tip.style.top=py+'px';}
 document.addEventListener('pointermove',function(e){var el=e.target.closest&&e.target.closest('[data-tip]');if(el)show(el,e.clientX,e.clientY);else tip.style.opacity=0;});
 document.addEventListener('focusin',function(e){var el=e.target.closest&&e.target.closest('[data-tip]');if(el){var r=el.getBoundingClientRect();show(el,r.left+r.width/2,r.top);}});
 document.addEventListener('focusout',function(){tip.style.opacity=0;});
 document.querySelectorAll('.vtoggle button[data-var]').forEach(function(b){b.addEventListener('click',function(){
   var sec=b.closest('section.sec');
   sec.querySelectorAll('.vtoggle button[data-var]').forEach(function(x){x.setAttribute('aria-pressed',x.dataset.var===b.dataset.var);});
   sec.querySelectorAll('.var').forEach(function(v){v.hidden=!v.classList.contains(b.dataset.var);});});});
 var ol=document.getElementById('toc');
 document.querySelectorAll('section.sec').forEach(function(sec){
   var li=document.createElement('li'),a=document.createElement('a');a.href='#'+sec.id;a.textContent=sec.querySelector('h2').firstChild.textContent.trim();li.appendChild(a);ol.appendChild(li);});
 if('IntersectionObserver' in window){var links={};ol.querySelectorAll('a').forEach(function(a){links[a.getAttribute('href').slice(1)]=a;});
  var io=new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){ol.querySelectorAll('a.cur').forEach(function(x){x.classList.remove('cur');});var a=links[e.target.id];if(a)a.classList.add('cur');}});},{rootMargin:'-160px 0px -70% 0px'});
  document.querySelectorAll('section.sec').forEach(function(sec){io.observe(sec);});}
})();
</script>
</body>
</html>
```

- [ ] **Step 2: 절 매크로**

`src/bullet_in/serve/templates/_dash_macros.html.j2` 전문.
부모 템플릿의 매크로는 자식의 블록 안에서 안 보이므로 (Jinja 의 `self` 는 블록만 가리킨다) 파일을 따로 두고 자식이 `import` 한다.

```jinja
{#- 대시보드 절 하나 · 인사이트 목록. 자식 템플릿이 `with context` 로 import 해 missing_note 를 본다. -#}
{%- macro section(s) %}
<section class="sec" id="{{ s.id }}">
  <div class="sec-head">
    <h2>{{ s.title }} <small>{{ s.sub }}</small></h2>
    {% if s.toggle and s.body_incl is not none %}
    <span class="vtoggle" role="group" aria-label="공개일 포함 여부"><span class="vt-lab">공개일 (08-29)</span>
      <button type="button" data-var="excl" aria-pressed="true">제외</button>
      <button type="button" data-var="incl" aria-pressed="false">포함</button></span>
    {% endif %}
  </div>
  {% if s.question %}<p class="q">{% for l in s.question %}<span class="l">{{ l }}</span>{% endfor %}</p>{% endif %}
  {% if s.missing %}
  <p class="missing">{{ missing_note }}</p>
  {% elif s.toggle and s.body_incl is not none %}
  <div class="var excl">{{ s.body }}{{ insights(s.insights) }}</div>
  <div class="var incl" hidden>{{ s.body_incl }}{{ insights(s.insights_incl) }}</div>
  {% else %}
  {{ s.body }}{{ insights(s.insights) }}
  {% endif %}
</section>
{%- endmacro %}
{%- macro insights(items) %}
{% if items %}<ul class="ins">{% for main, subs in items %}<li>{{ main }}{% if subs %}<ul class="sub">{% for x in subs %}<li>{{ x }}</li>{% endfor %}</ul>{% endif %}</li>{% endfor %}</ul>{% endif %}
{%- endmacro %}
```

- [ ] **Step 3: 행동 지표 템플릿**

`src/bullet_in/serve/templates/behavior.html.j2` 전문 (옛 내용은 버린다).

```jinja
{#- 행동 지표 화면 — 뷰모델 (serve/behavior_view.build_behavior_view) 만 읽는다.
    절 순서 · id 는 목업 v2.8 그대로이고 집계에 없는 절은 「다음 적재 뒤」 로 그린다 (스펙 §4). -#}
{% extends "_dash.html.j2" %}
{% import "_dash_macros.html.j2" as dash with context %}
{% block title %}bullet-in 행동 지표{% endblock %}
{% block page %}behavior{% endblock %}
{% block meta %}{{ view.generated_at }} 집계 · 인라인 SVG · 사용자 수는 하한선{% endblock %}
{% block content %}
<div class="ov">
{% for lab, txt, subs in view.overview %}
  <div class="ov-item"><div class="ov-lab">{{ lab }}</div><div class="ov-txt">{{ txt }}</div>
  {% if subs %}<ul class="ov-sub">{% for l, x in subs %}<li><b>{{ l }}</b>: {{ x }}</li>{% endfor %}</ul>{% endif %}</div>
{% endfor %}
</div>
{% if view.tiles %}
<div class="tiles">
{% for t in view.tiles %}
  <div class="tile"><div class="tl">{{ t.label }}</div><div class="tv">{{ t.value }}</div><div class="ts">{{ t.sub }}</div>{{ t.spark }}</div>
{% endfor %}
</div>
{% else %}
<p class="missing">{{ view.missing_note }}</p>
{% endif %}
{% for item in view.sections %}
{% if item.pair %}<div class="two-sec">{% for s in item.pair %}{{ dash.section(s) }}{% endfor %}</div>
{% else %}{{ dash.section(item) }}{% endif %}
{% endfor %}
{% endblock %}
```

`missing_note` 는 렌더가 `view.missing_note` 를 템플릿 변수로 넘기고 (아래 4c) `with context` 덕에 매크로가 본다.

- [ ] **Step 4: 커밋**

```bash
git add src/bullet_in/serve/templates/_dash.html.j2 src/bullet_in/serve/templates/_dash_macros.html.j2 src/bullet_in/serve/templates/behavior.html.j2
git commit -m "feat(serve): 대시보드 공통 조각과 행동 지표 템플릿을 목업 v2.8 대로 (안건 2φ · PR 1)"
```

#### 4c. 렌더와 회차 연결

- [ ] **Step 1: `render.py`**

`render.py:2158-2199` 의 `BEHAVIOR_AXES` · `_behavior_generated_at` · `render_behavior` · `write_behavior` 넷을 아래 둘로 바꾼다.
앞의 둘은 옛 템플릿만 쓰던 것이라 고아가 된다.

```python
def render_behavior(metrics: dict, *, players=(), articles=(), sources=None) -> str:
    """행동 지표 화면. 뷰모델은 serve/behavior_view 가 만들고 여기서는 템플릿만 부른다."""
    from bullet_in.serve.behavior_view import build_behavior_view
    view = build_behavior_view(metrics, players=players, articles=articles, sources=sources)
    return _env().get_template("behavior.html.j2").render(
        view=view, missing_note=view["missing_note"])


def write_behavior(metrics_path: str | Path, out_dir: str | Path, *,
                   players=(), articles=(), sources=None) -> bool:
    """집계 파일이 있으면 site/behavior.html 을 그린다.

    집계는 회차가 아니라 `warehouse_load` 태스크가 만든다. 파일이 없다는 것은 아직
    한 번도 안 돌았거나 그쪽이 실패했다는 뜻이고, 둘 다 회차를 멈출 이유는 아니다.
    선수 · 기사 · 소스는 화면이 슬러그 · 해시를 이름으로 바꾸는 데만 쓴다.
    """
    src = Path(metrics_path)
    if not src.exists():
        return False
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "behavior.html").write_text(
        render_behavior(json.loads(src.read_text(encoding="utf-8")),
                        players=players, articles=articles, sources=sources),
        encoding="utf-8")
    return True
```

`behavior_view` 를 함수 안에서 import 하는 이유는 `behavior_view` 가 `render` 의 `SITE_URL` · `player_slug` 를 위에서 import 하기 때문이다.
모듈 위에서 서로 부르면 순환이 된다.

- [ ] **Step 2: `run.py`**

`run.py:654-658` 의 호출 한 줄을 바꾼다.

```python
    try:
        write_behavior("state/behavior_metrics.json", "site",
                       players=pstore.page_players(), articles=rows, sources=sources)
    except Exception:
        logging.getLogger(__name__).warning(
            "행동 지표 뷰 생성 실패 — 파이프라인은 계속 진행", exc_info=True)
```

`rows` 는 같은 함수 위에서 `serving_rows` 가 걸러 준 서빙 행이고 `sources` 는 `_materials()` 가 준 설정이다.

- [ ] **Step 3: 통과 확인**

Run: `uv run --project . --extra dev pytest tests/test_behavior_view.py tests/test_run_stages.py -q`
Expected: `17 passed` + `6 passed`

- [ ] **Step 4: 전체 테스트**

Run: `cd <워크트리> && uv run --project . --extra dev pytest -q 2>&1 | tail -3`
Expected: 수집 수 1,704 − 10 (옛 행동 화면 테스트) + 16 (차트) + 12 (gold) + 11 (집계) + 17 (새 행동 화면) = **1,750** · 실패 0.
`tests/test_serve_render.py` 등 다른 파일이 `BEHAVIOR_AXES` 를 참조하고 있으면 그 참조를 지운다 (2026-09-05 grep 으로는 `render.py` 와 `test_behavior_view.py` 밖에 없다).

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/serve/render.py src/bullet_in/run.py
git commit -m "feat(serve): 행동 지표 렌더가 뷰모델을 거치고 회차가 선수 · 기사 행을 넘긴다 (안건 2φ · PR 1)"
```

#### 4d. 로컬에서 한 번 눈으로 본다

- [ ] **Step 1: 목업 데이터로 렌더**

목업 데이터 (`mockup_data2.json`) 는 집계 JSON 과 모양이 달라 그대로 못 쓴다.
테스트 픽스처 `METRICS` 로 그린다.

```bash
cd <워크트리>
uv run --project . python - <<'PY'
import json, sys
sys.path.insert(0, "tests")
from test_behavior_view import METRICS, PLAYERS, ARTICLES, SOURCES
from bullet_in.serve.render import render_behavior
open("/tmp/behavior.html", "w", encoding="utf-8").write(
    render_behavior(METRICS, players=PLAYERS, articles=ARTICLES, sources=SOURCES))
PY
```

- [ ] **Step 2: 로컬 서버로 본다**

`python -m http.server` 는 charset 을 안 보내 한글이 깨진다 (메모리 함정).
확장 매핑에 charset 을 넣은 핸들러로 띄운다.

```bash
cd /tmp && uv run --project <워크트리> python - <<'PY'
import http.server, functools
H = http.server.SimpleHTTPRequestHandler
H.extensions_map[".html"] = "text/html; charset=utf-8"
http.server.HTTPServer(("127.0.0.1", 8765), H).serve_forever()
PY
```

브라우저 (Chrome MCP · `http://127.0.0.1:8765/behavior.html`) 로 절 아홉 · 토글 · 툴팁 · 목차 · 다크 모드를 본다.
목업 v2.8 과 나란히 놓고 다른 곳을 적어 둔다 (스펙 §1 이 정본이다).

---

### Task 5: 트러블슈팅 §3 정정 — 계측은 이미 고쳐져 있었다

**Files:**
- Modify: `docs/troubleshooting/2026-09-04-three-charts-that-pointed-at-the-wrong-layer.md:36-47`

**Interfaces:**
- 없음 (문서).

- [ ] **Step 1: 사실 확인 한 번 더**

```bash
curl -sL https://bullet-in.pages.dev/app.js | grep -c "card_slug"
```

Expected: `1` (배포본이 슬러그를 보낸다). `/static/app.js` 는 소프트 404 라 첫 화면 HTML 이 온다 (2026-09-05 실물).

- [ ] **Step 2: §3 을 고친다**

「원인」 과 「처방」 두 문단을 아래로 바꾼다.

```markdown
**원인** — 카드 클릭 이벤트가 선수 카드에 슬러그를 싣기 시작한 것이 PR #439 (2026-09-03 01:26 KST 머지) 부터다.
gold 의 선수 카드 클릭 44건은 전부 09-01 이전 것이라 그 전에 쌓였다.
계측 (`app.js` 의 `track()`) 은 `data-slug` 를 `card_slug` 로 보내고 있고, 2026-09-05 에 배포본에서 확인했다.
처음 적었던 「값이 이벤트 파라미터로는 안 나간다」 는 틀렸다.
쌓인 44건이 전부 빈 것을 보고 계측이 지금도 빈 줄 알았던 것이다.

**처방** — 코드로 고칠 것은 없다.
배포 뒤 선수 카드를 한 번 누르고 다음 날 silver 에 `card_surface = 'pcard'` 이고 `card_slug` 가 찬 행이 생기는지 본다 (스펙 2026-09-05 §3.6).
쌓인 44건은 되살릴 수 없다.
```

「4. 공통 교훈」 끝에 한 줄을 더한다.

```markdown
셋째 것은 한 번 더 틀렸다.
빈 값 44건을 보고 「지금도 빈다」 고 적었는데, 그 44건은 전부 고치기 전 것이었다.
쌓인 값이 빈 것과 지금 나가는 값이 빈 것은 다른 관측이다.
```

- [ ] **Step 3: 서식 훅**

Run: `python3 .claude/hooks/check-doc-format.py docs/troubleshooting/2026-09-04-three-charts-that-pointed-at-the-wrong-layer.md`
Expected: `위반 없음`

- [ ] **Step 4: 커밋**

```bash
git add docs/troubleshooting/2026-09-04-three-charts-that-pointed-at-the-wrong-layer.md
git commit -m "docs(dashboard): 선수 카드 슬러그 계측은 #439 로 이미 고쳐져 있었다 (트러블슈팅 §3 정정)"
```

---

### Task 6: 기준값 재현 · PR · 배포 뒤 확인

**Files:**
- 없음 (검증 · PR 본문 · 메모리)

- [ ] **Step 1: 런북 §9 재현 (VM · 임시 클론)**

VM 의 주 체크아웃은 `advance` 태스크만 옮긴다 (CLAUDE.md).
브랜치를 밀어 올린 뒤 `/tmp` 에 따로 받아 돌린다.

```bash
git push -u origin worktree-dashboard
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 '
  rm -rf /tmp/bi-dash && git clone -q --depth 1 --branch worktree-dashboard https://github.com/benidjor/bullet-in /tmp/bi-dash &&
  cd /tmp/bi-dash && cp ~/bullet-in/.env . && set -a && . ./.env && set +a &&
  GOOGLE_APPLICATION_CREDENTIALS=/home/ubuntu/.bullet-in-lakehouse.json ~/.local/bin/uv run --project . python -m bullet_in.warehouse show --from 2026-08-28 --to 2026-09-03'
```

Expected (런북 §9 그대로):

```
사용자 7일 · 세션 · 참여 세션 비율 | 890 · 1,502 · 61%
공개일 DAU · 신규 | 688 · 666
퍼널 | 863 → 221 → 97 → 71
신뢰도 · 기자 필터 사용자 · 원문 이동 | 53 · 7
기사 상세를 본 사용자 | 254
선수 페이지 뷰 · 목록 뷰 | 108 · 71
모바일 비율 · fmkorea 참조 비율 | 66% · 70%
```

`show --from --to` 는 `build_metrics` 를 부르므로 gold 표 셋이 먼저 있어야 한다.
임시 클론에서 `python -m bullet_in.warehouse load` 를 한 번 돌리면 운영 카탈로그의 표를 새 코드로 갈아 끼운다.
그 표는 회차의 `warehouse_load` 가 어차피 매번 갈아 끼우므로 운영에 해가 없다.
다만 `state/behavior_metrics.json` 은 임시 클론 안에 떨어지므로 운영 파일은 안 건드린다.
줄 하나라도 다르면 표가 아니라 런북 §3 에서 §7 의 절차와 어디가 다른지를 먼저 찾는다 (§9 규칙).
기기 · 유입 두 비율은 목업이 이벤트 단위로 세고 코드는 사용자 × 날짜 · 세션 단위로 세므로 1 포인트 차이는 정의 차이다.
그때는 PR 본문에 두 값과 이유를 적는다.

- [ ] **Step 2: 임시 클론 정리**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 'rm -rf /tmp/bi-dash'
```

- [ ] **Step 3: PR 본문**

7절 구조 (컨벤션 §2) · `--body-file` · Claude 서명 없음.
§4 검증에 위 일곱 줄과 전체 테스트 수 (기대 1,750) 를 붙인다.
게시 전에 둘을 거친다.

```bash
python3 .claude/tools/check-pr-format.py --body <본문 파일> --title "feat(dashboard): 행동 지표 화면을 목업 v2.8 대로 — gold 표 셋 · 집계 다섯 · 차트 모듈 (안건 2φ · PR 1)"
```

humanize-korean fast 1회 (명사형 불릿 · 수치 · 경로 · 코드 블록은 변경 금지로 명시).

```bash
gh pr create --base main --head worktree-dashboard --title "<위 제목>" --body-file <본문 파일>
```

- [ ] **Step 4: 머지 뒤 (사용자가 머지한다)**

- 다음 회차의 `advance` 가 코드를 받는다. 그 회차의 `publish` 는 옛 JSON 을 읽어 절 여덟이 「다음 적재 뒤」 로 나온다 (스펙 §4). 정상이다.
- 그다음 회차부터 전부 채워진다. 확인은 `curl -sL https://bullet-in.pages.dev/behavior.html | grep -c 'class="sec"'` → `9`, `grep -c "<svg"` → 20 이상.
- 선수 카드 한 번 누르기 (광고 차단 없는 브라우저) → 다음 날 silver 에 `pcard` + `card_slug` 행 (스펙 §3.6).
- 워크트리 · 로컬 브랜치 · 원격 브랜치 · `git worktree prune` 넷을 지운다 (규율 §2).
- 메모리: `dashboard-redesign-track-2026-09-04` 에 PR 번호 · 재현 결과 · 「계측은 이미 고쳐져 있었다」 를 적고, 안건 표 2φ 행을 「PR 1 머지 · PR 2 는 09-06 저녁 판단」 으로 고친다.

---

## 자체 검토 (2026-09-05)

- 스펙 §3.1 표 셋 · 집계 다섯 · JSON 한 파일 → 태스크 2 · 3.
- 스펙 §3.2 차트 12종 · CSS 클래스 색 → 태스크 1.
- 스펙 §3.3 템플릿 둘 (이 PR 은 `behavior.html.j2` 만) · 공통 조각 · JS 셋 · 인사이트는 값에서 → 태스크 4.
- 스펙 §3.6 계측 확인 → 태스크 5 · 6.
- 스펙 §4 빈 구간 → 태스크 4 의 `_missing` 과 테스트 「집계에_없는_절」.
- 스펙 §5 §9 재현 명령 · 구조 단언 · 실제 컬럼 이름 픽스처 → 태스크 3 (`show --from --to`) · 1 · 2.
- 스펙 §3.4 · §3.5 (수집 현황 · README §4) 는 PR 2 의 몫이라 이 계획에 없다.

## 실행 중 정정 (2026-09-05)

계획서의 코드를 그대로 옮기다가 실물 (pyiceberg · Jinja · 테스트 수) 과 어긋난 자리를 고쳤다.
그 자리를 여기에 적는다.
코드 블록 자체는 고치지 않았으므로 아래가 우선한다.

| 태스크 | 계획서 | 실제 (고친 것) | 이유 |
| --- | --- | --- | --- |
| 0 | 워크트리 `dashboard` · 브랜치 `worktree-dashboard` | 워크트리 `dashboard-pr1` · 브랜치 `worktree-dashboard-pr1` (태스크 6 의 push · clone · PR head 도 같은 이름) | 사용자 지시 (스펙 PR 의 워크트리는 이미 정리됐다) |
| 1 | RED 기대 `ModuleNotFoundError` | 실제는 `ImportError` | `serve/__init__.py` 가 이미 있어 하위 모듈 부재는 `ImportError` 로 난다 |
| 1 | 차트 함수가 빈 입력에서 `max()` 예외 | `hbars` · `stacked_columns` · `line_chart` · `heatmap` 이 빈 입력이면 빈 `<svg>` 를 돌려준다 · 테스트 1 추가 (17) · `date` import 제거 | 리뷰 지적 · PR 2 가 빈 목록을 넘길 수 있다 |
| 3 | `_scan_rows` 가 요청 컬럼을 그대로 `selected_fields` 로 | 표 스키마에 있는 컬럼으로 좁히고 없는 컬럼은 경고 로그 | pyiceberg 0.11.1 은 없는 컬럼을 고르면 `ValueError` · 픽스처의 silver 에는 `page_location` 이 없다 |
| 3 | `agg_daily` 의 `traffic` 을 상위 10 으로 자름 | 자르지 않는다 (표시 자르기는 뷰모델 `_traffic_rows` 의 7) | 기준값 7행과 인사이트가 fmkorea 호스트 전부를 더하므로 잘린 목록이면 조용히 빠진다 |
| 3 | 히트맵 두 벌에 `start` 없음 | `start=LAUNCH_DATE.isoformat()` | 스펙 §3.1 의 창은 「공개 뒤 전체」 · 공개 전 시험 트래픽을 막는다 · 테스트 2 추가 (13) |
| 4 | `_dash.html.j2` 의 `<style>` 을 그대로 | `{% raw %}` 로 감쌌다 | CSS 의 `){#tip{…}}` 에서 `{#` 을 Jinja 가 주석 시작으로 읽어 렌더가 깨진다 |
| 4 | `_overview` 의 「기간」 · 「갱신」 항목이 2-튜플 | 셋째 원소 `[]` 를 붙였다 | 템플릿이 `for lab, txt, subs` 로 셋을 푼다 |
| 4 | `test_설명문…` 이 `>= 18` | `>= 16` | 절 아홉의 설명문 문장 합이 16 이다 |
| 4 | 인사이트 문장 여섯이 값과 무관한 해석 | 값이 실리는 절반만 남기거나 값에서 계산 (`(없음)` 클릭 수 비교) · 테스트 1 추가 (17) | 스펙 §3.3 (해석 문장은 화면에 안 싣는다) 이 계획서보다 우선한다 |
| 4 · 전체 | 테스트 17 · 전체 1,750 · `test_run_stages` 6 | 새 파일 17 (16 + 1) · 전체 1,753 (1,704 − 10 + 17 + 12 + 13 + 17) · `test_run_stages` 7 | 계획서의 세기가 틀렸다 |

정정을 판정한 근거는 스펙이 계획서보다 우선한다는 규칙이고, 미뤄 둔 사소한 지적은 PR 본문 §5 에 있다.
