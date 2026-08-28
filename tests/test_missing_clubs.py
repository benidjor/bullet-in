"""미등재 구단 관측 — 문턱이 필터의 본체다 (2026-08-28)."""
from bullet_in.quality import club_head, missing_club_candidates

CLUBS = {"토트넘": ["Tottenham"], "에버턴": ["Everton"]}
PEOPLE = ["마르티넬리", "아르테타", "뇌르고르"]
JOURNOS = ["벤 제이콥스"]


def _t(head, rest="아스날 가브리엘 마르티넬리 영입 추진"):
    return f"{head}, {rest}"


def test_club_head_takes_first_clause_head():
    assert club_head("알 힐랄, 마르티넬리 영입 임박") == "알 힐랄"
    assert club_head("토트넘, 토날리 영입전 합류… 다른 소식") == "토트넘"


def test_club_head_drops_sentence_fragment():
    # 구단명 자리에 문장이 오면 후보가 아니다
    assert club_head("이적 시장 마감 1주일 남은 시점의 아스날 상황 정리") is None


def test_repeated_unknown_name_is_reported():
    titles = [_t("알 힐랄"), _t("알 힐랄"), _t("알 힐랄")]
    out = missing_club_candidates(titles, CLUBS, PEOPLE, JOURNOS, min_count=3)
    assert [c["name"] for c in out] == ["알 힐랄"]
    assert out[0]["count"] == 3


def test_below_threshold_is_silent():
    # 되풀이되지 않는 것은 문장 조각 · 오탐이라 안 알린다
    titles = [_t("알 힐랄"), _t("알 힐랄")]
    assert missing_club_candidates(titles, CLUBS, PEOPLE, JOURNOS, min_count=3) == []


def test_known_club_is_not_reported():
    titles = [_t("토트넘")] * 5
    assert missing_club_candidates(titles, CLUBS, PEOPLE, JOURNOS, min_count=3) == []


def test_people_are_filtered_out():
    # 「아르테타 감독, …」 처럼 사람이 머리말에 오는 제목이 그 자리에 가장 흔하다
    titles = [_t("아르테타 감독")] * 5 + [_t("벤 제이콥스")] * 5
    assert missing_club_candidates(titles, CLUBS, PEOPLE, JOURNOS, min_count=3) == []


def test_arsenal_subject_titles_are_skipped():
    titles = ["아스날, 마르티넬리 매각 검토"] * 5
    assert missing_club_candidates(titles, CLUBS, PEOPLE, JOURNOS, min_count=3) == []


def test_result_is_sorted_by_count():
    titles = [_t("알 힐랄")] * 3 + [_t("알 나스르")] * 5
    out = missing_club_candidates(titles, CLUBS, PEOPLE, JOURNOS, min_count=3)
    assert [c["name"] for c in out] == ["알 나스르", "알 힐랄"]
