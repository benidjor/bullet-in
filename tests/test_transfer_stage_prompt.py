"""STAGE_PROMPT 문구 회귀 가드 — 두 축의 독립성이 프롬프트에서 사라지지 않게 고정한다.
구단명은 {club} 파라미터다 (단계 재정의 스펙 2026-08-10 §9) — 가드도 템플릿 문면 기준."""
from bullet_in.enrich import STAGE_PROMPT


def test_prompt_fixes_direction_baseline_to_club():
    assert "방향은 {club} 기준이다" in STAGE_PROMPT
    assert "당사자 (사는 쪽 또는 파는 쪽) 가 아니면 반드시 none 으로 답한다" in STAGE_PROMPT


def test_prompt_keeps_other_club_stage_rule():
    # #200 · #201 에서 의도적으로 넣은 문장 — 방향 문구가 이것을 밀어내면 안 된다
    assert "이적 주체가 {club} 이 아니어도" in STAGE_PROMPT


def test_prompt_states_the_two_axes_are_independent():
    assert "방향만 none 이고 단계는 그대로" in STAGE_PROMPT
