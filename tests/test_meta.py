from bullet_in.adapters.meta import extract_og_image, extract_article_body, extract_og_title

def test_extract_og_image_prefers_og():
    html = ('<meta property="og:image" content="https://img.test/a.jpg">'
            '<meta name="twitter:image" content="https://img.test/b.jpg">')
    assert extract_og_image(html) == "https://img.test/a.jpg"

def test_extract_og_image_falls_back_to_twitter():
    html = '<meta name="twitter:image" content="https://img.test/b.jpg">'
    assert extract_og_image(html) == "https://img.test/b.jpg"

def test_extract_og_image_none_when_absent():
    assert extract_og_image("<html><head></head></html>") is None

def test_extract_article_body_joins_paragraphs_in_article():
    html = ('<header>nav</header><article><p>First para.</p><p>Second para.</p>'
            '<figure><figcaption>cap</figcaption></figure></article><footer>f</footer>')
    out = extract_article_body(html)
    assert "First para." in out and "Second para." in out
    assert "nav" not in out and "cap" not in out

def test_extract_article_body_truncates():
    html = "<article>" + "<p>" + ("가" * 50) + "</p>" * 1 + "</article>"
    assert len(extract_article_body(html, max_chars=10)) == 10

def test_extract_og_title_prefers_og():
    html = '<meta property="og:title" content="Arsenal sign X"><title>ignored</title>'
    assert extract_og_title(html) == "Arsenal sign X"

def test_extract_og_title_fallback_title_tag():
    assert extract_og_title("<title>Fallback</title>") == "Fallback"

def test_extract_og_title_none():
    assert extract_og_title("<p>no title</p>") is None

from bullet_in.adapters.meta import extract_body_images

IMG_PAGE = ('<html><body><div class="story">'
            '<p>One.</p><img src="https://cdn.test/a.jpg">'
            '<p>Two.</p><img src="https://cdn.test/b.jpg">'
            '</div><img src="https://cdn.test/outside.jpg"></body></html>')

def test_images_scoped_to_container_in_order():
    assert extract_body_images(IMG_PAGE, ".story") == [
        "https://cdn.test/a.jpg", "https://cdn.test/b.jpg"]

def test_images_heuristic_root_when_no_selector():
    html = ('<html><body><article><img src="https://cdn.test/in.jpg"></article>'
            '<img src="https://cdn.test/out.jpg"></body></html>')
    assert extract_body_images(html) == ["https://cdn.test/in.jpg"]

def test_images_excludes_ad_hosts():
    html = ('<article><img src="https://cdn.test/a.jpg">'
            '<img src="https://ads.doubleclick.net/x.jpg">'
            '<img src="https://images.taboola.com/y.jpg">'
            '<img src="https://widgets.outbrain.com/z.jpg"></article>')
    assert extract_body_images(html) == ["https://cdn.test/a.jpg"]

def test_images_excludes_aside_and_related_blocks():
    html = ('<article><img src="https://cdn.test/a.jpg">'
            '<aside><img src="https://cdn.test/side.jpg"></aside>'
            '<div class="related-articles"><img src="https://cdn.test/rel.jpg"></div>'
            '</article>')
    assert extract_body_images(html) == ["https://cdn.test/a.jpg"]

def test_images_excludes_tiny_data_uri_and_svg():
    html = ('<article><img src="https://cdn.test/a.jpg">'
            '<img src="https://cdn.test/icon.png" width="24" height="24">'
            '<img src="data:image/gif;base64,R0lGOD">'
            '<img src="https://cdn.test/logo.svg"></article>')
    assert extract_body_images(html) == ["https://cdn.test/a.jpg"]

def test_images_resolves_lazyload_and_srcset():
    html = ('<article>'
            '<img data-src="https://cdn.test/lazy.jpg">'
            '<img srcset="https://cdn.test/s.jpg 320w, https://cdn.test/l.jpg 1280w">'
            '</article>')
    assert extract_body_images(html) == [
        "https://cdn.test/lazy.jpg", "https://cdn.test/l.jpg"]

def test_images_absolutizes_relative_and_dedups():
    html = '<article><img src="/img/a.jpg"><img src="https://cdn.test/img/a.jpg"></article>'
    assert extract_body_images(html, base_url="https://cdn.test/article/1") == [
        "https://cdn.test/img/a.jpg"]

def test_images_caps_at_limit():
    imgs = "".join(f'<img src="https://cdn.test/{i}.jpg">' for i in range(15))
    assert len(extract_body_images(f"<article>{imgs}</article>")) == 10

def test_images_empty_on_missing_container_or_blank():
    assert extract_body_images("<p>no container</p>", ".story") == []
    assert extract_body_images("") == []

from bullet_in.adapters.meta import extract_authors

def test_authors_from_json_ld_multiple_in_order():
    # BBC 실측 형태: NewsArticle.author 배열에 Person 2명
    html = ('<script type="application/ld+json">'
            '{"@type":"NewsArticle","author":[{"@type":"Person","name":"Alastair Telfer"},'
            '{"@type":"Person","name":"Sami Mokbel"}]}</script>')
    assert extract_authors(html) == ["Alastair Telfer", "Sami Mokbel"]

def test_authors_from_nested_json_ld_graph():
    # @graph 중첩 안의 author 도 재귀 탐색으로 찾는다
    html = ('<script type="application/ld+json">'
            '{"@graph":[{"@type":"WebPage"},'
            '{"@type":"NewsArticle","author":{"@type":"Person","name":"Raff Tindale"}}]}'
            '</script>')
    assert extract_authors(html) == ["Raff Tindale"]

def test_authors_accepts_string_author():
    html = ('<script type="application/ld+json">'
            '{"@type":"NewsArticle","author":"Moataz Elgammal"}</script>')
    assert extract_authors(html) == ["Moataz Elgammal"]

def test_authors_dedupes_preserving_order():
    html = ('<script type="application/ld+json">'
            '{"@type":"NewsArticle","author":[{"@type":"Person","name":"Sami Mokbel"},'
            '{"@type":"Person","name":"Sami Mokbel"}]}</script>')
    assert extract_authors(html) == ["Sami Mokbel"]

def test_authors_falls_back_to_meta_author():
    html = '<meta name="author" content="Raff Tindale">'
    assert extract_authors(html) == ["Raff Tindale"]

def test_authors_json_ld_wins_over_meta():
    html = ('<meta name="author" content="Desk">'
            '<script type="application/ld+json">'
            '{"@type":"NewsArticle","author":{"@type":"Person","name":"Real Person"}}</script>')
    assert extract_authors(html) == ["Real Person"]

def test_authors_excludes_url_and_empty_values():
    # BBC 실측: article:author 는 Facebook URL — 저자명이 아니다
    html = ('<meta property="article:author" content="https://www.facebook.com/BBCSport/">'
            '<script type="application/ld+json">'
            '{"@type":"NewsArticle","author":[{"@type":"Person","name":""},'
            '{"@type":"Person","name":"https://example.test/profile"},'
            '{"@type":"Person","name":"Dharmesh Sheth"}]}</script>')
    assert extract_authors(html) == ["Dharmesh Sheth"]

def test_authors_survives_broken_json_ld():
    html = ('<script type="application/ld+json">{ not json ]</script>'
            '<meta name="author" content="Kaya Kaynak">')
    assert extract_authors(html) == ["Kaya Kaynak"]

def test_authors_empty_when_absent():
    assert extract_authors("<html><body><p>no author</p></body></html>") == []

def test_authors_falls_back_when_json_ld_authors_all_invalid():
    # JSON-LD author 가 있으나 유효 저자 0명 → meta 폴백이 걸려야 한다
    html = ('<meta name="author" content="Real Fallback Author">'
            '<script type="application/ld+json">'
            '{"@type":"NewsArticle","author":[{"@type":"Person","name":""},'
            '{"@type":"Person","name":"https://example.test/profile"}]}</script>')
    assert extract_authors(html) == ["Real Fallback Author"]

def test_authors_recovers_json_ld_with_control_characters():
    # Sky Sports 실측 (2026-07-16): NewsArticle LD 문자열에 raw 제어 문자 → strict 파싱 거부
    html = ('<script type="application/ld+json">'
            '{"@type":"NewsArticle","headline":"Line\x1fbreak",'
            '"author":{"@type":"Person","name":"Keith Downie"}}</script>')
    assert extract_authors(html) == ["Keith Downie"]

def test_authors_unescapes_html_entities():
    html = ('<script type="application/ld+json">'
            '{"@type":"NewsArticle","author":{"@type":"Person","name":"Sam O&#39;Brien"}}</script>')
    assert extract_authors(html) == ["Sam O'Brien"]

def test_authors_splits_combined_names_on_ampersand():
    # Sky Sports 실측: 공저를 한 Person.name 에 ' & ' 로 결합 → 등재 기자 매칭이 깨짐
    html = ('<script type="application/ld+json">'
            '{"@type":"NewsArticle",'
            '"author":{"@type":"Person","name":"Keith Downie &amp; Dharmesh Sheth"}}</script>')
    assert extract_authors(html) == ["Keith Downie", "Dharmesh Sheth"]
