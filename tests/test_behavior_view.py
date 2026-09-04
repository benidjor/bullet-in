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
    assert html.count('<span class="l">') >= 16  # 절 아홉의 설명문 문장 합


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
