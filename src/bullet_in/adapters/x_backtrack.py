from __future__ import annotations
import re
from datetime import datetime, timezone

_NAME_RE = re.compile(r"[A-Z][A-Za-zÀ-ÿ''.\-]*(?:\s+[A-Z][A-Za-zÀ-ÿ''.\-]*)+")

_STOP = frozenset(
    "the a an and or to of in on for with set are is has have been will would "
    "from that this over amid could into out at as by".split())

def extract_entities(text: str) -> list[str]:
    """대문자로 시작하는 연속 단어 (2어 이상) = 인명 · 구단명 후보. 악센트 보존."""
    return _NAME_RE.findall(text or "")

def _sig_tokens(text: str) -> set[str]:
    words = re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ''\-]+", text or "")
    return {w for w in words if len(w) > 3 and w.lower() not in _STOP}

def _parse_dt(s: str | None) -> datetime | None:
    try:
        dt = datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

def match_original_tweet(af_text, af_dt, journ_tweets, window_min, overlap_min):
    """4단계 ①~③ : 기자 트윗 중 afcstuff 원본을 특정. 없으면 None."""
    af_sig = _sig_tokens(af_text)
    best, best_score, best_dt = None, -1, None
    for jt in journ_tweets:
        jdt = _parse_dt(jt.get("created_at"))
        if jdt is None or af_dt is None or jdt > af_dt:
            continue
        if (af_dt - jdt).total_seconds() > window_min * 60:
            continue
        score = len(af_sig & _sig_tokens(jt.get("text", "")))
        if score > best_score or (score == best_score and best_dt is not None and jdt > best_dt):
            best, best_score, best_dt = jt, score, jdt
    return best if best_score >= overlap_min else None
