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
        ("기간", f"{span}.", []),
        ("갱신", "화면은 회차마다 (3시간) 다시 그리지만 GA4 내보내기가 다음 날 오전에 도착하므로 숫자는 하루에 한 번 바뀐다.", []),
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
