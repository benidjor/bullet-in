from __future__ import annotations
import re

_NAME_RE = re.compile(r"[A-Z][A-Za-zÀ-ÿ''.\-]*(?:\s+[A-Z][A-Za-zÀ-ÿ''.\-]*)+")

def extract_entities(text: str) -> list[str]:
    """대문자로 시작하는 연속 단어 (2어 이상) = 인명 · 구단명 후보. 악센트 보존."""
    return _NAME_RE.findall(text or "")
