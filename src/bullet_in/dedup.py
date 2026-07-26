from typing import Literal

Decision = Literal["new", "duplicate", "changed", "blocked", "upgrade"]

def classify(url: str, new_hash: str,
             seen: dict[str, tuple[str, int, str, bool]],
             new_source: str, new_has_body: bool) -> tuple[Decision, int]:
    """seen: canonical url -> (last_hash, last_revision, source_id, has_body).

    2축 규칙 (spec 2026-07-26 §4) — 소스 동일 여부 × 완전체 여부:
    같은 소스는 현행대로 revision 갱신, 다른 소스는 완전체 보호 · 스텁 업그레이드.
    """
    if url not in seen:
        return "new", 1
    last_hash, last_rev, last_source, last_has_body = seen[url]
    if last_source == new_source:
        if last_hash == new_hash:
            return "duplicate", last_rev
        return "changed", last_rev + 1
    if last_has_body:
        return "blocked", last_rev
    if new_has_body:
        return "upgrade", last_rev + 1
    return "blocked", last_rev
