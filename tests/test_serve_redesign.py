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
