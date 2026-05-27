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
