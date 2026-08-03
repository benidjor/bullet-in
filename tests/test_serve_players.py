"""선수 색인 · 선수 페이지 순수 함수 단위 테스트 (스펙 §4 · §5)."""
import re
from datetime import datetime
from pathlib import Path
from bullet_in.serve.render import (TRANSFER_GROUPS, player_slug, stage_timeline,
                                    transfer_badge, transfer_group)

NOW = datetime(2026, 7, 10, 12, 0)
SOURCES = {"bbc_sport": {"display_name": "BBC Sport", "serving": "full"}}
STATIC = Path("src/bullet_in/serve/static")


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
    assert transfer_group("in_done") == "이적 확정"
    assert transfer_group("out_done") == "이적 확정"
    assert transfer_group("loan_in") == "이적 확정"
    assert transfer_group("loan_out") == "이적 확정"
    assert transfer_group("link_dropped") == "이적 무산"
    assert transfer_group("other_club") == "타 클럽행"
    assert transfer_group("none") == ""


def test_transfer_groups_order_and_collapse_flag():
    assert TRANSFER_GROUPS == [
        ("진행 중", False), ("이적 확정", False),
        ("이적 무산", True), ("타 클럽행", True)]


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
    # draft 리뷰에서 실제로 잡혔던 결함 — 머리와 목록이 어긋나지 않도록
    # 둘 다 other 를 뺀 같은 집합에서 나온다 (스펙 §5.3)
    arts = [_art("h1", 1, "rumour"), _art("h2", 2, None), _art("h3", 3, "other")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"},
                        {"content_hash": "h2", "stage": None},
                        {"content_hash": "h3", "stage": "other"}])]
    [e] = build_player_entries(arts, players)
    assert e["count"] == len(e["articles"]) == 2
    assert [n["stage"] for n in e["timeline"]] == ["rumour"]


def test_build_player_entries_excludes_other_from_list_and_count():
    # 머리 건수와 목록 수가 어긋나면 안 되므로 둘 다 같은 집합에서 나와야 한다.
    rows = [{"content_hash": "h1", "published_at": datetime(2026, 8, 1)},
            {"content_hash": "h2", "published_at": datetime(2026, 8, 2)},
            {"content_hash": "h3", "published_at": datetime(2026, 8, 3)}]
    players = [{"id": 1, "full_name": "Christos Tzolis", "surname": "Tzolis",
                "ko_full_name": None, "ko_name": "촐리스",
                "transfer_status": "in_link",
                "links": [{"content_hash": "h1", "stage": "interest"},
                          {"content_hash": "h2", "stage": "other"},
                          {"content_hash": "h3", "stage": "agreed"}]}]
    entry = build_player_entries(rows, players)[0]
    assert entry["count"] == 2
    assert len(entry["articles"]) == 2
    assert [a["content_hash"] for a in entry["articles"]] == ["h3", "h1"]


def test_build_player_entries_current_stage_is_latest_node():
    arts = [_art("h1", 1, "agreed"), _art("h2", 5, "rumour")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "agreed"},
                        {"content_hash": "h2", "stage": "rumour"}])]
    [e] = build_player_entries(arts, players)
    assert e["stage"] == "rumour"          # 역행이어도 최신 노드 값


def test_build_player_entries_drops_player_whose_articles_are_all_other():
    # 이적 얘기가 없는데 이름만 스친 선수 — 색인 56명이 50명으로 줄어든 근거다.
    rows = [{"content_hash": "h1", "published_at": datetime(2026, 8, 1)},
            {"content_hash": "h2", "published_at": datetime(2026, 8, 2)}]
    players = [{"id": 1, "full_name": "Martin Zubimendi", "surname": "Zubimendi",
                "ko_full_name": None, "ko_name": "수비멘디",
                "transfer_status": "in_link",
                "links": [{"content_hash": "h1", "stage": "other"},
                          {"content_hash": "h2", "stage": "other"}]}]
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
    assert "진행 중" in html and "타 클럽행" in html
    assert "이적 확정" not in html                 # 빈 그룹은 그리지 않는다
    assert 'href="player/tzolis.html"' in html
    assert "folded" in html                       # 타 클럽행 그룹 기본 접힘
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
    # 색이 계열을 나른다 — 영입 3종은 red, 방출 3종은 green.
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    for cls in ("t-inlink", "t-indone", "t-loanin"):
        line = next(l for l in css.splitlines() if l.startswith(f".{cls}{{"))
        assert "var(--red)" in line and "var(--green)" not in line
    for cls in ("t-outlink", "t-outdone", "t-loanout"):
        line = next(l for l in css.splitlines() if l.startswith(f".{cls}{{"))
        assert "var(--green)" in line and "var(--red)" not in line


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
                "links": [{"content_hash": "h1", "stage": "interest"}]}]
    assert build_player_entries(rows, players)[0]["name"] == "크리스토스 촐리스"


def test_build_player_entries_falls_back_to_ko_name():
    rows = [{"content_hash": "h1", "published_at": datetime(2026, 8, 1)}]
    players = [{"id": 1, "full_name": "Christos Tzolis", "surname": "Tzolis",
                "ko_full_name": None, "ko_name": "촐리스",
                "transfer_status": "in_link",
                "links": [{"content_hash": "h1", "stage": "interest"}]}]
    assert build_player_entries(rows, players)[0]["name"] == "촐리스"


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
