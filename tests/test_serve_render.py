import re
from pathlib import Path

STATIC = Path("src/bullet_in/serve/static")

def test_static_assets_exist_and_nonempty():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "data-theme" in css and "--paper" in css   # 테마 변수
    assert ".item" in css and ".side" in css
    assert ".stage.green" in css and ".stage.filled" in css  # 단계 배지 tone
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
    # 단계 필터의 방향 게이트와 무산 예외 (단계 재정의 스펙 §8) — render.in_stage_filter
    # 와 규칙이 갈라지면 계수와 목록이 어긋난다
    assert "data-dir" in js
    assert "d.stage === 'collapsed' || d.dir === 'in' || d.dir === 'out'" in js
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


def test_index_card_carries_direction_attr():
    # 단계 필터의 in · out 한정 판정 키 (단계 재정의 스펙 §8) — app.js 가 data-dir 로 읽는다
    html = render_index([_row(transfer_stage="agreed", transfer_direction="in")], SOURCES, NOW)
    assert 'data-dir="in"' in html
    html2 = render_index([_row(transfer_stage="agreed")], SOURCES, NOW)   # 방향 미태깅
    assert 'data-dir=""' in html2

def test_index_prefers_korean_title_and_escapes():
    html = render_index([_row(title_ko=None, title_original="A & B <script>x</script>")], SOURCES, NOW)
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html
    html2 = render_index([_row()], SOURCES, NOW)
    assert "한국어 제목" in html2

def test_index_placeholder_when_no_image():
    # 목록 항목엔 썸네일 자리표시가 없다 (spec2 §8) — 상위 3등급 리드만 밴드에 이미지
    html = render_index([_row(image_url=None)], SOURCES, NOW)
    assert "PHOTO" not in html
    html2 = render_index([_row(tier=1, image_url="https://img/x.jpg")], SOURCES, NOW)
    assert "https://img/x.jpg" in html2

def test_index_sorts_latest_first():
    old = _row(content_hash="old", title_ko="옛날", published_at=datetime(2026, 6, 28, 0, 0))
    new = _row(content_hash="new", title_ko="최신", published_at=datetime(2026, 6, 29, 11, 0))
    html = render_index([old, new], SOURCES, NOW)
    assert html.index("최신") < html.index("옛날")

def test_index_daygroup_carries_date_attr():
    # 주 단위 더보기 (spec §4) 의 JS 계약 — 날짜 그룹이 data-date 를 가진다
    html = render_index([_row()], SOURCES, NOW)
    assert 'class="daygroup' in html
    assert 'data-date="2026-06-29"' in html

def test_index_renders_active_stage_filter():
    html = render_index([_row(), _row(content_hash="h2")], SOURCES, NOW)
    assert "공신력 중" in html
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
    assert 'data-value="agreed,medical"' in html   # 사이드바 필터 체크박스 (agreed + medical 묶음)
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
    assert "핵심 요약" in html
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
    html = render_index([_row(tier=1, image_url=bad)], SOURCES, NOW)   # tier 1 -> 밴드 리드
    assert "evil" not in html   # _decorate 가 허용목록 밖 URL 을 제거

def test_index_keeps_valid_image_url():
    html = render_index([_row(tier=1, image_url="https://picsum.photos/seed/1/800/450")], SOURCES, NOW)
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
    assert "제안 · 협상" in html
    assert 'class="stage green' in html


def test_index_other_stage_has_data_attr_but_no_badge():
    html = render_index([_row(transfer_stage="other")], SOURCES, NOW)
    assert 'data-stage="other"' in html   # 속성은 있음 (필터로 제외됨)
    assert "stagebadge" not in html        # 배지는 없음


def test_detail_shows_stage_badge():
    a = _row(content_hash="cur", transfer_stage="medical")
    nb = build_neighbors([a], 0, SOURCES, NOW)
    html = render_article(_decorated(a), nb, "cur", SOURCES, NOW)
    assert "이적 합의" in html and 'class="stage red' in html   # medical -> 이적 합의 (표시 묶음 이동)


import re as _re

def test_index_hides_offmission_card_by_default():
    tr = _row(content_hash="t", transfer_stage="rumour")
    ot = _row(content_hash="o", transfer_stage="other")
    html = render_index([tr, ot], SOURCES, NOW)
    o_tag = _re.search(r'<a class="item[^"]*"[^>]*href="article/o\.html"', html).group(0)
    t_tag = _re.search(r'<a class="item[^"]*"[^>]*href="article/t\.html"', html).group(0)
    assert "display:none" in o_tag       # off-mission(other) 카드만 숨김
    assert "display:none" not in t_tag   # 이적 카드(rumour)는 노출

def test_index_still_hides_offmission_card_without_badge():
    # 회귀 가드 — 배지 없는 기타 글은 그대로 숨김 (PR #22 정책 유지)
    html = render_index([_row(content_hash="o2", transfer_stage="other")], SOURCES, NOW)
    tag = _re.search(r'<a class="item[^"]*"[^>]*href="article/o2\.html"', html).group(0)
    assert "display:none" in tag


def test_app_js_has_no_badge_exemption_left():
    # 배지 예외를 걷어낼 때 서버 렌더만 고치면 필터를 한 번 건드리는 순간 규칙이
    # 갈린다 — JS 판정에도 남은 것이 없어야 한다 (2026-08-27).
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "d.ctx" not in js


def test_sidebar_has_other_bucket_checkbox():
    html = render_index([_row(transfer_stage="other")], SOURCES, NOW)
    assert 'data-group="bucket"' in html
    assert 'data-value="other"' in html
    assert "기타" in html


def test_app_js_has_other_bucket_toggle_contract():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "bucket" in js              # '기타' 토글 셀렉터
    assert "showOther" in js            # other 노출 분기


def test_app_js_opens_other_when_narrowed_by_outlet_journalist_or_tier():
    """사이드바 건수에는 기타 기사가 들어 있는데 기타 토글 말고는 열 수단이 없었다.

    언론사 · 기자 · 공신력으로 좁히면 기타도 함께 열어야 건수와 목록이 맞는다
    (사이드바 계수 설계 §5.1). 공신력 축이 이 예외에서 빠져 있어 사이드바 숫자와
    필터 결과가 갈렸다 (2026-08-28 실측 — 「최상 94」 를 눌러도 91건).
    """
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "const narrowed = srcActive || tiers.length > 0;" in js
    assert "isOther ? (showOther || (narrowed && stageEnums.size === 0))" in js


def test_index_footer_does_not_link_to_ops_page():
    # 운영 뷰는 공개 화면에서 링크하지 않는다 (2026-08-23 공개 준비) — 배포에는
    # 그대로 올라가므로 주소를 아는 사람은 볼 수 있고, 색인만 ops.html 쪽에서 막는다.
    html = render_index([_row()], SOURCES, NOW)
    assert "ops.html" not in html


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
    assert "Miguel Delaney" in html                              # 메타 그리드 기자 칸
    assert html.index('class="title"') < html.index("Miguel Delaney")

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
    end = html.index('id="fstatus"', start)   # 기자가 마지막 그룹 → 상태줄까지
    return html[start:end]


def test_sidebar_omits_more_toggle_when_all_registered():
    directory = {"온스테인": {"name": "David Ornstein", "outlet": "The Athletic"}}

    class _Reg:
        outlets = {}
        journalists = {"온스테인": 1.0, "david ornstein": 1.0}

    # 등재 기자만 있고 tier 가 초기 노출 상한(1.5) 이내 → 미등재/더보기 단계가 없어야 함.
    # 기사를 둘 두는 것은 첫 화면 2건 문턱 때문이다 (기자 축 설계 §3.2) — 1건이면
    # 「더보기 · 기사 1건인 기자」 단계로 내려간다.
    html = render_index([_row(content_hash="h1", journalist="온스테인"),
                         _row(content_hash="h2", journalist="온스테인")], SOURCES, NOW,
                        directory=directory, registry=_Reg())
    section = _journalist_facet_section(html)
    assert "morestage" not in section
    assert "morebtn" not in section


def test_sidebar_renders_a_journalist_search_box_with_the_item_total():
    """기자 목록 맨 위 검색칸 (기자 축 설계 §3.3 가).

    인원수는 접힌 단계까지 합친 값이다 — 「지금 보이는 목록이 전부가 아니다」 를 그 자리에서
    알려 주는 것이 검색칸을 넣은 이유다. 언론사 목록에는 붙이지 않는다."""
    rows = [_row(content_hash="h1", journalist="온스테인"),
            _row(content_hash="h2", journalist="Sami Mokbel")]
    directory = {"온스테인": {"name": "David Ornstein", "outlet": "The Athletic"}}
    html = render_index(rows, SOURCES, NOW, directory=directory)
    section = _journalist_facet_section(html)
    assert 'id="jSearch"' in section
    assert "2명" in section
    assert html.count('id="jSearch"') == 1


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
    assert "공신력 최상" in html
    assert 'data-group="outlet" data-value="The Athletic"' in html
    # 미등재 기자도 기사 tier(4) 그룹으로 분류 — 접힌 단계 안에 있고 버튼이 예고한다
    assert "더보기 · 공신력 최하" in html
    assert 'class="morestage"' in html

def test_unregistered_journalist_grouped_by_row_tier():
    """비전담 (미등재) 기자는 '이름 (소속)' 라벨 + 기사 tier 그룹으로 분류된다
    (미등재 꼬리로 흘리지 않음 — 소스 tier = 비전담 기준선)."""
    sources = {"bbc_sport": {"display_name": "BBC Sport", "outlet": "BBC"}}
    html = render_index([_row(content_hash="h1", journalist="Alex Howell", tier=1.5),
                         _row(content_hash="h2", journalist="Alex Howell", tier=1.5)],
                        sources, NOW)
    section = _journalist_facet_section(html)
    assert "공신력 상" in section
    assert 'data-group="journalist" data-value="Alex Howell"' in section
    assert "Alex Howell (BBC)" in section
    assert "미등재" not in section


def test_org_byline_keeps_the_stored_spelling():
    """조직 바이라인 (BBC Sport 등) 은 원문이 저자로 적은 값 그대로 남긴다.

    옛 규칙은 이 값을 언론사 정식명 'BBC' 로 접었는데, 접어도 기자 항목은 그대로 남아
    아무것도 못 고쳤다 (기자 축 설계 §4.2 · §4.4 — 전수로 이 규칙이 잡는 자리는 2건뿐).
    조직 이름이 첫 화면에 올라오는 것은 소스 통칭 라벨 규칙이 따로 막는다."""
    sources = {"bbc_sport": {"display_name": "BBC Sport", "outlet": "BBC"}}
    html = render_index([_row(journalist="BBC Sport", tier=2)], sources, NOW)
    assert 'data-journalist="BBC Sport"' in html
    section = _journalist_facet_section(html)
    assert 'data-group="journalist" data-value="BBC Sport"' in section
    assert 'data-value="BBC"' not in section


def test_index_card_data_tier_keeps_one_point_five():
    # 밴드(상위 3등급 최대 5건) 뒤로 밀린 1.5 등급 기사가 목록에 data-tier="1.5" 로 실린다
    rows = ([_row(content_hash=f"f{i}", tier=0.0,
                  published_at=datetime(2026, 6, 29, 11, i)) for i in range(5)]
            + [_row(content_hash="x", tier=1.5)])
    html = render_index(rows, SOURCES, NOW)
    assert 'data-tier="1.5"' in html

def test_sidebar_tier_facet_lists_one_point_five():
    html = render_index([_row(tier=1.5)], SOURCES, NOW)
    assert 'data-group="tier" data-value="1.5"' in html
    assert "공신력 상" in html

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


# ---- SP-B 잔여 페이지 자동 정리 (spec §2.6) ----
from bullet_in.serve.render import write_site, sweep_orphan_pages

def test_write_site_removes_orphan_pages(tmp_path):
    art = tmp_path / "article"
    art.mkdir(parents=True)
    (art / "orphan.html").write_text("stale", encoding="utf-8")
    rows = [_row(content_hash="keep1"), _row(content_hash="keep2", url="https://x/2")]
    write_site(rows, SOURCES, tmp_path, NOW)
    assert not (art / "orphan.html").exists()
    assert (art / "keep1.html").exists() and (art / "keep2.html").exists()

def test_write_site_skips_sweep_when_no_articles(tmp_path):
    art = tmp_path / "article"
    art.mkdir(parents=True)
    (art / "orphan.html").write_text("stale", encoding="utf-8")
    write_site([], SOURCES, tmp_path, NOW)
    assert (art / "orphan.html").exists()   # 렌더 대상 0건 → 오삭제 방어로 건너뜀

def test_sweep_orphan_pages_returns_removed_names(tmp_path):
    art = tmp_path / "article"
    art.mkdir(parents=True)
    (art / "keep1.html").write_text("x", encoding="utf-8")
    (art / "old1.html").write_text("x", encoding="utf-8")
    (art / "old2.html").write_text("x", encoding="utf-8")
    removed = sweep_orphan_pages([{"content_hash": "keep1"}], tmp_path)
    assert removed == ["old1.html", "old2.html"]
    assert (art / "keep1.html").exists()

def test_sweep_orphan_pages_logs_every_removed_name(tmp_path, caplog):
    # 개수만 남기면 "무엇이 사라졌나" 를 사후에 못 묻는다 — 목록이 길어도 다 남아야 한다.
    art = tmp_path / "article"
    art.mkdir(parents=True)
    (art / "keep1.html").write_text("x", encoding="utf-8")
    names = ["old%02d.html" % i for i in range(25)]
    for n in names:
        (art / n).write_text("x", encoding="utf-8")
    with caplog.at_level("INFO", logger="bullet_in.serve.render"):
        sweep_orphan_pages([{"content_hash": "keep1"}], tmp_path)
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "잔여 페이지 25건 삭제" in logged
    for n in names:
        assert n in logged

# ── bbc_gossip 라운드업 항목화 — 원문 '(출처) , external' 표지 앵커 (옵션 B) ──
from bullet_in.serve.render import gossip_itemize

def test_gossip_itemize_converts_attributed_paragraph_to_item():
    blocks = [{"type": "p", "text": "아스날은 존 스톤스 영입을 검토하고 있다. (Sun)"}]
    out = gossip_itemize(blocks, {"Sun": 1})
    assert out == [{"type": "item", "text": "아스날은 존 스톤스 영입을 검토하고 있다.",
                    "source": "Sun"}]

def test_gossip_itemize_matches_translated_suffix_by_core():
    # 원문 "Athletic - subscription required" → core "Athletic",
    # 번역 "(Athletic - 구독 필요)" 도 같은 core 로 앵커돼야 한다
    blocks = [{"type": "p", "text": "첼시가 협상에 들어갔다. (Athletic - 구독 필요)"}]
    out = gossip_itemize(blocks, {"Athletic": 1})
    assert out[0]["type"] == "item"
    assert out[0]["source"] == "Athletic - 구독 필요"

def test_gossip_itemize_ignores_non_attribution_parenthetical():
    # 라운드업 뒤쪽 일정 섹션의 경기장 · 시각 괄호는 출처가 아님 (실데이터 함정)
    blocks = [{"type": "p", "text": "아스날 대 밀란 (Emirates Stadium, London, 14:00)"},
              {"type": "p", "text": "본문 중간 괄호 (£50.9m) 는 끝이 아니라 무관하다."},
              {"type": "img", "url": "https://x/i.jpg"}]
    out = gossip_itemize(blocks, {"Sun": 1})
    assert out == blocks

def test_render_article_itemizes_gossip_with_body_source_anchor():
    src = {"bbc_gossip": {"display_name": "BBC Football Gossip", "serving": "full"}}
    row = _row(source_id="bbc_gossip",
               body_ko="리드 문단이다.\n아스날이 영입을 검토 중이다. (Sun)",
               body_source="Arsenal are weighing a move. (Sun) , external")
    html = _ra(_dec(row, src, NOW), [], "h1", src, NOW)
    assert 'class="gossip-item"' in html
    assert 'class="src-tag"' in html and ">Sun<" in html
    assert "(Sun)" not in html          # 본문 텍스트에서 괄호 표지는 배지로 이동

def test_render_article_gossip_without_body_source_stays_plain():
    src = {"bbc_gossip": {"display_name": "BBC Football Gossip", "serving": "full"}}
    row = _row(source_id="bbc_gossip",
               body_ko="아스날이 영입을 검토 중이다. (Sun)")
    html = _ra(_dec(row, src, NOW), [], "h1", src, NOW)
    assert "gossip-item" not in html    # 앵커 없으면 변환하지 않음 (오탐 방지)

def test_render_article_non_gossip_not_itemized():
    row = _row(body_ko="아스날이 영입을 검토 중이다. (Sun)",
               body_source="Arsenal are weighing a move. (Sun) , external")
    html = _ra(_dec(row, SOURCES, NOW), [], "h1", SOURCES, NOW)
    assert "gossip-item" not in html


# ── 필터 도달 (2026-07-25 필터 버튼 버그 — 접힌 관련 보도 · 밴드 기사) ────

FILTER_SOURCES = {
    "skysports": {"display_name": "Sky Sports", "outlet": "Sky Sports", "serving": "full"},
    "goal": {"display_name": "Goal.com", "outlet": "Goal.com", "serving": "full"},
}


def test_index_relitem_carries_filter_data_attrs():
    # 접힌 관련 보도도 필터 대상 — 대표 카드와 같은 필터 키를 data 속성으로 가진다
    # 이 선수 이야기는 최근 날짜 밖에 둔다 (안건 π) — 최근 날짜에 걸리면 r2 가 접히지
    # 않고 자기 카드로 서서 relitem 이 아예 안 나온다. 최신 세 날짜는 다른 선수로 채운다.
    rep = _row(content_hash="r1", source_id="skysports", tier=2,
               title_ko="아스날, 에제 영입 합의", transfer_stage="agreed",
               published_at=datetime(2026, 6, 20, 10, 0, 0))
    # 최하는 이제 사건 묶음에 안 남고 가십 절로 간다 (2026-08-30) — 접힘을
    # 재려면 최하가 아닌 등급이어야 한다
    rel = _row(content_hash="r2", source_id="goal", tier=3, summary_ko="한 줄",
               title_ko="아스날, 에제 이적 임박", transfer_stage="rumour",
               published_at=datetime(2026, 6, 20, 9, 0, 0))
    fill = [_row(content_hash=f"f{d}", source_id="skysports", tier=2,
                 title_ko=f"아스날, 6월 {d}일 소식", transfer_stage="rumour",
                 published_at=datetime(2026, 6, d, 10, 0, 0)) for d in (29, 28, 27)]
    html = render_index([rep, rel] + fill, FILTER_SOURCES, NOW)
    i = html.index('href="article/r2.html"')
    seg = html[max(0, i - 200):i + 700]
    assert 'class="relitem"' in seg
    assert 'data-outlet="Goal.com"' in seg
    assert 'data-tier="3"' in seg
    assert 'data-stage="rumour"' in seg
    assert 'data-text=' in seg


def test_index_band_article_reappears_as_hidden_card_with_thumb():
    # 밴드 (히어로) 로 뽑힌 기사도 목록에 숨김 카드로 존재해야 필터가 찾는다 (썸네일 포함)
    lead = _row(content_hash="lead1", source_id="skysports", tier=1,
                image_url="https://img/lead.jpg", title_ko="아스날, 에제 영입 합의")
    other = _row(content_hash="o1", source_id="goal", tier=2,
                 title_ko="아스날, 사카 재계약 임박")
    html = render_index([lead, other], FILTER_SOURCES, NOW)
    assert html.count('href="article/lead1.html"') == 2   # 밴드 1 + 목록 숨김 카드 1
    i = html.index("dupcard")
    seg = html[max(0, i - 300):i + 900]
    assert "display:none" in seg
    assert "https://img/lead.jpg" in seg                   # 재출현 카드에도 썸네일


def test_index_day_header_counts_exclude_band_dup():
    # 날짜 헤더 '묶음 N개 · 보도 M건' 은 재출현 숨김 카드를 세지 않는다
    lead = _row(content_hash="lead1", source_id="skysports", tier=1,
                image_url="https://img/lead.jpg", title_ko="아스날, 에제 영입 합의")
    other = _row(content_hash="o1", source_id="goal", tier=2,
                 title_ko="아스날, 사카 재계약 임박")
    html = render_index([lead, other], FILTER_SOURCES, NOW)
    assert "묶음 1개 · 보도 1건" in html


def test_index_gossip_cards_are_all_plain_not_hidden_duplicates():
    # 2026-08-30 개정 뒤로 가십 절에는 대표 · 비대표가 없다 — 최하가 낱개 카드로
    # 늘어서므로 숨김 (dupcard) 으로 낼 이유가 사라졌다. 같은 기사를 카드와 숨김
    # 카드로 함께 두면 필터를 걸었을 때 두 번 보인다 (app.js 의 `active && m`).
    card = _row(content_hash="c1", source_id="skysports", tier=2,
                transfer_stage="agreed", title_ko="아스날, 사카 재계약 합의",
                published_at=datetime(2026, 6, 29, 12, 0))   # 그날 카드 → 꺼내기 안 걸림
    g1 = _row(content_hash="g1", source_id="goal", tier=4, transfer_stage="rumour",
              title_ko="아스날, 에제 영입설", published_at=datetime(2026, 6, 29, 11, 0))
    g2 = _row(content_hash="g2", source_id="goal", tier=4, transfer_stage="rumour",
              title_ko="아스날, 에제 이적 임박설", published_at=datetime(2026, 6, 29, 9, 0))
    html = render_index([card, g1, g2], FILTER_SOURCES, NOW)
    for h in ("g1", "g2"):
        i = html.index(f'href="article/{h}.html"')
        seg = html[max(0, i - 300):i + 300]
        assert "dupcard" not in seg
        assert "display:none" not in seg


def test_gossip_older_than_week_marked_gwk():
    # 가십 초기 노출 = 최신 가십 기준 최근 3일 (2026-08-30 — 7일이면 37장이라 넓다)
    card = _row(content_hash="c1", source_id="skysports", tier=2,
                transfer_stage="agreed", title_ko="아스날, 사카 재계약 합의",
                published_at=datetime(2026, 6, 29, 12, 0))   # 그날 카드 → 꺼내기 안 걸림
    recent = _row(content_hash="g1", source_id="bbc_gossip", tier=4,
                  title_ko="아스날, 촐리스 루머",
                  published_at=datetime(2026, 6, 29, 10, 0))
    old = _row(content_hash="g2", source_id="bbc_gossip", tier=4,
               title_ko="아스날, 진첸코 루머",
               published_at=datetime(2026, 6, 20, 10, 0))
    html = render_index([card, recent, old], {**SOURCES, "skysports":
        {"display_name": "Sky Sports", "serving": "full"}, "bbc_gossip":
        {"display_name": "BBC Football Gossip", "serving": "full"}}, NOW)
    i_old = html.index('href="article/g2.html"')
    seg_old = html[max(0, i_old - 400):i_old]
    assert "gwk" in seg_old                    # 7일 밖 → 초기 숨김 표식
    i_new = html.index('href="article/g1.html"')
    seg_new = html[max(0, i_new - 400):i_new]
    assert "gwk" not in seg_new
    assert "weekcut" in html                   # 숨길 것이 있으면 목록에 초기 컷


# ── 전체 기사 페이지 (spec 2026-07-26 §3) ────────────────────────────

from bullet_in.serve.render import render_all


def test_all_page_flat_without_clusters():
    # 같은 주인공 2건도 묶지 않고 낱개 카드로 — relitem 이 없어야 한다
    a1 = _row(content_hash="f1", title_ko="아스날, 에제 영입 합의", tier=2,
              transfer_stage="agreed")
    a2 = _row(content_hash="f2", title_ko="아스날, 에제 이적 임박", tier=4,
              transfer_stage="rumour", source_id="bbc_sport")
    html = render_all([a1, a2], SOURCES, NOW)
    assert 'href="article/f1.html"' in html
    assert 'href="article/f2.html"' in html
    assert "relitem" not in html
    assert 'class="reltoggle"' not in html


def test_all_page_daygroup_carries_date_attr():
    html = render_all([_row()], SOURCES, NOW)
    assert 'data-date="2026-06-29"' in html


def test_all_page_nav_active_and_sidebar():
    html = render_all([_row()], SOURCES, NOW)
    assert 'href="all.html"' in html          # 네비 항목
    assert 'id="applyBtn"' in html            # 필터 사이드바 재사용


def test_index_nav_links_all_page():
    html = render_index([_row()], SOURCES, NOW)
    assert 'href="all.html"' in html


def test_section_heads_link_to_all_page():
    # 최신 소식 · 가십 헤더 오른쪽에 전체 기사 진입 링크 (발견성 — 사용자 확정 배치)
    g = _row(content_hash="sl1", source_id="goal", tier=4, transfer_stage="rumour",
             title_ko="아스날, 에제 루머")
    html = render_index([_row(), g], {**SOURCES, **FILTER_SOURCES}, NOW)
    assert html.count('class="seclink"') == 2
    assert '전체 기사 보기' in html


def test_detail_note_says_meta_only_when_body_missing():
    """본문을 확보하지 못한 행은 자동 번역 안내문 대신 사유를 보여 준다 (스펙 §4.5)."""
    row = _row(body_ko=None, summary_ko=None, summary3_ko=None)
    html = render_article(_decorated(row), [], row["content_hash"], SOURCES, NOW)
    assert "원문 본문을 확보하지 못해" in html
    assert "자동 번역한 것입니다" not in html


def test_detail_note_stays_for_translated_body():
    # _row() 기본값에는 body_ko 가 없으므로 명시적으로 본문을 넣는다
    row = _row(body_ko="아스날이 센터백 영입을 추진한다.")
    html = render_article(_decorated(row), [], row["content_hash"], SOURCES, NOW)
    assert "자동 번역한 것입니다" in html
    assert "원문 본문을 확보하지 못해" not in html


def test_linked_player_badge_and_its_exposure_exception_are_gone():
    # 배지는 2026-08-27 에 걷어냈다 — 거취 어휘 조건이 "어느 선수의 거취인가" 를
    # 못 봐 실측 3건 중 하나가 엉뚱한 이름을 앞세웠다 (레앙 기사에 "왓킨스 외 1명").
    # 배지가 근거이던 기타 노출 예외도 함께 걷었다 — 배지 없이 예외만 남기면
    # 아스날과 무관한 글이 설명 없이 뜬다.
    ot = _row(content_hash="ob", transfer_stage="other", linked_players="기마랑이스",
              title_ko="뉴캐슬, 기마랑이스 재계약 추진")
    html = render_index([ot], SOURCES, NOW)
    assert 'class="ctx"' not in html          # 배지 없음
    assert 'data-ctx' not in html             # 필터 표식도 없음
    tag = _re.search(r'<a class="item[^"]*"[^>]*href="article/ob\.html"', html).group(0)
    assert "display:none" in tag              # 기타라서 숨는다 (예외 없음)


from bullet_in.serve.render import filter_stage


def test_filter_stage_returns_stored_value_for_bbc_gossip():
    # 가십 루머 롤업 하드코딩 제거 (방향 축 스펙 §5) — filter_stage 는 이제
    # source_id 분기 없이 저장값을 그대로 반환한다. 배포판 실측으로 bbc_gossip
    # 전행 (59건) 이 rule_stage 규칙에 따라 rumour 로 저장돼 있어 화면은 불변이다.
    row = {"source_id": "bbc_gossip", "transfer_stage": "rumour"}
    assert filter_stage(row) == "rumour"


# --- 공저 기사의 카드 속성 · 바이라인 (설계 §2.3 · §2.4) ---

_CO_DIR = {"온스테인": {"name": "David Ornstein", "outlet": "The Athletic"},
           "david ornstein": {"name": "David Ornstein", "outlet": "The Athletic"}}


def test_decorate_card_attr_carries_every_author():
    row = _row(journalist="David Ornstein", body_ko="본문",
               authors_json='["David Ornstein", "James McNicholas"]')
    a = _dec(row, SOURCES, NOW, directory=_CO_DIR)
    assert a["_journalist"] == "David Ornstein|James McNicholas"


def test_decorate_byline_counts_the_other_authors():
    row = _row(journalist="David Ornstein", body_ko="본문",
               authors_json='["David Ornstein", "James McNicholas"]')
    a = _dec(row, SOURCES, NOW, directory=_CO_DIR)
    assert a["_authors"] == ["David Ornstein", "James McNicholas"]
    assert a["_more_authors"] == 1


def test_decorate_single_author_has_no_other_authors():
    a = _dec(_row(journalist="Hugo Guillemet", body_ko="본문"), SOURCES, NOW)
    assert a["_authors"] == ["Hugo Guillemet"] and a["_more_authors"] == 0


def test_detail_lists_every_author_in_the_meta_grid():
    row = _row(journalist="David Ornstein", body_ko="본문",
               authors_json='["David Ornstein", "James McNicholas"]')
    a = _dec(row, SOURCES, NOW, directory=_CO_DIR)
    html = _ra(a, [], "h1", SOURCES, NOW)
    assert "David Ornstein · James McNicholas" in html


def test_detail_origin_block_shows_lead_author_and_the_rest_as_count():
    row = _row(journalist="David Ornstein", body_ko="본문",
               authors_json='["David Ornstein", "James McNicholas"]')
    a = _dec(row, SOURCES, NOW, directory=_CO_DIR)
    html = _ra(a, [], "h1", SOURCES, NOW)
    assert "David Ornstein 외 1명" in html


def test_detail_origin_block_keeps_the_stored_byline_for_a_single_author():
    # 배포 시점 무변화 — 소급 전에는 authors 가 비어 있고 원문 블록이 안 흔들려야 한다
    a = _dec(_row(journalist="온스테인", body_ko="본문"), SOURCES, NOW, directory=_CO_DIR)
    assert "<span>온스테인</span>" in _ra(a, [], "h1", SOURCES, NOW)


# ── 공개 준비 · 검색과 링크 미리보기 메타 (2026-08-23) ────────────────────
# 태그가 산출물에 있는 것과 커뮤니티 · 메신저가 그것을 어떻게 그리는가는 다른 층이다.
# 여기서 보는 것은 앞쪽 하나뿐이고, 뒤쪽은 실물 링크로 따로 확인한다.
from bullet_in.serve.render import SITE_URL, ARTICLE_ROBOTS, render_players as _rp


def test_index_carries_description_canonical_and_open_graph():
    html = render_index([_row()], SOURCES, NOW)
    assert '<meta name="description" content="' in html
    assert f'<link rel="canonical" href="{SITE_URL}/">' in html
    assert f'<meta property="og:url" content="{SITE_URL}/">' in html
    assert '<meta property="og:title" content="Bullet-in · 아스날 이적 뉴스">' in html
    assert '<meta property="og:site_name" content="Bullet-in">' in html


def test_list_and_player_pages_are_indexable():
    # 색인 대상 — robots 메타를 아예 달지 않아 기본값 (색인 허용) 으로 둔다
    assert '<meta name="robots"' not in render_index([_row()], SOURCES, NOW)
    assert '<meta name="robots"' not in _rp([], NOW)


def test_article_detail_is_noindex_but_still_followed():
    # 번역문이 원문 대신 검색에 뜨는 것을 막는다. follow 는 남겨 목록 · 선수 페이지로
    # 크롤이 흐르게 한다 (2026-08-23 확정).
    a = _dec(_row(content_hash="hmeta", body_ko="본문"), SOURCES, NOW)
    html = _ra(a, [], "hmeta", SOURCES, NOW)
    assert f'<meta name="robots" content="{ARTICLE_ROBOTS}">' in html
    assert ARTICLE_ROBOTS == "noindex,follow"
    assert f'<link rel="canonical" href="{SITE_URL}/article/hmeta.html">' in html
    assert '<meta property="og:type" content="article">' in html


def test_article_with_an_image_uses_the_large_preview_card():
    a = _dec(_row(content_hash="himg", body_ko="본문",
                  image_url="https://example.com/a.jpg"), SOURCES, NOW)
    html = _ra(a, [], "himg", SOURCES, NOW)
    assert '<meta property="og:image" content="https://example.com/a.jpg">' in html
    assert '<meta name="twitter:card" content="summary_large_image">' in html


def _home_html_with(block):
    """블록 하나를 홈 템플릿에 그대로 넣고 렌더한다.

    묶음을 만드는 경로는 DB (선수 사전) 를 타므로 블록을 손으로 만든다 — 보려는 것이
    「블록에 결말이 있을 때 그리는가」이지 「묶음이 결말을 찾는가」가 아니다."""
    from bullet_in.serve.render import _env
    return _env().get_template("index.html.j2").render(
        lead=None, mains=[], gossip=[], gossip_hidden=0, gossip_days=3,
        gossip_shown=0, gossip_total=0, news_today=0, gossip_today=0,
        day_blocks=[{"date": "2026-06-29", "label": "오늘", "n": 1, "reports": 2,
                     "all_dup": False, "blocks": [block]}],
        facets={"team": {}, "tiers": [], "total": 0, "stage": {}, "stage_groups": [],
                "other": 0, "outlets": {"initial": [], "stages": []},
                "journalists": {"initial": [], "stages": [], "total": 0}},
        active="home", root="", meta=None)


def test_ending_card_is_drawn_on_the_home_page_with_its_destination_badge():
    """결말 카드를 홈에 되살린다 (안건 2π · 2026-09-01).

    2026-08-23 에 뺀 이유는 카드 자체가 아니라 설명이 사라진 것이었다 — 행선지 구단
    배지를 떼자 둘째 카드가 왜 붙어 있는지 알 수 없어 같은 소식이 두 번 나온 것처럼
    읽혔다 (실측 16블록). 그래서 되살릴 때 배지를 함께 단다."""
    from bullet_in.serve.render import _decorate
    rep = _decorate(_row(content_hash="cr", title_ko="아스날, 로저스 관심"), SOURCES, NOW)
    end = _decorate(_row(content_hash="ce", title_ko="첼시, 로저스 영입 합의"), SOURCES, NOW)
    html = _home_html_with({"rep": rep, "ending": {"article": end, "club": "첼시"},
                            "branches": [], "rel_count": 0, "count": 2})
    assert 'data-hash="cr"' in html                 # 대표 (검사가 헛돌지 않는지)
    assert 'data-hash="ce"' in html                 # 결말도 그린다
    assert '<span class="dest">첼시</span>' in html   # 왜 붙어 있는지를 배지가 설명한다


def test_ending_card_without_a_club_carries_no_destination_badge():
    """행선지가 없는 무산 결말에는 배지를 안 단다 — 빈 배지가 서면 안 된다."""
    from bullet_in.serve.render import _decorate
    rep = _decorate(_row(content_hash="cr", title_ko="아스날, 로저스 관심"), SOURCES, NOW)
    end = _decorate(_row(content_hash="ce", title_ko="로저스 영입 철수"), SOURCES, NOW)
    html = _home_html_with({"rep": rep, "ending": {"article": end, "club": None},
                            "branches": [], "rel_count": 0, "count": 2})
    assert 'data-hash="ce"' in html
    assert 'class="dest"' not in html


def test_no_analytics_script_without_a_measurement_id():
    # 측정 ID 가 비면 스크립트를 아예 넣지 않는다 — 로컬 렌더 · 목업에서 계측이 0 이어야
    # 목업을 띄우는 것만으로 공개 주간 수치가 흐려지지 않는다.
    assert "googletagmanager" not in render_index([_row()], SOURCES, NOW)


def test_analytics_script_is_wired_when_a_measurement_id_is_set(monkeypatch):
    monkeypatch.setattr("bullet_in.serve.render.GA_MEASUREMENT_ID", "G-TEST123")
    html = render_index([_row()], SOURCES, NOW)
    assert "googletagmanager.com/gtag/js?id=G-TEST123" in html
    assert "gtag('config','G-TEST123')" in html


def test_origin_links_are_marked_for_the_exit_event():
    # 원문 이탈은 이 표식으로 센다 — 표식이 없으면 app.js 가 걸 자리를 못 찾는다.
    a = _dec(_row(content_hash="hexit", body_ko="본문"), SOURCES, NOW)
    html = _ra(a, [], "hexit", SOURCES, NOW)
    assert 'data-exit="origin_button"' in html
    assert 'data-hash="hexit"' in html


def test_article_without_an_image_falls_back_to_the_small_preview_card():
    a = _dec(_row(content_hash="hnoimg", body_ko="본문", image_url=None), SOURCES, NOW)
    html = _ra(a, [], "hnoimg", SOURCES, NOW)
    assert "og:image" not in html
    assert '<meta name="twitter:card" content="summary">' in html


# ── 접속 통계 고지 — 계측이 켜진 렌더에만 싣는다 ─────────────────────────
# 안 모으면서 모은다고 적으면 그 문장 자체가 사실과 어긋난다. 그래서 고지와 계측
# 스크립트가 같은 조건에 걸려 있고, 아래 두 검사가 그 짝을 지킨다.
from bullet_in.serve.render import render_about as _ra_about


def test_privacy_notice_is_absent_when_analytics_is_off():
    assert "접속 통계" not in _ra_about()
    assert "접속 통계 안내" not in render_index([_row()], SOURCES, NOW)


def test_privacy_notice_appears_with_analytics(monkeypatch):
    monkeypatch.setattr("bullet_in.serve.render.GA_MEASUREMENT_ID", "G-TEST123")
    about = _ra_about()
    assert '<h2 id="stats">접속 통계</h2>' in about
    assert "Google 애널리틱스" in about
    assert "14개월" in about
    # 목록 · 상세 어디서든 고지로 갈 수 있어야 한다
    assert 'href="about.html#stats"' in render_index([_row()], SOURCES, NOW)
    a = _dec(_row(content_hash="hnote", body_ko="본문"), SOURCES, NOW)
    assert 'href="../about.html#stats"' in _ra(a, [], "hnote", SOURCES, NOW)


# ── 최하는 전부 가십 절로 · 카드가 없는 날짜는 가십에서 꺼낸다 ──────────
# 2026-08-30 사용자 확정. 배포본 실측 = 관련 보도 698 → 330 · 가십 74 → 440장.

def _gossip(html: str) -> str:
    """가십 절 구간만 잘라 낸다 — 「어디에 놓였나」 를 마크업 위치로 판정한다."""
    i, j = html.find('class="gossiplist'), html.find('gossipnote')
    return html[i:j] if i >= 0 and j > i else ""


def _low(**kw):
    base = dict(tier=4.0, transfer_stage="rumour", transfer_direction="in")
    base.update(kw)
    return _row(**base)


def test_lowest_goes_to_gossip_even_when_the_story_has_a_higher_source():
    # 같은 선수 묶음에 공신력 최상이 있어도 최하는 접히지 않고 가십 절로 간다
    high = _row(content_hash="hi", tier=2.0, transfer_stage="agreed",
                transfer_direction="in", title_ko="아스날, 사카 재계약 합의")
    low = _low(content_hash="lo", title_ko="아스날, 사카 이적설 부인")
    html = render_index([high, low], SOURCES, NOW)
    assert "lo" in _gossip(html)                       # 가십 절에 있다
    assert 'class="relitem" href="article/lo' not in html   # 접힘에 안 남는다
    assert "hi" not in _gossip(html)                   # 상위는 그대로 카드


def test_day_with_only_lowest_articles_still_gets_a_date_group():
    # 그날 카드가 0장이면 가십에서 꺼내 날짜 그룹을 세운다
    low = _low(content_hash="lo", title_ko="아스날, 사카 이적설 부인")
    html = render_index([low], SOURCES, NOW)
    assert "오늘" in html
    assert 'href="article/lo.html"' in html
    assert "lo" not in _gossip(html)                   # 꺼낸 것은 가십 목록에서 뺀다
    assert "lowsolo" in html                           # 한 장이어도 반 폭 유지


def test_lowest_stays_in_gossip_when_the_day_already_has_a_card():
    # 그날 카드가 서 있으면 꺼내기가 안 걸린다 — 최하는 가십 절에만
    high = _row(content_hash="hi", tier=2.0, transfer_stage="agreed",
                transfer_direction="in", title_ko="아스날, 사카 재계약 합의")
    low = _low(content_hash="lo", title_ko="아스날, 라이스 이적설 부인")
    html = render_index([high, low], SOURCES, NOW)
    assert "lo" in _gossip(html)
    assert 'href="article/lo.html"' not in html.replace(_gossip(html), "")


def test_section_is_named_news_and_counts_are_split():
    # 「최신 소식」 → 「최신 뉴스」 · 오늘 건수를 뉴스 · 가십으로 갈라 적는다
    low = _low(content_hash="lo", title_ko="아스날, 사카 이적설 부인")
    html = render_index([low], SOURCES, NOW)
    assert "<h2>최신 뉴스</h2>" in html
    assert "오늘 뉴스 1건" in html
    # 오늘치가 전부 최신 뉴스로 올라가 가십 절에 0건이면 링크를 걸지 않는다 (c안)
    assert "gossipjump" not in html


def test_gossip_head_carries_an_anchor_and_both_counts():
    low = [_low(content_hash="lo1", title_ko="아스날, 사카 이적설 부인"),
           _low(content_hash="lo2", title_ko="아스날, 라이스 이적설 부인")]
    high = _row(content_hash="hi", tier=2.0, transfer_stage="agreed",
                transfer_direction="in", title_ko="아스날, 외데고르 재계약 합의")
    html = render_index(low + [high], SOURCES, NOW)
    assert 'id="gossip"' in html
    assert "최근 3일 2건 · 전체 2건" in html
    assert 'class="gossipjump"' in html and "가십 2건" in html


def test_mobile_query_gives_the_ladder_title_its_own_line():
    """선수 페이지 사다리가 좁은 화면에서 제목 자리를 잃던 자리 (2026-08-31).

    한 줄에 날짜 · 단계 · 제목 · 매체 · 건수를 늘어놓는데 제목만 flex 로 줄어들어,
    386px 뷰포트에서 폭 19px · 높이 538px 로 한 글자씩 세로로 흘렀다.
    한계: pytest 는 브라우저를 안 띄우므로 규칙이 있는지만 본다 — 실제 배치는
    실브라우저로 확인했다 (제목 폭 339px · 높이 45px).
    """
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    mobile = css[css.index("@media (max-width:640px)"):]
    assert re.search(r"\.tltitle\{[^}]*flex:1 0 100%", mobile)
    # 썸네일 168px 고정이 제목 자리를 133px 로 밀어 제목이 잘렸다 — 목록 기본값으로 되돌린다
    assert re.search(r"\.daylist\.plist \.item\.hasthumb\{[^}]*132px", mobile)


def test_lowest_tier_title_gets_two_lines_on_mobile():
    """공신력 최하 제목의 한 줄 클램프가 좁은 화면에서 열 자 남짓만 남기던 자리.

    한 줄 클램프 자체는 「최하는 덜 두드러지게」 라는 설계라 데스크톱에서는 그대로 두고
    (그쪽은 한 줄에 제목이 거의 다 들어간다), 모바일에서만 두 줄로 푼다.
    """
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    base, mobile = css.split("@media (max-width:640px)")
    assert re.search(r"\.item\.g4 \.htitle\{[^}]*-webkit-line-clamp:1", base)
    assert re.search(r"\.item\.g4 \.htitle\{[^}]*-webkit-line-clamp:2", mobile)
