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

def test_extract_og_title_nested_title_tag():
    assert extract_og_title("<title>Foo <b>Bar</b></title>") == "Foo Bar"

def test_extract_og_title_none():
    assert extract_og_title("<p>no title</p>") is None
