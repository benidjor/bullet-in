from bullet_in import backfill_fmkorea_body as bf


def test_match_targets_pairs_exact_titles_only():
    targets = {"h1": "[텔레그래프] 아스날 수비 보강", "h2": "[더 타임스] 미드필더 관심"}
    found = [("[텔레그래프] 아스날 수비 보강", "https://www.fmkorea.com/111"),
             ("[더 타임스] 미드필더 관심 (수정)", "https://www.fmkorea.com/222")]
    assert bf.match_targets(targets, found) == {"h1": "https://www.fmkorea.com/111"}


def test_match_targets_ignores_surrounding_whitespace():
    targets = {"h1": "[BBC] 아스날 소식"}
    found = [("  [BBC] 아스날 소식 ", "https://www.fmkorea.com/1")]
    assert bf.match_targets(targets, found) == {"h1": "https://www.fmkorea.com/1"}


def test_row_update_extracts_body_and_journalist():
    html = ('<div class="rd_body"><div class="xe_content">'
            '<p>By David Ornstein June 19, 2026 3:19 am 리버풀이 협상 중이다.</p>'
            '</div></div>')
    upd = bf.row_update(html, ".xe_content")
    assert upd["body_level"] == 1
    assert "June 19, 2026" not in upd["body"]
    assert "By David Ornstein" in upd["body"]
    assert upd["journalist"] == "David Ornstein"


def test_row_update_returns_none_when_repost_blocked():
    html = ('<div class="rd_body"><div class="xe_content"><p>본문.</p></div>'
            '<strong>[퍼가기가 금지된 글입니다]</strong></div>')
    assert bf.row_update(html, ".xe_content") is None


def test_row_update_returns_none_when_body_empty():
    assert bf.row_update('<div class="rd_body"></div>', ".xe_content") is None
