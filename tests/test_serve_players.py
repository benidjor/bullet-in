"""선수 색인 · 선수 페이지 순수 함수 단위 테스트 (스펙 §4 · §5)."""
from datetime import datetime
from bullet_in.serve.render import (TRANSFER_GROUPS, player_slug, stage_timeline,
                                    transfer_badge, transfer_group)

NOW = datetime(2026, 7, 10, 12, 0)
SOURCES = {"bbc_sport": {"display_name": "BBC Sport", "serving": "full"}}


def _row(day: int, h: str = "h1"):
    """전이 판정용 최소 행 — stage_timeline 은 순서만 쓰고 정렬 키를 읽지 않는다."""
    return {"content_hash": h, "published_at": datetime(2026, 7, day, 12, 0)}


def test_transfer_badge_covers_all_eight_values():
    values = ["in_link", "out_link", "in_done", "out_done",
              "loan_in", "loan_out", "link_dropped", "other_club"]
    labels = [transfer_badge(v)["label"] for v in values]
    assert labels == ["영입 링크", "방출 링크", "영입 완료", "방출 완료",
                      "임대 영입", "임대 이적", "링크 소멸", "타 클럽행"]


def test_transfer_badge_is_none_for_no_axis():
    assert transfer_badge("none") is None
    assert transfer_badge("") is None


def test_transfer_group_splits_eight_values_without_gap():
    assert transfer_group("in_link") == "진행 중"
    assert transfer_group("out_link") == "진행 중"
    for v in ("in_done", "out_done", "loan_in", "loan_out"):
        assert transfer_group(v) == "성사"
    for v in ("link_dropped", "other_club"):
        assert transfer_group(v) == "무산과 종료"
    assert transfer_group("none") is None


def test_transfer_groups_order_and_collapse_flag():
    assert [g for g, _ in TRANSFER_GROUPS] == ["진행 중", "성사", "무산과 종료"]
    assert [c for _, c in TRANSFER_GROUPS] == [False, False, True]


def test_player_slug_is_lowercased_surname():
    assert player_slug("Tzolis", 12, set()) == "tzolis"
    assert player_slug("Gibbs-White", 7, set()) == "gibbswhite"


def test_player_slug_falls_back_to_surname_id_on_collision():
    dupes = {"vieira"}
    assert player_slug("Vieira", 41, dupes) == "vieira-41"
    assert player_slug("Vieira", 88, dupes) == "vieira-88"


def test_stage_timeline_makes_node_only_when_stage_changes():
    entries = [{"row": _row(1), "stage": "rumour"},
               {"row": _row(2), "stage": "rumour"},
               {"row": _row(3), "stage": "interest"}]
    nodes = stage_timeline(entries)
    assert [n["stage"] for n in nodes] == ["interest", "rumour"]   # 최신 우선
    assert nodes[1]["follow"] == 1                                  # 같은 단계 1건 접힘
    assert nodes[0]["follow"] == 0


def test_stage_timeline_skips_other_and_blank():
    entries = [{"row": _row(1), "stage": "other"},
               {"row": _row(2), "stage": None},
               {"row": _row(3), "stage": "agreed"}]
    nodes = stage_timeline(entries)
    assert [n["stage"] for n in nodes] == ["agreed"]
    assert nodes[0]["follow"] == 0            # other · 빈 값은 follow 도 올리지 않는다


def test_stage_timeline_keeps_regression_as_its_own_node():
    entries = [{"row": _row(1), "stage": "agreed"},
               {"row": _row(2), "stage": "rumour"}]
    nodes = stage_timeline(entries)
    assert [n["stage"] for n in nodes] == ["rumour", "agreed"]


def test_stage_timeline_is_empty_when_no_article_has_a_stage():
    assert stage_timeline([{"row": _row(1), "stage": "other"}]) == []
