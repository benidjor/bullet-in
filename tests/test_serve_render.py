from pathlib import Path

STATIC = Path("src/bullet_in/serve/static")

def test_static_assets_exist_and_nonempty():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "data-theme" in css and "--bg" in css      # 테마 변수
    assert ".card" in css and ".side" in css
    assert "s-interest" in css and "s-personal" in css  # 신규 단계 점 색
    assert "data-outlet" in js and "data-tier" in js   # 카드 필터 계약
    assert "data-stage" in js                          # 단계 필터 계약
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

def test_index_renders_active_stage_filter():
    html = render_index([_row(), _row(content_hash="h2")], SOURCES, NOW)
    assert "tier 2" in html
    # 영입 단계 필터가 활성 (2-b): 체크박스 + data-group="stage"
    assert "영입 단계" in html
    assert 'data-group="stage"' in html
    assert 'data-value="official"' in html and 'data-value="rumour"' in html
    # 타 구단 자리 제거 + 단계 비활성 자리 제거 → disabled 없음
    assert "Manchester United" not in html
    assert "disabled" not in html


from bullet_in.serve.render import render_article, build_neighbors


def _decorated(row):
    from bullet_in.serve.render import _decorate
    return _decorate(row, SOURCES, NOW)


def test_decorate_sets_stage_fields():
    from bullet_in.serve.render import _decorate
    d = _decorate(_row(transfer_stage="medical"), SOURCES, NOW)
    assert d["_stage"] == "medical"
    assert d["_stage_badge"] is True
    assert d["_stage_label"] == "메디컬"
    assert d["_stage_class"] == "s-med"


def test_decorate_other_stage_no_badge():
    from bullet_in.serve.render import _decorate
    d = _decorate(_row(transfer_stage="other"), SOURCES, NOW)
    assert d["_stage"] == "other"
    assert d["_stage_badge"] is False


def test_detail_shows_summary3_body_and_origin():
    a = _row(content_hash="cur", summary3_ko="첫째 줄\n둘째 줄\n셋째 줄",
             body_ko="첫 문단입니다.\n둘째 문단입니다.", journalist="사미 목벨",
             url="https://src/article")
    nb = build_neighbors([a], 0, SOURCES, NOW)
    html = render_article(_decorated(a), nb, "cur", SOURCES, NOW)
    assert "3줄 요약" in html
    assert "첫째 줄" in html and "셋째 줄" in html
    assert "<li>첫째 줄</li>" in html
    assert "<p>첫 문단입니다.</p>" in html and "<p>둘째 문단입니다.</p>" in html
    assert "사미 목벨" in html
    assert 'href="https://src/article"' in html


def test_detail_neighbor_window_marks_current():
    arts = [_row(content_hash=f"h{i}", title_ko=f"기사{i}",
                 published_at=datetime(2026, 6, 29, 12 - i, 0)) for i in range(10)]
    ordered = sorted(arts, key=lambda x: x["published_at"], reverse=True)
    idx = 5
    nb = build_neighbors(ordered, idx, SOURCES, NOW)
    assert len(nb) == 5
    cur = [n for n in nb if n["_is_current"]]
    assert len(cur) == 1 and cur[0]["content_hash"] == ordered[idx]["content_hash"]
    html = render_article(_decorated(ordered[idx]), nb, ordered[idx]["content_hash"], SOURCES, NOW)
    assert html.count("지금") == 1


def test_detail_small_corpus_shows_all():
    arts = [_row(content_hash=f"h{i}", title_ko=f"기사{i}") for i in range(3)]
    nb = build_neighbors(arts, 1, SOURCES, NOW)
    assert len(nb) == 3


from bullet_in.serve.render import write_site


def test_write_site_creates_index_articles_and_assets(tmp_path):
    arts = [_row(content_hash=f"h{i}", title_ko=f"기사{i}",
                 published_at=datetime(2026, 6, 29, 12 - i, 0)) for i in range(3)]
    write_site(arts, SOURCES, tmp_path, now=NOW)
    assert (tmp_path / "index.html").exists()
    assert (tmp_path / "style.css").exists()
    assert (tmp_path / "app.js").exists()
    for i in range(3):
        assert (tmp_path / "article" / f"h{i}.html").exists()
    # 상세에서 정적 자산은 ../ 로 참조
    detail = (tmp_path / "article" / "h0.html").read_text(encoding="utf-8")
    assert 'href="../style.css"' in detail and 'src="../app.js"' in detail
    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert 'href="style.css"' in index
    # 상세 사이드바에 실제 패싯(BBC Sport 언론사) 카운트가 반영됨 — 빈 패싯이 아닌 증거
    assert 'data-value="BBC Sport"' in detail


# ── 보안 픽스: image_url 인라인 CSS url() 탈출 · javascript: 스킴 차단 ──

def test_index_rejects_malicious_image_url():
    bad = "x'); } body{display:none} a{background:url('http://evil/leak"
    html = render_index([_row(image_url=bad)], SOURCES, NOW)
    assert "evil" not in html
    assert "PHOTO · 16:9" in html  # falls back to placeholder

def test_index_keeps_valid_image_url():
    html = render_index([_row(image_url="https://picsum.photos/seed/1/800/450")], SOURCES, NOW)
    assert "https://picsum.photos/seed/1/800/450" in html

def test_detail_rejects_javascript_origin_url():
    a = _row(url="javascript:alert(1)")
    nb = build_neighbors([a], 0, SOURCES, NOW)
    html = render_article(_decorated(a), nb, "h1", SOURCES, NOW)
    assert "javascript:alert(1)" not in html

def test_detail_keeps_valid_origin_url():
    a = _row(url="https://src/article")
    nb = build_neighbors([a], 0, SOURCES, NOW)
    html = render_article(_decorated(a), nb, "h1", SOURCES, NOW)
    assert 'href="https://src/article"' in html


def test_index_shows_stage_badge_and_data_attr():
    html = render_index([_row(transfer_stage="negotiating")], SOURCES, NOW)
    assert 'data-stage="negotiating"' in html
    assert "협상 중" in html
    assert "stagebadge" in html


def test_index_other_stage_has_data_attr_but_no_badge():
    html = render_index([_row(transfer_stage="other")], SOURCES, NOW)
    assert 'data-stage="other"' in html   # 속성은 있음 (필터로 제외됨)
    assert "stagebadge" not in html        # 배지는 없음


def test_detail_shows_stage_badge():
    a = _row(content_hash="cur", transfer_stage="medical")
    nb = build_neighbors([a], 0, SOURCES, NOW)
    html = render_article(_decorated(a), nb, "cur", SOURCES, NOW)
    assert "메디컬" in html and "stagebadge" in html


import re as _re

def test_index_hides_offmission_card_by_default():
    tr = _row(content_hash="t", transfer_stage="rumour")
    ot = _row(content_hash="o", transfer_stage="other")
    html = render_index([tr, ot], SOURCES, NOW)
    o_tag = _re.search(r'<a class="card"[^>]*href="article/o\.html"', html).group(0)
    t_tag = _re.search(r'<a class="card"[^>]*href="article/t\.html"', html).group(0)
    assert "display:none" in o_tag       # off-mission(other) 카드만 숨김
    assert "display:none" not in t_tag   # 이적 카드(rumour)는 노출

def test_sidebar_has_other_bucket_checkbox():
    html = render_index([_row(transfer_stage="other")], SOURCES, NOW)
    assert 'data-group="bucket"' in html
    assert 'data-value="other"' in html
    assert "기타" in html


def test_app_js_has_other_bucket_toggle_contract():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "data-group=bucket" in js   # '기타' 토글 셀렉터
    assert "showOther" in js            # other 노출 분기


def test_index_footer_links_to_ops_page():
    html = render_index([_row()], SOURCES, NOW)
    assert '<a href="ops.html">수집 현황</a>' in html


from bullet_in.serve.render import interleave_body, _decorate as _dec, render_article as _ra

def test_interleave_every_two_paragraphs():
    blocks = interleave_body(["p1", "p2", "p3", "p4"], ["i1", "i2"])
    assert [b["type"] for b in blocks] == ["p", "p", "img", "p", "p", "img"]
    assert blocks[2]["url"] == "i1"

def test_interleave_images_exhausted_then_paragraphs_only():
    blocks = interleave_body(["p1", "p2", "p3", "p4", "p5", "p6"], ["i1"])
    assert [b["type"] for b in blocks].count("img") == 1

def test_interleave_surplus_images_dropped():
    blocks = interleave_body(["p1", "p2"], ["i1", "i2", "i3"])
    assert [b["type"] for b in blocks].count("img") == 1

def test_interleave_empty_inputs():
    assert interleave_body([], ["i1"]) == []
    assert [b["type"] for b in interleave_body(["p1"], [])] == ["p"]

def test_decorate_dedups_hero_from_inline_images():
    row = _row(image_url="https://img/x.jpg",
               images_json='["https://img/x.jpg?w=1200", "https://img/y.jpg"]')
    a = _dec(row, SOURCES, NOW)
    assert a["_images"] == ["https://img/y.jpg"]

def test_decorate_promotes_first_inline_to_hero():
    row = _row(image_url=None,
               images_json='["https://img/a.jpg", "https://img/b.jpg"]')
    a = _dec(row, SOURCES, NOW)
    assert a["image_url"] == "https://img/a.jpg"
    assert a["_images"] == ["https://img/b.jpg"]

def test_decorate_rejects_invalid_inline_urls_and_bad_json():
    row = _row(image_url="https://img/hero.jpg",
               images_json='["javascript:alert(1)", "https://img/ok.jpg"]')
    assert _dec(row, SOURCES, NOW)["_images"] == ["https://img/ok.jpg"]
    row2 = _row(image_url="https://img/hero.jpg", images_json="not json")
    assert _dec(row2, SOURCES, NOW)["_images"] == []

def test_detail_interleaves_inline_images_with_defenses():
    row = _row(body_ko="""문단1
문단2
문단3""", image_url="https://img/hero.jpg",
               images_json='["https://img/in1.jpg"]')
    a = _dec(row, SOURCES, NOW)
    html = _ra(a, [], "h1", SOURCES, NOW)
    assert '<img src="https://img/in1.jpg"' in html
    assert 'loading="lazy"' in html and 'referrerpolicy="no-referrer"' in html
    assert "onerror" in html
    assert html.index("문단2") < html.index("in1.jpg") < html.index("문단3")

def test_css_has_inline_image_style():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert ".body figure img" in css

def test_interleave_classifies_heading_and_quote_blocks():
    blocks = interleave_body(["### 소제목", "> 인용문", "본문"], [])
    assert [b["type"] for b in blocks] == ["h3", "quote", "p"]
    assert blocks[0]["text"] == "소제목"
    assert blocks[1]["text"] == "인용문"

def test_md_bold_escapes_html_before_markup():
    from bullet_in.serve.render import _md_bold
    out = str(_md_bold("**bold** <script>x</script>"))
    assert "<strong>bold</strong>" in out
    assert "<script>" not in out and "&lt;script&gt;" in out

def test_detail_renders_markdown_lite_blocks_and_bold():
    row = _row(body_ko="### 전술 변화\n> 우리는 준비돼 있다\n**알바레스**가 왔다\n둘째 문단",
               image_url="https://img/hero.jpg")
    a = _dec(row, SOURCES, NOW)
    html = _ra(a, [], "h1", SOURCES, NOW)
    assert "<h3>전술 변화</h3>" in html
    assert "<blockquote>우리는 준비돼 있다</blockquote>" in html
    assert "<strong>알바레스</strong>가 왔다" in html

def test_detail_shows_byline_under_title():
    row = _row(journalist="Miguel Delaney", body_ko="본문")
    a = _dec(row, SOURCES, NOW)
    html = _ra(a, [], "h1", SOURCES, NOW)
    assert '<p class="byline">Miguel Delaney</p>' in html
    assert html.index('class="title"') < html.index('class="byline"')

def test_detail_no_byline_when_journalist_missing():
    row = _row(body_ko="본문")
    a = _dec(row, SOURCES, NOW)
    assert "byline" not in _ra(a, [], "h1", SOURCES, NOW)

def test_decorate_resolves_byline_to_canonical_english():
    row = _row(journalist="온스테인", body_ko="본문")
    a = _dec(row, SOURCES, NOW,
             directory={"온스테인": {"name": "David Ornstein", "outlet": "The Athletic"}})
    assert a["_byline"] == "David Ornstein (The Athletic)"
    assert a["_journalist"] == "David Ornstein"

def test_decorate_byline_passthrough_when_unregistered():
    a = _dec(_row(journalist="Hugo Guillemet", body_ko="본문"), SOURCES, NOW)
    assert a["_byline"] == "Hugo Guillemet"
    assert a["_journalist"] == "Hugo Guillemet"

def test_index_card_has_journalist_data_attr():
    html = render_index([_row(journalist="온스테인")], SOURCES, NOW,
                        directory={"온스테인": {"name": "David Ornstein", "outlet": None}})
    assert 'data-journalist="David Ornstein"' in html   # 체크박스 값과 같은 정규화 키

def test_index_card_journalist_attr_empty_when_missing():
    html = render_index([_row()], SOURCES, NOW)
    assert 'data-journalist=""' in html
