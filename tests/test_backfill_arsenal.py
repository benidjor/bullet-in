from bullet_in.backfill_arsenal import rebody_update


def test_rebody_update_targets_only_longer_bodies():
    row = {"content_hash": "h1", "body_source": "12345"}
    assert rebody_update(row, "1234567") == {"h": "h1", "b": "1234567"}


def test_rebody_update_skips_same_or_shorter_body():
    # 응답 이상 · 파서 회귀로 본문을 줄이지 않는다 (기존 값 보호)
    row = {"content_hash": "h1", "body_source": "12345"}
    assert rebody_update(row, "12345") is None
    assert rebody_update(row, "123") is None
    assert rebody_update(row, "") is None


def test_rebody_update_fills_empty_body():
    assert rebody_update({"content_hash": "h1", "body_source": None}, "본문") == {
        "h": "h1", "b": "본문"}
