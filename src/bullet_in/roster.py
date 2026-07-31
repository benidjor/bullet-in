"""enrich 추출 쌍 → players · article_players 반영 (스펙 §4.1)."""
from __future__ import annotations
import logging, re
from bullet_in import transfer_stage as _stage
from bullet_in.enrich import _fold_latin
from bullet_in.storage.players import PlayerStore

log = logging.getLogger(__name__)

_MAX_PAIRS = 30          # 모델이 폭주 출력을 내도 회차당 처리 상한
_MAX_FULL_NAME = 100     # players.full_name VARCHAR(100)
_MAX_KO = 50             # players.ko_candidate VARCHAR(50)
_HANGUL_RE = re.compile(r"[가-힣]")


def normalize_pairs(raw) -> list[dict]:
    """모델 출력 players 필드 검증 — 이름 없는 항목 · 비 dict · 중복은 버리고
    stage 는 enum 정규화 (official 은 규칙 경로 전용이라 agreed 강등 · 분류 패스와 동일).
    스키마 폭 (VARCHAR 100/50) 을 넘는 출력과 배열 폭주는 여기서 걸러 DB 예외를 막는다."""
    if not isinstance(raw, list):
        return []
    out, seen = [], set()
    for item in raw[:_MAX_PAIRS]:
        if not isinstance(item, dict):
            continue
        fn = (item.get("full_name") or "").strip()
        if not fn or len(fn) > _MAX_FULL_NAME or _HANGUL_RE.search(fn):
            continue
        folded = _fold_latin(fn)
        if folded in seen:
            continue
        seen.add(folded)
        stage = _stage.normalize(item.get("stage"))
        if stage == "official":
            stage = "agreed"
        ko = (item.get("ko") or "").strip() or None
        if ko and len(ko) > _MAX_KO:
            ko = None
        out.append({"full_name": fn, "ko": ko, "stage": stage})
    return out


def record_article_players(store: PlayerStore, content_hash: str,
                           pairs: list[dict]) -> list[dict]:
    """쌍을 저장하고 명단 밖 선수는 후보 등재 — 신규 후보 목록을 반환한다 (알림 입력).
    매칭은 접힌 full_name 우선, 다음 접힌 성 (동성 복수면 제외) — 성 폴백은 한 단어
    출력에만 적용한다. 풀네임 (두 단어 이상) 이 by_full 미스면 성 폴백 없이 후보로
    등재한다 — 동성 타인 (예: Harvey White) 이 기존 선수 (Ben White) 에게 조용히
    링크되는 것을 막는다."""
    if not pairs:
        return []
    by_full, by_surname = store.match_maps()
    created: list[dict] = []
    for p in pairs:
        folded = _fold_latin(p["full_name"])
        tokens = p["full_name"].split()
        pid = by_full.get(folded)
        if pid is None and len(tokens) == 1:
            pid = by_surname.get(_fold_latin(tokens[-1]))
        if pid is None:
            surname = tokens[-1]
            if len(surname) > 50:
                log.warning("성 길이 초과 (50자) — 후보 등재 · 링크 skip: %s",
                           p["full_name"])
                continue
            first_name = " ".join(tokens[:-1]) or None
            if first_name and len(first_name) > 50:
                first_name = None
            pid = store.insert_candidate(
                full_name=p["full_name"],
                first_name=first_name,
                surname=surname,
                ko_candidate=p["ko"],
                first_seen=content_hash)
            by_full[folded] = pid
            created.append({**p, "player_id": pid})
            log.info("후보 등재: %s (%s) stage=%s 근거=%s",
                     p["ko"] or "?", p["full_name"], p["stage"], content_hash[:8])
        store.link_article(content_hash, pid, p["stage"])
    return created
