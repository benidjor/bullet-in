"""ko_full_name 적재 규칙 — 승인 표기 우선 · 나머지는 ko_candidate 길이 규칙."""
from bullet_in.backfill_ko_full_name import APPROVED, resolve


def test_approved_table_wins_over_candidate():
    # 승인 표기가 있으면 ko_candidate 가 무엇이든 그 값을 쓴다.
    assert resolve("Bradley Barcola", "바르콜라", "바르콜라") == "브래들리 바르콜라"


def test_longer_candidate_is_adopted():
    assert resolve("Christian Norgaard", "뇌르고르", "크리스티안 뇌르고르") == "크리스티안 뇌르고르"


def test_shorter_candidate_is_skipped():
    # ko_name 이 이미 풀네임이고 후보가 성만인 경우 — Jon Martin.
    assert resolve("Jon Martin", "욘 마르틴", "마르틴") is None


def test_equal_candidate_is_skipped():
    assert resolve("Nico Williams", "니코 윌리암스", "니코 윌리암스") is None


def test_missing_ko_name_takes_candidate():
    # ko_name 이 비어 있으면 화면이 영문으로 떨어지므로 후보를 그대로 쓴다.
    assert resolve("Aladji Bamba", None, "알라지 밤바") == "알라지 밤바"


def test_kyran_thompson_keeps_user_confirmed_spelling():
    # 후보 (카이런 톰슨) 가 더 길지만 사용자 확정 값은 ko_name 쪽이다.
    assert resolve("Kyran Thompson", "키란 톰슨", "카이런 톰슨") == "키란 톰슨"


def test_no_candidate_returns_none():
    assert resolve("Ezri Konsa2", "콘사2", None) is None


def test_approved_table_has_23_entries():
    assert len(APPROVED) == 23
