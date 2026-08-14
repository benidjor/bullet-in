from bullet_in.backfill_authors import authors_for


def _row(**kw):
    base = {"content_hash": "h1", "source_id": "bbc_sport",
            "journalist": None, "body_source": None}
    base.update(kw)
    return base


def test_uses_collected_author_list_when_present():
    row = _row(journalist="Alastair Telfer")
    assert authors_for(row, ["Alastair Telfer", "Sami Mokbel"]) == [
        "Alastair Telfer", "Sami Mokbel"]


def test_splits_author_stored_as_one_string_by_the_old_rule():
    # 수집 시점 규칙은 ' and ' 를 구분자로 안 봐서 두 사람이 한 칸에 들어 있다
    assert authors_for(_row(), ["Sam Blitz and Nick Wright"]) == ["Sam Blitz", "Nick Wright"]


def test_reparses_fmkorea_body_byline():
    row = _row(source_id="fmkorea", journalist="David Ornstein",
               body_source="By David Ornstein and James McNicholas 아스날이")
    assert authors_for(row, None) == ["David Ornstein", "James McNicholas"]


def test_drops_stored_representative_polluted_with_a_month_token():
    # 운영 6건 — 파서가 축약형 월을 이름에 붙여 저장했다 (그 표기가 항목으로 샌다)
    row = _row(source_id="fmkorea", journalist="Conor O'Neill Aug",
               body_source="By Conor O'Neill Aug. 2, 2026 아스날이")
    assert authors_for(row, None) == ["Conor O'Neill"]


def test_keeps_bracket_journalist_that_body_byline_does_not_cover():
    row = _row(source_id="fmkorea", journalist="온스테인",
               body_source="By David Ornstein 아스날이")
    assert authors_for(row, None) == ["온스테인", "David Ornstein"]


def test_splits_stored_composite_journalist_for_other_sources():
    row = _row(source_id="x_afcstuff", journalist="잭 로서, 사이먼 콜링스")
    assert authors_for(row, None) == ["잭 로서", "사이먼 콜링스"]


def test_empty_when_there_is_no_byline_anywhere():
    assert authors_for(_row(source_id="fmkorea", body_source="아스날이 영입한다."), None) == []


from bullet_in.backfill_authors import cleaned_journalist


def test_cleans_representative_that_only_adds_a_date_fragment():
    row = _row(journalist="David Ornstein Aug")
    assert cleaned_journalist(row, ["David Ornstein"]) == "David Ornstein"


def test_leaves_representative_alone_when_it_is_a_real_name():
    assert cleaned_journalist(_row(journalist="David Ornstein"), ["David Ornstein"]) is None
    assert cleaned_journalist(_row(journalist="온스테인"), ["David Ornstein"]) is None


def test_leaves_composite_representative_alone():
    # 합성 문자열을 첫 저자로 갈아 끼우면 등재 기자 우선 규칙이 죽는다
    # ('잭 로서, 사이먼 콜링스' 는 등재된 사이먼 콜링스가 대표여야 한다)
    row = _row(source_id="x_afcstuff", journalist="잭 로서, 사이먼 콜링스")
    assert cleaned_journalist(row, ["잭 로서", "사이먼 콜링스"]) is None
