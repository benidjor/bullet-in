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


def rule_stage(source_id: str | None,
               accept_path: str | None = None) -> tuple[str | None, str | None]:
    """소스 조건 규칙 (stage, direction) — 방향 축 스펙 §4.1.
    공홈은 stage 만 고정 (방향은 LLM 몫) · 가십은 둘 다 고정 (LLM 완전 제외).
    official 은 이 규칙 경로에서만 생성된다 (LLM enum 에서 제외 · 반환 시 강등).

    accept_path 는 공홈 어댑터의 채택 경로다 (공홈 수집 개정 스펙 2026-08-12 §3.3).
    'title' 이면 고정하지 않는다 — 이 규칙이 실질적으로 뜻하는 것은 "공홈에서 왔다"
    가 아니라 "구단이 이적 뉴스 태그를 붙였다" 이고, 우리 제목 추측으로 주워 온
    기사에는 그 근거가 없다. 개정 전 적재분은 값이 없고 전건 태그 채택이었다.
    고정에서 빠진 뒤 모델 판정을 받는 경로는 promote_official 이 잇는다."""
    if source_id == "arsenal_official":
        return (None, None) if accept_path == "title" else ("official", None)
    if source_id == "bbc_gossip":
        return "rumour", "none"
    return None, None


def promote_official(stage: str | None, source_id: str | None,
                     accept_path: str | None) -> str | None:
    """모델이 완료로 읽은 제목 채택 공홈 기사를 official 로 올린다 (개정 2026-08-13).

    rule_stage 가 제목 채택분의 고정을 뺀 것은 태그가 없으면 구단이 이적 발표라고
    말한 근거도 없기 때문인데, 태그를 빠뜨린 진짜 발표가 실재해 (뇌르고르 에버튼
    이적) 그 기사가 화면에서 오피셜 표기를 두 자리 잃었다 — 목록 카드의 배지와
    선수 페이지 머리 배지다 (후자는 render.current_stage 의 첫 갈래가 official
    귀속 행을 요구하는데 그 행이 안 만들어져서다).

    태그 하나를 근거 둘로 대신한다 — 구단 홈페이지에서 왔고, 모델이 그 기사를 이적
    완료로 읽었을 때만 올린다. 제목에 이적 어휘만 우연히 든 기사는 완료 판정을 못
    받으므로 고정 제외가 막으려던 오탐은 그대로 걸러진다. 문턱을 done 하나로 둔 것은
    합의 · 협상 보도가 발표가 아니기 때문이다."""
    if (source_id == "arsenal_official" and accept_path == "title"
            and stage == "done"):
        return "official"
    return stage
