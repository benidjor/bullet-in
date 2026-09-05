"""수집 현황 화면의 뷰모델 — MariaDB 스냅샷과 게이트 집계를 절 열의 값 · SVG 로 바꾼다.

화면 (`ops.html.j2`) 은 이 모듈이 돌려주는 dict 만 본다.
절 순서와 `id` 는 목업 v2.8 그대로이고, 마지막 절은 기존 두 표 (재작성 잔존율 · 선수 추출 누락) 다.
시각은 전부 UTC 다 — 저장값이 UTC 이고 목업도 UTC 로 그렸다.
스냅샷 키가 비어도 (첫 회차 · 로컬) 절은 전부 그리고 타일만 비운다 (스펙 §4 · 빈 구간 없음).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from markupsafe import Markup

from bullet_in.dbt_gate import GateTally
from bullet_in.serve import charts as C
from bullet_in.serve.behavior_view import (MISSING_NOTE, TIER_KO, TIER_ORDER, _fig, _pct, _section,
                                           _tier_key, _two)

OPS_EPOCH = date(2026, 6, 12)              # 첫 라이브 실행 · 회차 전체의 시작 (storage.mariadb.OPS_EPOCH 와 같은 날)
MIX_SINCE = date(2026, 7, 13)              # 주별 구성의 시작 (월요일 · storage.mariadb.MIX_SINCE)
EXPECTED_RUNS_PER_DAY = 8
RECENT_RUNS = 30                           # 타일 · SLO-2 의 창
EVENTS = (("2026-09-04", "Airflow"),)      # 회차가 Airflow 로 옮겨 간 날 (2026-09-04 15:51 KST)
SLO2_TARGET = 0.99
SLO4_TARGET = 0.99
# SLO-1 은 회차마다 안 재므로 런북 값을 고정으로 적는다 (README §4 · 런북 2026-07-14-slo1-benchmark.md).
SLO1_VALUE = "56.5%↓"
SLO1_HOW = "벤치마크 3회 중앙값 · 2026-07-15 · 회차마다 안 잰다"
STAGE_GROUPS = (("루머", ("rumour",)), ("관심", ("interest",)), ("협상", ("negotiating",)),
                ("합의 · 메디컬", ("agreed", "personal_terms", "medical")),
                ("공식 · 완료", ("official", "done")), ("무산", ("collapsed",)),
                ("기타", ("other", None)))
UNNAMED = "이름 미확정 (후보 명단)"
NO_GATE = "게이트 결과 없음"
NONE_YET = '<p class="q">아직 없다.</p>'


# --- 작은 헬퍼 -----------------------------------------------------------------

def _monday(d: date) -> date:
    return d - timedelta(d.isoweekday() - 1)


def _weeks(start: date, end: date) -> list[date]:
    out, d = [], _monday(start)
    while d <= end:
        out.append(d)
        d += timedelta(7)
    return out


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(i) for i in range((end - start).days + 1)]


def _wl(d: date) -> str:
    """주 · 날짜 라벨 — 08/31"""
    return f"{d:%m/%d}"


def _pctile(vals, q) -> float:
    """가장 가까운 순위 백분위 — 값이 없으면 0."""
    s = sorted(vals)
    return s[int(q * (len(s) - 1) + 0.5)] if s else 0.0


def _yw_monday(yw: int) -> date:
    """YEARWEEK(x, 3) 정수 → 그 주 월요일"""
    return date.fromisocalendar(yw // 100, yw % 100, 1)


def _display(sources, sid) -> str:
    return (sources or {}).get(sid, {}).get("display_name") or sid


def _by_day(runs_all) -> dict[date, list[dict]]:
    out = defaultdict(list)
    for r in runs_all:
        out[r["started_at"].date()].append(r)
    return out


def _by_week(runs_all) -> dict[date, list[dict]]:
    out = defaultdict(list)
    for r in runs_all:
        out[_monday(r["started_at"].date())].append(r)
    return out


def _gate_at(iso: str) -> str:
    try:
        return f"{datetime.fromisoformat(iso.replace('Z', '+00:00')):%m-%d %H:%M} UTC"
    except ValueError:
        return iso or "시각 없음"


# --- 타일 ---------------------------------------------------------------------

def _tiles(runs_all, recent, stale_count, span_weeks) -> list[dict]:
    if not recent:
        return []
    top = recent[-1]
    n = len(recent)
    new, dup = sum(r["new_count"] for r in recent), sum(r["dup_count"] for r in recent)
    rates = [_pct(r["dup_count"], r["new_count"] + r["dup_count"]) for r in recent]
    durs = [r["duration_sec"] for r in recent]
    fetch = [r["fetch_duration_sec"] for r in recent if r.get("fetch_duration_sec") is not None]
    sr = sum(r["success_rate"] for r in recent) / n
    errs = sum(1 for r in runs_all if r["error_count"] > 0)
    return [
        {"label": "신규 · 최근 회차", "value": C.fmt(top["new_count"]),
         "sub": f"{top['started_at']:%m-%d %H:%M} UTC",
         "spark": Markup(C.sparkline([r["new_count"] for r in recent]))},
        {"label": f"Dedup Rate · {n}회", "value": f"{_pct(dup, new + dup)}%",
         "sub": "중복 차단 ÷ (신규 + 중복)", "spark": Markup(C.sparkline(rates))},
        {"label": f"Success Rate · {n}회", "value": f"{sr * 100:.1f}%",
         "sub": f"SLO-2 목표 {SLO2_TARGET * 100:.0f}%", "spark": ""},
        {"label": f"Run Duration p50 · {n}회", "value": f"{_pctile(durs, .5):.0f}초",
         "sub": f"fetch {_pctile(fetch, .5):.0f}초" if fetch else "fetch 이력 없음",
         "spark": Markup(C.sparkline(durs))},
        {"label": "Stale Sources", "value": "—" if stale_count is None else C.fmt(stale_count),
         "sub": "임계 초과 소스 (SLO-5)", "spark": ""},
        {"label": f"Runs · {span_weeks}주", "value": C.fmt(len(runs_all)),
         "sub": f"에러 회차 {C.fmt(errs)} · 기대 {EXPECTED_RUNS_PER_DAY}/일", "spark": ""},
    ]


# --- SLO ----------------------------------------------------------------------

def _slo_rows(recent, stale_count, anomaly_count, gate: GateTally | None, articles_total: int) -> list[dict]:
    def row(i, name, target, value, how, status):
        return {"slo_id": f"SLO-{i}", "name": name, "target": target, "value": value, "how": how, "status": status}

    rows = [row(1, "병렬화 수집 시간 단축", "순차 대비 ≥ 55%↓", SLO1_VALUE, SLO1_HOW, "ok")]
    if recent:
        sr = sum(r["success_rate"] for r in recent) / len(recent)
        rows.append(row(2, "회차 성공률", f"≥ {SLO2_TARGET * 100:.0f}%", f"{sr * 100:.1f}%",
                        f"최근 {len(recent)}회 평균 success_rate", "ok" if sr >= SLO2_TARGET else "bad"))
    else:
        rows.append(row(2, "회차 성공률", f"≥ {SLO2_TARGET * 100:.0f}%", "—", "회차 이력 없음", "info"))
    total = articles_total or 1
    if gate is None:
        rows.append(row(3, "중복 적재율", "0%", NO_GATE, "dbt unique 테스트", "info"))
        rows.append(row(4, "필수 필드 완전성", f"≥ {SLO4_TARGET * 100:.0f}%", NO_GATE, "dbt not_null 테스트", "info"))
    else:
        at = _gate_at(gate.generated_at)
        dups = sum(t.failures for t in gate.unique_failed)
        how3 = (f"dbt unique 테스트 {gate.unique_total}종 "
                + ("통과" if not gate.unique_failed else f"가운데 {len(gate.unique_failed)}종 실패")
                + f" · 게이트 {at}")
        rows.append(row(3, "중복 적재율", "0%", "0%" if not dups else f"{dups / total * 100:.2f}%", how3,
                        "ok" if not gate.unique_failed else "bad"))
        worst = max((t.failures for t in gate.not_null_failed), default=0)
        comp = 1 - worst / total
        how4 = (f"dbt not_null 테스트 {gate.not_null_total}종 "
                + ("통과" if not gate.not_null_failed
                   else f"가운데 {len(gate.not_null_failed)}종 결측 {worst}행")
                + " · 같은 게이트")
        rows.append(row(4, "필수 필드 완전성", f"≥ {SLO4_TARGET * 100:.0f}%", f"{comp * 100:.1f}%", how4,
                        "ok" if comp >= SLO4_TARGET else "bad"))
    rows.append(row(5, "소스 신선도", "끊긴 소스 0", "—" if stale_count is None else C.fmt(stale_count),
                    "source_freshness 워터마크 · 임계 초과 소스 수",
                    "info" if stale_count is None else ("ok" if not stale_count else "bad")))
    rows.append(row(6, "수집량 이상", "이상 소스 0", C.fmt(anomaly_count),
                    "직전 회차들 대비 ±2σ 드롭 · 스파이크 (quality.volume_anomalies)",
                    "ok" if anomaly_count == 0 else "bad"))
    return rows


_PILL = {"ok": '<span class="pill ok">✓ 충족</span>', "bad": '<span class="pill bad">✕ 미달</span>',
         "info": '<span class="pill">참고</span>'}


def _slo(rows, gate):
    q = ("회차 성공률 · 중복 적재율 · 필수 필드 완전성 · 소스 신선도 · 수집량 이상 · 병렬화 여섯 지표가 각자의 목표치를 지금 지키는지 확인한다. "
         "2 · 5 · 6 은 회차마다 코드가 직접 재고 3 · 4 는 회차 끝 dbt 게이트가 낸 테스트 결과에서 읽으며 1 은 벤치마크로 잰 값이다.")
    body = ('<table class="fresh"><thead><tr><th>#</th><th>지표</th><th>목표</th><th class="num">현재</th>'
            '<th>측정</th><th>상태</th></tr></thead><tbody>'
            + "".join(f"<tr><td>{r['slo_id']}</td><td>{C.E(r['name'])}</td><td>{C.E(r['target'])}</td>"
                      f"<td class=\"num\">{C.E(r['value'])}</td><td>{C.E(r['how'])}</td><td>{_PILL[r['status']]}</td></tr>"
                      for r in rows)
            + "</tbody></table>")
    ins = []
    bad = [r["slo_id"] for r in rows if r["status"] == "bad"]
    if bad:
        ins.append((f"미달은 {' · '.join(bad)} 이다.", []))
    ins.append((f"SLO-3 · 4 는 직전 회차 게이트 ({_gate_at(gate.generated_at)}) 의 값이다." if gate
                else "SLO-3 · 4 는 게이트 결과 파일이 생기면 채워진다.", []))
    return _section("sec-slo", "SLO", "여섯 지표 · 목표 · 현재", q, body, ins)


# --- 절 -----------------------------------------------------------------------

def _volume(runs_all, today: date, span_weeks: int):
    title, sub = "Ingestion Volume", "일별 신규 기사 · 회차 수"
    q = (f"{span_weeks}주 동안 하루에 몇 건씩 새 기사가 들어왔는지 캘린더로 본다. "
         f"회차가 하루 {EXPECTED_RUNS_PER_DAY}회를 채웠는지 기준선과 함께 확인한다.")
    days = _days(OPS_EPOCH, today)
    by = _by_day(runs_all)
    new = {d.isoformat(): sum(r["new_count"] for r in by.get(d, [])) for d in days}
    counts = [len(by.get(d, [])) for d in days]
    events = [(days.index(date.fromisoformat(d)), lab) for d, lab in EVENTS if date.fromisoformat(d) in days]
    body = (_two(_fig("일별 신규 기사 (캘린더)", C.calendar(new, OPS_EPOCH, today, w=520)),
                 _fig(f"일별 회차 수 (기대 {EXPECTED_RUNS_PER_DAY})",
                      C.line_chart([_wl(d) for d in days], [("회차", counts)], unit="회",
                                   ref=EXPECTED_RUNS_PER_DAY, events=events, w=520, h=190)))
            + C.table(["날짜", "신규", "중복", "회차", "에러 회차", "p50 소요"],
                      [(d.isoformat(), new[d.isoformat()], sum(r["dup_count"] for r in by[d]), len(by[d]),
                        sum(1 for r in by[d] if r["error_count"] > 0),
                        f"{_pctile([r['duration_sec'] for r in by[d]], .5):.0f}")
                       for d in days if d in by]))
    ins = []
    if by:
        top = max(new, key=new.get)
        ins.append((f"하루 최고는 {top[5:]} 의 {C.fmt(new[top])}건이다.", []))
        short = sum(1 for d in days if d in by and d != today and len(by[d]) < EXPECTED_RUNS_PER_DAY)
        ins.append((f"회차가 있던 날 가운데 {EXPECTED_RUNS_PER_DAY}회에 못 미친 날은 {short}일이다 (오늘 제외).", []))
    return _section("sec-ingestion-volume", title, sub, q, body, ins)


def _coverage(runs_all, sources, today: date, span_weeks: int):
    title, sub = "Source Coverage", "소스 × 주 신규 기사"
    q = ("소스마다 주 단위로 새 기사 수를 보고 어느 소스가 언제 살아 있었는지 확인한다. "
         "회차 기록에 남은 소스별 건수라 재수집으로 날짜가 옮겨진 것과는 상관이 없다. "
         "빈 칸이 이어지면 셀렉터가 깨졌거나 차단당한 구간이다.")
    weeks = _weeks(OPS_EPOCH, today)
    cells = defaultdict(int)
    for r in runs_all:
        wk = _monday(r["started_at"].date())
        for sid, n in r["source_counts"].items():
            cells[(sid, wk)] += n
    sids = set(sources or {}) | {sid for sid, _ in cells}
    total = {sid: sum(v for (s, _), v in cells.items() if s == sid) for sid in sids}
    rows = sorted(sids, key=lambda s: (-total[s], s))
    full = {(s, w): cells.get((s, w), 0) for s in rows for w in weeks}
    body = C.heatmap(rows, weeks, full, w=980, unit="건", rowlab=lambda s: _display(sources, s), collab=_wl)
    ins = []
    if rows and total[rows[0]]:
        ins.append((f"{span_weeks}주 합이 가장 큰 소스는 {_display(sources, rows[0])} {C.fmt(total[rows[0]])}건이다.", []))
        gappy = []
        for s in rows:
            seen = False
            for w in weeks[:-1]:                     # 이번 주는 아직 진행 중이라 안 센다
                if full[(s, w)]:
                    seen = True
                elif seen:
                    gappy.append(s)
                    break
        if gappy:
            ins.append((f"살아난 뒤 빈 주가 있는 소스는 {' · '.join(_display(sources, s) for s in gappy)} 다.", []))
    return _section("sec-source-coverage", title, sub, q, body, ins)


def _throughput(runs_all, today: date, span_weeks: int):
    title, sub = "Throughput", "주별 신규 · 중복 차단"
    q = "들어온 것 가운데 새 기사가 얼마이고 같은 원문이 다시 들어온 것이 얼마인지 주마다 본다."
    weeks = _weeks(OPS_EPOCH, today)
    per = _by_week(runs_all)
    new = [sum(r["new_count"] for r in per.get(w, [])) for w in weeks]
    dup = [sum(r["dup_count"] for r in per.get(w, [])) for w in weeks]
    labels = [_wl(w) for w in weeks]
    rate = [_pct(d, n + d) for n, d in zip(new, dup)]
    body = _two(_fig("주별 신규 기사 (건)", C.stacked_columns(labels, [("신규", new, "s1")], unit="건")),
                _fig("Dedup Rate · 중복 차단 ÷ (신규 + 중복) · %",
                     C.line_chart(labels, [("Dedup Rate", rate)], unit="%", w=520, h=190)))
    tn, td = sum(new), sum(dup)
    # 주 수는 타일 · 개요와 같은 span_weeks 다 — 주 열 (월요일 수) 로 세면 한 화면에 12주와 13주가 섞인다
    ins = ([(f"{span_weeks}주 합은 신규 {C.fmt(tn)}건 · 중복 차단 {C.fmt(td)}건이다.",
             [f"중복이 신규의 {td / tn:.0f}배다."] if tn else [])] if tn or td else [])
    return _section("sec-throughput", title, sub, q, body, ins)


def _duration(runs_all, today: date):
    title, sub = "Run Duration", "p10 에서 p90 밴드 · p50 선 · 주별 구성"
    q = "회차에 걸린 시간이 어떻게 분포하는지 보고 그 시간이 수집과 번역 · 게이트 · 배포로 어떻게 나뉘는지 확인한다."
    days = _days(OPS_EPOCH, today)
    by = _by_day(runs_all)

    def pq(d, q_):
        return _pctile([r["duration_sec"] for r in by.get(d, [])], q_)

    run_days = [d for d in days if d in by]
    p50 = [pq(d, .5) for d in run_days]
    band = ([pq(d, .1) for d in run_days], [pq(d, .9) for d in run_days])
    fails = []
    for i, d in enumerate(run_days):
        k = sum(1 for r in by[d] if r["error_count"] > 0)
        if k:
            fails.append((i, f"에러 회차 {k}회"))
    events = [(run_days.index(date.fromisoformat(d)), lab) for d, lab in EVENTS
              if date.fromisoformat(d) in run_days]
    weeks = _weeks(OPS_EPOCH, today)
    per = _by_week(runs_all)

    def avg(w, f):
        rs = per.get(w, [])
        return sum(f(r) for r in rs) / len(rs) if rs else 0

    fetch = [avg(w, lambda r: r.get("fetch_duration_sec") or 0) for w in weeks]        # NULL 이력은 0 (옛 13회)
    rest = [avg(w, lambda r: r["duration_sec"] - (r.get("fetch_duration_sec") or 0)) for w in weeks]
    body = _two(_fig("하루 p50 (초) · 밴드 p10 에서 p90 · ✕ 에러 회차",
                     C.line_chart([_wl(d) for d in run_days], [("p50", p50)], unit="초", band=band, fails=fails,
                                  events=events, w=520, h=190)),
                _fig("주별 회차당 평균 소요 구성 (초)",
                     C.stacked_columns([_wl(w) for w in weeks],
                                       [("수집 (fetch)", fetch, "s1"), ("번역 · 게이트 · 배포", rest, "s2")], unit="초")
                     + C.legend([("수집 (fetch)", "s1"), ("번역 · 게이트 · 배포", "s2")])))
    ins = []
    recent = runs_all[-RECENT_RUNS:]
    if recent:
        fv = [r["fetch_duration_sec"] for r in recent if r.get("fetch_duration_sec") is not None]
        ins.append((f"지난 {len(recent)}회 p50 은 {_pctile([r['duration_sec'] for r in recent], .5):.0f}초이고"
                    + (f" fetch 가 {_pctile(fv, .5):.0f}초다." if fv else " fetch 이력은 없다."), []))
        ins.append((f"1,000초를 넘긴 회차는 {C.fmt(sum(1 for r in runs_all if r['duration_sec'] > 1000))}회다.", []))
    return _section("sec-run-duration", title, sub, q, body, ins)


def _latency(latency, sources):
    title, sub = "Ingestion Latency", "발행 → 수집 지연 · 소스별 p50 · p95"
    q = ("기사가 발행된 뒤 우리가 받기까지 걸린 시간을 소스마다 본다. "
         "3시간 회차의 이론 하한은 1.5시간이다. "
         "07-14 이후에 수집한 것만 세고 30일 넘는 것은 뺐다.")
    by = defaultdict(list)
    for sid, h in latency:
        by[sid].append(h)
    # p95 하한 0.5 — 로그 축의 아래 끝 (charts.dumbbell_log 의 lo) 과 같아지면 눈금이 0 으로 나뉜다
    rows = sorted(((_display(sources, s), _pctile(v, .5), max(_pctile(v, .95), 0.5), len(v)) for s, v in by.items()),
                  key=lambda r: r[1])
    body = C.dumbbell_log(rows, w=560) if rows else NONE_YET
    ins = []
    if rows:
        ins.append((f"p50 이 가장 짧은 소스는 {rows[0][0]} {rows[0][1]:.1f}시간이고 "
                    f"가장 긴 소스는 {rows[-1][0]} {rows[-1][1]:.1f}시간이다.", []))
        ins.append((f"회차 간격 (3시간) 안에 드는 소스는 {sum(1 for r in rows if r[1] <= 3)}곳이다.", []))
    return _section("sec-ingestion-latency", title, sub, q, body, ins)


def _players(subjects):
    title, sub = "Coverage by Player", "기사 주체 기준 · 상위 10"
    total = sum(r["n"] for r in subjects)
    q = (f"누구 이야기가 가장 많이 들어오는지 본다. "
         f"기사의 주체 (subject) 로 귀속된 {C.fmt(total)}건만 세고 본문에 스친 언급 (mention) 은 뺀다. "
         "감독 · 임원은 축에서 뺀다.")
    named = sorted((r for r in subjects if r.get("ko_name")), key=lambda r: -r["n"])[:10]
    rows = [{"lab": r["ko_name"], "n": r["n"], "cls": "s1" if r["category"] == "squad" else "s2"} for r in named]
    unnamed = sum(r["n"] for r in subjects if not r.get("ko_name"))
    if unnamed:
        rows.append({"lab": UNNAMED, "n": unnamed, "cls": "dimbar"})
    body = ((C.hbars(rows, value="n", label="lab", unit="건", dim_label=UNNAMED) if rows else NONE_YET)
            + C.legend([("아스날 스쿼드", "s1"), ("외부 선수 (영입 링크)", "s2"), ("이름 미확정", "dimbar")]))
    ins = []
    if named:
        ins.append((f"{named[0]['ko_name']} 가 {C.fmt(named[0]['n'])}건으로 1위다.", []))
    if unnamed:
        ins.append((f"한국어 표기가 아직 안 붙은 후보 명단 인물이 주체 {C.fmt(unnamed)}건이다.", []))
    return _section("sec-coverage-by-player", title, sub, q, body, ins)


def _mix(weekly_mix, today: date):
    title, sub = "Credibility Mix · Stage Mix", "주별 구성 비율 · %"
    q = ("들어오는 기사의 공신력 등급 구성과 이적 단계 구성이 주마다 어떻게 바뀌는지 본다. "
         "칸의 숫자는 그 주 기사 가운데 그 등급 · 단계가 차지하는 비율이다.")
    weeks = _weeks(MIX_SINCE, today)
    tot, tier_tot, byline = defaultdict(int), defaultdict(int), defaultdict(int)
    tier, stage = defaultdict(int), defaultdict(int)
    for r in weekly_mix:
        w = _yw_monday(r["yw"])
        tot[w] += r["n"]
        byline[w] += r["n_byline"]
        key = _tier_key(r["tier"])
        if key in TIER_ORDER:
            tier[(key, w)] += r["n"]
            tier_tot[w] += r["n"]
        grp = next((g for g, keys in STAGE_GROUPS if r["stage"] in keys), "기타")
        stage[(grp, w)] += r["n"]

    def cells(keys, src, denom):
        return {(k, w): (_pct(src.get((k, w), 0), denom[w]) if denom.get(w) else None) for k in keys for w in weeks}

    groups = [g for g, _ in STAGE_GROUPS]
    labels = [_wl(w) for w in weeks]
    rate = [_pct(byline[w], tot[w]) if tot.get(w) else 0 for w in weeks]
    body = ('<div class="two">'
            + _fig("공신력 등급 (0 에서 4) · 주별 비율 %",
                   C.heatmap(list(TIER_ORDER), weeks, cells(TIER_ORDER, tier, tier_tot), w=500, unit="%",
                             show_text=True, rowlab=lambda t: TIER_KO[t], collab=_wl))
            + _fig("이적 단계 (루머 → 무산) · 주별 비율 %",
                   C.heatmap(groups, weeks, cells(groups, stage, tot), w=500, unit="%", show_text=True, collab=_wl))
            + _fig("기자 식별률 (바이라인이 잡힌 기사 비율 · %)",
                   C.line_chart(labels, [("식별률", rate)], unit="%", w=640, h=170,
                                annotate=(0, len(labels) - 1) if labels else ()))
            + "</div>")
    with_data = [w for w in weeks if tot.get(w)]
    ins = []
    if with_data:
        w4 = max((w for w in with_data if tier_tot.get(w)), key=lambda w: tier.get(("4", w), 0) / tier_tot[w],
                 default=None)
        if w4 is not None:
            ins.append((f"등급 4 비중이 가장 높은 주는 {_wl(w4)} ({_pct(tier.get(('4', w4), 0), tier_tot[w4])}%) 다.", []))
        rs = [r for w, r in zip(weeks, rate) if tot.get(w)]
        ins.append((f"기자 식별률은 {min(rs)}% 에서 {max(rs)}% 사이다.", []))
    return _section("sec-credibility-mix-stage-mix", title, sub, q, body, ins)


def _freshness(fresh_rows, sources):
    """절과 함께 최신 회차의 stale 수를 돌려준다 (타일 · SLO-5 가 같은 값을 쓴다)."""
    title, sub = "Source Freshness", "SLO-5 · 임계 대비 경과"
    q = "소스마다 마지막 수집이 임계 시간의 어디까지 왔는지 미터로 본다. 미터가 다 차면 수집이 끊겼다."
    latest_run = fresh_rows[-1]["run_id"] if fresh_rows else None
    latest = {r["source_id"]: r for r in fresh_rows if r["run_id"] == latest_run}
    history = defaultdict(list)
    for r in fresh_rows:                              # 부재 회차 없음 = 진짜 결측
        if r["age_hours"] is not None:
            history[r["source_id"]].append(float(r["age_hours"]))

    def ratio(r):
        return (r["age_hours"] or 0) / (r["threshold_hours"] or 1)

    rows = []
    for sid, r in sorted(latest.items(), key=lambda kv: -ratio(kv[1])):
        disp = C.E(_display(sources, sid))
        if r["age_hours"] is None:
            rows.append(f'<tr><td>{disp}</td><td>이력 없음</td><td>— / {r["threshold_hours"]:.0f}h</td>'
                        f'<td></td><td></td><td><span class="pill">이력 없음</span></td></tr>')
            continue
        pill = '<span class="pill bad">✕ 초과</span>' if r["stale"] else '<span class="pill ok">✓ 신선</span>'
        rows.append(f'<tr><td>{disp}</td><td>{r["last_fetched_at"]:%m-%d %H:%M}</td>'
                    f'<td>{r["age_hours"]:.1f}h / {r["threshold_hours"]:.0f}h</td>'
                    f'<td>{C.meter(r["age_hours"], r["threshold_hours"])}</td>'
                    f'<td>{C.sparkline(history[sid], w=84, h=18)}</td><td>{pill}</td></tr>')
    body = (('<table class="fresh"><thead><tr><th>소스</th><th>마지막 수집</th><th>경과 / 임계</th>'
             '<th>임계 대비</th><th>최근 12회</th><th>상태</th></tr></thead><tbody>'
             + "".join(rows) + "</tbody></table>") if rows else '<p class="q">이력 없음.</p>')
    ins = []
    thr = [r["threshold_hours"] for r in latest.values()]
    if thr and min(thr) != max(thr):
        ins.append((f"임계는 소스마다 다르다 ({min(thr):.0f}h 에서 {max(thr):.0f}h).", []))
    stale = [_display(sources, s) for s, r in latest.items() if r["stale"]]
    if stale:
        ins.append((f"임계를 넘은 소스는 {' · '.join(stale)} 다.", []))
    stale_count = sum(1 for r in latest.values() if r["stale"]) if latest else None
    return _section("sec-source-freshness", title, sub, q, body, ins), stale_count


def _review(high, unmatched):
    title, sub = "확인 대상", "재작성 잔존율 · 선수 추출 누락"
    q = ("사람이 볼 두 표다. "
         "재작성 잔존율이 임계를 넘은 기사는 원문 문장이 그대로 남았을 수 있다. "
         "영입 단계는 있는데 귀속 선수가 0명인 기사는 어느 선수 페이지에도 실리지 않아 재추출 대상이다.")
    ht = (('<table class="fresh"><thead><tr><th>기사</th><th>언론사</th><th class="num">잔존율</th></tr></thead><tbody>'
           + "".join(f'<tr><td><a class="alink" href="article/{r["content_hash"]}.html">{r["content_hash"][:8]}</a></td>'
                     f'<td>{C.E(r["outlet"] or "—")}</td><td class="num">{r["retention"]:.2f}</td></tr>' for r in high)
           + "</tbody></table>") if high else '<p class="q">임계값 초과 없음.</p>')
    ut = (('<table class="fresh"><thead><tr><th>날짜 (KST)</th><th>소스</th><th>제목</th></tr></thead><tbody>'
           + "".join(f'<tr><td>{C.E(r["date"])}</td><td>{C.E(r["source"])}</td><td>{C.E(r["title"])}</td></tr>'
                     for r in unmatched)
           + "</tbody></table>") if unmatched else '<p class="q">없음.</p>')
    body = _two(_fig(f"재작성 잔존율 확인 대상 ({len(high)}건)", ht), _fig(f"선수 추출 누락 ({len(unmatched)}건)", ut))
    return _section("sec-review-tables", title, sub, q, body, [])


# --- 조립 ---------------------------------------------------------------------

def _overview(articles_total: int, span_weeks: int, span_days: int):
    return [
        ("데이터 원천", "MariaDB (silver) 의 표 셋과 회차 끝 dbt 게이트의 테스트 결과.",
         [("pipeline_runs", "회차마다 한 행 · 신규 · 중복 · 에러 · 소요 시간 · 소스별 건수."),
          ("source_freshness", "회차 × 소스의 마지막 수집 시각과 임계."),
          ("articles", f"기사 {C.fmt(articles_total)}건 · 등급 · 이적 단계 · 발행 시각."),
          ("dbt 게이트", "unique · not_null 테스트 결과 (SLO-3 · 4).")]),
        ("기간", f"{OPS_EPOCH.isoformat()} 첫 라이브 실행부터 {span_weeks}주 ({span_days}일).", []),
        ("갱신", "3시간마다 회차가 끝날 때 다시 그린다.", []),
        ("시각", "UTC · KST 는 +9시간.", []),
    ]


def build_ops_view(snapshot: dict, sources: dict, anomaly_count: int, now: datetime, *,
                   gate: GateTally | None = None, unmatched=None) -> dict:
    """스냅샷 · 게이트 집계를 화면이 그릴 dict 로. 키가 비어도 절은 전부 그린다."""
    runs_all = snapshot.get("runs_all") or []
    recent = runs_all[-RECENT_RUNS:]
    today = now.date()
    span_days = (today - OPS_EPOCH).days + 1
    span_weeks = span_days // 7
    articles_total = snapshot.get("articles_total") or 0
    fresh_sec, stale_count = _freshness(snapshot.get("freshness") or [], sources)
    slo = _slo_rows(recent, stale_count, anomaly_count, gate, articles_total)
    sections = [
        _slo(slo, gate),
        _volume(runs_all, today, span_weeks),
        _coverage(runs_all, sources, today, span_weeks),
        _throughput(runs_all, today, span_weeks),
        _duration(runs_all, today),
        {"pair": [_latency(snapshot.get("latency") or [], sources),
                  _players(snapshot.get("player_subjects") or [])]},
        _mix(snapshot.get("weekly_mix") or [], today),
        fresh_sec,
        _review(snapshot.get("high_retention") or [], list(unmatched or [])),
    ]
    return {"generated_at": f"{now:%Y-%m-%d %H:%M} UTC",
            "overview": _overview(articles_total, span_weeks, span_days),
            "tiles": _tiles(runs_all, recent, stale_count, span_weeks),
            "slo": slo, "sections": sections, "missing_note": MISSING_NOTE}
