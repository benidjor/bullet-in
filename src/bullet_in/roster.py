"""enrich 추출 쌍 → players · article_players 반영 (스펙 §4.1)."""
from __future__ import annotations
import logging
from bullet_in import transfer_stage as _stage
from bullet_in.enrich import _fold_latin
from bullet_in.storage.players import PlayerStore

log = logging.getLogger(__name__)


def normalize_pairs(raw) -> list[dict]:
    """모델 출력 players 필드 검증 — 이름 없는 항목 · 비 dict · 중복은 버리고
    stage 는 enum 정규화 (official 은 규칙 경로 전용이라 agreed 강등 · 분류 패스와 동일)."""
    if not isinstance(raw, list):
        return []
    out, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        fn = (item.get("full_name") or "").strip()
        if not fn or _fold_latin(fn) in seen:
            continue
        seen.add(_fold_latin(fn))
        stage = _stage.normalize(item.get("stage"))
        if stage == "official":
            stage = "agreed"
        out.append({"full_name": fn,
                    "ko": (item.get("ko") or "").strip() or None,
                    "stage": stage})
    return out


def record_article_players(store: PlayerStore, content_hash: str,
                           pairs: list[dict]) -> list[dict]:
    """쌍을 저장하고 명단 밖 선수는 후보 등재 — 신규 후보 목록을 반환한다 (알림 입력).
    매칭은 접힌 full_name 우선, 다음 접힌 성 (동성 복수면 제외) — 성만 온 출력이
    기존 선수의 중복 행을 만드는 것을 막는다."""
    if not pairs:
        return []
    by_full, by_surname = store.match_maps()
    created: list[dict] = []
    for p in pairs:
        folded = _fold_latin(p["full_name"])
        tokens = p["full_name"].split()
        pid = by_full.get(folded) or by_surname.get(_fold_latin(tokens[-1]))
        if pid is None:
            pid = store.insert_candidate(
                full_name=p["full_name"],
                first_name=" ".join(tokens[:-1]) or None,
                surname=tokens[-1],
                ko_candidate=p["ko"],
                first_seen=content_hash)
            by_full[folded] = pid
            created.append({**p, "player_id": pid})
            log.info("후보 등재: %s (%s) stage=%s 근거=%s",
                     p["ko"] or "?", p["full_name"], p["stage"], content_hash[:8])
        store.link_article(content_hash, pid, p["stage"])
    return created
