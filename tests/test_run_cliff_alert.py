from contextlib import contextmanager

from bullet_in.run import cliff_alert_payload


class _Adapter:
    def __init__(self, source_id, codes=None):
        self.source_id = source_id
        if codes is not None:
            self.search_failure_codes = codes


def test_payload_none_when_no_history():
    """첫 회차 — 직전 행이 없으면 판정하지 않는다."""
    assert cliff_alert_payload({"goal": 14}, [], adapters=[], sources={},
                               success_rate=1.0, run_id="r") is None


def test_payload_none_when_no_cliff():
    history = [{"goal": 13, "fmkorea": 10}]
    assert cliff_alert_payload({"goal": 14, "fmkorea": 9}, history,
                               adapters=[], sources={},
                               success_rate=1.0, run_id="r") is None


def test_payload_built_for_cliff_with_adapter_codes():
    history = [{"fmkorea": 10, "goal": 13}]
    payload = cliff_alert_payload(
        {"goal": 14}, history,
        adapters=[_Adapter("fmkorea", {430: 4}), _Adapter("goal")],
        sources={"fmkorea": {"display_name": "fmkorea 축구 소식통"}},
        success_rate=1.0, run_id="3259230a")
    assert "수집 0건" in payload["title"]
    assert "`HTTP 430` 4건" in payload["fields"][0]["value"]


def test_payload_carries_the_funnel_from_adapters_that_count_it():
    """발견 4단 계수를 내놓는 어댑터만 걷는다 — 안 내놓는 어댑터가 섞여도 깨지지 않는다."""
    quiet = _Adapter("fmkorea")
    quiet.funnel = {"selected": 13, "deduped": 13, "titled": 7, "passed": 3}
    payload = cliff_alert_payload(
        {"goal": 14}, [{"fmkorea": 10, "goal": 13}],
        adapters=[quiet, _Adapter("goal")],   # goal 은 funnel 속성이 아예 없다
        sources={"fmkorea": {"display_name": "fmkorea 축구 소식통"}},
        success_rate=1.0, run_id="3259230a")
    assert "발견 퍼널: 목록 13 → URL 13 → 제목 7 → 키워드 3" in str(payload["fields"])


def test_payload_ignores_source_already_at_zero():
    """arsenal_official 은 직전에도 0 — 전이가 아니므로 알림이 없다."""
    history = [{"arsenal_official": 0, "goal": 13}]
    assert cliff_alert_payload({"goal": 14}, history, adapters=[], sources={},
                               success_rate=1.0, run_id="r") is None


# --- 서빙 무관 글 제외 (2026-08-04) ---
from bullet_in.run import serving_rows, roster_surnames

TERMS = ["아스날", "아스널", "arsenal"]
NAMES = {"얀 디오망데", "우스망 디오망데", "케파", "고든", "제주스"}


def _row(sid, title="", body="", ko="", h="h1"):
    return {"source_id": sid, "title_original": title, "body_ko": body,
            "title_ko": ko, "content_hash": h}


def _hide(rows, linked=None):
    """무관 필터만 보는 헬퍼 — 옛 글 계수는 아래 전용 테스트가 따로 본다."""
    keep, hidden, _stale = serving_rows(
        rows, relevance_terms=TERMS, player_names=NAMES, linked=linked or set())
    return keep, hidden


def test_serving_rows_keeps_other_sources_untouched():
    """필터는 fmkorea 에만 건다 — 다른 소스는 아스날 전용 피드다."""
    keep, hidden = _hide([_row("guardian", "Newcastle reject bid"), _row("bbc_sport")])
    assert len(keep) == 2 and hidden == 0


def test_serving_rows_drops_nonarsenal_fmkorea():
    keep, hidden = _hide([_row("fmkorea", "첼시, 조던 헨더슨 영입전 선두", "본문",
                               ko="첼시, 조던 헨더슨 영입전 선두")])
    assert keep == [] and hidden == 1


def test_serving_rows_drops_club_term_that_only_appears_in_body():
    """본문에만 있는 구단 키워드로는 안 남긴다 (2026-08-28 개정).

    본문은 배경 설명에 남의 구단을 흔히 적어 타 구단 기사를 끌고 온다 — 실측 14건.
    수집 필터는 종전대로 본문을 보므로 이 행은 DB 에 남고 화면에서만 빠진다.
    """
    keep, hidden = _hide([_row("fmkorea", "제목에는 없음", "아스널이 영입을 추진한다")])
    assert keep == [] and hidden == 1


def test_serving_rows_keeps_club_term_variant_in_original_title():
    """표기 변형은 제목에서 본다 — 「아스널」 도 「아스날」 과 같게 친다."""
    keep, hidden = _hide([_row("fmkorea", "아스널, 영입 추진", "본문")])
    assert len(keep) == 1 and hidden == 0


def test_serving_rows_drops_passing_mention_of_arsenal_in_body():
    """실물 재현 — 6년 전 이적을 설명하는 배경 문장 하나로 남던 첼시 기사."""
    keep, hidden = _hide([_row(
        "fmkorea", "[디 애슬레틱] 첼시, 에밀리아노 마르티네스 영입 합의",
        "마르티네스는 2020년 9월 아스널을 떠나 빌라에 합류한 뒤 총 256경기에 출전했다.",
        ko="첼시, 에밀리아노 마르티네스 영입 합의")])
    assert keep == [] and hidden == 1


def test_serving_rows_keeps_full_name_in_original_title():
    keep, hidden = _hide([_row("fmkorea", "얀 디오망데, 이적 임박", "본문")])
    assert len(keep) == 1 and hidden == 0


def test_serving_rows_keeps_when_translation_restores_context():
    """원문 제목엔 없고 번역 제목이 아스날 맥락을 되살린 경우."""
    keep, hidden = _hide([_row("fmkorea", "[RMC]디오망데를 주시 중인 PSG", "본문",
                               ko="PSG, 아스날도 주시하는 디오망데 영입전 참전")])
    assert len(keep) == 1 and hidden == 0


def test_serving_rows_keeps_surname_only_title():
    """제목이 성만 써도 명단 선수 기사다 — 동명이인이어도 둘 다 명단이라 무방."""
    keep, hidden = _hide([_row("fmkorea", "[Sky] 라이프치히, 디오망데 이적료 £112M 요구",
                               "본문", ko="라이프치히, 디오망데 이적료로 £112M 요구")])
    assert len(keep) == 1 and hidden == 0


def test_serving_rows_keeps_article_linked_to_confirmed_player():
    """추출이 확정 선수를 붙인 기사 — 추출 보강 시 자동 복구되는 경로."""
    keep, hidden = _hide([_row("fmkorea", "노팅엄, 슐라거 영입 임박", "본문", h="abc")],
                         linked={"abc"})
    assert len(keep) == 1 and hidden == 0


def _dt(y, m, d):
    from datetime import datetime as _datetime
    return _datetime(y, m, d)


def _dated(published, sid="fmkorea", h="hd"):
    """아스날 맥락은 갖췄고 발행일만 다른 행 — 옛 글 필터만 갈라 본다."""
    r = _row(sid, "아스날, 영입 추진", "본문", ko="아스날, 영입 추진", h=h)
    r["published_at"] = published
    return r


def test_serving_rows_drops_fmkorea_published_before_the_window():
    # fmkorea 검색이 옛 글을 함께 물어 온다 — 2026-02 글이 지금 소식처럼 카드로 떴다
    # (2026-08-27 실측 275건 중 19건이 2026-06 이전 · 그중 11건 노출).
    keep, hidden, stale = serving_rows(
        [_dated(_dt(2026, 2, 9))], relevance_terms=TERMS, player_names=NAMES,
        linked=set())
    assert keep == [] and stale == 1
    assert hidden == 0                      # 무관이 아니라 옛 글이라 빠졌다


def test_serving_rows_keeps_fmkorea_inside_the_window():
    keep, hidden, stale = serving_rows(
        [_dated(_dt(2026, 8, 23))], relevance_terms=TERMS, player_names=NAMES,
        linked=set())
    assert len(keep) == 1 and stale == 0 and hidden == 0


def test_serving_rows_keeps_fmkorea_without_a_published_date():
    # 뺄 근거가 없으면 남긴다 — 발행일 미상을 옛 글로 단정하지 않는다.
    keep, hidden, stale = serving_rows(
        [_dated(None)], relevance_terms=TERMS, player_names=NAMES, linked=set())
    assert len(keep) == 1 and stale == 0


def test_serving_rows_window_applies_to_fmkorea_only():
    # 다른 소스는 아스날 전용 피드라 대상이 아니다 (무관 필터와 같은 경계).
    keep, hidden, stale = serving_rows(
        [_dated(_dt(2022, 10, 22), sid="guardian")],
        relevance_terms=TERMS, player_names=NAMES, linked=set())
    assert len(keep) == 1 and stale == 0


def test_roster_surnames_skips_single_token_and_short_names():
    """한 어절 이름은 풀네임 매칭 대상 · 두 글자 성은 오탐한다."""
    assert roster_surnames({"얀 디오망데", "우스망 디오망데", "케파", "칼빈 고든"}) == {"디오망데"}


def test_linked_hashes_sql_drops_mention():
    """신호 ④ 재료 — 스치는 언급뿐인 귀속은 근거가 아니다.

    언급 하나로 아스날이 한 글자도 안 나오는 기사가 남아 있었다 (실측 2건).
    미기입을 함께 남기던 조건은 걷어냈다 — 역할이 NOT NULL 이라 그 값이 들어올 수
    없고, 남겨 두면 제약이 깨졌을 때 화면에서 조용히 넘어간다 (안건 f-③)."""
    with _linked_db() as c:
        from sqlalchemy import text
        from bullet_in.run import LINKED_HASHES_SQL
        c.execute(text("INSERT INTO players VALUES (1,'confirmed'),(2,'confirmed'),(3,'candidate')"))
        # 운영 스키마는 (content_hash, player_id) 가 PK 라 한 기사에 같은 선수를 두 번
        # 넣을 수 없다 — 'both' 는 서로 다른 선수 둘로 만든다 (실물과 같은 모양).
        c.execute(text("INSERT INTO article_players VALUES "
                       "('subj',1,'subject'),"      # 주역 — 남는다
                       "('ment',1,'mention'),"      # 언급뿐 — 빠진다
                       "('both',1,'mention'),('both',2,'subject'),"  # 하나라도 주역이면 남는다
                       "('cand',3,'subject')"))     # 미확정 선수 — 원래대로 안 센다
        c.execute(text("INSERT INTO articles VALUES "
                       "('subj','아스날, 영입 추진','x'),('ment','x','x'),"
                       "('both','x','x'),('cand','x','x')"))
        got = set(c.execute(text(LINKED_HASHES_SQL)).scalars().all())
    assert got == {"subj", "both"}


@contextmanager
def _linked_db():
    """LINKED_HASHES_SQL 이 읽는 세 테이블만 세운 메모리 DB."""
    from sqlalchemy import create_engine, text
    engine = create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE players (id INTEGER, status TEXT)"))
        c.execute(text("CREATE TABLE article_players "
                       "(content_hash TEXT, player_id INTEGER, role TEXT)"))
        c.execute(text("CREATE TABLE articles "
                       "(content_hash TEXT, title_ko TEXT, title_original TEXT)"))
        yield c


def test_linked_hashes_sql_keeps_archived_player_linked_to_arsenal():
    """보관 선수라도 아스날 링크 기록이 있으면 그 거취 기사를 남긴다 (2026-08-28).

    아스날이 노리던 선수가 어디로 갔는지는 제목에 아스날이 없어도 우리 소식이다.
    """
    with _linked_db() as c:
        from sqlalchemy import text
        from bullet_in.run import LINKED_HASHES_SQL
        c.execute(text("INSERT INTO players VALUES (1,'archived')"))
        c.execute(text("INSERT INTO article_players VALUES "
                       "('link',1,'subject'),('dest',1,'subject')"))
        c.execute(text("INSERT INTO articles VALUES "
                       "('link','아스날, 영입 문의','x'),"     # 링크 근거
                       "('dest','첼시, 영입 합의','x')"))      # 거취 — 제목에 아스날 없음
        got = set(c.execute(text(LINKED_HASHES_SQL)).scalars().all())
    assert got == {"link", "dest"}


def test_linked_hashes_sql_drops_archived_player_never_linked_to_arsenal():
    """아스날 링크가 한 번도 없는 보관 선수의 거취는 우리 소식이 아니다 (2026-08-28).

    자동 등재가 아스날과 무관한 선수를 명단에 올려 둔 실측이 있다 (우스망 디오망데 —
    주역 3건이 전부 리즈 · 노팅엄 · 라이프치히 이야기).
    """
    with _linked_db() as c:
        from sqlalchemy import text
        from bullet_in.run import LINKED_HASHES_SQL
        c.execute(text("INSERT INTO players VALUES (1,'archived')"))
        c.execute(text("INSERT INTO article_players VALUES ('a',1,'subject'),('b',1,'subject')"))
        c.execute(text("INSERT INTO articles VALUES "
                       "('a','리즈, 영입 준비','x'),('b','노팅엄, 제안','x')"))
        got = set(c.execute(text(LINKED_HASHES_SQL)).scalars().all())
    assert got == set()


def test_linked_hashes_sql_arsenal_link_counts_english_title():
    """링크 근거는 원문 제목의 영문 표기로도 인정한다."""
    with _linked_db() as c:
        from sqlalchemy import text
        from bullet_in.run import LINKED_HASHES_SQL
        c.execute(text("INSERT INTO players VALUES (1,'archived')"))
        c.execute(text("INSERT INTO article_players VALUES ('a',1,'subject')"))
        c.execute(text("INSERT INTO articles VALUES "
                       "('a','첼시, 영입 합의','Arsenal make approach for the defender')"))
        got = set(c.execute(text(LINKED_HASHES_SQL)).scalars().all())
    assert got == {"a"}


def test_serving_rows_drops_namesake_of_a_roster_player():
    """성만 겹치는 남의 선수 기사는 화면에서 뺀다 (2026-08-31).

    명단 표기가 대부분 성이라, fmkorea 전재 글의 제목에 같은 성을 쓰는 다른 사람이
    나오면 관련성 판정이 아스날 기사로 오인했다 (실측 3건 — 전부 남의 이적 기사).
    사건 묶음이 쓰는 것과 같은 마스킹 (`_NOT_OUR_PLAYERS`) 을 여기에도 태운다.
    """
    keep, hidden = _hide([_row("fmkorea", "Venezia agree deal with Juan Jesus", "본문",
                               ko="베네치아, 주앙 제주스와 구두 합의")],)
    assert keep == [] and hidden == 1


def test_serving_rows_keeps_our_player_written_with_the_surname_only():
    """가리는 것은 남의 이름뿐 — 우리 선수를 성으로만 쓴 제목은 그대로 남는다.

    동명이인 목록에 없는 성은 본문 뒷받침을 요구하지 않는다 (아래 제주스 테스트와 짝).
    """
    keep, hidden = _hide([_row("fmkorea", "PSG close on Diomande", "본문",
                               ko="PSG, 디오망데 영입 근접")])
    assert len(keep) == 1 and hidden == 0


def test_serving_rows_drops_ambiguous_surname_without_the_full_name_in_body():
    """동명이인이 잦은 성은 본문이 풀네임으로 뒷받침할 때만 남긴다 (2026-08-31).

    「포르투갈 대표팀 지휘봉 잡은 제주스」 는 조르제 제주스 감독 기사인데, 명단 표기가
    성이라 관련성 판정을 통과해 화면에 서 있었다. 이름 마스킹으로는 못 잡는다 — 제목에
    성만 있어 지울 이름이 없기 때문이다.
    """
    keep, hidden = _hide([_row("fmkorea", "Jorge Jesus takes Portugal job",
                               "제주스 감독은 4-3-3 을 쓴다",
                               ko="포르투갈 대표팀 지휘봉 잡은 제주스, 전술 변화 예고")])
    assert keep == [] and hidden == 1


def test_serving_rows_keeps_ambiguous_surname_backed_by_the_body():
    keep, hidden = _hide([_row("fmkorea", "Napoli eye Jesus",
                               "가브리엘 제주스는 아스날을 떠날 수 있다",
                               ko="나폴리, 제주스 영입 관심 표명")])
    assert len(keep) == 1 and hidden == 0
