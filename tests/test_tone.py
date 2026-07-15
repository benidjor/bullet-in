from bullet_in.tone import has_polite_ending, select_tone_backfill

def _row(h, s, s3=None):
    return {"content_hash": h, "summary_ko": s, "summary3_ko": s3}

def test_select_picks_rows_flagged_in_either_field():
    rows = [_row("a", "합의했다."),
            _row("b", "합의했습니다."),
            _row("c", "협상했다.", "발표했다.\n메디컬이 남았습니다.")]
    picked = select_tone_backfill(rows, limit=10)
    assert [r["content_hash"] for r in picked] == ["b", "c"]

def test_select_respects_limit():
    rows = [_row(str(i), "확정했습니다.") for i in range(5)]
    assert len(select_tone_backfill(rows, limit=2)) == 2

def test_select_empty_pool_returns_empty():
    assert select_tone_backfill([], limit=20) == []

def test_detects_hamnida_ending():
    assert has_polite_ending("아스날이 기마랑이스 영입에 합의했습니다.")

def test_detects_haeyo_ending():
    assert has_polite_ending("이적료는 협상 중이에요.")

def test_passes_plain_reportive_ending():
    assert not has_polite_ending("아스날이 기마랑이스 영입에 합의했다.")

def test_quoted_polite_speech_is_ignored():
    assert not has_polite_ending('킴은 "우리는 준비돼 있습니다"라고 말했다.')

def test_multiline_summary3_detects_any_sentence():
    s3 = "아스날이 합의했다.\n메디컬이 남았습니다.\n발표는 임박했다."
    assert has_polite_ending(s3)

def test_polite_stem_mid_sentence_is_not_flagged():
    # '필요'처럼 '요'로 끝나는 명사 · 문장 중간의 존댓말 어간은 잡지 않는다
    assert not has_polite_ending("추가 보강이 필요하다는 관측이 나왔다.")

def test_curly_quoted_polite_speech_is_ignored():
    s = "킴은 다음과 같이 말했다. “우리는 준비돼 있습니다. 발표는 곧 있을 예정입니다.” 그는 웃으며 자리를 떴다."
    assert not has_polite_ending(s)

def test_none_and_empty_are_false():
    assert not has_polite_ending(None)
    assert not has_polite_ending("")

def test_plain_anida_ending_is_not_flagged():
    # '아니다'는 평어체 — '~니다' 패턴 오탐 회귀 방지 (2026-07-15 본문 백필에서 실측)
    assert not has_polite_ending("프리미어리그 우승 후, 이는 쉬운 과제가 아니다.")

def test_polite_animnida_is_still_flagged():
    assert has_polite_ending("이는 쉬운 과제가 아닙니다.")
