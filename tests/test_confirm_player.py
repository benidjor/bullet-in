from bullet_in.confirm_player import recheck_titles, surname_warning


def test_surname_warning_on_two_words():
    assert surname_warning("Van Dijk") is not None    # 가드 축 조용한 꺼짐 경고 (스펙 §3.3)
    assert surname_warning("Gyokeres") is None


def _row(**kw):
    base = {"content_hash": "h1", "source_id": "skysports",
            "title_original": "Arsenal agree Nico Williams deal",
            "title_ko": "아스날, 니코 윌리엄스 합의", "body_source": "Nico Williams ...",
            "body_excerpt": None}
    return {**base, **kw}


def test_recheck_flags_hallucinated_name():
    # 확장된 사전 기준으로 원문에 근거 없는 인명이 제목에 있으면 의심
    rows = [_row(title_ko="아스날, 윌리엄스 대신 조르제 영입",
                 title_original="Arsenal agree Nico Williams deal")]
    assert recheck_titles(rows, {"조르제": "Djordje", "윌리엄스": "Williams"}) == ["h1"]


def test_recheck_passes_grounded_title():
    rows = [_row()]
    assert recheck_titles(rows, {"윌리엄스": "Williams"}) == []


def test_recheck_skips_rows_without_translation():
    rows = [_row(title_ko=None)]
    assert recheck_titles(rows, {"윌리엄스": "Williams"}) == []


def test_recheck_excludes_roundup_reverse_axis():
    # bbc_gossip 은 제목 재초점이 정상 — 역방향 (인명 누락) 축 제외 (finalize 와 동일 규칙)
    rows = [_row(source_id="bbc_gossip", title_ko="아스날 이적 소식 모음",
                 title_original="Nico Williams to Arsenal gossip",
                 body_source="Nico Williams ...")]
    assert recheck_titles(rows, {"윌리엄스": "Williams"}) == []
