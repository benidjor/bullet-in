import bullet_in.transfer_stage as ts


def test_sidebar_stages_order_and_count():
    enums = [e for e, _, _ in ts.SIDEBAR_STAGES]
    assert enums == ["official", "medical", "personal_terms",
                     "negotiating", "interest", "rumour"]


def test_label_and_css_lookup():
    assert ts.label_for("official") == "오피셜"
    assert ts.label_for("personal_terms") == "개인 합의"
    assert ts.css_for("interest") == "s-interest"
    assert ts.label_for("other") == ""   # other는 라벨 없음


def test_normalize_keeps_valid_else_other():
    assert ts.normalize("medical") == "medical"
    assert ts.normalize("other") == "other"
    assert ts.normalize("bogus") == "other"
    assert ts.normalize(None) == "other"


def test_is_displayable_excludes_other_and_none():
    assert ts.is_displayable("rumour") is True
    assert ts.is_displayable("other") is False
    assert ts.is_displayable(None) is False
