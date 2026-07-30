"""선수 명단 이관 상수 단위 테스트."""
from bullet_in.roster_seed import ROSTER

VALID_CATEGORY = {"squad", "manager", "external"}
VALID_TRANSFER = {"none", "in_link", "in_done", "out_link", "out_done",
                  "link_dropped", "other_club", "loan_in", "loan_out"}


def test_roster_shape_and_uniqueness():
    assert len(ROSTER) == 39                     # name_map 실측 (스펙 "40" 은 계수 착오)
    assert len({r["full_name"] for r in ROSTER}) == 39
    assert len({r["ko_name"] for r in ROSTER}) == 39


def test_roster_surnames_single_word():
    # 풀네임 근거 가드의 단일 단어 성 전제 (스펙 §3.3)
    assert all(" " not in r["surname"] for r in ROSTER)


def test_roster_enum_values():
    assert all(r["category"] in VALID_CATEGORY for r in ROSTER)
    assert all(r["transfer_status"] in VALID_TRANSFER for r in ROSTER)
