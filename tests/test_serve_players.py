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


from bullet_in.serve.render import build_player_entries


def _art(h, day, stage=None, title="제목"):
    """서빙 행 — tests/test_serve_render.py 의 _row 와 같은 컬럼 구성을 따른다.
    _decorate 가 url · image_url · tier 를 읽으므로 빠뜨리면 렌더 테스트가 깨진다."""
    return {"content_hash": h, "url": f"https://x/{h}", "source_id": "bbc_sport",
            "title_original": title, "title_ko": title, "summary_ko": "한 줄 요약",
            "tier": 2, "confidence_score": 0.5, "image_url": None, "outlet": None,
            "team": "arsenal", "transfer_stage": stage,
            "published_at": datetime(2026, 7, day, 12, 0)}


def _player(pid, surname, ko, status, links):
    """links = [{"content_hash", "stage"}] — page_player_links 반환 형태."""
    return {"id": pid, "full_name": f"{ko} {surname}", "surname": surname,
            "ko_name": ko, "transfer_status": status, "links": links}


def test_build_player_entries_orders_articles_newest_first():
    arts = [_art("h1", 1, "rumour"), _art("h2", 5, "interest")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"},
                        {"content_hash": "h2", "stage": "interest"}])]
    [e] = build_player_entries(arts, players)
    assert [a["content_hash"] for a in e["articles"]] == ["h2", "h1"]
    assert e["count"] == 2


def test_build_player_entries_header_count_matches_article_list():
    # draft 리뷰에서 실제로 잡혔던 결함 — 단계 없는 기사도 목록에 든다 (스펙 §5.3)
    arts = [_art("h1", 1, "rumour"), _art("h2", 2, None), _art("h3", 3, "other")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"},
                        {"content_hash": "h2", "stage": None},
                        {"content_hash": "h3", "stage": "other"}])]
    [e] = build_player_entries(arts, players)
    assert e["count"] == len(e["articles"]) == 3
    assert [n["stage"] for n in e["timeline"]] == ["rumour"]


def test_build_player_entries_current_stage_is_latest_node():
    arts = [_art("h1", 1, "agreed"), _art("h2", 5, "rumour")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "agreed"},
                        {"content_hash": "h2", "stage": "rumour"}])]
    [e] = build_player_entries(arts, players)
    assert e["stage"] == "rumour"          # 역행이어도 최신 노드 값


def test_build_player_entries_has_no_stage_when_all_other():
    arts = [_art("h1", 1, "other")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "other"}])]
    [e] = build_player_entries(arts, players)
    assert e["stage"] is None


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
                "links": [{"content_hash": "h1", "stage": "rumour"}]}]
    [e] = build_player_entries(arts, players)
    assert e["name"] == "Aladji Bamba"


from bullet_in.serve.render import render_player, render_players


def test_render_players_groups_and_collapses():
    arts = [_art("h1", 1, "rumour"), _art("h2", 2, "agreed")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"}]),
               _player(2, "Nduka", "은두카", "other_club",
                       [{"content_hash": "h2", "stage": "agreed"}])]
    html = render_players(build_player_entries(arts, players), NOW)
    assert "진행 중" in html and "무산과 종료" in html
    assert "성사" not in html                     # 빈 그룹은 그리지 않는다
    assert 'href="player/tzolis.html"' in html
    assert "folded" in html                       # 무산 그룹 기본 접힘
    assert 'class="side"' not in html             # 사이드바 제외 (스펙 §5.3)


def test_render_player_shows_timeline_and_full_list():
    arts = [_art("h1", 1, "rumour", "촐리스 관심"), _art("h2", 2, "rumour", "촐리스 재보도"),
            _art("h3", 3, None, "촐리스 단계 없음")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"},
                        {"content_hash": "h2", "stage": "rumour"},
                        {"content_hash": "h3", "stage": None}])]
    [e] = build_player_entries(arts, players)
    html = render_player(e, SOURCES, NOW)
    assert "기사 3건" in html
    assert "이후 1건" in html                     # 같은 단계 연속 접힘
    assert "촐리스 단계 없음" in html              # 단계 없는 기사도 목록에


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
