"""roster 모듈 단위 테스트."""
from bullet_in.roster import normalize_pairs


def test_normalize_pairs_validates_and_normalizes():
    raw = [{"full_name": "Bruno Guimaraes", "ko": "기마랑이스", "stage": "personal_terms"},
           {"full_name": "", "ko": "x", "stage": "rumour"},          # 이름 없음 → drop
           {"full_name": "Nico Williams", "stage": "발표"},           # 비enum → other
           {"full_name": "Someone", "ko": "누군가", "stage": "official"},  # 규칙 경로 전용 → agreed
           "잘못된 항목",                                              # dict 아님 → drop
           {"full_name": "bruno guimarães", "ko": "기마랑", "stage": "agreed"}]  # 중복 → drop
    out = normalize_pairs(raw)
    assert [p["full_name"] for p in out] == ["Bruno Guimaraes", "Nico Williams", "Someone"]
    assert out[1]["stage"] == "other"
    assert out[2]["stage"] == "agreed"


def test_normalize_pairs_tolerates_non_list():
    assert normalize_pairs(None) == []
    assert normalize_pairs("아무거나") == []
