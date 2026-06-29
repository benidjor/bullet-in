from pathlib import Path

STATIC = Path("src/bullet_in/serve/static")

def test_static_assets_exist_and_nonempty():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "data-theme" in css and "--bg" in css      # 테마 변수
    assert ".card" in css and ".side" in css
    assert "data-outlet" in js and "data-tier" in js   # 카드 필터 계약
    assert "localStorage" in js                        # 테마 영속


from datetime import datetime
from bullet_in.serve.render import render_index

NOW = datetime(2026, 6, 29, 12, 0, 0)
SOURCES = {"bbc_sport": {"display_name": "BBC Sport"}}

def _row(**kw):
    base = dict(content_hash="h1", url="https://x/1", source_id="bbc_sport",
                title_original="Original", title_ko="한국어 제목", summary_ko="한 줄 요약",
                tier=2, confidence_score=0.5, image_url=None, outlet=None,
                team="arsenal", published_at=datetime(2026, 6, 29, 10, 0, 0))
    base.update(kw); return base

def test_index_card_has_data_attrs_and_link():
    html = render_index([_row()], SOURCES, NOW)
    assert 'href="article/h1.html"' in html
    assert 'data-outlet="BBC Sport"' in html   # outlet NULL → display_name 폴백
    assert 'data-tier="2"' in html
    assert 'data-published="2026-06-29T10:00:00"' in html
    assert 'data-confidence="0.5"' in html

def test_index_prefers_korean_title_and_escapes():
    html = render_index([_row(title_ko=None, title_original="A & B <script>x</script>")], SOURCES, NOW)
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html
    html2 = render_index([_row()], SOURCES, NOW)
    assert "한국어 제목" in html2

def test_index_placeholder_when_no_image():
    html = render_index([_row(image_url=None)], SOURCES, NOW)
    assert "PHOTO · 16:9" in html
    html2 = render_index([_row(image_url="https://img/x.jpg")], SOURCES, NOW)
    assert "https://img/x.jpg" in html2

def test_index_sorts_latest_first():
    old = _row(content_hash="old", title_ko="옛날", published_at=datetime(2026, 6, 28, 0, 0))
    new = _row(content_hash="new", title_ko="최신", published_at=datetime(2026, 6, 29, 11, 0))
    html = render_index([old, new], SOURCES, NOW)
    assert html.index("최신") < html.index("옛날")

def test_index_renders_facet_counts_and_disabled_stage():
    html = render_index([_row(), _row(content_hash="h2")], SOURCES, NOW)
    assert "tier 2" in html
    # 영입 단계는 비활성 자리(2-b)
    assert "영입 단계" in html and html.count("disabled") >= 4
