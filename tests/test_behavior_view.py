"""행동 지표 페이지 — 표본 수가 늘 함께 보이는지.

픽스처의 값은 2026-09-03 운영 집계에서 그대로 가져왔다 (지어낸 수가 아니다).
"""
import json

from bullet_in.serve.render import render_behavior, write_behavior

METRICS = {
    "generated_at": "2026-09-03T03:40:00+00:00",
    "totals": {"all": 577, "launch_day": 306, "counted": 271},
    "dates": {"from": "2026-08-24", "to": "2026-09-01"},
    "axes": {
        "card_outlet": [
            {"value": "The Athletic", "n_clicks": 31,
             "n_articles": 0, "per_article": None},
            {"value": "BBC", "n_clicks": 25, "n_articles": 0, "per_article": None},
        ],
        "card_stage": [
            {"value": "negotiating", "n_clicks": 59,
             "n_articles": 267, "per_article": 0.22},
        ],
        "card_tier": [
            {"value": "4", "n_clicks": 67, "n_articles": 448, "per_article": 0.15},
            {"value": "2", "n_clicks": 51, "n_articles": 130, "per_article": 0.39},
            {"value": "(없음)", "n_clicks": 52,
             "n_articles": 0, "per_article": None},
        ],
        "card_surface": [
            {"value": "item", "n_clicks": 207, "n_articles": 0,
             "per_article": None},
        ],
    },
}


def test_클릭_수_곁에_표본_수가_함께_나온다():
    html = render_behavior(METRICS)
    assert "67" in html and "448" in html and "0.15" in html


def test_공개일을_뺐다는_사실을_적는다():
    html = render_behavior(METRICS)
    assert "306" in html and "271" in html


def test_없음_칸이_무엇인지_적는다():
    # 실측 52 = 주요 소식 24 + 선수 카드 26 + 타임라인 제목 2 — 등급 없는 기사가 아니다.
    html = render_behavior(METRICS)
    assert "「(없음)」 은" in html and "선수 카드" in html and "주요 소식" in html


def test_기사_수가_0이면_기사당_값을_안_적는다():
    # 매체 축은 분모가 없다. 0으로 나눈 값을 지어내면 안 된다.
    html = render_behavior(METRICS)
    assert "The Athletic" in html
    assert "0.00" not in html


def test_네_축이_모두_그려진다():
    html = render_behavior(METRICS)
    for title in ("매체", "이적 단계", "기자 등급", "화면"):
        assert title in html


def test_등급_축에는_기사당_설명이_붙는다():
    # 클릭 수만 보면 결론이 뒤집히는 축이라 무엇으로 정렬했는지 화면에 적어야 한다.
    html = render_behavior(METRICS)
    assert "기사당" in html


def test_검색엔진에_안_실리게_막는다():
    assert 'name="robots"' in render_behavior(METRICS)


def test_집계_파일이_없으면_페이지를_안_그린다(tmp_path):
    assert write_behavior(tmp_path / "없다.json", tmp_path) is False
    assert not (tmp_path / "behavior.html").exists()


def test_집계_파일이_있으면_페이지를_그린다(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps(METRICS, ensure_ascii=False), encoding="utf-8")
    assert write_behavior(p, tmp_path) is True
    assert "The Athletic" in (tmp_path / "behavior.html").read_text(encoding="utf-8")


def test_집계_시각을_한국_시간으로_보여_준다():
    # 저장은 UTC 이지만 읽는 사람은 한국에 있다.
    html = render_behavior(METRICS)
    assert "2026-09-03 12:40 KST" in html
    assert "2026-09-03T03:40:00+00:00" not in html
