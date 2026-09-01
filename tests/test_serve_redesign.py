"""UI 개편 뷰모델 헬퍼 단위 테스트 (docs/superpowers/plans/2026-07-22-serve-ui-redesign.md)."""
from collections import Counter
from datetime import date, datetime

from bullet_in.serve import render as R


# ── Task 1: 표시 단계 매핑 · 독자 등급 라벨 ──────────────────────────────

def test_display_stage_folds_medical_and_personal_terms():
    # 메디컬 배지는 이적 합의로 접는다 (단계 재정의 스펙 2026-08-10 §3 — 협상 중에서 이동)
    # 개인 합의는 제안 · 협상으로 접는다 (2026-08-13) — 구단 간 합의 전이라 이적 합의로
    # 접으면 딜이 성사된 것으로 읽힌다 (개인 합의까지 갔다가 무산된 실측 사례가 있다)
    assert R.display_stage("official") == {"label": "오피셜", "tone": "red", "filled": True}
    assert R.display_stage("done") == {"label": "이적 완료", "tone": "blue", "filled": False}
    assert R.display_stage("agreed") == {"label": "이적 합의", "tone": "red", "filled": False}
    assert R.display_stage("medical") == {"label": "이적 합의", "tone": "red", "filled": False}
    assert R.display_stage("negotiating") == {"label": "제안 · 협상", "tone": "green", "filled": False}
    assert R.display_stage("personal_terms") == {"label": "제안 · 협상", "tone": "green", "filled": False}
    assert R.display_stage("interest") == {"label": "관심", "tone": "gray", "filled": False}
    assert R.display_stage("rumour") == {"label": "루머", "tone": "gray", "filled": False}
    assert R.display_stage("collapsed") == {"label": "무산", "tone": "ash", "filled": False}
    assert R.display_stage("other") is None
    assert R.display_stage(None) is None


def test_reader_tier_hides_internal_grade():
    assert R.reader_tier(0.0) == "구단 공식"
    assert R.reader_tier(1.0) == "공신력 최상"
    assert R.reader_tier(1.5) == "공신력 상"
    assert R.reader_tier(2.0) == "공신력 중"
    assert R.reader_tier(3.0) == "공신력 하"
    assert R.reader_tier(4.0) == "공신력 최하"
    assert R.reader_tier(None) == ""


# ── Task 2: KST 변환 · 날짜 묶기 · 번역 대기 표지 ────────────────────────

def test_to_kst_adds_nine_hours():
    assert R.to_kst(datetime(2026, 7, 20, 1, 0)) == datetime(2026, 7, 20, 10, 0)


def test_group_by_day_labels_today_and_yesterday():
    now = datetime(2026, 7, 20, 3, 0)   # KST 12:00
    a = {"content_hash": "a", "published_at": datetime(2026, 7, 20, 2, 0),
         "published_precision": "time", "fetched_at": datetime(2026, 7, 20, 2, 0)}
    b = {"content_hash": "b", "published_at": datetime(2026, 7, 19, 2, 0),
         "published_precision": "time", "fetched_at": datetime(2026, 7, 19, 2, 0)}
    groups = R.group_by_day([a, b], now)
    assert groups[0]["label"] == "오늘"
    assert groups[0]["articles"] == [a]
    assert groups[1]["label"] == "어제"


def test_group_by_day_older_uses_weekday_label():
    now = datetime(2026, 7, 20, 3, 0)          # KST 2026-07-20 (월)
    old = {"content_hash": "c", "published_at": datetime(2026, 7, 18, 2, 0),
           "published_precision": "time", "fetched_at": datetime(2026, 7, 18, 2, 0)}
    groups = R.group_by_day([old], now)
    assert groups[0]["label"] == "7월 18일 (토)"   # 2026-07-18 = 토요일


def test_time_in_group_blank_for_day_precision():
    row_time = {"published_at": datetime(2026, 7, 20, 1, 30), "published_precision": "time"}
    row_day = {"published_at": datetime(2026, 7, 20, 1, 30), "published_precision": "day"}
    assert R.time_in_group(row_time) == "10:30"
    assert R.time_in_group(row_day) == ""


def test_published_datetime_time_precision_shows_kst_time():
    row = {"published_at": datetime(2026, 7, 14, 13, 37), "published_precision": "time"}
    assert R.published_datetime(row) == "2026-07-14 22:37"   # KST = +9h


def test_published_datetime_day_precision_date_only():
    row = {"published_at": datetime(2026, 7, 14, 0, 0), "published_precision": "day"}
    assert R.published_datetime(row) == "2026-07-14"         # 없는 시각을 지어내지 않음


def test_published_datetime_blank_without_pub():
    assert R.published_datetime({"published_at": None}) == ""


def test_title_pending_when_ko_missing():
    assert R.title_pending({"title_ko": None, "title_original": "Arsenal sign X"}) is True
    assert R.title_pending({"title_ko": "", "title_original": "Arsenal sign X"}) is True
    assert R.title_pending({"title_ko": "아스날 X 영입", "title_original": "Arsenal sign X"}) is False
    assert R.title_pending({"title_ko": None, "title_original": None}) is False


def test_gossip_when_date_only_even_with_time_precision():
    # 가십 카드는 날짜만 — 상세한 시각은 메타 줄을 줄바꿈시켜 3열 간격을 깬다 (상세 페이지에만)
    now = datetime(2026, 7, 23, 0, 0)
    row = {"published_at": datetime(2026, 7, 15, 11, 0), "published_precision": "time",
           "fetched_at": datetime(2026, 7, 20, 12, 0)}
    assert R.gossip_when(row, now) == "7월 15일 (수)"


def test_gossip_when_none_precision_date_only():
    now = datetime(2026, 7, 23, 0, 0)
    row = {"published_at": datetime(2026, 7, 20, 12, 43), "published_precision": None,
           "fetched_at": datetime(2026, 7, 20, 18, 0)}
    assert R.gossip_when(row, now) == "7월 20일 (월)"


def test_bbc_gossip_stage_matches_stored_rumour():
    # 가십 루머 롤업 하드코딩은 저장 계층 규칙 (rule_stage) 으로 이동했다
    # (방향 축 스펙 §5) — _decorate 는 더 이상 source_id 로 override 하지 않고
    # 저장값을 그대로 쓴다. 배포판 실측으로 bbc_gossip 전행이 이미 rumour 로
    # 저장돼 있어 화면 표시는 하드코딩 제거 전후로 동일하다.
    now = datetime(2026, 7, 23)
    row = {"content_hash": "x", "source_id": "bbc_gossip",
           "transfer_stage": "rumour", "title_ko": "t", "tier": 4.0}
    a = R._decorate(row, {}, now)
    assert a["_stage_disp"] == {"label": "루머", "tone": "gray", "filled": False}
    assert a["_stage"] == "rumour"      # 필터 키도 루머로 일치


# ── Task 3: 톱스토리 선정 (히어로 · 주요 소식) ──────────────────────────

def _row(**k):
    base = {"title_ko": "제목", "tier": 1.0, "transfer_stage": "rumour",
            "published_at": datetime(2026, 7, 20), "published_precision": "time",
            "fetched_at": datetime(2026, 7, 20), "image_url": "https://x/y.jpg"}
    base.update(k)
    return base


def test_arsenal_subject_startswith():
    assert R.arsenal_subject({"title_ko": "아스날, 요케레스 영입"}) is True
    assert R.arsenal_subject({"title_ko": "첼시, 로저스 영입 합의"}) is False
    assert R.arsenal_subject({"title_ko": None}) is False


def test_arsenal_subject_true_for_club_official_whatever_the_title():
    # 구단 공식은 아스날이 직접 낸 발표라 제목이 선수 이름으로 시작해도 주체가 아스날이다
    # (2026-09-02 실측 — Arsenal.com 의 「가브리엘 제주스, FC 바르셀로나로 완전 이적」 이
    #  제목 첫 글자 때문에 남의 소식으로 판정돼 1면에서 밀렸다)
    assert R.arsenal_subject({"title_ko": "가브리엘 제주스, FC 바르셀로나로 완전 이적",
                              "tier": 0.0}) is True


def test_arsenal_subject_keeps_title_rule_below_club_official():
    # 구단 공식이 아니면 종전대로 제목으로 판정한다
    assert R.arsenal_subject({"title_ko": "바르셀로나, 제주스 영입 완료",
                              "tier": 1.0}) is False
    assert R.arsenal_subject({"title_ko": "아스날, 제주스 이적 합의",
                              "tier": 1.0}) is True


def test_top_story_club_official_beats_an_earlier_one_by_time():
    # 같은 구단 공식끼리는 시각으로 갈린다 — 제목 형태가 그 앞을 가로막지 않는다
    now = datetime(2026, 7, 20, 18, 0)
    early = _row(content_hash="early", tier=0.0, transfer_stage="official",
                 title_ko="아스날 미드필더 트로사르, 함부르크로 완전 이적",
                 published_at=datetime(2026, 7, 20, 11, 0),
                 fetched_at=datetime(2026, 7, 20, 11, 0))
    late = _row(content_hash="late", tier=0.0, transfer_stage="official",
                title_ko="가브리엘 제주스, FC 바르셀로나로 완전 이적",
                published_at=datetime(2026, 7, 20, 12, 47),
                fetched_at=datetime(2026, 7, 20, 12, 47))
    assert R.pick_top_stories([early, late], now)["lead"] is late


def test_top_story_excludes_below_top_three_tiers():
    now = datetime(2026, 7, 20, 12, 0)
    low = _row(tier=4.0, title_ko="아스날 트로사르 방출")
    hi = _row(tier=0.0, title_ko="레안드로 트로사르 베식타스 이적")
    picks = R.pick_top_stories([low, hi], now)
    assert picks["lead"] is hi            # tier 4 는 후보 제외 (상위 3등급만)
    assert low not in picks["mains"]


def test_arsenal_subject_beats_higher_tier():
    now = datetime(2026, 7, 20, 12, 0)
    leak = _row(tier=1.0, title_ko="맨시티, 아스날 유망주 은두카 영입")
    ours = _row(tier=1.5, title_ko="아스날, 요케레스 영입 임박")
    picks = R.pick_top_stories([leak, ours], now)
    assert picks["lead"] is ours          # 아스날 주체가 공신력보다 앞 (spec2 §5 2번)


def test_top_story_horizon_excludes_old():
    now = datetime(2026, 7, 20, 12, 0)
    old = _row(tier=0.0, published_at=datetime(2026, 7, 5), fetched_at=datetime(2026, 7, 5))
    assert R.pick_top_stories([old], now)["lead"] is None   # 10일 초과 제외


def test_top_story_mains_display_newest_first():
    # 주요 소식은 선정 순위(단계·공신력)와 무관하게 화면에서 최신 먼저 (Image #6)
    now = datetime(2026, 7, 23, 12, 0)
    lead_pick = _row(content_hash="L", tier=0.0, title_ko="아스날, C 영입 오피셜",
                     transfer_stage="official", published_at=datetime(2026, 7, 13, 10, 0),
                     fetched_at=datetime(2026, 7, 13, 10, 0))
    main_old = _row(content_hash="A", tier=0.0, title_ko="아스날, A 영입 합의",
                    transfer_stage="agreed", published_at=datetime(2026, 7, 14, 10, 0),
                    fetched_at=datetime(2026, 7, 14, 10, 0))
    main_new = _row(content_hash="B", tier=0.0, title_ko="아스날, B 영입 협상",
                    transfer_stage="negotiating", published_at=datetime(2026, 7, 22, 10, 0),
                    fetched_at=datetime(2026, 7, 22, 10, 0))
    picks = R.pick_top_stories([lead_pick, main_old, main_new], now)
    assert picks["lead"]["content_hash"] == "L"        # 히어로는 선정 순위(단계 오피셜) 그대로
    assert [m["content_hash"] for m in picks["mains"]] == ["B", "A"]   # 주요 소식만 최신순


def test_group_blocks_reports_counts_same_day_only():
    # 보도 건수는 그 날짜 기사만 (묶음은 여러 날에 걸치므로 대표 날짜 기사만 카운트)
    now = datetime(2026, 7, 23)

    def art(h, day):
        return {"content_hash": h, "published_at": datetime(2026, 7, day, 1, 0),
                "published_precision": "time", "fetched_at": datetime(2026, 7, day, 1, 0)}

    rep = art("r", 19)
    block = {"rep": rep, "count": 3, "_articles": [rep, art("a2", 19), art("a3", 15)]}
    out = R.group_blocks_by_day([block], now)
    assert out[0]["label"] == "7월 19일 (일)"
    assert out[0]["reports"] == 2      # 7/19 기사 2건만 · 7/15 는 제외


def test_top_story_mains_capped_at_four():
    now = datetime(2026, 7, 20, 12, 0)
    rows = [_row(tier=0.0, published_at=datetime(2026, 7, 20, h)) for h in range(6)]
    picks = R.pick_top_stories(rows, now)
    assert picks["lead"] is not None
    assert len(picks["mains"]) == 4


# ── Task 10-14: 사건 묶음 ───────────────────────────────────────────

PLAYERS = ["기마랑이스", "디오망데", "로저스", "트로사르"]
CLUBS = {"첼시": ["Chelsea"], "뉴캐슬": ["Newcastle"], "토트넘": ["Tottenham", "Spurs"]}


def test_protagonist_after_transition_word():
    assert R.protagonist("아스날, 로저스 놓친 후 디오망데 측과 접촉", PLAYERS) == "디오망데"


def test_protagonist_no_transition_uses_first():
    assert R.protagonist("아스날, 트로사르 재계약 임박", PLAYERS) == "트로사르"


def test_protagonist_transition_without_dict_player_keeps_first():
    assert R.protagonist("아스날, 로저스 놓친 후 다른 선수 물색", PLAYERS) == "로저스"


def test_protagonist_after_release_word():
    # 「A 방출 … B 영입」 — 앞 선수가 나가고 뒤 선수가 그 소식의 주인공이다 (2026-08-28).
    # 실물: 「가브리엘 마르티넬리 방출 결정에 내부적 의문 제기…마커스 래시포드 임대 영입설」
    assert R.protagonist("로저스 방출 결정에 의문…디오망데 임대 영입설", PLAYERS) == "디오망데"


def test_protagonist_after_vacancy_word():
    # 「A 공백 … B」 — 앞 선수가 비운 자리를 뒤 선수가 메운다 (2026-08-28).
    # 실물: 「윌리엄 살리바 공백 메울 적임자로 낙점된 에즈리 콘사」
    assert R.protagonist("로저스 공백 메울 적임자로 낙점된 디오망데", PLAYERS) == "디오망데"


def test_protagonist_release_without_a_player_after_it_keeps_first():
    # 「A 방출」 로 끝나면 뒤에 선수가 없으므로 A 가 그대로 주인공이다.
    assert R.protagonist("아스날, 트로사르 방출", PLAYERS) == "트로사르"


def test_protagonist_none_when_no_player():
    assert R.protagonist("아스날, 여름 이적 시장 대비", PLAYERS) is None


def test_cluster_groups_same_protagonist():
    a = _row(content_hash="a", title_ko="아스날, 로저스 영입 추진")
    b = _row(content_hash="b", title_ko="첼시, 로저스 영입 합의")
    c = _row(content_hash="c", title_ko="아스날, 트로사르 방출")
    clusters = R.cluster_events([a, b, c], PLAYERS)
    by_key = {cl["key"]: [x["content_hash"] for x in cl["articles"]] for cl in clusters}
    assert by_key["로저스"] == ["a", "b"]
    assert by_key["트로사르"] == ["c"]


def _on_day(h, day, stage, title, hour=12):
    """지정한 7월 날짜의 기사 — 묶음 키가 날짜로 갈리는지 보는 데 쓴다."""
    return _row(content_hash=h, transfer_stage=stage, title_ko=title,
                published_at=datetime(2026, 7, day, hour, 0),
                fetched_at=datetime(2026, 7, day, hour, 0))


def test_cluster_events_splits_by_day():
    # 하루 안에서만 묶는다 — 어제 기사와 오늘 기사는 같은 선수라도 다른 카드다
    a = _on_day("a", 20, "interest", "아스날, 로저스 영입 검토")
    b = _on_day("b", 21, "interest", "아스날, 로저스 영입 추진")
    out = R.cluster_events([b, a], ["로저스"])
    assert len(out) == 2
    assert {len(c["articles"]) for c in out} == {1, 1}


def test_cluster_events_splits_by_display_stage():
    # 같은 날 같은 선수라도 화면 배지가 다르면 다른 카드다
    a = _on_day("a", 20, "interest", "아스날, 로저스 영입 검토", hour=1)
    b = _on_day("b", 20, "agreed", "아스날, 로저스 영입 합의", hour=2)
    out = R.cluster_events([b, a], ["로저스"])
    assert len(out) == 2


def test_cluster_events_folds_medical_into_agreed():
    # 표시 묶음으로 묶으므로 메디컬과 이적 합의는 한 카드다 (배지가 같다)
    a = _on_day("a", 20, "agreed", "아스날, 로저스 영입 합의", hour=1)
    b = _on_day("b", 20, "medical", "로저스, 메디컬 테스트", hour=2)
    out = R.cluster_events([b, a], ["로저스"])
    assert len(out) == 1
    assert out[0]["stage_group"] == "이적 합의"


def test_cluster_events_keeps_unstaged_articles_single():
    # 단계가 기타 · 빈 값이면 묶지 않는다 (카드에서 기본 숨김인 값이다)
    a = _on_day("a", 20, "other", "아스날, 로저스 관련 보도", hour=1)
    b = _on_day("b", 20, "other", "아스날, 로저스 다른 보도", hour=2)
    out = R.cluster_events([b, a], ["로저스"])
    assert len(out) == 2


def test_pick_representative_lowest_excluded_when_higher_exists():
    afc = _row(content_hash="afc", tier=4.0, title_ko="아스날, 로저스 영입 추진", body_ko="")
    sky = _row(content_hash="sky", tier=1.0, title_ko="첼시, 로저스 영입 합의", body_ko="")
    assert R.pick_representative([afc, sky]) is sky        # 최하 제외 가드 (로저스 사고)


def test_pick_representative_official_always():
    off = _row(content_hash="off", tier=0.0, title_ko="첼시, 로저스 영입 공식 발표", body_ko="")
    ars = _row(content_hash="ars", tier=1.5, title_ko="아스날, 로저스 관심", body_ko="")
    assert R.pick_representative([off, ars]) is off


def test_pick_representative_prefers_credibility_over_recency():
    # 같은 날 같은 단계면 늦게 들어온 낮은 등급보다 공신력이 앞선다 (2026-09-02)
    late_mid = _row(content_hash="late", tier=2.0, body_ko="본문", body_level=1,
                    title_ko="아스날, 포파나 영입 검토",
                    published_at=datetime(2026, 7, 20, 7, 0),
                    fetched_at=datetime(2026, 7, 20, 7, 0))
    early_top = _row(content_hash="early", tier=1.0, body_ko="본문", body_level=1,
                     title_ko="아스날, 포파나 영입 제안받아",
                     published_at=datetime(2026, 7, 20, 1, 38),
                     fetched_at=datetime(2026, 7, 20, 1, 38))
    assert R.pick_representative([late_mid, early_top]) is early_top


def test_pick_representative_recency_still_breaks_a_credibility_tie():
    # 공신력이 같으면 늦은 기사가 이긴다 (기존 성질 유지)
    early = _row(content_hash="e", tier=1.0, body_ko="본문", body_level=1,
                 title_ko="아스날, 포파나 영입 검토",
                 published_at=datetime(2026, 7, 20, 1, 0),
                 fetched_at=datetime(2026, 7, 20, 1, 0))
    late = _row(content_hash="l", tier=1.0, body_ko="본문", body_level=1,
                title_ko="아스날, 포파나 영입 추진",
                published_at=datetime(2026, 7, 20, 9, 0),
                fetched_at=datetime(2026, 7, 20, 9, 0))
    assert R.pick_representative([early, late]) is late


def test_top_stories_dedup_by_event():
    now = datetime(2026, 7, 20, 12, 0)
    rows = [_row(content_hash=f"t{i}", tier=1.0, title_ko="아스날, 트로사르 방출",
                 published_at=datetime(2026, 7, 20, 10, i)) for i in range(3)]
    rows.append(_row(content_hash="r", tier=1.0, title_ko="아스날, 로저스 영입"))
    picks = R.pick_top_stories(rows, now, PLAYERS)
    keys = [R.protagonist(a["title_ko"], PLAYERS)
            for a in ([picks["lead"]] + picks["mains"])]
    assert keys.count("트로사르") == 1        # 같은 사건은 한 번만
    assert "로저스" in keys


# ── 최근 며칠치 기사는 따로 세운다 (안건 π) ─────────────────────────

def _p(h, day, tier=1.0, hour=1):
    """시험용 기사 — 날짜 · 공신력만 다르게 둔다."""
    return _row(content_hash=h, tier=tier,
                published_at=datetime(2026, 7, day, hour, 0),
                fetched_at=datetime(2026, 7, day, hour, 0))


def test_recent_days_counts_articles_not_blocks():
    # 날짜 범위는 카드가 아니라 기사에서 뽑는다 — 꺼낸 결과가 범위를 흔들면 안 된다
    arts = [_p("a", 21), _p("b", 20), _p("c", 20), _p("d", 18), _p("e", 15)]
    assert R.recent_days(arts) == {date(2026, 7, 21), date(2026, 7, 20), date(2026, 7, 18)}


def test_story_links_only_for_players_with_a_page():
    # 페이지가 만들어진 선수만 담는다 — 없는 선수에게 링크를 달면 죽은 링크가 된다
    entries = [{"ko_name": "알바레스", "slug": "alvarez", "count": 77},
               {"ko_name": None, "slug": "nameless", "count": 3}]
    assert R.story_links(entries) == {"알바레스": {"slug": "alvarez", "count": 77}}


# 성이 겹치는 남의 이름 (2026-08-28) — 사전은 대부분 성만 담아 부분 매치로 걸린다
NAMESAKE_PLAYERS = ["넬슨", "딕슨", "화이트", "두에", "래시포드", "로저스"]


def test_protagonist_skips_other_person_with_same_surname():
    # 레스터의 벤 넬슨 기사가 아스날 리스 넬슨 묶음으로 들어가던 자리
    assert R.protagonist(
        "맨체스터 유나이티드·웨스트햄, 레스터 시티 벤 넬슨 영입 주시",
        NAMESAKE_PLAYERS) is None


def test_protagonist_keeps_our_player_with_same_surname():
    # 같은 성이라도 우리 선수 기사는 그대로 묶인다
    assert R.protagonist("아스날, 리스 넬슨과 계약 해지 합의",
                         NAMESAKE_PLAYERS) == "넬슨"


def test_protagonist_skips_hyphenated_other_name():
    # 「깁스-화이트」 는 벤 화이트가 아니다 — 사전에 없는 긴 이름이라 위치 규칙이 못 막는다
    assert R.protagonist("아스날, 깁스-화이트 영입 경쟁… PSG 가세",
                         NAMESAKE_PLAYERS) is None


def test_protagonist_falls_through_to_real_subject():
    # 남의 이름을 지우면 그 기사의 진짜 주인공이 드러난다 (리 딕슨 -> 래시포드)
    assert R.protagonist(
        "아스날 레전드 리 딕슨, 마커스 래시포드-마일스 루이스-스켈리 스왑딜 제안",
        NAMESAKE_PLAYERS) == "래시포드"


def test_joao_jesus_does_not_join_the_gabriel_jesus_story():
    # 성만 겹치는 남의 선수가 우리 묶음으로 들어가던 자리 (2026-08-31 · 배포본 실측)
    assert R.protagonist("베네치아, 주앙 제주스와 구두 합의… 내일 계약 체결 예정",
                         ["제주스", "래시포드"]) is None
    # 「제주스」 만 쓴 우리 기사는 그대로 잡혀야 한다 — 미탐을 만들면 안 된다
    assert R.protagonist("나폴리, 제주스 영입 관심 표명",
                         ["제주스", "래시포드"]) == "제주스"


def test_mask_keeps_title_length():
    # 길이를 그대로 둬야 전환어 위치 비교가 안 흔들린다
    t = "아스날 레전드 리 딕슨, 스왑딜 제안"
    assert len(R.mask_other_people(t)) == len(t)


# ── 최하는 전부 가십 절로 · 카드가 없는 날짜는 가십에서 꺼낸다 ──────────

def test_is_lowest_reads_the_tier_not_the_cluster():
    # 가십 배정 기준이 「묶음 전원이 최하」 에서 「이 기사가 최하」 로 바뀐다
    assert R.is_lowest(_row(tier=4.0)) is True
    assert R.is_lowest(_row(tier=3.0)) is False
    assert R.is_lowest(_row(tier=None)) is False


def test_gossip_days_window_is_three():
    # 7일 창은 보이는 카드가 37장이라 너무 많았다 (2026-08-30 실측 · 3일이면 22장)
    assert R.GOSSIP_DAYS == 3


def test_pick_empty_day_gossip_lifts_when_the_day_has_no_card():
    # 그날 카드가 한 장도 안 서면 가십에서 꺼내 날짜 그룹에 세운다
    low = [_p("a", 21, tier=4.0), _p("b", 20, tier=4.0)]
    picks = R.pick_empty_day_gossip(low, carded=set(), window=R.recent_days(low),
                                    players=PLAYERS)
    assert [a["content_hash"] for a in picks] == ["a", "b"]


def test_pick_empty_day_gossip_skips_a_day_that_already_has_a_card():
    low = [_p("a", 21, tier=4.0), _p("b", 20, tier=4.0)]
    picks = R.pick_empty_day_gossip(low, carded={date(2026, 7, 21)},
                                    window=R.recent_days(low), players=PLAYERS)
    assert [a["content_hash"] for a in picks] == ["b"]


def test_pick_empty_day_gossip_skips_days_outside_the_window():
    low = [_p("old", 1, tier=4.0)]
    window = R.recent_days([_p("x", 21), _p("y", 20), _p("z", 19)])
    assert R.pick_empty_day_gossip(low, carded=set(), window=window,
                                   players=PLAYERS) == []


def test_pick_empty_day_gossip_leaves_hidden_stage_behind():
    # 기타 단계는 카드가 화면에서 숨으므로 꺼내면 아무 데서도 안 보인다 (_stage_visible 가드)
    low = [_p("other", 21, tier=4.0), _p("ok", 21, tier=4.0)]
    low[0]["transfer_stage"] = "other"
    picks = R.pick_empty_day_gossip(low, carded=set(), window=R.recent_days(low),
                                    players=PLAYERS)
    assert [a["content_hash"] for a in picks] == ["ok"]


def test_pick_empty_day_gossip_caps_per_player_and_day():
    # 한 선수가 그날 카드를 다 가져가지 않게 (PROMOTE_PER_PLAYER_DAY)
    low = [_p(f"t{i}", 21, tier=4.0, hour=i) for i in range(4)]
    for a in low:
        a["title_ko"] = "아스날, 트로사르 이적설"
    picks = R.pick_empty_day_gossip(low, carded=set(), window=R.recent_days(low),
                                    players=PLAYERS, cap=2)
    assert len(picks) == 2


def test_mask_ambiguous_needs_the_full_name_in_the_body():
    # 동명이인이 잦은 성은 본문이 풀네임으로 뒷받침할 때만 이름으로 인정한다
    t = "포르투갈 대표팀 지휘봉 잡은 제주스, 전술 변화 예고"
    assert "제주스" not in R.mask_ambiguous(t, "제주스 감독은 4-3-3 을 쓴다")
    assert "제주스" in R.mask_ambiguous(t, "가브리엘 제주스는 아스날을 떠난다")
    # 길이는 그대로 둔다 (mask_other_people 과 같은 계약)
    assert len(R.mask_ambiguous(t, "본문")) == len(t)


def test_mask_ambiguous_leaves_unlisted_names_alone():
    t = "나폴리, 래시포드 영입 관심"
    assert R.mask_ambiguous(t, "본문에 풀네임 없음") == t
