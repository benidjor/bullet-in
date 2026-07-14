from bullet_in.tone import has_polite_ending

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

def test_none_and_empty_are_false():
    assert not has_polite_ending(None)
    assert not has_polite_ending("")
