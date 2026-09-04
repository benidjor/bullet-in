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
from datetime import timedelta

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
    if not labels or not series or not any(v for _, v in series):
        return svg(w, h, "")
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
    if not labels:
        return svg(w, h, "")
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
    if not rows:
        return svg(w, T + 4, "")
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
    if not rows or not cols:
        return svg(w, T, "")
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
