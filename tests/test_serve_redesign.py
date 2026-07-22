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
