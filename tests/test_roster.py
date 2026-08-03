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


def test_normalize_pairs_caps_array_at_30():
    raw = [{"full_name": f"Player {i}", "ko": "선수", "stage": "rumour"}
           for i in range(31)]
    out = normalize_pairs(raw)
    assert len(out) == 30
    assert [p["full_name"] for p in out] == [f"Player {i}" for i in range(30)]


def test_normalize_pairs_drops_full_name_over_100_chars():
    raw = [{"full_name": "A" * 101, "ko": "긴이름", "stage": "rumour"},
           {"full_name": "A" * 100, "ko": "긴이름", "stage": "rumour"}]
    out = normalize_pairs(raw)
    assert [p["full_name"] for p in out] == ["A" * 100]


def test_normalize_pairs_blanks_ko_over_50_chars():
    raw = [{"full_name": "Someone Long", "ko": "가" * 51, "stage": "rumour"}]
    out = normalize_pairs(raw)
    assert len(out) == 1
    assert out[0]["ko"] is None                # 항목은 유지, ko 만 None


def test_normalize_pairs_drops_hangul_full_name():
    raw = [{"full_name": "손흥민", "ko": "손흥민", "stage": "rumour"},
           {"full_name": "Son Heung-min", "ko": "손흥민", "stage": "rumour"}]
    out = normalize_pairs(raw)
    assert [p["full_name"] for p in out] == ["Son Heung-min"]


def test_normalize_pairs_keeps_official_for_arsenal_official():
    raw = [{"full_name": "Martin Zubimendi", "ko": "수비멘디", "stage": "official"}]
    out = normalize_pairs(raw, "arsenal_official")
    assert out[0]["stage"] == "official"


def test_normalize_pairs_demotes_official_for_other_sources():
    raw = [{"full_name": "Martin Zubimendi", "ko": "수비멘디", "stage": "official"}]
    assert normalize_pairs(raw, "bbc_sport")[0]["stage"] == "agreed"
    assert normalize_pairs(raw, None)[0]["stage"] == "agreed"
    assert normalize_pairs(raw)[0]["stage"] == "agreed"        # 인자 생략 = 강등


def test_normalize_pairs_arsenal_official_does_not_promote_other_stages():
    raw = [{"full_name": "Someone", "ko": "누군가", "stage": "rumour"},
           {"full_name": "Another One", "ko": "다른이", "stage": "발표"}]
    out = normalize_pairs(raw, "arsenal_official")
    assert [p["stage"] for p in out] == ["rumour", "other"]
