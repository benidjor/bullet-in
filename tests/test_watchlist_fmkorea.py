from bullet_in.watchlist_fmkorea import (read_cursor, write_cursor, next_slice,
                                         build_keywords, next_cursor)

IDS = [10, 20, 30, 40, 50]

def test_next_slice_from_start_when_no_cursor():
    assert next_slice(IDS, None, size=3) == [10, 20, 30]

def test_next_slice_starts_after_cursor():
    assert next_slice(IDS, 20, size=2) == [30, 40]

def test_next_slice_wraps_around():
    assert next_slice(IDS, 40, size=3) == [50, 10, 20]

def test_next_slice_restarts_when_cursor_is_last():
    assert next_slice(IDS, 50, size=2) == [10, 20]

def test_next_slice_cursor_id_removed_uses_next_id():
    # 커서 25 가 명단에서 사라짐 → 그다음 id (30) 부터 (스펙 §6)
    assert next_slice(IDS, 25, size=2) == [30, 40]

def test_next_slice_small_roster_no_duplicates():
    assert next_slice([10, 20], 10, size=10) == [20, 10]

def test_next_slice_empty_roster():
    assert next_slice([], None) == []

def test_cursor_roundtrip(tmp_path):
    p = tmp_path / "state" / "watchlist_cursor"
    write_cursor(p, 42)                  # 부모 디렉토리 자동 생성
    assert read_cursor(p) == 42

def test_read_cursor_missing_or_corrupt(tmp_path):
    assert read_cursor(tmp_path / "absent") is None
    p = tmp_path / "cursor"
    p.write_text("not-a-number")
    assert read_cursor(p) is None

def test_build_keywords_title_target():
    assert build_keywords(["디오망데", "히메네스"]) == [
        {"keyword": "디오망데", "target": "title"},
        {"keyword": "히메네스", "target": "title"}]

def test_next_cursor_advances_to_slice_end():
    assert next_cursor([30, 40, 50], search_failures=0) == 50

def test_next_cursor_holds_on_search_failure():
    # 검색 실패 시 커서 유지 — 같은 슬라이스 재시도 (스펙 §6)
    assert next_cursor([30, 40, 50], search_failures=1) is None

def test_next_cursor_none_on_empty_slice():
    assert next_cursor([], search_failures=0) is None
