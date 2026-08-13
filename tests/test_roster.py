"""roster 모듈 단위 테스트."""
from bullet_in.roster import decide_role, duplicate_suspects, normalize_pairs


def test_normalize_pairs_validates_and_normalizes():
    raw = [{"full_name": "Bruno Guimaraes", "ko": "기마랑이스", "stage": "personal_terms"},
           {"full_name": "", "ko": "x", "stage": "rumour"},          # 이름 없음 → drop
           {"full_name": "Nico Williams", "stage": "발표"},           # 비enum → other
           {"full_name": "Someone", "ko": "누군가", "stage": "official"},  # 규칙 경로 전용 → done
           "잘못된 항목",                                              # dict 아님 → drop
           {"full_name": "bruno guimarães", "ko": "기마랑", "stage": "agreed"}]  # 중복 → drop
    out = normalize_pairs(raw)
    assert [p["full_name"] for p in out] == ["Bruno Guimaraes", "Nico Williams", "Someone"]
    assert out[1]["stage"] == "other"
    assert out[2]["stage"] == "done"


def test_normalize_pairs_official_pin_follows_accept_path():
    raw = [{"full_name": "Christian Norgaard", "ko": "뇌르고르", "stage": "done"},
           {"full_name": "Someone Else", "ko": "누군가", "stage": "agreed"}]
    tagged = normalize_pairs(raw, "arsenal_official")
    assert [p["stage"] for p in tagged] == ["official", "official"]
    # 제목 채택분은 고정에서 빠지되, 모델이 완료로 읽은 선수는 오피셜로 올라간다
    # (2026-08-13 개정) — 기사 단위와 같은 판정이라 한 기사가 두 화면에서 갈리지 않는다
    titled = normalize_pairs(raw, "arsenal_official", accept_path="title")
    assert [p["stage"] for p in titled] == ["official", "agreed"]


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
    # 강등 목적지는 기사 단위 경로와 동일하게 done (단계 재정의 스펙 2026-08-10 §4)
    raw = [{"full_name": "Martin Zubimendi", "ko": "수비멘디", "stage": "official"}]
    assert normalize_pairs(raw, "bbc_sport")[0]["stage"] == "done"
    assert normalize_pairs(raw, None)[0]["stage"] == "done"
    assert normalize_pairs(raw)[0]["stage"] == "done"          # 인자 생략 = 강등


def test_normalize_pairs_overwrites_stage_for_arsenal_official():
    # 추출 프롬프트가 official 을 선택지에서 배제하므로 모델은 agreed 를 답한다
    # — 유지 방식으로는 승격이 일어나지 않아 규칙으로 덮어쓴다
    raw = [{"full_name": "Martin Zubimendi", "ko": "수비멘디", "stage": "agreed"},
           {"full_name": "Someone Else", "ko": "누군가", "stage": "rumour"},
           {"full_name": "Third Guy", "ko": "셋째", "stage": "발표"}]
    out = normalize_pairs(raw, "arsenal_official")
    assert [p["stage"] for p in out] == ["official", "official", "official"]


def test_normalize_pairs_does_not_overwrite_for_other_sources():
    raw = [{"full_name": "Martin Zubimendi", "ko": "수비멘디", "stage": "agreed"},
           {"full_name": "Someone Else", "ko": "누군가", "stage": "rumour"}]
    out = normalize_pairs(raw, "bbc_sport")
    assert [p["stage"] for p in out] == ["agreed", "rumour"]


def test_normalize_pairs_normalizes_role_and_drops_unknown():
    # 어휘 밖 · 미기입은 None — 서빙이 옛 규칙으로 판정해 종전 화면을 유지한다 (스펙 §3.2)
    raw = [{"full_name": "Christos Tzolis", "ko": "촐리스", "stage": "interest",
            "role": " Subject "},
           {"full_name": "Morgan Rogers", "ko": "로저스", "stage": "other",
            "role": "mention"},
           {"full_name": "Ben White", "ko": "화이트", "stage": "other",
            "role": "배경"},
           {"full_name": "Bukayo Saka", "ko": "사카", "stage": "other"}]
    assert [p["role"] for p in normalize_pairs(raw)] == [
        "subject", "mention", None, None]


def test_normalize_pairs_applies_glossary_to_ko():
    # 추출은 영문 원문을 읽고 한글 표기를 직접 만들어 음역이 회차마다 흔들린다
    # — 후보 등재 이름이 오표기로 들어가는 것을 사전이 막는다 (스펙 §8.4)
    raw = [{"full_name": "Christos Tzolis", "ko": "졸리스", "stage": "interest"}]
    out = normalize_pairs(raw, glossary={"졸리스": "촐리스"})
    assert out[0]["ko"] == "촐리스"


def test_normalize_pairs_without_glossary_keeps_ko():
    raw = [{"full_name": "Christos Tzolis", "ko": "졸리스", "stage": "interest"}]
    assert normalize_pairs(raw)[0]["ko"] == "졸리스"


# ---------------------------------------------------------------- 역할 규칙

def _article(title_ko="", title_original="", body_ko=""):
    return {"title_ko": title_ko, "title_original": title_original,
            "body_ko": body_ko}


TZOLIS = {"full_name": "Christos Tzolis", "ko": "촐리스", "stage": "interest",
          "role": None}


def test_decide_role_subject_when_translated_title_has_name():
    art = _article(title_ko="아스날, 크리스토스 촐리스 영입 합의")
    assert decide_role(art, TZOLIS) == "subject"


def test_decide_role_subject_when_original_title_has_name():
    art = _article(title_ko="아스날, 그리스 공격수 영입",
                   title_original="Arsenal sign Christos Tzolis")
    assert decide_role(art, TZOLIS) == "subject"


def test_decide_role_subject_when_subheading_has_name():
    art = _article(title_ko="아스날 여름 이적시장 총정리",
                   body_ko="첫 문단\n### 촐리스 영입 배경\n아스날이 촐리스 영입에 합의했다")
    assert decide_role(art, TZOLIS) == "subject"


def test_decide_role_mention_when_subheading_name_is_absent_from_its_section():
    # fmkorea 전재가 원문의 관련기사 헤더만 끌어와 소제목에만 이름이 남는다 (`ad4e18de`)
    art = _article(title_ko="아스날, 브루노 기마랑이스 영입 근접",
                   body_ko="### 아스날 유망주 촐리스, 도르트문트의 관심 끌어\n"
                           "아스날은 기마랑이스 영입을 원한다")
    assert decide_role(art, TZOLIS) == "mention"


def test_decide_role_mention_when_name_is_absent_from_title_and_subheadings():
    art = _article(title_ko="아스날, 브루노 기마랑이스 영입 합의",
                   title_original="Arsenal agree Guimaraes fee",
                   body_ko="본문에 촐리스가 나오지만 제목 · 소제목에는 없다")
    assert decide_role(art, TZOLIS) == "mention"


def test_decide_role_model_veto_downgrades_title_only_subject():
    # 제목만 근거일 때에 한해 모델이 언급이라 하면 내린다 (스펙 §5.1 ④)
    art = _article(title_ko="아스날이 노리는 선수 명단에 촐리스")
    assert decide_role(art, {**TZOLIS, "role": "mention"}) == "mention"


def test_decide_role_model_veto_does_not_apply_to_subheading_evidence():
    art = _article(title_ko="아스날 여름 이적시장 총정리",
                   body_ko="### 촐리스 영입 배경\n아스날이 촐리스 영입에 합의했다")
    assert decide_role(art, {**TZOLIS, "role": "mention"}) == "subject"


def test_decide_role_model_subject_cannot_overturn_rule_mention():
    art = _article(title_ko="아스날, 브루노 기마랑이스 영입 합의")
    assert decide_role(art, {**TZOLIS, "role": "subject"}) == "mention"


TROSSARD = {"full_name": "Leandro Trossard", "ko": "트로사르", "stage": "done",
            "role": "subject"}


def test_decide_role_mention_when_named_as_the_replaced_player_in_subheading():
    # 촐리스 영입 기사이고 트로사르는 비교 기준점이다 (`b8055b5b`)
    art = _article(title_ko="아스날, 클뤼프 브뤼허 윙어 촐리스 영입 합의",
                   body_ko="### 촐리스가 트로사르의 완벽한 대체자인 이유\n"
                           "촐리스는 트로사르의 직접적인 대체자로 합류한다")
    assert decide_role(art, TROSSARD) == "mention"


def test_decide_role_mention_when_named_as_the_replaced_player_in_title():
    # 제목 경로도 같다 — 소제목만 보는 규칙으로는 이 두 건을 못 잡는다 (`681dfde6`)
    art = _article(title_ko="아스날, 레안드로 트로사르 대체자로 촐리스 영입 추진")
    assert decide_role(art, TROSSARD) == "mention"


def test_decide_role_original_title_cannot_revive_the_replaced_player():
    # 같은 기사의 두 표현이라 번역 제목이 대체 대상으로 부르면 원제도 근거가 아니다 (`b5d9f90a`)
    art = _article(title_ko="아스날, 레안드로 트로사르 대체자로 촐리스 영입 공식 발표",
                   title_original="Officially: Arsenal announce deal for Trossard's replacement")
    assert decide_role(art, TROSSARD) == "mention"


def test_decide_role_subject_for_the_signing_named_after_the_replaced_player():
    # 같은 줄이라도 「대체자」 뒤에 오는 이름은 영입되는 쪽이다
    art = _article(title_ko="아스날, 레안드로 트로사르 대체자로 촐리스 영입 추진")
    assert decide_role(art, TZOLIS) == "subject"


def test_decide_role_subject_when_replacement_word_is_far_from_the_name():
    # 갈라타사라이가 그를 노리는 기사다 — 「대체자」 는 아스날이 찾을 선수를 가리킨다 (`0f2fbcd4`)
    art = _article(title_ko="갈라타사라이, 마르티넬리 영입 추진…아스날은 대체자 물색이 우선")
    martinelli = {"full_name": "Gabriel Martinelli", "ko": "마르티넬리",
                  "stage": "interest", "role": "subject"}
    assert decide_role(art, martinelli) == "subject"


def test_decide_role_matches_roster_form_when_model_spelling_differs():
    # 음역 흔들림은 유사도가 아니라 명단 표기와의 직접 일치가 잡는다 (스펙 §5.1)
    art = _article(title_ko="아스날, 크리스토스 촐리스 영입 합의")
    forms = {"full_name": "Christos Tzolis", "surname": "Tzolis",
             "ko_name": "촐리스", "ko_full_name": "크리스토스 촐리스"}
    assert decide_role(art, {**TZOLIS, "ko": "졸리스"}, forms) == "subject"


def test_decide_role_ignores_spacing_in_korean_names():
    art = _article(title_ko="아스날, 가브리엘제주스 매각 검토")
    pair = {"full_name": "Gabriel Jesus", "ko": "가브리엘 제주스",
            "stage": "other", "role": None}
    assert decide_role(art, pair) == "subject"


def test_decide_role_ignores_diacritics_in_latin_names():
    art = _article(title_ko="아스날 여름 계획",
                   title_original="Arsenal open talks for Gyökeres")
    pair = {"full_name": "Viktor Gyokeres", "ko": "요케레스",
            "stage": "interest", "role": None}
    assert decide_role(art, pair) == "subject"


def test_decide_role_drops_too_short_latin_candidates():
    # 세 글자 이하 라틴 후보는 일반 단어에 걸린다 — 후보에서 뺀다
    art = _article(title_ko="아스날 소식", title_original="Arsenal eye a new deal")
    pair = {"full_name": "Eye", "ko": "아이", "stage": "other", "role": None}
    assert decide_role(art, pair) == "mention"


# ---------------------------------------------------------------- 중복 후보 감지

def test_duplicate_suspects_flags_same_surname_with_near_first_name():
    existing = [{"id": 7, "full_name": "Ilan Meslier", "surname": "Meslier"}]
    assert duplicate_suspects("Illan Meslier", "Meslier", existing) == [
        {"id": 7, "full_name": "Ilan Meslier"}]


def test_duplicate_suspects_flags_nico_and_neco_williams():
    # 편집거리 2 · 한글 표기까지 같지만 다른 선수다 — 그래서 병합하지 않고 알리기만 한다
    existing = [{"id": 3, "full_name": "Neco Williams", "surname": "Williams"}]
    assert [s["id"] for s in
            duplicate_suspects("Nico Williams", "Williams", existing)] == [3]


def test_duplicate_suspects_ignores_different_surname():
    existing = [{"id": 3, "full_name": "Neco Williams", "surname": "Williams"}]
    assert duplicate_suspects("Nico Wilson", "Wilson", existing) == []


def test_duplicate_suspects_ignores_distant_first_name():
    existing = [{"id": 3, "full_name": "Harvey White", "surname": "White"}]
    assert duplicate_suspects("Ben White", "White", existing) == []
