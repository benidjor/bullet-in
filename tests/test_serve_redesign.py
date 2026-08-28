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


def test_pick_representative_lowest_excluded_when_higher_exists():
    afc = _row(content_hash="afc", tier=4.0, title_ko="아스날, 로저스 영입 추진", body_ko="")
    sky = _row(content_hash="sky", tier=1.0, title_ko="첼시, 로저스 영입 합의", body_ko="")
    assert R.pick_representative([afc, sky]) is sky        # 최하 제외 가드 (로저스 사고)


def test_pick_representative_official_always():
    off = _row(content_hash="off", tier=0.0, title_ko="첼시, 로저스 영입 공식 발표", body_ko="")
    ars = _row(content_hash="ars", tier=1.5, title_ko="아스날, 로저스 관심", body_ko="")
    assert R.pick_representative([off, ars]) is off


def test_ending_card_detects_other_club_transfer():
    cluster = {"key": "로저스", "articles": [
        _row(content_hash="e", tier=1.0, transfer_stage="agreed",
             title_ko="첼시, 로저스 영입 합의"),
        _row(content_hash="a", tier=2.0, transfer_stage="rumour",
             title_ko="아스날, 로저스 관심"),
    ]}
    end = R.ending_card(cluster, CLUBS)
    assert end["article"]["content_hash"] == "e"
    assert end["club"] == "첼시"


def test_ending_card_ignores_arsenal_subject():
    cluster = {"key": "트로사르", "articles": [
        _row(content_hash="a", transfer_stage="agreed", title_ko="아스날, 트로사르 방출 합의"),
    ]}
    assert R.ending_card(cluster, CLUBS) is None


def test_related_reports_branch_sorted_by_sort_ts_desc():
    # 발행 시각 있음 · day 정밀도 보간 · 시각 부재 폴백이 섞여도 갈래는 최신 먼저 (spec2 §6.3)
    rep = _row(content_hash="rep", title_ko="아스날, 로저스 영입 추진")
    newest = _row(content_hash="n", title_ko="아스날, 로저스 관련 최신",
                  published_at=datetime(2026, 7, 21, 10, 0), published_precision="time",
                  fetched_at=datetime(2026, 7, 21, 12, 0))
    midday = _row(content_hash="m", title_ko="아스날, 로저스 관련 중간",
                  published_at=datetime(2026, 7, 20, 0, 0), published_precision="day",
                  fetched_at=datetime(2026, 7, 20, 15, 0))
    publess = _row(content_hash="o", title_ko="아스날, 로저스 관련 시각부재",
                   published_at=None, fetched_at=datetime(2026, 7, 19, 9, 0))
    cluster = {"key": "로저스", "articles": [publess, midday, newest, rep]}
    rel = R.related_reports(cluster, rep, None, CLUBS)
    assert [a["content_hash"] for a in rel["arsenal"]] == ["n", "m", "o"]


def test_is_other_club_report_arsenal_inbound_excluded():
    # 현 소속이 제목 앞머리에 나와도 '아스날 이적 의사' 면 아스날로 오는 사건 (오탐 차단)
    inbound = {"title_ko": "뉴캐슬 주장 기마랑이스, 아스날 이적 의사 구단에 전달"}
    assert R._is_other_club_report(inbound, "기마랑이스", CLUBS) is None
    # 실제 다른 구단행은 그대로 구단명 반환
    other = {"title_ko": "첼시, 로저스 영입 합의"}
    assert R._is_other_club_report(other, "로저스", CLUBS) == "첼시"


def test_is_gossip_cluster_only_when_all_lowest():
    assert R.is_gossip_cluster({"articles": [_row(tier=4.0), _row(tier=4.0)]}) is True
    assert R.is_gossip_cluster({"articles": [_row(tier=4.0), _row(tier=1.5)]}) is False


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


def test_promote_recent_lifts_folded_article_in_window():
    # 최근 날짜에 든 기사는 접힘에서 나와 자기 카드를 갖는다
    rep, new = _p("rep", 15), _p("new", 21)
    block = {"rep": rep, "count": 2, "_articles": [rep, new], "rel_count": 1,
             "branches": [{"label": "", "articles": [new]}]}
    out = R.promote_recent([block], R.recent_days([rep, new]))
    assert [b["rep"]["content_hash"] for b in out] == ["new"]
    assert out[0]["rel_count"] == 0 and out[0]["branches"] == []
    assert block["rel_count"] == 0 and block["branches"] == []
    assert block["_articles"] == [rep]          # 날짜 머리글 건수가 두 번 세지 않게


def test_promote_recent_keeps_articles_outside_window_folded():
    rep, old = _p("rep", 15), _p("old", 16)
    block = {"rep": rep, "count": 2, "_articles": [rep, old], "rel_count": 1,
             "branches": [{"label": "", "articles": [old]}]}
    window = R.recent_days([rep, old, _p("x", 21), _p("y", 20), _p("z", 19)])
    assert R.promote_recent([block], window) == []
    assert block["rel_count"] == 1


def test_promote_recent_caps_per_player_and_day():
    # 한 선수가 그날 카드를 다 가져가지 않게 — 꺼내는 것은 공신력 높은 쪽부터
    rep = _p("rep", 15)
    low, mid, high = _p("low", 21, tier=4.0), _p("mid", 21, tier=2.0), _p("high", 21, tier=1.0)
    block = {"rep": rep, "count": 4, "_articles": [rep, low, mid, high], "rel_count": 3,
             "branches": [{"label": "", "articles": [low, mid, high]}]}
    out = R.promote_recent([block], R.recent_days([rep, low]), cap=1)
    assert [b["rep"]["content_hash"] for b in out] == ["high"]
    assert block["rel_count"] == 2               # 못 꺼낸 둘은 접힌 채로 남는다


def test_promote_recent_default_is_three_per_player_a_day():
    # 기본값 = 한 선수 소식 하루 세 장 (2026-08-27 사용자 확정)
    rep = _p("rep", 15)
    worst, low = _p("worst", 21, tier=4.0), _p("low", 21, tier=3.0)
    mid, high = _p("mid", 21, tier=2.0), _p("high", 21, tier=1.0)
    block = {"rep": rep, "count": 5, "_articles": [rep, worst, low, mid, high],
             "rel_count": 4,
             "branches": [{"label": "", "articles": [worst, low, mid, high]}]}
    out = R.promote_recent([block], R.recent_days([rep, low]))
    assert R.PROMOTE_PER_PLAYER_DAY == 3
    assert [b["rep"]["content_hash"] for b in out] == ["high", "mid", "low"]
    assert block["rel_count"] == 1              # 공신력 최하 한 장만 접힌 채로 남는다


def test_promote_recent_prefers_sky_within_mid_tier():
    # 공신력 중끼리 겹치면 Sky Sports 를 먼저 세운다 (2026-08-27 사용자 결정)
    rep = _p("rep", 15)
    espn = _p("espn", 21, tier=2.0, hour=9) | {"_outlet": "ESPN"}
    sky = _p("sky", 21, tier=2.0, hour=2) | {"_outlet": "Sky Sports"}
    block = {"rep": rep, "count": 3, "_articles": [rep, espn, sky], "rel_count": 2,
             "branches": [{"label": "", "articles": [espn, sky]}]}
    out = R.promote_recent([block], R.recent_days([rep, espn]), cap=1)
    assert [b["rep"]["content_hash"] for b in out] == ["sky"]   # 더 옛 기사인데도 Sky


def test_promote_recent_sky_preference_does_not_beat_credibility():
    # 등급이 먼저다 — 공신력 상 기사가 있으면 Sky (중) 보다 그쪽이 선다
    rep = _p("rep", 15)
    sky = _p("sky", 21, tier=2.0, hour=9) | {"_outlet": "Sky Sports"}
    athletic = _p("ath", 21, tier=1.5, hour=2) | {"_outlet": "The Athletic"}
    block = {"rep": rep, "count": 3, "_articles": [rep, sky, athletic], "rel_count": 2,
             "branches": [{"label": "", "articles": [sky, athletic]}]}
    out = R.promote_recent([block], R.recent_days([rep, sky]), cap=1)
    assert [b["rep"]["content_hash"] for b in out] == ["ath"]


def test_promote_recent_leaves_hidden_stage_folded():
    # 「기타」 단계는 첫 화면에서 카드가 감춰진다 — 꺼내면 관련 보도에서도 사라져
    # 아무 데서도 안 보이게 되므로 접힌 채로 둔다
    rep = _p("rep", 15)
    other = _p("other", 21) | {"transfer_stage": "other"}
    blank = _p("blank", 21) | {"transfer_stage": None}
    ok = _p("ok", 21)
    block = {"rep": rep, "count": 4, "_articles": [rep, other, blank, ok], "rel_count": 3,
             "branches": [{"label": "", "articles": [other, blank, ok]}]}
    out = R.promote_recent([block], R.recent_days([rep, ok]))
    assert [b["rep"]["content_hash"] for b in out] == ["ok"]
    assert block["rel_count"] == 2               # 기타 · 무단계 둘은 접힌 채로 남는다


def test_promote_recent_leaves_lowest_tier_folded():
    # 원래 최신 소식에는 최하 카드가 설 수 없었다 (대표 선정의 not_lowest · 전부 최하인
    # 묶음은 가십 절로) — 꺼내기가 그 불변 조건을 깨지 않게 한다
    rep = _p("rep", 15)
    lowest, ok = _p("lowest", 21, tier=4.0), _p("ok", 21, tier=3.0)
    block = {"rep": rep, "count": 3, "_articles": [rep, lowest, ok], "rel_count": 2,
             "branches": [{"label": "", "articles": [lowest, ok]}]}
    out = R.promote_recent([block], R.recent_days([rep, ok]))
    assert [b["rep"]["content_hash"] for b in out] == ["ok"]
    assert block["rel_count"] == 1              # 최하는 접힌 채로 남는다


def test_story_links_only_for_players_with_a_page():
    # 페이지가 만들어진 선수만 담는다 — 없는 선수에게 링크를 달면 죽은 링크가 된다
    entries = [{"ko_name": "알바레스", "slug": "alvarez", "count": 77},
               {"ko_name": None, "slug": "nameless", "count": 3}]
    assert R.story_links(entries) == {"알바레스": {"slug": "alvarez", "count": 77}}


def test_promote_recent_carries_story_key():
    # 꺼낸 카드가 어느 선수 이야기에서 나왔는지 들고 나와야 선수 페이지로 이을 수 있다
    rep, new = _p("rep", 15), _p("new", 21)
    block = {"rep": rep, "key": "알바레스", "count": 2, "_articles": [rep, new],
             "rel_count": 1, "branches": [{"label": "", "articles": [new]}]}
    out = R.promote_recent([block], R.recent_days([rep, new]))
    assert out[0]["key"] == "알바레스"


def test_promote_recent_counts_each_day_separately():
    # 장수는 날짜마다 따로 센다 — 같은 선수라도 날이 다르면 각각 한 장씩 선다
    rep, d20, d21 = _p("rep", 15), _p("d20", 20), _p("d21", 21)
    block = {"rep": rep, "count": 3, "_articles": [rep, d20, d21], "rel_count": 2,
             "branches": [{"label": "", "articles": [d21, d20]}]}
    out = R.promote_recent([block], R.recent_days([rep, d20, d21]), cap=1)
    assert sorted(b["rep"]["content_hash"] for b in out) == ["d20", "d21"]


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


def test_mask_keeps_title_length():
    # 길이를 그대로 둬야 전환어 위치 비교가 안 흔들린다
    t = "아스날 레전드 리 딕슨, 스왑딜 제안"
    assert len(R.mask_other_people(t)) == len(t)


def test_branch_label_keeps_club_when_branch_is_mostly_that_club():
    # 갈래의 다수가 결말 구단이면 이름표에 구단명이 그대로 남는다 (안건 τ-ⓐ)
    oth = [_row(content_hash="o1"), _row(content_hash="o2")]
    related = {"arsenal": [_row(content_hash="a1")], "other": oth,
               "other_clubs": Counter({"첼시": 2})}
    labels = [b["label"] for b in R.branch_views(related, {"club": "첼시"})]
    assert labels == ["첼시행 관련", "아스날 쪽 보도"]


def test_branch_label_drops_club_when_branch_is_mostly_other_clubs():
    # 결말 한 건의 구단명이 갈래 전체를 대표하지 못하면 구단명을 뺀다 (안건 τ-ⓐ)
    oth = [_row(content_hash="o%d" % i) for i in range(4)]
    related = {"arsenal": [_row(content_hash="a1")], "other": oth,
               "other_clubs": Counter({"토트넘": 3, "첼시": 1})}
    labels = [b["label"] for b in R.branch_views(related, {"club": "첼시"})]
    assert labels == ["영입 경쟁", "아스날 쪽 보도"]


def test_related_reports_counts_other_clubs():
    rep = _row(content_hash="rep", title_ko="아스날, 로저스 영입 추진")
    a = _row(content_hash="a", title_ko="첼시, 로저스 영입 임박")
    b = _row(content_hash="b", title_ko="첼시, 로저스 메디컬 진행")
    cluster = {"key": "로저스", "articles": [rep, a, b]}
    rel = R.related_reports(cluster, rep, None, CLUBS)
    assert rel["other_clubs"] == Counter({"첼시": 2})
