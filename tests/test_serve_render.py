import re
from pathlib import Path

STATIC = Path("src/bullet_in/serve/static")

def test_static_assets_exist_and_nonempty():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "data-theme" in css and "--bg" in css      # 테마 변수
    assert ".card" in css and ".side" in css
    assert "s-interest" in css and "s-personal" in css  # 신규 단계 점 색
    assert ".morebtn" in css                           # 기자 더보기 버튼
    # .morebtn 은 display:block 을 선언해 브라우저 기본 [hidden]{display:none} 을
    # 덮어쓴다 (작성자 스타일 > UA 스타일, 특정도 무관). JS 가 hidden 속성을
    # 정확히 설정해도 화면에서 숨지 않는 결함 — 작성자 스타일 안에서 다시
    # [hidden]{display:none} 을 명시해야 한다.
    # 한계: pytest 는 브라우저를 띄우지 않으므로 이 규칙이 "존재"하는지만
    # 검사할 수 있다 — 계산된 display 값 · 실제 화면 표시 여부는 검증하지
    # 못하며, 그건 실브라우저(Playwright)로만 확인 가능하다.
    assert re.search(r"\.morebtn\[hidden\]\s*\{[^}]*display\s*:\s*none", css), (
        ".morebtn[hidden]{display:none} 규칙이 없음 — 더보기 버튼이 hidden "
        "속성으로 숨지 않는 결함"
    )
    assert "data-outlet" in js and "data-tier" in js   # 카드 필터 계약
    assert "data-stage" in js                          # 단계 필터 계약
    assert "localStorage" in js                        # 테마 영속
    assert "journalist" in js                          # 기자 필터 계약
    assert "URLSearchParams" in js                     # 필터 상태 URL 직렬화
    assert "replaceState" in js                        # 인덱스 URL 동기화
    assert "morestage" in js and "facetgroup" in js    # tier 단계 전개 계약
    assert "jmore" not in js                           # 옛 이분법 토글 제거


from datetime import datetime
from bullet_in.serve.render import render_index

NOW = datetime(2026, 6, 29, 12, 0, 0)
SOURCES = {"bbc_sport": {"display_name": "BBC Sport", "serving": "full"}}

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
    assert "Tier 2" in html
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


def test_decorate_agreed_stage_badge():
    from bullet_in.serve.render import _decorate
    d = _decorate(_row(transfer_stage="agreed"), SOURCES, NOW)
    assert d["_stage_badge"] is True
    assert d["_stage_label"] == "이적 합의"
    assert d["_stage_class"] == "s-agree"


def test_sidebar_and_card_render_agreed():
    html = render_index([_row(transfer_stage="agreed")], SOURCES, NOW)
    assert 'data-value="agreed"' in html      # 사이드바 필터 체크박스
    assert "이적 합의" in html                  # 라벨 노출


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


def test_build_neighbors_resolves_journalist_via_directory():
    # _decorate 가 호출 경로 (render_index/write_site vs build_neighbors) 와
    # 무관하게 동일한 정규화 결과를 내야 한다 — 이웃 목록도 카드 · 상세와 같은 정식명을 가져야 함.
    arts = [_row(content_hash=f"h{i}", title_ko=f"기사{i}", journalist="온스테인")
            for i in range(3)]
    nb = build_neighbors(arts, 1, SOURCES, NOW,
                         directory={"온스테인": {"name": "David Ornstein", "outlet": "The Athletic"}})
    assert all(n["_journalist"] == "David Ornstein" for n in nb)


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


def _journalist_facet_section(html: str) -> str:
    """사이드바 '기자' 견출부터 다음 <h4> 전까지 — 기자 facet 만 스코프.
    언론사 facet 도 같은 .morestage/.morebtn 마크업을 쓰므로 전체 html 로 보면 오검출된다."""
    start = html.index("<h4>기자</h4>")
    end = html.index("<h4>", start + 1)
    return html[start:end]


def test_sidebar_omits_more_toggle_when_all_registered():
    directory = {"온스테인": {"name": "David Ornstein", "outlet": "The Athletic"}}

    class _Reg:
        outlets = {}
        journalists = {"온스테인": 1.0, "david ornstein": 1.0}

    # 등재 기자만 있고 tier 가 초기 노출 상한(1.5) 이내 → 미등재/더보기 단계가 없어야 함
    html = render_index([_row(journalist="온스테인")], SOURCES, NOW,
                        directory=directory, registry=_Reg())
    section = _journalist_facet_section(html)
    assert "morestage" not in section
    assert "morebtn" not in section


def test_journalist_facet_data_value_matches_card_data_journalist():
    """app.js:75 의 journalists.includes(card.dataset.journalist) 는 문자열 동등 비교다.
    facet 체크박스의 data-value 가 표시 라벨(괄호 소속 포함)이 아니라 카드의
    data-journalist 와 같은 정규화 이름이어야 필터가 실제로 걸린다."""
    rows = [_row(content_hash="h1", journalist="온스테인"),
            _row(content_hash="h2", journalist="Hugo Guillemet")]
    directory = {"온스테인": {"name": "David Ornstein", "outlet": "The Athletic"}}
    html = render_index(rows, SOURCES, NOW, directory=directory)

    card_values = set(_re.findall(r'data-journalist="([^"]*)"', html))
    card_values.discard("")  # 기자 미상 카드는 빈 문자열

    section = _journalist_facet_section(html)
    facet_values = set(_re.findall(r'data-group="journalist" data-value="([^"]*)"', section))

    assert card_values == {"David Ornstein", "Hugo Guillemet"}  # 픽스처가 실제로 기자 카드를 만들었는지 확인
    assert card_values == facet_values


def test_sidebar_renders_tier_heading_and_initial_only():
    rows = [_row(content_hash="h1", journalist="온스테인", outlet="The Athletic", tier=1),
            _row(content_hash="h2", journalist="Kaya Kaynak", outlet="The Sun", tier=4),
            _row(content_hash="h3", journalist="Kaya Kaynak", outlet="afcstuff", tier=4)]
    directory = {"온스테인": {"name": "David Ornstein", "outlet": "The Athletic"}}

    class _Reg:
        outlets = {"the athletic": 1.0, "the sun": 4.0}
        journalists = {"온스테인": 1.0, "david ornstein": 1.0}

    html = render_index(rows, SOURCES, NOW, directory=directory, registry=_Reg())
    assert "Tier 1 · 공신력 최상" in html
    assert 'data-group="outlet" data-value="The Athletic"' in html
    # 미등재 기자도 기사 tier(4) 그룹으로 분류 — 접힌 단계 안에 있고 버튼이 예고한다
    assert "더보기 · Tier 4" in html
    assert 'class="morestage"' in html

def test_unregistered_journalist_grouped_by_row_tier():
    """비전담 (미등재) 기자는 '이름 (소속)' 라벨 + 기사 tier 그룹으로 분류된다
    (미등재 꼬리로 흘리지 않음 — 소스 tier = 비전담 기준선)."""
    sources = {"bbc_sport": {"display_name": "BBC Sport", "outlet": "BBC"}}
    html = render_index([_row(journalist="Alex Howell", tier=1.5)], sources, NOW)
    section = _journalist_facet_section(html)
    assert "Tier 1.5 · 공신력 상" in section
    assert 'data-group="journalist" data-value="Alex Howell"' in section
    assert "Alex Howell (BBC)" in section
    assert "미등재" not in section


def test_org_byline_folds_to_outlet_name():
    """조직 바이라인 (BBC Sport 등) 은 outlet 정식명으로 접는다 — 칩 · 카드 키 모두 'BBC'."""
    sources = {"bbc_sport": {"display_name": "BBC Sport", "outlet": "BBC"}}
    html = render_index([_row(journalist="BBC Sport", tier=1.5)], sources, NOW)
    assert 'data-journalist="BBC"' in html
    section = _journalist_facet_section(html)
    assert 'data-group="journalist" data-value="BBC"' in section
    assert "BBC Sport" not in section          # 접힌 뒤 원문 표기는 남지 않는다
    assert "BBC (BBC)" not in html             # name == outlet → 괄호 생략


def test_index_card_data_tier_keeps_one_point_five():
    html = render_index([_row(tier=1.5)], SOURCES, NOW)
    assert 'data-tier="1.5"' in html

def test_sidebar_tier_facet_lists_one_point_five():
    html = render_index([_row(tier=1.5)], SOURCES, NOW)
    assert 'data-group="tier" data-value="1.5"' in html
    assert "Tier 1.5" in html

def test_layout_emits_no_whitespace_before_doctype():
    """매크로 정의를 {% endmacro %} 로 닫으면 개행이 새어나와 doctype 앞에 붙는다.
    눈에 안 띄는 회귀라 고정한다 — {% endmacro -%} 를 쓸 것."""
    html = render_index([_row()], SOURCES, NOW)
    assert html.startswith("<!doctype html>")

def test_decorate_body_images_false_drops_inline_but_keeps_thumbnail():
    srcs = {"bbc_sport": {"display_name": "BBC Sport", "body_images": False}}
    # 히어로 (썸네일) 유지 + 인라인만 제거
    row = _row(image_url="https://img/hero.jpg",
               images_json='["https://img/in1.jpg", "https://img/in2.jpg"]')
    a = _dec(row, srcs, NOW)
    assert a["image_url"] == "https://img/hero.jpg"
    assert a["_images"] == []
    # og:image 부재 → 인라인 1번의 썸네일 승격은 유지, 나머지 인라인은 제거
    row2 = _row(image_url=None, images_json='["https://img/a.jpg", "https://img/b.jpg"]')
    a2 = _dec(row2, srcs, NOW)
    assert a2["image_url"] == "https://img/a.jpg"
    assert a2["_images"] == []

def test_index_card_carries_content_hash_for_view_sort():
    html = render_index([_row()], SOURCES, NOW)
    assert 'data-hash="h1"' in html

def test_layout_has_header_sort_select_with_views():
    from pathlib import Path
    tpl = (Path("src/bullet_in/serve/templates/_layout.html.j2")).read_text(encoding="utf-8")
    # 정렬은 헤더 (테마 토글 옆) 셀렉트 — 인덱스에서만 렌더, 사이드바 라디오는 제거
    assert 'id="sortSel"' in tpl and 'value="views"' in tpl and "조회순" in tpl
    assert tpl.index('id="sortSel"') < tpl.index('id="themeBtn"')
    assert 'name="sort"' not in tpl


from bullet_in.serve.render import _sorted_latest

def test_sorted_latest_ties_broken_by_fetched_at():
    same = datetime(2026, 7, 19, 13, 37, 2)
    rows = [
        {"content_hash": "sky", "published_at": same,
         "fetched_at": datetime(2026, 7, 19, 13, 36, 28)},
        {"content_hash": "fmk", "published_at": same,
         "fetched_at": datetime(2026, 7, 19, 13, 36, 36)},
    ]
    assert [r["content_hash"] for r in _sorted_latest(rows)] == ["fmk", "sky"]

def test_sorted_latest_published_still_primary():
    rows = [
        {"content_hash": "old", "published_at": datetime(2026, 7, 18, 9, 0),
         "fetched_at": datetime(2026, 7, 19, 23, 0)},
        {"content_hash": "new", "published_at": datetime(2026, 7, 19, 9, 0),
         "fetched_at": datetime(2026, 7, 19, 1, 0)},
    ]
    assert [r["content_hash"] for r in _sorted_latest(rows)] == ["new", "old"]


from bullet_in.serve.render import _sort_ts, _fmt_day_only

def test_sort_ts_day_interpolates_by_fetched_within_day():
    row = {"published_at": datetime(2026, 7, 19),        # day 00:00
           "fetched_at": datetime(2026, 7, 19, 11, 2),
           "published_precision": "day"}
    assert _sort_ts(row)[0] == datetime(2026, 7, 19, 11, 2)

def test_sort_ts_day_clamps_late_fetch_into_published_day():
    row = {"published_at": datetime(2026, 7, 19),
           "fetched_at": datetime(2026, 7, 22, 9, 0),    # 수일 뒤 수집
           "published_precision": "day"}
    assert _sort_ts(row)[0] == datetime(2026, 7, 19, 23, 59, 59)

def test_sort_ts_time_precision_passthrough():
    row = {"published_at": datetime(2026, 7, 19, 14, 30),
           "fetched_at": datetime(2026, 7, 19, 15, 0),
           "published_precision": "time"}
    assert _sort_ts(row)[0] == datetime(2026, 7, 19, 14, 30)

def test_sort_ts_null_precision_passthrough():
    row = {"published_at": datetime(2026, 7, 19, 14, 30),
           "fetched_at": datetime(2026, 7, 19, 15, 0)}
    assert _sort_ts(row)[0] == datetime(2026, 7, 19, 14, 30)

def test_fmt_day_only_current_year_omits_year():
    now = datetime(2026, 7, 20)
    assert _fmt_day_only(datetime(2026, 7, 19), now) == "7월 19일"
    assert _fmt_day_only(datetime(2025, 7, 19), now) == "2025년 7월 19일"

def test_decorate_day_precision_shows_date_not_relative():
    from bullet_in.serve.render import _decorate
    now = datetime(2026, 7, 20, 12, 0)
    row = {"published_at": datetime(2026, 7, 19),
           "fetched_at": datetime(2026, 7, 19, 11, 2),
           "published_precision": "day", "tier": 2}
    d = _decorate(row, {}, now)
    assert d["_when"] == "7월 19일"                       # "N시간 전" 아님
    assert d["_published_iso"] == "2026-07-19T11:02:00"   # 유효 시각 (보간) — data-published 계약


# ---- SP-B 차등 서빙: serving_mode · excerpt_paras (spec §2.3) ----
from bullet_in.serve.render import serving_mode, excerpt_paras

def test_serving_mode_reads_config_and_defaults_to_excerpt():
    sources = {"bbc_sport": {"serving": "excerpt"}, "x_afcstuff": {"serving": "full"}}
    assert serving_mode("x_afcstuff", sources) == "full"
    assert serving_mode("bbc_sport", sources) == "excerpt"
    assert serving_mode("new_source", sources) == "excerpt"   # 미지정 소스 → 안전 기본값
    assert serving_mode(None, sources) == "excerpt"

def test_serving_mode_invalid_value_falls_back_to_excerpt():
    assert serving_mode("s", {"s": {"serving": "banana"}}) == "excerpt"

def test_excerpt_paras_takes_at_most_two_paragraphs():
    paras = ["짧은 첫 문단.", "둘째 문단.", "셋째 문단."]
    assert excerpt_paras(paras) == ["짧은 첫 문단.", "둘째 문단."]

def test_excerpt_paras_stops_when_first_paragraph_reaches_limit():
    long_first = "가" * 300
    assert excerpt_paras([long_first, "둘째"]) == [long_first]

def test_excerpt_paras_empty_input():
    assert excerpt_paras([]) == []


def test_detail_excerpt_mode_cuts_body_and_shows_notice():
    src = {"bbc_sport": {"display_name": "BBC Sport", "serving": "excerpt"}}
    row = _row(body_ko="첫 문단." + "가" * 300 + "\n둘째 문단.\n셋째 문단.")
    html = _ra(_dec(row, src, NOW), [], "h1", src, NOW)
    assert "셋째 문단" not in html                    # 발췌 범위 밖 본문 제외
    assert 'class="excerpt-note"' in html
    assert "원문 전체 보기" in html

def test_detail_full_mode_keeps_whole_body_without_notice():
    row = _row(body_ko="첫 문단.\n둘째 문단.\n셋째 문단.")
    html = _ra(_dec(row, SOURCES, NOW), [], "h1", SOURCES, NOW)
    assert "셋째 문단" in html
    assert "excerpt-note" not in html

def test_detail_excerpt_mode_drops_inline_images():
    src = {"bbc_sport": {"serving": "excerpt"}}
    row = _row(body_ko="문단1\n문단2\n문단3\n문단4",
               image_url="https://img/hero.jpg",
               images_json='["https://img/a.jpg", "https://img/b.jpg"]')
    html = _ra(_dec(row, src, NOW), [], "h1", src, NOW)
    assert "img/a.jpg" not in html and "img/b.jpg" not in html
