import bullet_in.transfer_stage as ts


def test_sidebar_stages_order_and_count():
    # 진행 단계 순 (사다리 스펙 §4.1 · 단계 재정의 스펙 2026-08-10 §3.1) — 화면 순서
    # (render._STAGE_DISPLAY_GROUPS) 가 정답이고, medical 은 이적 합의 묶음의 짝이라
    # agreed 바로 뒤에 둔다. collapsed 는 종결이라 맨 뒤다.
    enums = [e for e, _, _ in ts.SIDEBAR_STAGES]
    assert enums == ["official", "done", "agreed", "medical",
                     "personal_terms", "negotiating", "interest", "rumour",
                     "collapsed"]


def test_label_and_css_lookup():
    assert ts.label_for("official") == "오피셜"
    assert ts.label_for("personal_terms") == "개인 합의"
    assert ts.css_for("interest") == "s-interest"
    assert ts.label_for("other") == ""   # other는 라벨 없음
    assert ts.label_for("agreed") == "이적 합의"
    assert ts.css_for("agreed") == "s-agree"
    assert ts.label_for("done") == "이적 완료"
    assert ts.css_for("done") == "s-done"
    assert ts.label_for("collapsed") == "무산"
    assert ts.css_for("collapsed") == "s-collapsed"


def test_normalize_keeps_valid_else_other():
    assert ts.normalize("medical") == "medical"
    assert ts.normalize("other") == "other"
    assert ts.normalize("bogus") == "other"
    assert ts.normalize(None) == "other"


def test_is_displayable_excludes_other_and_none():
    assert ts.is_displayable("rumour") is True
    assert ts.is_displayable("other") is False
    assert ts.is_displayable(None) is False


def test_rule_stage_returns_stage_direction_pairs():
    # 규칙 경로 2형태 (스펙 2026-08-02 §4.1) — 공홈은 stage 만 고정 (방향은 LLM 몫),
    # 가십은 둘 다 고정 (다주제 라운드업은 대표 단계 · 방향이 성립하지 않음)
    assert ts.rule_stage("arsenal_official") == ("official", None)
    assert ts.rule_stage("bbc_gossip") == ("rumour", "none")
    assert ts.rule_stage("bbc_sport") == (None, None)
    assert ts.rule_stage(None) == (None, None)


def test_rule_stage_skips_official_for_title_accepted_articles():
    # 구단이 이적 태그를 붙인 기사에만 오피셜 근거가 있다 — 우리 제목 추측으로 주워 온
    # 기사는 LLM 분류에 맡긴다 (공홈 수집 개정 스펙 2026-08-12 §3.3).
    assert ts.rule_stage("arsenal_official", "tag") == ("official", None)
    assert ts.rule_stage("arsenal_official", "title") == (None, None)
    # 개정 전 적재분은 값이 없다 — 전건 태그 채택이었으므로 고정을 유지한다
    assert ts.rule_stage("arsenal_official", None) == ("official", None)
    assert ts.rule_stage("bbc_gossip", "title") == ("rumour", "none")


def test_normalize_direction_keeps_valid_else_none():
    assert ts.normalize_direction("in") == "in"
    assert ts.normalize_direction("out") == "out"
    assert ts.normalize_direction("none") == "none"
    assert ts.normalize_direction("bogus") == "none"
    assert ts.normalize_direction(None) == "none"
