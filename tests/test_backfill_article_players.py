from bullet_in.backfill_article_players import filter_targets, load_state, append_state


def test_filter_targets_excludes_state(tmp_path):
    state = tmp_path / "state.txt"
    append_state(state, "h1")
    rows = [{"content_hash": "h1"}, {"content_hash": "h2"}]
    assert [r["content_hash"] for r in filter_targets(rows, load_state(state))] == ["h2"]


def test_load_state_missing_file_is_empty(tmp_path):
    assert load_state(tmp_path / "none.txt") == set()


def test_append_state_accumulates(tmp_path):
    state = tmp_path / "state.txt"
    append_state(state, "h1")
    append_state(state, "h2")
    assert load_state(state) == {"h1", "h2"}
