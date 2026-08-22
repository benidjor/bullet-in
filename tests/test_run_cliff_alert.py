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


def test_payload_ignores_source_already_at_zero():
    """arsenal_official 은 직전에도 0 — 전이가 아니므로 알림이 없다."""
    history = [{"arsenal_official": 0, "goal": 13}]
    assert cliff_alert_payload({"goal": 14}, history, adapters=[], sources={},
                               success_rate=1.0, run_id="r") is None


# --- 서빙 무관 글 제외 (2026-08-04) ---
from bullet_in.run import serving_rows, roster_surnames

TERMS = ["아스날", "아스널", "arsenal"]
NAMES = {"얀 디오망데", "우스망 디오망데", "케파", "고든"}


def _row(sid, title="", body="", ko="", h="h1"):
    return {"source_id": sid, "title_original": title, "body_ko": body,
            "title_ko": ko, "content_hash": h}


def _hide(rows, linked=None):
    return serving_rows(rows, relevance_terms=TERMS, player_names=NAMES,
                        linked=linked or set())


def test_serving_rows_keeps_other_sources_untouched():
    """필터는 fmkorea 에만 건다 — 다른 소스는 아스날 전용 피드다."""
    keep, hidden = _hide([_row("guardian", "Newcastle reject bid"), _row("bbc_sport")])
    assert len(keep) == 2 and hidden == 0


def test_serving_rows_drops_nonarsenal_fmkorea():
    keep, hidden = _hide([_row("fmkorea", "첼시, 조던 헨더슨 영입전 선두", "본문",
                               ko="첼시, 조던 헨더슨 영입전 선두")])
    assert keep == [] and hidden == 1


def test_serving_rows_keeps_club_term_variant_in_body():
    """표기 변형 3종을 본문에서도 본다 (수집 필터와 같은 규칙)."""
    keep, hidden = _hide([_row("fmkorea", "제목에는 없음", "아스널이 영입을 추진한다")])
    assert len(keep) == 1 and hidden == 0


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


def test_roster_surnames_skips_single_token_and_short_names():
    """한 어절 이름은 풀네임 매칭 대상 · 두 글자 성은 오탐한다."""
    assert roster_surnames({"얀 디오망데", "우스망 디오망데", "케파", "칼빈 고든"}) == {"디오망데"}


def test_linked_hashes_sql_drops_mention():
    """신호 ④ 재료 — 스치는 언급뿐인 귀속은 근거가 아니다.

    언급 하나로 아스날이 한 글자도 안 나오는 기사가 남아 있었다 (실측 2건).
    미기입을 함께 남기던 조건은 걷어냈다 — 역할이 NOT NULL 이라 그 값이 들어올 수
    없고, 남겨 두면 제약이 깨졌을 때 화면에서 조용히 넘어간다 (안건 f-③)."""
    from sqlalchemy import create_engine, text
    from bullet_in.run import LINKED_HASHES_SQL
    engine = create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE players (id INTEGER, status TEXT)"))
        c.execute(text("CREATE TABLE article_players "
                       "(content_hash TEXT, player_id INTEGER, role TEXT)"))
        c.execute(text("INSERT INTO players VALUES (1,'confirmed'),(2,'confirmed'),(3,'candidate')"))
        # 운영 스키마는 (content_hash, player_id) 가 PK 라 한 기사에 같은 선수를 두 번
        # 넣을 수 없다 — 'both' 는 서로 다른 선수 둘로 만든다 (실물과 같은 모양).
        c.execute(text("INSERT INTO article_players VALUES "
                       "('subj',1,'subject'),"      # 주역 — 남는다
                       "('ment',1,'mention'),"      # 언급뿐 — 빠진다
                       "('both',1,'mention'),('both',2,'subject'),"  # 하나라도 주역이면 남는다
                       "('cand',3,'subject')"))     # 미확정 선수 — 원래대로 안 센다
        got = set(c.execute(text(LINKED_HASHES_SQL)).scalars().all())
    assert got == {"subj", "both"}
