"""영입 단계 단일 출처 — enum ↔ 한국어 라벨 ↔ css 클래스.

enrich (프롬프트 · 검증) · render (라벨 · 클래스) · 서빙 템플릿이 이 모듈을
공유해 단계 정의가 한 곳에만 존재하도록 한다.
"""
from __future__ import annotations

# (enum, 한국어 라벨, css 클래스) — 라벨 · 클래스 조회의 단일 출처다.
# 여기 나열 순서는 화면에 나타나지 않는다 — 사이드바 필터가 그리는 것은
# render._STAGE_DISPLAY_GROUPS 이고, 그쪽이 agreed 와 medical 을 이적 합의
# 하나로 묶는다. 이 주석이 "사이드바 표시 순서" 라고 적혀 있어 실제로 오진을
# 부른 적이 있다 (docs/troubleshooting/2026-08-04-called-design-a-defect-without-reading-it.md).
# 2026-08-06 사다리 스펙 §4.1 로 화면 순서 (render._STAGE_DISPLAY_GROUPS) 와 같은
# 순서로 정합해 두었다 — 사다리의 진행 단계 정렬은 그쪽 목록이 기준이다.
# done · collapsed 는 2026-08-10 단계 재정의 스펙 §3.1 신설 — 메디컬은 이적 합의
# 묶음의 짝으로 이동했고, collapsed 는 진행 단계가 아니라 사다리 축에서 빠진다 (§8).
SIDEBAR_STAGES: list[tuple[str, str, str]] = [
    ("official", "오피셜", "s-off"),
    ("done", "이적 완료", "s-done"),
    ("agreed", "이적 합의", "s-agree"),
    ("medical", "메디컬", "s-med"),
    ("personal_terms", "개인 합의", "s-personal"),
    ("negotiating", "협상 중", "s-talk"),
    ("interest", "관심", "s-interest"),
    ("rumour", "루머", "s-rum"),
    ("collapsed", "무산", "s-collapsed"),
]

OTHER = "other"

DIRECTIONS = {"in", "out", "none"}


def normalize_direction(value: str | None) -> str:
    """LLM이 돌려준 방향이 허용 값이면 그대로, 아니면 none으로 강등."""
    return value if value in DIRECTIONS else "none"


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


def rule_stage(source_id: str | None) -> tuple[str | None, str | None]:
    """소스 조건 규칙 (stage, direction) — 방향 축 스펙 §4.1.
    공홈은 stage 만 고정 (방향은 LLM 몫) · 가십은 둘 다 고정 (LLM 완전 제외).
    official 은 이 규칙 경로에서만 생성된다 (LLM enum 에서 제외 · 반환 시 강등)."""
    if source_id == "arsenal_official":
        return "official", None
    if source_id == "bbc_gossip":
        return "rumour", "none"
    return None, None
