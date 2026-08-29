from bullet_in.canonical import canonical_url, content_hash

def test_canonical_strips_tracking_and_fragment():
    a = canonical_url("https://x.test/a?utm_source=tw&id=5#frag")
    assert a == "https://x.test/a?id=5"

def test_canonical_lowercases_host_and_drops_trailing_slash():
    assert canonical_url("https://X.Test/a/") == "https://x.test/a"

def test_content_hash_stable_and_title_insensitive_to_whitespace():
    h1 = content_hash("  Arteta speaks  ", "https://x.test/a")
    h2 = content_hash("Arteta speaks", "https://x.test/a")
    assert h1 == h2 and len(h1) == 64

def test_canonical_folds_bbc_uk_host_into_com():
    uk = canonical_url("https://www.bbc.co.uk/sport/football/articles/c4gd1r1nel2o")
    com = canonical_url("https://www.bbc.com/sport/football/articles/c4gd1r1nel2o")
    assert uk == com == "https://www.bbc.com/sport/football/articles/c4gd1r1nel2o"

def test_canonical_keeps_sky_section_number():
    # 섹션 번호를 지우면 키로는 맞지만 주소로는 못 쓴다 — 기사에 못 가고 축구 섹션
    # 첫 화면으로 떨어진다 (2026-08-29 실측 8건 전부 · 안건 2ζ 로 규칙을 걷어냄).
    url = "https://www.skysports.com/football/news/11095/13574990/ezri-konsa-arsenal"
    assert canonical_url(url) == url

def test_canonical_keeps_sky_live_blog_section_number():
    url = "https://www.skysports.com/football/live-blog/11661/13570000/x"
    assert canonical_url(url) == url

def test_canonical_keeps_sky_section_shape_on_other_hosts():
    url = "https://other.test/football/news/11095/13574990/x"
    assert canonical_url(url) == url

def test_canonical_drops_athletic_slug():
    a = canonical_url("https://www.nytimes.com/athletic/7451792/2026/08/19/ezri-konsa-aston-villa")
    b = canonical_url("https://www.nytimes.com/athletic/7451792/2026/08/19/ezri-konsa-aston-vila")
    assert a == b == "https://www.nytimes.com/athletic/7451792/2026/08/19"

def test_canonical_drops_added_tracking_params():
    a = canonical_url("https://www.nytimes.com/athletic/7460471/2026/07/21/x?smid=tw-share")
    b = canonical_url("https://www.nytimes.com/athletic/7460471/2026/07/21/x"
                      "?source=articleShare&unlocked_article_code=abc")
    assert a == b == "https://www.nytimes.com/athletic/7460471/2026/07/21"
