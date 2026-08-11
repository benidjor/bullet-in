"""enrich 추출 쌍 → players · article_players 반영 (스펙 §4.1)."""
from __future__ import annotations
import logging, re
from bullet_in import transfer_stage as _stage
from bullet_in.enrich import _fold_latin
from bullet_in.storage.players import PlayerStore, ROLES

log = logging.getLogger(__name__)

_MAX_PAIRS = 30          # 모델이 폭주 출력을 내도 회차당 처리 상한
_MAX_FULL_NAME = 100     # players.full_name VARCHAR(100)
_MAX_KO = 50             # players.ko_candidate VARCHAR(50)
_HANGUL_RE = re.compile(r"[가-힣]")


def normalize_role(raw) -> str | None:
    """추출이 낸 역할 값 정규화 — 어휘 밖은 미기입 (None) 으로 떨어뜨린다.

    미기입은 서빙에서 주역으로 읽히므로 (스펙 §3.2), 모델이 값을 빠뜨리거나
    모르는 낱말을 내도 기사가 화면에서 사라지지 않는 쪽으로 넘어진다."""
    if not isinstance(raw, str):
        return None
    v = raw.strip().lower()
    return v if v in ROLES else None


def normalize_pairs(raw, source_id: str | None = None) -> list[dict]:
    """모델 출력 players 필드 검증 — 이름 없는 항목 · 비 dict · 중복은 버리고
    stage 는 enum 정규화.

    공홈 기사면 모델이 낸 stage 와 무관하게 official 로 덮어쓴다 (스펙 §8.1 의
    승격 규칙과 동일) — 추출 프롬프트가 stage 선택지에서 official 을 빼 놓아
    모델은 공홈에서도 agreed 등을 답하므로, "official 이면 유지" 방식으로는
    승격이 일어나지 않는다. 기사 단위 경로 (run.py 의 stage_ruled) 와 소급
    UPDATE 가 이미 공홈 기사의 stage 를 조건 없이 official 로 덮어쓰고 있어
    여기서도 같은 규칙을 적용해 소급분과 이후 적재분이 갈리지 않게 한다.
    판정은 rule_stage() 를 재사용한다 (arsenal_official 문자열의 단일 출처 유지).
    스키마 폭 (VARCHAR 100/50) 을 넘는 출력과 배열 폭주는 여기서 걸러 DB 예외를 막는다."""
    if not isinstance(raw, list):
        return []
    ruled_official = _stage.rule_stage(source_id)[0] == "official"
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
        if ruled_official:
            stage = "official"
        elif stage == "official":
            # 강등 목적지는 기사 단위 경로와 동일하게 done (2026-08-10 스펙 §4)
            stage = "done"
        ko = (item.get("ko") or "").strip() or None
        if ko and len(ko) > _MAX_KO:
            ko = None
        out.append({"full_name": fn, "ko": ko, "stage": stage,
                    "role": normalize_role(item.get("role"))})
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
        store.link_article(content_hash, pid, p["stage"], p.get("role"))
    return created
