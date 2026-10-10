"""수집 범위 판정 — 이적 + 선수 · 팀 소식 + 경기 평점 (설계 2026-10-07 §2).

언론사 세 소스와 공식 소스가 같은 판정을 쓴다. 갈래는 위에서 아래 순서로 보고
처음 맞은 하나를 돌려준다 — 기록 (`passed_by`) 으로 넓힌 갈래가 무엇을 가져왔는지
재기 위해서다. 이적 키워드 갈래는 종전 필터와 같은 부분 일치를 그대로 둔다
(바꾸면 지금 받는 기사가 줄어 범위 확대와 섞인다 · 설계 §2.1)."""
from __future__ import annotations

import re
from collections.abc import Iterable

EXTRA_WORDS = ("interest", "ratings")
TEAM_WORDS = ("Emirates", "stadium", "Pro Ref", "referee", "academy", "injury", "fitness")
DROPPED_MAX = 40
DROPPED_CHARS = 120


def _words(words: Iterable[str], flags: int = 0) -> re.Pattern | None:
    ws = sorted(set(words), key=len, reverse=True)       # 긴 이름 먼저 (Mikel Arteta > Arteta)
    if not ws:
        return None
    return re.compile(r"\b(?:" + "|".join(map(re.escape, ws)) + r")\b", flags)


_EXTRA_RE = _words(EXTRA_WORDS, re.IGNORECASE)
_TEAM_RE = _words(TEAM_WORDS, re.IGNORECASE)


def scope_names(roster: Iterable[tuple[str, str]], extras: Iterable[str] = (),
                full_only: Iterable[str] = ()) -> set[str]:
    """명단 (full_name, surname) → 판정에 쓸 이름 집합 (설계 §2.2).

    full_only 에 든 성은 흔한 낱말과 겹쳐 (「White Hart Lane」) 성으로는 안 받고
    전체 이름만 남긴다."""
    skip = set(full_only)
    out = set(extras)
    for full, sur in roster:
        if full:
            out.add(full)
        if sur and sur not in skip:
            out.add(sur)
    return out


class ScopeRule:
    """제목이 받을 범위인가 — 이적 키워드 · 추가 낱말 · 명단 이름 · 팀 낱말."""

    def __init__(self, keywords: Iterable[str] = (), names: Iterable[str] = ()):
        self.keywords = tuple(k.lower() for k in keywords)
        self._name_re = _words(names)                     # 이름만 대소문자를 가린다

    def match(self, title: str) -> str | None:
        if any(k in title.lower() for k in self.keywords):
            return "keyword"
        if _EXTRA_RE.search(title):
            return "extra"
        if self._name_re is not None and self._name_re.search(title):
            return "name"
        if _TEAM_RE.search(title):
            return "team"
        return None


def record(funnel: dict, title: str, reason: str | None) -> None:
    """수집 단계 기록에 받은 갈래 수와 버린 제목을 남긴다 (설계 §5.1)."""
    if reason:
        by = funnel.setdefault("passed_by", {})
        by[reason] = by.get(reason, 0) + 1
        return
    dropped = funnel.setdefault("dropped", [])
    if len(dropped) < DROPPED_MAX:
        dropped.append(title[:DROPPED_CHARS])
