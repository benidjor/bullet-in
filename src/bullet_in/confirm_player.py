"""후보 선수 확정 CLI — 승격 → 게이트 재검사 → 재번역 → 재렌더 (스펙 §4.3).

실행 전 `set -a; source .env; set +a` 필수 (이 프로젝트는 dotenv 미사용).
    uv run python -m bullet_in.confirm_player --name "Nico Williams" --ko "니코 윌리엄스" \
        --category external --transfer-status in_link
    uv run python -m bullet_in.confirm_player --name "Nico Williams" --ko "니코 윌리엄스" --dry-run
"""
from __future__ import annotations
import argparse, logging, os
from bullet_in.enrich import (BODY_AS_TITLE_SOURCES, NAME_MISSING_PREFIX,
                              detect_title_hallucination, detect_title_mistranslation)

log = logging.getLogger(__name__)


def surname_warning(surname: str) -> str | None:
    """두 단어 성 경고 (스펙 §3.3) — 풀네임 근거 가드 축이 조용히 꺼진다."""
    if " " in surname.strip():
        return (f"surname '{surname}' 이 두 단어 — _has_name_context 가드가 근거를 못 찾아 "
                "이 축의 보호 없이 등재된다 (가드의 두 단어 성 지원은 범위 밖)")
    return None


def recheck_titles(rows: list[dict], name_map: dict[str, str]) -> list[str]:
    """저장된 번역 제목을 확장된 사전으로 재검사 — 의심 행 content_hash 목록 (스펙 §4.3).
    축 구성은 finalize_translation 1차 검출과 같다 (환각 + 역방향 · 라운드업 제외 · 트윗 예외).
    임대 무근거 축은 사전과 무관해 이미 1차에서 걸렀으므로 여기서 다시 보지 않는다."""
    suspects = []
    for row in rows:
        if not row.get("title_ko"):
            continue
        src_text = " ".join(filter(None, [row.get("title_original"),
                                          row.get("body_source"),
                                          row.get("body_excerpt")]))
        reasons = detect_title_hallucination(row["title_ko"], src_text, name_map)
        if row.get("source_id") != "bbc_gossip":
            rev = detect_title_mistranslation(row["title_ko"], row.get("title_original"),
                                              name_map, src_text)
            if row.get("source_id") in BODY_AS_TITLE_SOURCES:
                rev = [r for r in rev if not r.startswith(NAME_MISSING_PREFIX)]
            reasons += rev
        if reasons:
            log.warning("재검사 의심 content_hash=%s 사유=%s", row["content_hash"], reasons)
            suspects.append(row["content_hash"])
    return suspects
