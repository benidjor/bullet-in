from typing import Literal

Decision = Literal["new", "duplicate", "changed", "blocked", "upgrade"]

def classify(url: str, new_hash: str,
             seen: dict[str, tuple[str, int, str, int]],
             new_source: str, new_body_level: int) -> tuple[Decision, int]:
    """seen: canonical url -> (last_hash, last_revision, source_id, body_level).

    2축 규칙 (spec 2026-07-26 §4) — 소스 동일 여부 × 본문 출처 등급:
    같은 소스는 현행대로 revision 갱신, 다른 소스는 3단 사다리 (0 없음 · 1 게시글 · 2 언론사)
    에서 등급이 오를 때만 교체한다. 같은 등급이면 먼저 들어온 행이 남고,
    2 → 1 은 차단이다 — 커뮤니티가 옮긴 본문이 언론사 원문을 밀어내지 못하게 한다.
    """
    if url not in seen:
        return "new", 1
    last_hash, last_rev, last_source, last_level = seen[url]
    if last_source == new_source:
        if last_hash == new_hash:
            return "duplicate", last_rev
        return "changed", last_rev + 1
    if new_body_level > last_level:
        return "upgrade", last_rev + 1
    return "blocked", last_rev
