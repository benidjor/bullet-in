from bullet_in.dedup import classify

def test_new_when_url_unseen():
    assert classify("https://x.test/a", "h1", {}, "bbc_sport", 2) == ("new", 1)

def test_duplicate_same_source_same_hash():
    seen = {"https://x.test/a": ("h1", 3, "bbc_sport", 2)}
    assert classify("https://x.test/a", "h1", seen, "bbc_sport", 2) == ("duplicate", 3)

def test_changed_same_source_hash_differs():
    # revision 원 목적 (같은 소스의 정당한 기사 갱신) 은 계속 허용 (spec §4)
    seen = {"https://x.test/a": ("h1", 3, "bbc_sport", 2)}
    assert classify("https://x.test/a", "h2", seen, "bbc_sport", 2) == ("changed", 4)

def test_blocked_cross_source_both_outlet_bodies():
    # BBC 언론사 본문 행에 fmkorea 가 받아온 언론사 본문 도착 → 먼저 들어온 행 유지
    seen = {"https://x.test/a": ("h1", 1, "bbc_sport", 2)}
    assert classify("https://x.test/a", "h2", seen, "fmkorea", 2) == ("blocked", 1)

def test_upgrade_stub_to_post_body():
    # 온스테인 스텁 행에 fmkorea 게시글 전문 도착 → 같은 행 승격 (0 → 1)
    seen = {"https://x.test/a": ("h1", 1, "x_ornstein", 0)}
    assert classify("https://x.test/a", "h2", seen, "fmkorea", 1) == ("upgrade", 2)

def test_upgrade_stub_to_outlet_body():
    seen = {"https://x.test/a": ("h1", 1, "x_ornstein", 0)}
    assert classify("https://x.test/a", "h2", seen, "fmkorea", 2) == ("upgrade", 2)

def test_upgrade_post_body_to_outlet_body():
    # 커뮤니티가 옮긴 본문 행에 언론사 원문 도착 → 원문으로 교체 (1 → 2)
    seen = {"https://x.test/a": ("h1", 1, "fmkorea", 1)}
    assert classify("https://x.test/a", "h2", seen, "bbc_sport", 2) == ("upgrade", 2)

def test_blocked_outlet_body_to_post_body():
    # 커뮤니티 번역본이 언론사 원문을 밀어내지 못한다 (2 → 1 차단)
    seen = {"https://x.test/a": ("h1", 1, "bbc_sport", 2)}
    assert classify("https://x.test/a", "h2", seen, "fmkorea", 1) == ("blocked", 1)

def test_blocked_cross_source_same_post_body_level():
    # 정보가 늘지 않는 교체는 불허 — first-seen 승리
    seen = {"https://x.test/a": ("h1", 1, "fmkorea", 1)}
    assert classify("https://x.test/a", "h2", seen, "other_post", 1) == ("blocked", 1)

def test_blocked_cross_source_both_stubs():
    seen = {"https://x.test/a": ("h1", 1, "x_ornstein", 0)}
    assert classify("https://x.test/a", "h2", seen, "other_stub", 0) == ("blocked", 1)
