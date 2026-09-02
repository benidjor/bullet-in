"""선수 색인 · 선수 페이지 순수 함수 단위 테스트 (스펙 §4 · §5)."""
import pytest
import re
from datetime import datetime
from pathlib import Path
from bullet_in.serve.render import (TRANSFER_GROUPS, player_slug, stage_ladder,
                                    transfer_badge, transfer_group)

NOW = datetime(2026, 7, 10, 12, 0)
SOURCES = {"bbc_sport": {"display_name": "BBC Sport", "serving": "full"}}
STATIC = Path("src/bullet_in/serve/static")


def _row(day: int, h: str = "h1", tier=2):
    """사다리 판정용 최소 행 — stage_ladder 는 tier 와 입력 순서만 쓴다."""
    return {"content_hash": h, "tier": tier,
            "published_at": datetime(2026, 7, day, 12, 0)}


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
    # 진행 중은 영입 · 방출로 갈라져 있다 (2026-08-23) — 한 묶음일 때는 들어오는
    # 선수와 나가는 선수가 섞여 어느 쪽을 보러 왔든 목록을 통째로 훑어야 했다.
    assert transfer_group("in_link") == "영입 진행 중"
    assert transfer_group("out_link") == "방출 진행 중"
    assert transfer_group("in_done") == "이적 확정"
    assert transfer_group("out_done") == "이적 확정"
    assert transfer_group("loan_in") == "이적 확정"
    assert transfer_group("loan_out") == "이적 확정"
    assert transfer_group("link_dropped") == "이적 무산"
    assert transfer_group("other_club") == "타 클럽행"
    # 이적 축이 없는 선수는 어느 그룹에도 안 들어간다 — 빈 문자열이 아니라 없음이다.
    assert transfer_group("none") is None
    assert transfer_group(None) is None


def test_transfer_groups_order_and_collapse_flag():
    # 타 클럽행이 이적 무산 위다 (2026-08-28) — 행선지가 있는 소식을 먼저 둔다.
    assert TRANSFER_GROUPS == [
        ("영입 진행 중", False), ("방출 진행 중", False), ("이적 확정", False),
        ("타 클럽행", True), ("이적 무산", True)]


def test_player_slug_is_lowercased_surname():
    assert player_slug("Tzolis", 12, set()) == "tzolis"
    assert player_slug("Gibbs-White", 7, set()) == "gibbswhite"


def test_player_slug_falls_back_to_surname_id_on_collision():
    dupes = {"vieira"}
    assert player_slug("Vieira", 41, dupes) == "vieira-41"
    assert player_slug("Vieira", 88, dupes) == "vieira-88"


def test_stage_ladder_one_line_per_group_in_progress_order():
    entries = [{"row": _row(1, "h1"), "stage": "rumour"},
               {"row": _row(2, "h2"), "stage": "rumour"},
               {"row": _row(3, "h3"), "stage": "agreed"}]
    lines = stage_ladder(entries)
    assert [l["stage"] for l in lines] == ["agreed", "rumour"]   # 진행 단계 순 (위가 앞)
    assert [l["count"] for l in lines] == [1, 2]                 # 건수 = 묶음 전체 (대표 포함)


def test_stage_ladder_merges_agreed_and_medical_into_one_line():
    # 메디컬의 표시 묶음 소속이 협상 중 → 이적 합의로 이동했다 (단계 재정의 스펙 §3)
    entries = [{"row": _row(1, "h1", tier=4), "stage": "agreed"},
               {"row": _row(2, "h2", tier=4), "stage": "medical"}]
    [line] = stage_ladder(entries)
    assert line["row"]["content_hash"] == "h2"   # 동률 → 늦은 기사 (2026-08-07 개정)
    assert line["count"] == 2                    # 이적 합의 한 줄로 합산


def test_stage_ladder_excludes_collapsed_and_ended_marker_carries_it():
    # 무산은 진행 단계가 아니라 사다리 축에 넣지 않고 종결 표시로 뗀다 (단계 재정의 스펙 §8)
    from bullet_in.serve.render import ended_marker
    entries = [{"row": _row(1, "h1", tier=4), "stage": "negotiating"},
               {"row": _row(2, "h2", tier=1), "stage": "collapsed"},
               {"row": _row(3, "h3", tier=4), "stage": "collapsed"}]
    [line] = stage_ladder(entries)
    assert line["stage"] == "negotiating"        # collapsed 는 사다리 줄이 아니다
    end = ended_marker(entries, transfer_status="link_dropped")
    assert end["stage"] == "collapsed"
    assert end["row"]["content_hash"] == "h2"    # 대표 규칙 동일 — 공신력 높은 순
    assert end["count"] == 2


def test_ended_marker_is_none_without_collapsed():
    from bullet_in.serve.render import ended_marker
    assert ended_marker([{"row": _row(1), "stage": "agreed"}],
                        transfer_status="link_dropped") is None


def test_ended_marker_needs_roster_backing():
    # 종결 줄은 사다리 맨 위에 꽂혀 "이 사가는 끝났다" 를 먼저 말한다 — 명단이 부정하는
    # 종결을 그리면 같은 페이지의 머리 배지와 반대를 말한다 (실측: 영입을 마친 선수
    # 페이지에 이적 완료 열흘 전 가십 한 건으로 만든 무산 줄).
    from bullet_in.serve.render import ended_marker
    entries = [{"row": _row(1, "h1", tier=4), "stage": "collapsed"}]
    assert ended_marker(entries, transfer_status="in_done") is None
    assert ended_marker(entries, transfer_status="in_link") is None
    assert ended_marker(entries, transfer_status=None) is None
    for backing in ("link_dropped", "other_club"):
        assert ended_marker(entries, transfer_status=backing)["stage"] == "collapsed"


def test_stage_ladder_rep_is_highest_credibility_and_missing_tier_is_lowest():
    entries = [{"row": _row(1, "h1", tier=4), "stage": "agreed"},
               {"row": _row(2, "h2", tier=1), "stage": "agreed"},
               {"row": _row(3, "h3", tier=None), "stage": "agreed"}]
    [line] = stage_ladder(entries)
    assert line["row"]["content_hash"] == "h2"   # tier 작을수록 높음 · 미상 (None) 은 최하
    assert line["count"] == 3


def test_stage_ladder_tie_picks_latest_in_every_group():
    # 동률이면 전 묶음 공통으로 늦은 기사다 (스펙 §4.2 개정 2026-08-07) — 줄의 날짜가
    # 그 단계의 최신 보도를 가리키게 한다. 오피셜의 "마지막 공지" 규칙도 여기 포함된다.
    entries = [{"row": _row(4, "ag1", tier=1), "stage": "agreed"},
               {"row": _row(14, "off1", tier=0), "stage": "official"},
               {"row": _row(14, "ag2", tier=1), "stage": "agreed"},
               {"row": _row(16, "off2", tier=0), "stage": "official"}]
    lines = stage_ladder(entries)
    assert lines[0]["row"]["content_hash"] == "off2"   # 오피셜 — 늦은 공지
    assert lines[1]["row"]["content_hash"] == "ag2"    # 나머지 묶음도 늦은 기사


def test_stage_ladder_skips_other_and_blank():
    entries = [{"row": _row(1, "h1"), "stage": "other"},
               {"row": _row(2, "h2"), "stage": None},
               {"row": _row(3, "h3"), "stage": "agreed"}]
    lines = stage_ladder(entries)
    assert [l["stage"] for l in lines] == ["agreed"]
    assert lines[0]["count"] == 1     # other · 빈 값은 줄도 건수도 만들지 않는다


def test_stage_ladder_is_empty_when_no_article_has_a_stage():
    assert stage_ladder([{"row": _row(1), "stage": "other"}]) == []


from bullet_in.serve.render import build_player_entries


def _art(h, day, stage=None, title="제목"):
    """서빙 행 — tests/test_serve_render.py 의 _row 와 같은 컬럼 구성을 따른다.
    _decorate 가 url · image_url · tier 를 읽으므로 빠뜨리면 렌더 테스트가 깨진다."""
    return {"content_hash": h, "url": f"https://x/{h}", "source_id": "bbc_sport",
            "title_original": title, "title_ko": title, "summary_ko": "한 줄 요약",
            "tier": 2, "confidence_score": 0.5, "image_url": None, "outlet": None,
            "team": "arsenal", "transfer_stage": stage,
            "published_at": datetime(2026, 7, day, 12, 0)}


def _player(pid, surname, ko, status, links, club=None):
    """links = [{"content_hash", "stage", "role"}] — page_player_links 반환 형태.

    role 은 컬럼이 NOT NULL 이라 실물에서 늘 실려 온다 — 목록 판정과 무관한
    테스트가 매번 적지 않도록 안 적은 링크는 주역으로 채운다."""
    return {"id": pid, "full_name": f"{ko} {surname}", "surname": surname,
            "ko_name": ko, "transfer_status": status, "club": club,
            "links": [{"role": "subject", **l} for l in links]}


def test_build_player_entries_orders_articles_newest_first():
    arts = [_art("h1", 1, "rumour"), _art("h2", 5, "interest")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"},
                        {"content_hash": "h2", "stage": "interest"}])]
    [e] = build_player_entries(arts, players)
    assert [a["content_hash"] for a in e["articles"]] == ["h2", "h1"]
    assert e["count"] == 2


def test_build_player_entries_header_count_matches_article_list():
    # draft 리뷰에서 실제로 잡혔던 결함 — 머리와 목록이 어긋나지 않도록
    # 둘 다 other 를 뺀 같은 집합에서 나온다 (스펙 §5.3)
    arts = [_art("h1", 1, "rumour"), _art("h2", 2, None), _art("h3", 3, "other")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"},
                        {"content_hash": "h2", "stage": None},
                        {"content_hash": "h3", "stage": "other",
                         "role": "mention"}])]
    [e] = build_player_entries(arts, players)
    assert e["count"] == len(e["articles"]) == 2
    assert [l["stage"] for l in e["ladder"]] == ["rumour"]


def test_build_player_entries_excludes_mention_from_list_and_count():
    # 머리 건수와 목록 수가 어긋나면 안 되므로 둘 다 같은 집합에서 나와야 한다.
    rows = [{"content_hash": "h1", "published_at": datetime(2026, 8, 1)},
            {"content_hash": "h2", "published_at": datetime(2026, 8, 2)},
            {"content_hash": "h3", "published_at": datetime(2026, 8, 3)}]
    players = [{"id": 1, "full_name": "Christos Tzolis", "surname": "Tzolis",
                "ko_full_name": None, "ko_name": "촐리스",
                "transfer_status": "in_link",
                "links": [{"content_hash": "h1", "stage": "interest",
                           "role": "subject"},
                          {"content_hash": "h2", "stage": "agreed",
                           "role": "mention"},
                          {"content_hash": "h3", "stage": "agreed",
                           "role": "subject"}]}]
    entry = build_player_entries(rows, players)[0]
    assert entry["count"] == 2
    assert len(entry["articles"]) == 2
    assert [a["content_hash"] for a in entry["articles"]] == ["h3", "h1"]


def test_build_player_entries_judges_only_by_role():
    # 단계 폴백을 걷어냈다 — 목록은 역할 하나로만 갈린다 (안건 f-③).
    # 단계가 other 인 주역 기사는 남고, 단계가 진행 중이어도 언급이면 빠진다.
    arts = [_art("h1", 1, "agreed"), _art("h2", 2, "other")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "agreed",
                         "role": "mention"},          # 언급 — 빠진다
                        {"content_hash": "h2", "stage": "other",
                         "role": "subject"}])]        # 주역 — 남는다
    [e] = build_player_entries(arts, players)
    assert [a["content_hash"] for a in e["articles"]] == ["h2"]
    assert e["count"] == 1


def test_build_player_entries_raises_when_a_link_has_no_role():
    # 미기입은 쓰기 쪽에서 막는다 (article_players.role NOT NULL) — 서빙이 임의로
    # 한쪽으로 읽으면 화면이 조용히 틀어지므로 여기서는 터뜨린다.
    arts = [_art("h1", 1, "interest")]
    players = [{"id": 1, "full_name": "촐리스 Tzolis", "surname": "Tzolis",
                "ko_name": "촐리스", "transfer_status": "in_link",
                "links": [{"content_hash": "h1", "stage": "interest"}]}]
    with pytest.raises(KeyError):
        build_player_entries(arts, players)


def test_build_player_entries_keeps_subject_other_without_ladder_row():
    # 경쟁 구단 접근 · 잔류 협상 — 주역인데 아스날 축에 담을 단계가 없는 기사 (스펙 §2.3)
    arts = [_art("h1", 1, "interest"), _art("h2", 2, "other")]
    players = [_player(1, "Kepa", "케파", "out_link",
                       [{"content_hash": "h1", "stage": "interest",
                         "role": "subject"},
                        {"content_hash": "h2", "stage": "other",
                         "role": "subject"}])]
    [e] = build_player_entries(arts, players)
    assert [a["content_hash"] for a in e["articles"]] == ["h2", "h1"]
    assert [l["stage"] for l in e["ladder"]] == ["interest"]   # other 는 줄이 없다
    assert e["stage"] == "interest"                            # 현재 상태도 안 바뀐다


def test_player_chips_skip_mention_links():
    # 기사 카드의 선수 칩도 같은 목록에서 나오므로 잡음 칩이 함께 사라진다 (스펙 §4)
    # 로저스에게 subject 역할의 기사(h2)를 하나 더 줘서 페이지가 생긴 상태에서
    # h1 칩만 빠지는지 본다 — h1 링크(mention)만 있으면 paired 가 비어 페이지
    # 자체가 안 생기고, 그러면 h1 에 칩이 없는 이유가 "mention 을 건너뛰어서"
    # 가 아니라 "선수 페이지가 없어서" 가 되어 이 테스트의 취지가 흐려진다.
    from bullet_in.serve.render import player_chips
    arts = [_art("h1", 1, "agreed"), _art("h2", 2, "agreed")]
    players = [_player(1, "Rogers", "로저스", "other_club",
                       [{"content_hash": "h1", "stage": "agreed",
                         "role": "mention"},
                        {"content_hash": "h2", "stage": "agreed",
                         "role": "subject"}]),
               _player(2, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "agreed",
                         "role": "subject"}])]
    chips = player_chips(build_player_entries(arts, players))
    assert [c["name"] for c in chips["h1"]] == ["촐리스"]


def test_build_player_entries_current_stage_is_time_axis_latest():
    arts = [_art("h1", 1, "agreed"), _art("h2", 5, "rumour")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "agreed"},
                        {"content_hash": "h2", "stage": "rumour"}])]
    [e] = build_player_entries(arts, players)
    assert e["stage"] == "rumour"          # 역행이어도 시간축 최신값 (사다리 첫 줄 아님)


def test_build_player_entries_stage_ignores_ladder_top_official():
    # §6.2 회귀 방어 — 오피셜 기사가 섞여 있어도 머리 · 색인 배지는 시간축 최신
    # 단계다. 사다리 첫 줄 (오피셜) 을 그대로 읽으면 실측 다섯 명 전부 틀린다.
    arts = [_art("h1", 1, "official"), _art("h2", 5, "interest")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "official"},
                        {"content_hash": "h2", "stage": "interest"}])]
    [e] = build_player_entries(arts, players)
    assert e["stage"] == "interest"
    assert e["ladder"][0]["stage"] == "official"   # 사다리 자체는 오피셜이 위


def test_build_player_entries_stage_prefers_terminal_over_later_mention():
    # 딜이 끝난 뒤 그 선수를 배경으로만 언급한 기사가 뒤에 와도 현재 상태를 덮지 않는다
    # (실측: 재계약으로 끝난 비니시우스가 '협상 중' 으로 표시됐다 · 2026-08-11 개정)
    arts = [_art("h1", 1, "negotiating"), _art("h2", 3, "collapsed"),
            _art("h3", 5, "negotiating")]
    players = [_player(1, "Vinicius", "비니시우스", "link_dropped",
                       [{"content_hash": "h1", "stage": "negotiating"},
                        {"content_hash": "h2", "stage": "collapsed"},
                        {"content_hash": "h3", "stage": "negotiating"}])]
    [e] = build_player_entries(arts, players)
    assert e["stage"] == "collapsed"


def test_build_player_entries_stage_uses_latest_backed_terminal():
    arts = [_art("h1", 1, "collapsed"), _art("h2", 5, "done")]
    players = [_player(1, "Tzolis", "촐리스", "in_done",
                       [{"content_hash": "h1", "stage": "collapsed"},
                        {"content_hash": "h2", "stage": "done"}])]
    [e] = build_player_entries(arts, players)
    assert e["stage"] == "done"      # 영입 완료 선수라 무산은 뒷받침이 없다


def test_build_player_entries_stage_ignores_terminal_the_roster_denies():
    # 상류 오분류 한 건이 배지를 영구히 지배하지 않게 하는 가드 — 실측 3명이 근거다
    # (영입을 마친 업슨이 무산으로 · 아직 이적 안 한 코네 · 알바레스가 무산으로).
    arts = [_art("h1", 1, "interest"), _art("h2", 5, "collapsed")]
    links = [{"content_hash": "h1", "stage": "interest"},
             {"content_hash": "h2", "stage": "collapsed"}]
    [e] = build_player_entries(arts, [_player(1, "Kone", "코네", "in_link", links)])
    assert e["stage"] == "interest"          # 명단이 진행 중이라 무산을 안 쓴다
    [e2] = build_player_entries(arts, [_player(2, "Upson", "업슨", "in_done", links)])
    assert e2["stage"] == "interest"         # 영입 완료 선수도 마찬가지
    [e3] = build_player_entries(arts, [_player(3, "Vinicius", "비니시우스",
                                               "link_dropped", links)])
    assert e3["stage"] == "collapsed"        # 명단이 뒷받침하면 쓴다


def test_build_player_entries_stage_prefers_official_for_completed_player():
    # 이적을 마친 선수는 공홈 발표를 먼저 쓴다 — 완료 기사 유무에 따라 어떤 선수는
    # 오피셜 · 어떤 선수는 이적 완료로 갈리던 것을 없앤다 (실측 9명 중 6명이 공홈 보유)
    arts = [_art("h1", 1, "official"), _art("h2", 5, "done")]
    links = [{"content_hash": "h1", "stage": "official"},
             {"content_hash": "h2", "stage": "done"}]
    [e] = build_player_entries(arts, [_player(1, "Kiwior", "키비오르", "out_done", links)])
    assert e["stage"] == "official"
    # 진행 중인 선수의 공홈 합의 공지는 여전히 현재 상태를 가로채지 못한다 (§6.2)
    [e2] = build_player_entries(arts, [_player(2, "Kone", "코네", "in_link", links)])
    assert e2["stage"] != "official"


def test_stage_ladder_rep_prefers_article_about_the_player():
    # 오귀속 기사의 공신력이 본인 기사보다 높아도 대표가 되면 안 된다
    # (실측: 뇌르고르 사다리 세 줄이 전부 기마랑이스 기사였다)
    entries = [{"row": _row(1, "h1", tier=1) | {"title_ko": "기마랑이스 이적 확정"},
                "stage": "done"},
               {"row": _row(2, "h2", tier=1.5) | {"title_ko": "에버튼, 뇌르고르 영입 확정"},
                "stage": "done"}]
    [line] = stage_ladder(entries, "뇌르고르")
    assert line["row"]["content_hash"] == "h2"
    # 이름을 안 주면 종전대로 공신력 우선
    [plain] = stage_ladder(entries)
    assert plain["row"]["content_hash"] == "h1"


def test_render_player_cards_use_player_axis_stage():
    # 선수 페이지 카드 배지는 선수 축이다 — 아스날 건이 관심에서 멈춘 선수의 카드에
    # 타 구단 딜의 "이적 합의" 가 뜨던 자리 (실측 · 스톤스)
    arts = [_art("h1", 1, "agreed", "스톤스, 인터 밀란행 임박")]
    players = [_player(1, "Stones", "스톤스", "other_club",
                       [{"content_hash": "h1", "stage": "interest"}])]
    [e] = build_player_entries(arts, players)
    html = render_player(e, SOURCES, NOW)
    assert 'data-stage="interest"' in html
    assert 'data-stage="agreed"' not in html          # 기사 축이 새 나오면 안 된다
    assert ">이적 합의<" not in html                   # 기사 축 배지도 마찬가지


def test_build_player_entries_drops_player_whose_links_are_all_mention():
    # 남의 기사에 이름만 스친 선수 — 색인이 부풀지 않게 페이지를 만들지 않는다.
    rows = [{"content_hash": "h1", "published_at": datetime(2026, 8, 1)},
            {"content_hash": "h2", "published_at": datetime(2026, 8, 2)}]
    players = [{"id": 1, "full_name": "Martin Zubimendi", "surname": "Zubimendi",
                "ko_full_name": None, "ko_name": "수비멘디",
                "transfer_status": "in_link",
                "links": [{"content_hash": "h1", "stage": "agreed",
                           "role": "mention"},
                          {"content_hash": "h2", "stage": "done",
                           "role": "mention"}]}]
    assert build_player_entries(rows, players) == []


def test_build_player_entries_drops_player_with_no_serving_article():
    # DB 에는 귀속이 있으나 서빙 목록에 그 기사가 없는 경우 (빈 페이지 방지)
    players = [_player(1, "Ghost", "고스트", "in_link",
                       [{"content_hash": "h9", "stage": "rumour"}])]
    assert build_player_entries([_art("h1", 1, "rumour")], players) == []


def test_build_player_entries_disambiguates_same_surname():
    arts = [_art("h1", 1, "rumour")]
    players = [_player(1, "Vieira", "비에이라", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"}]),
               _player(2, "Vieira", "파트리크 비에이라", "other_club",
                       [{"content_hash": "h1", "stage": "rumour"}])]
    slugs = [e["slug"] for e in build_player_entries(arts, players)]
    assert sorted(slugs) == ["vieira-1", "vieira-2"]


def test_build_player_entries_falls_back_to_full_name():
    arts = [_art("h1", 1, "rumour")]
    players = [{"id": 1, "full_name": "Aladji Bamba", "surname": "Bamba",
                "ko_name": None, "transfer_status": "other_club",
                "links": [{"content_hash": "h1", "stage": "rumour",
                           "role": "subject"}]}]
    [e] = build_player_entries(arts, players)
    assert e["name"] == "Aladji Bamba"


from bullet_in.serve.render import render_player, render_players


def test_render_players_omits_badge_in_single_value_groups():
    # 타 클럽행 · 이적 무산 그룹은 값이 하나뿐이라 축 배지가 그룹명을 되풀이하거나
    # 같은 값을 다른 말로 부른다 (링크 소멸) — 색인에서는 생략한다 (2026-08-11).
    arts = [_art("h1", 1, "rumour"), _art("h2", 2, "collapsed")]
    players = [_player(1, "Nduka", "은두카", "other_club",
                       [{"content_hash": "h1", "stage": "rumour"}]),
               _player(2, "Vinicius", "비니시우스", "link_dropped",
                       [{"content_hash": "h2", "stage": "collapsed"}])]
    html = render_players(build_player_entries(arts, players), NOW)
    assert "타 클럽행" in html and "이적 무산" in html   # 그룹 머리는 남는다
    assert "링크 소멸" not in html                      # 중복 · 불일치 배지는 없다
    assert html.count("타 클럽행") == 1                 # 그룹 머리 1회 (배지로 반복 안 함)


def test_render_players_keeps_badge_where_group_has_several_values():
    # 이적 확정 그룹은 영입 완료 · 방출 완료 · 임대가 섞이므로 배지가 정보를 준다.
    # 진행 중을 영입 · 방출로 가른 뒤 (2026-08-23) 값이 여럿인 그룹은 여기 하나다.
    arts = [_art("h1", 1, "official")]
    players = [_player(1, "Zubimendi", "수비멘디", "in_done",
                       [{"content_hash": "h1", "stage": "official"}])]
    html = render_players(build_player_entries(arts, players), NOW)
    assert "영입 완료" in html


def test_render_players_keeps_the_axis_badge_where_it_carries_a_colour():
    # 갈라진 두 그룹은 값이 하나씩이라 배지가 그룹 머리를 되풀이하지만, 초록 · 빨강으로
    # 축을 한 번 더 말한다 — 카드 하나만 떼어 봐도 들어오는 쪽인지 보이게 남긴다
    # (2026-08-23 · 목업으로 고름).
    arts = [_art("h1", 1, "interest")]
    players = [_player(1, "Zubimendi", "수비멘디", "out_link",
                       [{"content_hash": "h1", "stage": "interest"}])]
    html = render_players(build_player_entries(arts, players), NOW)
    assert "방출 진행 중" in html          # 그룹 머리
    assert "t-outlink" in html            # 색을 나르는 배지도 함께 남는다


def test_render_players_drops_the_axis_badge_where_it_is_only_a_repeat():
    # 이 둘은 배지가 회색이라 색 신호가 없고 그룹 머리를 되풀이하기만 한다
    # — 「링크 소멸」 은 같은 값을 다른 말로 부르고, 「타 클럽행」 은 글자까지 같다.
    arts = [_art("h1", 1, "rumour"), _art("h2", 2, "collapsed")]
    players = [_player(1, "Nduka", "은두카", "other_club",
                       [{"content_hash": "h1", "stage": "rumour"}]),
               _player(2, "Vinicius", "비니시우스", "link_dropped",
                       [{"content_hash": "h2", "stage": "collapsed"}])]
    html = render_players(build_player_entries(arts, players), NOW)
    assert "링크 소멸" not in html
    assert "t-otherclub" not in html


def test_render_players_shows_the_destination_club_for_other_club():
    # 그룹 머리는 「다른 데로 갔다」 까지만 말한다 — 어디로 갔는지는 club 이 채운다
    # (2026-08-27 · 단계 배지를 생략한 그 자리다).
    arts = [_art("h1", 1, "interest")]
    players = [_player(1, "Tonali", "토날리", "other_club",
                       [{"content_hash": "h1", "stage": "interest"}],
                       club="Tottenham")]
    html = render_players(build_player_entries(arts, players), NOW)
    assert '<span class="pclub">토트넘</span>' in html      # 저장은 영문 · 화면은 한글


def test_club_ko_falls_back_to_the_stored_name():
    # 매핑을 빠뜨려도 배지가 사라지지 않는다 — 영문이라도 띄우는 편이 낫다.
    from bullet_in.serve.render import club_ko
    assert club_ko("Manchester City") == "맨체스터 시티"
    assert club_ko("Some New FC") == "Some New FC"
    assert club_ko(None) is None
    assert club_ko("") is None


def test_render_players_omits_the_club_badge_when_unknown():
    # 모르는 것을 빈 배지로 채우지 않는다.
    arts = [_art("h1", 1, "interest")]
    players = [_player(1, "Gordon", "고든", "other_club",
                       [{"content_hash": "h1", "stage": "interest"}])]
    html = render_players(build_player_entries(arts, players), NOW)
    assert 'class="pclub"' not in html


def test_render_players_club_badge_is_only_for_the_other_club_group():
    # 진행 중 선수의 현 소속은 「어디로 갔나」 가 아니라서 이 배지를 안 단다.
    arts = [_art("h1", 1, "interest")]
    players = [_player(1, "Alvarez", "알바레스", "in_link",
                       [{"content_hash": "h1", "stage": "interest"}],
                       club="Atletico Madrid")]
    html = render_players(build_player_entries(arts, players), NOW)
    assert 'class="pclub"' not in html


def test_render_players_drops_the_stage_badge_in_the_other_club_group():
    # 그룹 머리는 "그 선수가 어디로 갔나" (명단 축) 를, 단계 배지는 "아스날이 어디까지
    # 갔나" (기사 단계) 를 말한다. 둘 다 사실인데 "타 클럽행 + 관심" 은 모순으로 읽힌다
    # — 색인에서는 단계 배지를 생략한다 (2026-08-25 · 목업 셋을 렌더해 고름).
    arts = [_art("h1", 1, "interest"), _art("h2", 2, "collapsed")]
    players = [_player(1, "Torres", "토레스", "other_club",
                       [{"content_hash": "h1", "stage": "interest"}]),
               _player(2, "Vinicius", "비니시우스", "link_dropped",
                       [{"content_hash": "h2", "stage": "collapsed"}])]
    html = render_players(build_player_entries(arts, players), NOW)
    assert "타 클럽행" in html                 # 그룹 머리는 남는다
    assert "관심" not in html                  # 그 그룹의 단계 배지는 없다
    assert "무산" in html                      # 이적 무산 그룹은 그대로 둔다


def test_render_players_groups_and_collapses():
    arts = [_art("h1", 1, "rumour"), _art("h2", 2, "agreed")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"}]),
               _player(2, "Nduka", "은두카", "other_club",
                       [{"content_hash": "h2", "stage": "agreed"}])]
    html = render_players(build_player_entries(arts, players), NOW)
    assert "진행 중" in html and "타 클럽행" in html
    assert "이적 확정" not in html                 # 빈 그룹은 그리지 않는다
    assert 'href="player/tzolis.html"' in html
    assert "folded" in html                       # 타 클럽행 그룹 기본 접힘
    assert 'class="side"' not in html             # 사이드바 제외 (스펙 §5.3)


def test_render_player_ladder_line_has_count_and_credibility():
    arts = [_art("h1", 1, "rumour", "촐리스 관심"), _art("h2", 2, "rumour", "촐리스 재보도"),
            _art("h3", 3, None, "촐리스 단계 없음")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"},
                        {"content_hash": "h2", "stage": "rumour"},
                        {"content_hash": "h3", "stage": None}])]
    [e] = build_player_entries(arts, players)
    html = render_player(e, SOURCES, NOW)
    assert "기사 3건" in html
    assert "같은 단계 2건" in html            # 묶음 전체 건수 (대표 포함)
    assert "이후 " not in html                 # 전이형 문구 잔존 방지
    assert "공신력 중" in html                 # tier 2 독자 라벨 — tlsrc 에 병기 (§4.3)
    assert "촐리스 단계 없음" in html          # 단계 없는 기사도 목록에


def test_render_player_shows_collapsed_as_ended_row():
    # 무산 기사는 사다리 줄이 아니라 종결 줄 (tlend) 로 그린다 (단계 재정의 스펙 §8)
    arts = [_art("h1", 1, "negotiating", "촐리스 협상"),
            _art("h2", 5, "collapsed", "촐리스 잔류 확정")]
    players = [_player(1, "Tzolis", "촐리스", "link_dropped",
                       [{"content_hash": "h1", "stage": "negotiating"},
                        {"content_hash": "h2", "stage": "collapsed"}])]
    [e] = build_player_entries(arts, players)
    html = render_player(e, SOURCES, NOW)
    assert 'tlnode tlend' in html              # 종결 줄 존재
    assert html.count('class="tlnode') == 2    # 협상 1줄 + 종결 1줄 — 이중 표기 없음
    assert "무산" in html
    # 종결 줄이 맨 위다 (개정 2026-08-11) — 아래에 두면 끝난 사가가 진행 중으로 읽힌다
    assert html.index('tlnode tlend') < html.index('class="tlnode"')


def test_render_player_ladder_hides_count_when_single():
    arts = [_art("h1", 1, "agreed", "촐리스 합의")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "agreed"}])]
    [e] = build_player_entries(arts, players)
    html = render_player(e, SOURCES, NOW)
    assert "같은 단계" not in html             # 1건이면 건수 표시 없음 (§4.2)


def test_write_player_pages_removes_orphans(tmp_path):
    from bullet_in.serve.render import write_player_pages
    (tmp_path / "player").mkdir()
    (tmp_path / "player" / "gone.html").write_text("낡음", encoding="utf-8")
    arts = [_art("h1", 1, "rumour")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"}])]
    entries = build_player_entries(arts, players)
    write_player_pages(entries, {}, tmp_path, datetime(2026, 7, 6))
    assert (tmp_path / "player" / "tzolis.html").exists()
    assert not (tmp_path / "player" / "gone.html").exists()
    assert (tmp_path / "players.html").exists()


def test_write_player_pages_skips_delete_when_no_entries(tmp_path):
    from bullet_in.serve.render import write_player_pages
    (tmp_path / "player").mkdir()
    (tmp_path / "player" / "keep.html").write_text("기존", encoding="utf-8")
    write_player_pages([], {}, tmp_path, datetime(2026, 7, 6))
    assert (tmp_path / "player" / "keep.html").exists()   # 조회 0건은 오삭제 방어


def test_player_chips_only_include_players_with_pages():
    from bullet_in.serve.render import player_chips
    arts = [_art("h1", 1, "rumour")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"}])]
    chips = player_chips(build_player_entries(arts, players))
    assert chips["h1"] == [{"name": "촐리스", "slug": "tzolis"}]


def test_player_chips_are_empty_for_unlinked_article():
    from bullet_in.serve.render import player_chips
    arts = [_art("h1", 1, "rumour"), _art("h2", 2, "rumour")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"}])]
    assert player_chips(build_player_entries(arts, players)).get("h2") is None


def test_unmatched_articles_lists_staged_rows_without_extraction():
    from bullet_in.serve.render import unmatched_articles
    arts = [_art("h1", 1, "rumour", "추출됨"), _art("h2", 2, "agreed", "추출 실패"),
            _art("h3", 3, "other", "단계 없음")]
    rows = unmatched_articles(arts, linked={"h1"})
    assert [r["title"] for r in rows] == ["추출 실패"]
    assert rows[0]["source"] == "bbc_sport"


def test_unmatched_articles_ignores_stageless_rows():
    from bullet_in.serve.render import unmatched_articles
    arts = [_art("h1", 1, None), _art("h2", 2, "other")]
    assert unmatched_articles(arts, linked=set()) == []


# ── 무산 그룹 접기 — 회귀 가드 (리뷰 지적) ──────────────────────────
# pytest 는 브라우저를 띄우지 않으므로 아래 단언은 app.js · style.css ·
# players.html.j2 세 파일이 같은 문자열 계약 (.plfold 셀렉터 · folded 클래스 ·
# display:none 규칙) 을 공유하는지만 고정한다 — 클릭 시 실제로 접히는 화면
# 동작 자체는 실브라우저(Playwright)로만 검증 가능하다. 이게 없으면 누가
# 버튼 클래스명이나 셀렉터를 바꿔도 pytest 는 전부 통과한 채 접기 기능만
# 조용히 죽는다.
def test_app_js_has_player_group_fold_contract():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert ".plfold" in js                              # 버튼 셀렉터
    assert "folded" in js                                # 토글 클래스명


def test_style_css_folds_playerlist_when_group_is_folded():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert re.search(r"\.plgrp\.folded\s+\.playerlist\s*\{[^}]*display\s*:\s*none", css), (
        ".plgrp.folded .playerlist{display:none} 규칙이 없음 — "
        "접기 버튼을 눌러도 화면에서 목록이 숨지 않는 결함"
    )


def test_style_css_defines_all_eight_transfer_badge_classes():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    for cls in ("t-inlink", "t-outlink", "t-indone", "t-outdone",
                "t-loanin", "t-loanout", "t-dropped", "t-otherclub"):
        assert f".{cls}" in css, f".{cls} 스타일 누락"


def test_transfer_badge_color_splits_in_and_out():
    # 색이 계열을 나른다 — 영입 3종은 green, 방출 3종은 red (2026-08-23 뒤집음).
    # 반대로 두었던 자리라 처음 보는 사람이 들어오는 선수와 나가는 선수를 뒤집어 읽었다.
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    for cls in ("t-inlink", "t-indone", "t-loanin"):
        line = next(l for l in css.splitlines() if l.startswith(f".{cls}{{"))
        assert "var(--green)" in line and "var(--red)" not in line
    for cls in ("t-outlink", "t-outdone", "t-loanout"):
        line = next(l for l in css.splitlines() if l.startswith(f".{cls}{{"))
        assert "var(--red)" in line and "var(--green)" not in line


def test_transfer_badge_never_uses_white_fill():
    # 다크 토큰은 흰 글자와 대비가 무너진다 (red 3.23:1 · green 2.10:1).
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    for cls in ("t-inlink", "t-indone", "t-loanin",
                "t-outlink", "t-outdone", "t-loanout"):
        line = next(l for l in css.splitlines() if l.startswith(f".{cls}{{"))
        assert "background" not in line


def test_render_players_every_group_has_a_fold_button():
    # 접힌 그룹만 버튼이 있으면 펼쳐진 그룹은 접을 수 없고, 접힌 그룹은 비어 보인다.
    entries = [
        {"name": "촐리스", "slug": "tzolis", "transfer_status": "in_link",
         "stage": "interest", "count": 3, "last_ts": datetime(2026, 8, 2)},
        {"name": "모건 로저스", "slug": "rogers", "transfer_status": "other_club",
         "stage": "agreed", "count": 5, "last_ts": datetime(2026, 8, 1)},
    ]
    html = render_players(entries, datetime(2026, 8, 3))
    assert html.count('class="plfold"') == 2
    assert ">접기<" in html
    assert ">펼치기<" in html


def test_build_player_entries_prefers_ko_full_name():
    rows = [{"content_hash": "h1", "published_at": datetime(2026, 8, 1)}]
    players = [{"id": 1, "full_name": "Christos Tzolis", "surname": "Tzolis",
                "ko_full_name": "크리스토스 촐리스", "ko_name": "촐리스",
                "transfer_status": "in_link",
                "links": [{"content_hash": "h1", "stage": "interest",
                           "role": "subject"}]}]
    assert build_player_entries(rows, players)[0]["name"] == "크리스토스 촐리스"


def test_build_player_entries_falls_back_to_ko_name():
    rows = [{"content_hash": "h1", "published_at": datetime(2026, 8, 1)}]
    players = [{"id": 1, "full_name": "Christos Tzolis", "surname": "Tzolis",
                "ko_full_name": None, "ko_name": "촐리스",
                "transfer_status": "in_link",
                "links": [{"content_hash": "h1", "stage": "interest",
                           "role": "subject"}]}]
    assert build_player_entries(rows, players)[0]["name"] == "촐리스"


def test_render_player_section_title_and_flatlist():
    arts = [_art("h1", 1, "rumour")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"}])]
    [e] = build_player_entries(arts, players)
    html = render_player(e, SOURCES, NOW)
    assert "진행 단계" in html and "단계 흐름" not in html   # 제목 (§5.3)
    assert 'class="daylist plist flatlist"' in html          # 행 높이 정렬 (§5.1)


def test_render_player_marks_extra_blocks_beyond_ten():
    arts = [_art(f"h{i}", min(i, 28), "rumour", f"기사 {i}") for i in range(1, 13)]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": f"h{i}", "stage": "rumour"}
                        for i in range(1, 13)])]
    [e] = build_player_entries(arts, players)
    html = render_player(e, SOURCES, NOW)
    assert html.count("pl-extra") == 2                        # 11 · 12번째 블록만
    assert "기사 더보기 · 남은 2건" in html
    assert 'id="plMore"' in html and 'class="latestmore"' in html


def test_render_player_has_no_more_button_at_ten_or_less():
    arts = [_art("h1", 1, "rumour")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"}])]
    [e] = build_player_entries(arts, players)
    html = render_player(e, SOURCES, NOW)
    assert "pl-extra" not in html
    assert "plMore" not in html


# pytest 는 브라우저를 띄우지 않으므로 아래 단언은 세 파일이 같은 문자열 계약
# (pl-extra 클래스 · plMore id) 을 공유하는지만 고정한다 (.plfold 계약 테스트와
# 같은 방식) — 클릭 동작 자체는 실브라우저로만 검증된다.
def test_player_more_contract_shared_across_three_files():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    tpl = Path("src/bullet_in/serve/templates/player.html.j2").read_text(encoding="utf-8")
    assert "pl-extra" in js and "plMore" in js
    assert re.search(r"\.block\.pl-extra\s*\{[^}]*display\s*:\s*none", css), (
        ".block.pl-extra{display:none} 규칙이 없음 — 더보기 전에도 전량 노출되는 결함")
    assert "pl-extra" in tpl and 'id="plMore"' in tpl


def test_app_js_guards_sidebar_null_check_for_daylist_items():
    """선수 페이지는 daylist 가 있지만 사이드바가 없어서 TypeError 유발.

    렌더링된 선수 페이지는 solo=True 로 사이드바를 제외 (클래스 "side" 없음)
    하지만 daylist 클래스는 있어서, 브라우저의 app.js 에서 querySelector('.daylist .item')
    이 반환하는 NodeList 가 비지 않는다. items.length > 0 이므로 조건문 진입하는데,
    side 가 null 이어서 side.addEventListener() 에서 TypeError 가 난다.

    이 조합 (daylist 있음 + side 없음) 을 만드는 유일한 페이지가 player.html.j2
    이므로, app.js 에서 널 검사 && side 가 필수다. 선수 페이지가 생겨서야 문제가 드러났으므로
    회귀 방어는 양쪽 조건을 함께 검증한다."""
    # app.js 가 items.length 체크할 때 side 를 함께 확인하는가?
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "items.length && side" in js, (
        "app.js 에서 items.length 체크에 side 널 검사 병합 필요 — "
        "선수 페이지가 유일하게 daylist 있고 sidebar 없는 조합"
    )

    # render_player 가 정말 그 조합을 출력하는가?
    arts = [_art("h1", 1, "rumour")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"}])]
    [e] = build_player_entries(arts, players)
    html = render_player(e, SOURCES, NOW)
    assert 'class="daylist' in html, (
        "선수 페이지가 daylist 없음 (널 검사 필요성 전제 깨짐)"
    )
    assert 'class="side"' not in html, (
        "선수 페이지가 sidebar 있음 (널 검사 필요성 전제 깨짐)"
    )


def test_render_players_sorts_group_members_by_latest_report():
    # 색인은 최근 보도순이다 (2026-08-23 에 성 가나다순으로 갔다가 2026-08-28 되돌림).
    #
    # 두 차례를 실제로 가르는 배치여야 한다 — 이 테스트는 되돌리기 전까지 가나다
    # 앞선 선수에게 최신 기사를 줘서 어느 정렬이든 같은 답이 나왔고, 그래서 정렬을
    # 바꿔도 통과했다. 이제는 가나다 앞선 넬슨에게 옛 기사를 준다.
    arts = [_art("h1", 1, "rumour"), _art("h2", 9, "rumour")]
    players = [_player(1, "Nelson", "넬슨", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"}]),
               _player(2, "Gyokeres", "요케레스", "in_link",
                       [{"content_hash": "h2", "stage": "rumour"}])]
    html = render_players(build_player_entries(arts, players), NOW)
    assert html.index("요케레스") < html.index("넬슨")


# --- 선수 색인 개정 2026-08-28 (정렬 되돌림 · 전환 단추 · 카드 사진) ----------

from bullet_in.serve.render import assign_player_photos


def _pe(name, slug, last, status="in_link", articles=None):
    return {"name": name, "ko_name": name, "slug": slug, "transfer_status": status,
            "stage": "interest", "count": len(articles or []) or 1,
            "last_ts": last, "articles": articles or []}


def _pimg(h, img, source_id="skysports"):
    return {"content_hash": h, "image_url": img, "source_id": source_id}


def test_player_index_defaults_to_most_recent_first():
    entries = [_pe("가온", "a", datetime(2026, 7, 1)),
               _pe("하온", "h", datetime(2026, 8, 28)),
               _pe("나온", "n", datetime(2026, 8, 10))]
    html = render_players(entries, datetime(2026, 8, 28))
    assert html.index("하온") < html.index("나온") < html.index("가온")


def test_player_index_carries_both_sort_keys_for_the_toggle():
    html = render_players([_pe("촐리스", "tzolis", datetime(2026, 8, 2))],
                          datetime(2026, 8, 3))
    assert 'data-last="2026-08-02T00:00:00"' in html
    assert 'data-name="촐리스"' in html
    assert 'id="plSort"' in html and ">최근 보도순<" in html


def test_player_photo_comes_from_the_newest_article_with_an_image():
    e = _pe("알바레스", "alvarez", datetime(2026, 8, 28),
            articles=[_pimg("h1", None), _pimg("h2", "img-new"), _pimg("h3", "img-old")])
    assign_player_photos([e])
    assert e["_photo"] == "img-new"


def test_player_photo_skips_the_gossip_banner():
    e = _pe("콘사", "konsa", datetime(2026, 8, 28),
            articles=[_pimg("h1", "banner", source_id="bbc_gossip"),
                      _pimg("h2", "real")])
    assign_player_photos([e])
    assert e["_photo"] == "real"


def test_two_players_never_share_one_photo():
    # 둘이 함께 찍힌 사진이 서로 다른 카드에 걸리면 어느 쪽도 못 믿는다.
    hot = _pe("래시포드", "rashford", datetime(2026, 8, 28),
              articles=[_pimg("h1", "both")])
    cold = _pe("마르티넬리", "martinelli", datetime(2026, 8, 20),
               articles=[_pimg("h1", "both"), _pimg("h2", "own")])
    assign_player_photos([hot, cold])
    assert hot["_photo"] == "both"      # 최근 보도가 있는 쪽이 먼저 가져간다
    assert cold["_photo"] == "own"


def test_player_with_no_usable_image_gets_no_photo():
    e = _pe("스벤손", "svensson", datetime(2026, 8, 1),
            articles=[_pimg("h1", None), _pimg("h2", "")])
    assign_player_photos([e])
    assert e["_photo"] is None
    html = render_players([e], datetime(2026, 8, 2))
    assert "hasphoto" not in html


def test_player_photo_removes_its_slot_when_the_image_fails():
    # onerror 가 없으면 실패한 사진 자리에 빈 회색 상자가 남는다 (기사 썸네일과 같은 규약).
    e = _pe("알바레스", "alvarez", datetime(2026, 8, 28),
            articles=[_pimg("h1", "https://x/img.jpg")])
    html = render_players([e], datetime(2026, 8, 28))
    assert 'referrerpolicy="no-referrer"' in html
    assert "classList.remove('hasphoto')" in html
    assert "closest('.pphoto').remove()" in html


def test_pinned_photo_beats_the_automatic_pick():
    # 자동 선택은 회차마다 갈아타므로 (30일에 177회 실측) 어긋난 선수만 손으로 박는다.
    e = _pe("알렉스 스콧", "scott", datetime(2026, 8, 27),
            articles=[_pimg("h1", "남의-얼굴.jpg")])
    e["photo_url"] = "https://x/scott.jpg"
    assign_player_photos([e])
    assert e["_photo"] == "https://x/scott.jpg"


def test_pinned_photo_is_not_reused_by_the_automatic_pick():
    # 박은 사진을 다른 선수가 또 가져가면 박은 뜻이 없어진다.
    pinned = _pe("스콧", "scott", datetime(2026, 8, 20), articles=[])
    pinned["photo_url"] = "https://x/shared.jpg"
    auto = _pe("래시포드", "rashford", datetime(2026, 8, 28),
               articles=[_pimg("h1", "https://x/shared.jpg"), _pimg("h2", "own.jpg")])
    assign_player_photos([pinned, auto])
    assert pinned["_photo"] == "https://x/shared.jpg"
    assert auto["_photo"] == "own.jpg"


def test_blank_pin_falls_back_to_the_automatic_pick():
    e = _pe("콘사", "konsa", datetime(2026, 8, 28), articles=[_pimg("h1", "auto.jpg")])
    e["photo_url"] = "   "
    assign_player_photos([e])
    assert e["_photo"] == "auto.jpg"


# --- 이적시장 타이머 일정 (2026-08-28) --------------------------------------
# 계산은 app.js 가 하고 여기서는 재료만 본다 — 값이 틀리면 화면이 조용히 어긋난다.

from datetime import timezone as _tz  # noqa: E402

from bullet_in.serve.render import TRANSFER_WINDOWS  # noqa: E402


def _iso(s):
    return datetime.fromisoformat(s)


def test_transfer_windows_carry_an_explicit_utc_offset():
    # 「9월 1일 23시」 만 적으면 읽는 쪽 시간대에 따라 어긋난다 — 오프셋을 못박는다.
    for w in TRANSFER_WINDOWS:
        for key in ("open", "close"):
            assert _iso(w[key]).tzinfo is not None, f"{w['name']} {key} 에 오프셋이 없다"


def test_transfer_windows_are_ordered_and_non_overlapping():
    for a, b in zip(TRANSFER_WINDOWS, TRANSFER_WINDOWS[1:]):
        assert _iso(a["open"]) < _iso(a["close"]) <= _iso(b["open"])


def test_summer_deadline_is_the_announced_instant():
    # 현지 2026-09-01 23:00 (BST) = 한국 2026-09-02 07:00 · 사용자가 준 값이다.
    close = _iso(next(w for w in TRANSFER_WINDOWS if w["name"] == "여름")["close"])
    assert close.astimezone(_tz.utc) == datetime(2026, 9, 1, 22, 0, tzinfo=_tz.utc)


def test_winter_window_opens_new_year_and_closes_february_first():
    w = next(w for w in TRANSFER_WINDOWS if w["name"] == "겨울")
    assert _iso(w["open"]).astimezone(_tz.utc) == datetime(2027, 1, 1, 0, 0, tzinfo=_tz.utc)
    assert _iso(w["close"]).astimezone(_tz.utc) == datetime(2027, 2, 1, 23, 0, tzinfo=_tz.utc)


def test_layout_carries_the_schedule_to_the_page():
    html = render_players([_pe("촐리스", "tzolis", datetime(2026, 8, 2))],
                          datetime(2026, 8, 3))
    assert 'id="mktClock"' in html and "data-windows=" in html
    assert "여름" in html and "겨울" in html


def test_timeline_title_carries_the_article_hash_for_click_tracking():
    """선수 페이지 타임라인 제목에도 기사 해시를 싣는다 (2026-09-02).

    클릭 계측이 `dataset.hash` 를 읽는데 이 자리에만 속성이 없어,
    표면 `tltitle` 의 클릭이 어느 기사인지 모르는 채로 쌓였다."""
    arts = [_art("tlh1", 1, "interest", "스톤스, 아스날 관심")]
    players = [_player(1, "Stones", "스톤스", "incoming",
                       [{"content_hash": "tlh1", "stage": "interest"}])]
    [e] = build_player_entries(arts, players)
    html = render_player(e, SOURCES, NOW)
    assert re.search(r'class="tltitle"[^>]*data-hash="tlh1"', html)


def test_player_card_carries_the_slug_for_click_tracking():
    """선수 카드에도 선수 식별자를 싣는다 (2026-09-03).

    선수 카드에는 기사 해시가 없어 클릭 48건이 어느 선수인지 모르는 채로 쌓였다.
    주소에는 이미 slug 가 들어 있어 값을 새로 만들 필요가 없다."""
    arts = [_art("ph1", 1, "rumour", "스톤스, 아스날 관심")]
    players = [_player(1, "Stones", "스톤스", "other_club",
                       [{"content_hash": "ph1", "stage": "rumour"}])]
    html = render_players(build_player_entries(arts, players), NOW)
    assert re.search(r'class="pcard[^"]*"[^>]*data-slug="stones"', html)
