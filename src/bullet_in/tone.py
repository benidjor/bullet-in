from __future__ import annotations
import re

# 존댓말(합니다체·해요체) 종결어미 — 문장 끝에서만 검출한다.
# '니다'가 합니다/입니다/됩니다/갑니다/습니다 계열 전부를 커버한다.
# 단 '아니다'는 평어체라 제외 ('아닙니다'는 '닙니다'로 끝나 계속 걸린다).
_POLITE_END = re.compile(
    r"((?<!아)니다|해요|예요|에요|세요|네요|군요|는데요|어요|아요|지요|죠)\s*$")

# 인용부호 안은 화자 발화라 존댓말이 정상 — 검출 전에 제거한다.
_QUOTED = re.compile(r'"[^"]*"|“[^”]*”|「[^」]*」|『[^』]*』|\'[^\']*\'')

_SENT_SPLIT = re.compile(r"[.!?…\n]+")

def has_polite_ending(text: str | None) -> bool:
    """요약 텍스트의 문장 끝에 존댓말 종결어미가 남았는지 판정한다."""
    if not text:
        return False
    cleaned = _QUOTED.sub("", text)
    for sent in _SENT_SPLIT.split(cleaned):
        if _POLITE_END.search(sent.strip()):
            return True
    return False


def select_tone_backfill(rows: list[dict], limit: int) -> list[dict]:
    """summary_ko · summary3_ko 에 존댓말이 남은 행을 limit 건까지 선별한다."""
    picked: list[dict] = []
    for r in rows:
        if has_polite_ending(r.get("summary_ko")) or has_polite_ending(r.get("summary3_ko")):
            picked.append(r)
            if len(picked) >= limit:
                break
    return picked
