"""UI 개편 뷰모델 헬퍼 단위 테스트 (docs/superpowers/plans/2026-07-22-serve-ui-redesign.md)."""
from datetime import datetime

from bullet_in.serve import render as R


# ── Task 1: 표시 단계 매핑 · 독자 등급 라벨 ──────────────────────────────

def test_display_stage_groups_medical_into_negotiating():
    assert R.display_stage("official") == {"label": "오피셜", "tone": "red", "filled": True}
    assert R.display_stage("agreed") == {"label": "이적 합의", "tone": "red", "filled": False}
    assert R.display_stage("medical") == {"label": "협상 중", "tone": "green", "filled": False}
    assert R.display_stage("negotiating") == {"label": "협상 중", "tone": "green", "filled": False}
    assert R.display_stage("personal_terms") == {"label": "개인 합의", "tone": "yellow", "filled": False}
    assert R.display_stage("interest") == {"label": "관심", "tone": "gray", "filled": False}
    assert R.display_stage("rumour") == {"label": "루머", "tone": "gray", "filled": False}
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
