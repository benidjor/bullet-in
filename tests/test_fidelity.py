from bullet_in.fidelity import (RETENTION_THRESHOLD, char_ngram_retention,
                                extra_numbers, gate_verdict, missing_numbers, missing_quotes, quote_spans, select_best)


def test_missing_numbers_reports_dropped_token():
    src = "아스날이 £50m 을 제안했고 계약은 2031년까지다."
    out = "아스날이 £50m 을 제안했다."
    assert missing_numbers(src, out) == ["2031"]


def test_missing_numbers_ignores_unit_conversion():
    # €80m → 8,000만 유로는 같은 값을 옮겨 적은 것이다 (트러블슈팅 §2.1)
    src = "이적료는 €80m 이다."
    out = "이적료는 8,000만 유로다."
    assert missing_numbers(src, out) == []


def test_missing_numbers_ignores_url_digits():
    # 본문 끝 원문 링크의 기사 ID · 날짜 경로가 원문 숫자로 잡히던 결함 (트러블슈팅 §2.3)
    src = "아스날 소식. https://www.nytimes.com/athletic/7404309/2026/07/24/arsenal/"
    out = "아스날 소식이다."
    assert missing_numbers(src, out) == []


def test_missing_numbers_ignores_byline_datetime():
    # 발행 시각은 바꿔 쓸 수 없어 '빠뜨리지 마라' 와 '베끼지 마라' 가 양립하지 않는다
    src = "By David Ornstein June 19, 2026 3:19 am 리버풀이 협상 중이다."
    out = "리버풀이 협상을 진행하고 있다."
    assert missing_numbers(src, out) == []


def test_missing_numbers_empty_when_source_has_no_digits():
    assert missing_numbers("아스날이 승리했다.", "아스날이 이겼다.") == []


def test_char_ngram_retention_is_one_for_verbatim_copy():
    text = "아스날이 비니시우스 주니오르 영입을 추진하고 있다는 보도가 나왔다."
    assert char_ngram_retention(text, text) == 1.0


def test_char_ngram_retention_is_zero_for_unrelated_text():
    src = "아스날이 비니시우스 주니오르 영입을 추진한다."
    out = "리버풀은 수비 보강에 집중하고 있는 상황이다."
    assert char_ngram_retention(src, out) == 0.0


def test_char_ngram_retention_zero_when_output_shorter_than_window():
    assert char_ngram_retention("아스날이 승리했다.", "승리") == 0.0


def test_gate_verdict_passes_clean_rewrite():
    src = "아스날이 £50m 을 제안했다. 계약 기간은 2031년까지로 알려졌다."
    out = "아스날은 £50m 규모의 제안을 건넸고, 계약은 2031년까지로 전해졌다."
    v = gate_verdict(src, out, threshold=0.9)
    assert v["missing"] == [] and v["ok"] is True


def test_gate_verdict_fails_on_missing_number():
    src = "아스날이 £50m 을 제안했다. 계약은 2031년까지다."
    out = "아스날이 제안을 건넸다."
    v = gate_verdict(src, out)
    assert v["missing"] and v["ok"] is False


def test_gate_verdict_fails_on_verbatim_copy():
    text = "아스날이 비니시우스 주니오르 영입을 추진하고 있다는 보도가 나왔다."
    v = gate_verdict(text, text)
    assert v["missing"] == []
    assert v["retention"] == 1.0 and v["ok"] is False


def test_select_best_prefers_no_missing_then_lowest_retention():
    attempts = [
        {"parsed": {"body_ko": "A"}, "missing": [], "retention": 0.80},
        {"parsed": {"body_ko": "B"}, "missing": [], "retention": 0.42},
        {"parsed": {"body_ko": "C"}, "missing": ["2031"], "retention": 0.20},
    ]
    assert select_best(attempts)["parsed"]["body_ko"] == "B"


def test_select_best_falls_back_to_fewest_missing():
    # 본문을 버리지 않는 설계 — 전부 누락이 있어도 하나는 채택한다 (스펙 §4.4)
    attempts = [
        {"parsed": {"body_ko": "A"}, "missing": ["1", "2", "3"], "retention": 0.20},
        {"parsed": {"body_ko": "B"}, "missing": ["1"], "retention": 0.70},
    ]
    assert select_best(attempts)["parsed"]["body_ko"] == "B"


def test_threshold_default_is_documented_value():
    assert RETENTION_THRESHOLD == 0.75


def test_extra_numbers_flags_invented_figure():
    src = "아스날이 5,000만 파운드를 제안했다."
    out = "아스날이 5,000만 파운드를 제안했고 계약 기간은 3년이다."
    assert extra_numbers(src, out) == ["3"]


def test_extra_numbers_allows_unit_conversion():
    src = "아스날이 £50m 을 제안했다."
    out = "아스날이 5,000만 파운드를 제안했다."
    assert extra_numbers(src, out) == []


def test_extra_numbers_ignores_url_and_publish_date():
    src = "아스날 소식."
    out = "아스날 소식. https://ex.test/2026/07/31 July 24, 2026 기준이다."
    assert extra_numbers(src, out) == []


def test_quote_spans_collects_both_quote_marks():
    text = '그는 “우리는 준비됐다” 고 했고 감독은 "시간이 필요하다" 고 했다.'
    assert quote_spans(text) == ["우리는 준비됐다", "시간이 필요하다"]


def test_missing_quotes_flags_rewritten_quote():
    src = '아르테타는 “우리는 더 나은 선수가 필요하다” 고 말했다.'
    out = '아르테타는 “더 좋은 선수가 있어야 한다” 고 말했다.'
    assert missing_quotes(src, out) == ["우리는 더 나은 선수가 필요하다"]


def test_missing_quotes_passes_preserved_quote():
    src = '아르테타는 “우리는 더 나은 선수가 필요하다” 고 말했다.'
    out = '감독은 “우리는 더 나은 선수가 필요하다” 는 말을 남겼다.'
    assert missing_quotes(src, out) == []


def test_missing_quotes_ignores_whitespace_change():
    src = '그는 “우리는  준비됐다” 고 했다.'
    out = '그는 “우리는 준비됐다” 고 했다.'
    assert missing_quotes(src, out) == []




def test_missing_quotes_flags_rewritten_straight_quote():
    # 곧은따옴표 (U+0022) 경로 — 굽은따옴표 테스트와 짝을 이룬다
    src = '아르테타는 "우리는 더 나은 선수가 필요하다" 고 말했다.'
    out = '아르테타는 "더 좋은 선수가 있어야 한다" 고 말했다.'
    assert missing_quotes(src, out) == ["우리는 더 나은 선수가 필요하다"]


def test_gate_verdict_fails_on_invented_number():
    src = "아스날이 £50m 을 제안했다."
    out = "아스날이 5,000만 파운드를 제안했고 계약은 3년이다."
    v = gate_verdict(src, out)
    assert v["extra"] == ["3"]
    assert v["ok"] is False


def test_gate_verdict_fails_on_broken_quote():
    src = '그는 "우리는 준비가 됐다" 고 말했다.'
    out = '그는 "준비는 끝났다" 고 밝혔다.'
    v = gate_verdict(src, out)
    assert v["quotes"] == ["우리는 준비가 됐다"]
    assert v["ok"] is False


def test_select_best_prefers_fewest_violations():
    a = {"parsed": "a", "missing": [], "extra": ["3"], "quotes": [],
         "names": [], "clubs": [], "retention": 0.1}
    b = {"parsed": "b", "missing": [], "extra": [], "quotes": [],
         "names": [], "clubs": [], "retention": 0.6}
    assert select_best([a, b])["parsed"] == "b"


def test_select_best_rejects_verbatim_copy_over_real_rewrite():
    # 복제본은 어느 축도 어기지 않아 위반 0 이 된다 — 잔존율을 위반으로 세지
    # 않으면 진짜 재작성을 언제나 이긴다.
    copy = {"parsed": {"body_ko": "복제"}, "missing": [], "extra": [],
            "quotes": [], "names": [], "clubs": [], "retention": 0.96}
    real = {"parsed": {"body_ko": "재작성"}, "missing": [], "extra": ["3"],
            "quotes": [], "names": [], "clubs": [], "retention": 0.18}
    assert select_best([copy, real])["parsed"]["body_ko"] == "재작성"
