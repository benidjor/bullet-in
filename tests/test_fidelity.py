from bullet_in.fidelity import (RETENTION_THRESHOLD, char_ngram_retention,
                                gate_verdict, missing_numbers, select_best)


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
