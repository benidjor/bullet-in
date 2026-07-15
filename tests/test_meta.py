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
