"""영입 단계 단일 출처 — enum ↔ 한국어 라벨 ↔ css 클래스 ↔ 사이드바 순서.

enrich (프롬프트 · 검증) · render (라벨 · 클래스) · 서빙 템플릿이 이 모듈을
공유해 단계 정의가 한 곳에만 존재하도록 한다.
"""
from __future__ import annotations

# (enum, 한국어 라벨, css 클래스) — 사이드바 표시 순서 (위 → 아래, 진행 단계 높은 순)
SIDEBAR_STAGES: list[tuple[str, str, str]] = [
    ("official", "오피셜", "s-off"),
    ("agreed", "이적 합의", "s-agree"),
    ("medical", "메디컬", "s-med"),
    ("personal_terms", "개인 합의", "s-personal"),
    ("negotiating", "협상 중", "s-talk"),
    ("interest", "관심", "s-interest"),
    ("rumour", "루머", "s-rum"),
]

OTHER = "other"

STAGE_ENUMS: list[str] = [e for e, _, _ in SIDEBAR_STAGES]
_LABEL = {e: label for e, label, _ in SIDEBAR_STAGES}
_CSS = {e: css for e, _, css in SIDEBAR_STAGES}
VALID_STAGES = set(STAGE_ENUMS) | {OTHER}


def normalize(value: str | None) -> str:
    """LLM이 돌려준 값이 허용 enum이면 그대로, 아니면 other로 강등."""
    return value if value in VALID_STAGES else OTHER


def label_for(stage: str | None) -> str:
    return _LABEL.get(stage or "", "")


def css_for(stage: str | None) -> str:
    return _CSS.get(stage or "", "")


def is_displayable(stage: str | None) -> bool:
    """배지 표시 대상인지 (other · None · 미지정은 배지 생략)."""
    return (stage or "") in _LABEL


def rule_stage(source_id: str | None) -> str | None:
    """소스 조건 규칙 단계 (spec §4.1) — 공홈만 official, 그 외는 None(LLM 분류 몫).
    official 은 이 규칙 경로에서만 생성된다 (LLM enum 에서 제외 · 반환 시 강등)."""
    return "official" if source_id == "arsenal_official" else None
