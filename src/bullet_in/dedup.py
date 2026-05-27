from typing import Literal

Decision = Literal["new", "duplicate", "changed"]

def classify(url: str, new_hash: str,
             seen: dict[str, tuple[str, int]]) -> tuple[Decision, int]:
    """seen: canonical url -> (last_hash, last_revision)."""
    if url not in seen:
        return "new", 1
    last_hash, last_rev = seen[url]
    if last_hash == new_hash:
        return "duplicate", last_rev
    return "changed", last_rev + 1
