from bullet_in.dedup import classify

def test_new_when_url_unseen():
    assert classify("https://x.test/a", "h1", {}, "bbc_sport", True) == ("new", 1)

def test_duplicate_same_source_same_hash():
    seen = {"https://x.test/a": ("h1", 3, "bbc_sport", True)}
    assert classify("https://x.test/a", "h1", seen, "bbc_sport", True) == ("duplicate", 3)

def test_changed_same_source_hash_differs():
    # revision 원 목적 (같은 소스의 정당한 기사 갱신) 은 계속 허용 (spec §4)
    seen = {"https://x.test/a": ("h1", 3, "bbc_sport", True)}
    assert classify("https://x.test/a", "h2", seen, "bbc_sport", True) == ("changed", 4)

def test_blocked_cross_source_existing_complete():
    # BBC 완전체 행에 fmkorea 퍼온 글 도착 → 보호 (2026-07-25 오염 사례 차단)
    seen = {"https://x.test/a": ("h1", 1, "bbc_sport", True)}
    assert classify("https://x.test/a", "h2", seen, "fmkorea", True) == ("blocked", 1)

def test_upgrade_cross_source_stub_to_complete():
    # 온스테인 스텁 행에 fmkorea 전문 도착 → 같은 행 승격 (spec §4 upgrade)
    seen = {"https://x.test/a": ("h1", 1, "x_ornstein", False)}
    assert classify("https://x.test/a", "h2", seen, "fmkorea", True) == ("upgrade", 2)

def test_blocked_cross_source_both_stubs():
    # 정보가 늘지 않는 교체는 불허 — first-seen 승리
    seen = {"https://x.test/a": ("h1", 1, "x_ornstein", False)}
    assert classify("https://x.test/a", "h2", seen, "other_stub", False) == ("blocked", 1)
