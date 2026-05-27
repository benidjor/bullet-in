from bullet_in.dedup import classify

def test_new_when_url_unseen():
    assert classify(url="https://x.test/a", new_hash="h1", seen={}) == ("new", 1)

def test_duplicate_when_url_and_hash_match():
    assert classify(url="https://x.test/a", new_hash="h1",
                    seen={"https://x.test/a": ("h1", 3)}) == ("duplicate", 3)

def test_changed_when_url_seen_but_hash_differs():
    assert classify(url="https://x.test/a", new_hash="h2",
                    seen={"https://x.test/a": ("h1", 3)}) == ("changed", 4)
