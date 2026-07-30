"""재작성 산출물의 충실도 판정 — 숫자 누락 · 원문 복제.

LLM 을 쓰지 않는 규칙 코드다. 판정 결과는 재생성 트리거로만 쓰고 본문을 버리지
않는다 (스펙 2026-07-29 §4.4).

숫자를 세기 전에 보정 세 가지를 반드시 적용한다. 하나라도 빠지면 수치가 통째로
틀린다 (docs/troubleshooting/2026-07-29-llm-metric-artifacts.md §3).
  ① URL 제거          — 기사 ID · 날짜 경로가 원문 숫자로 잡힌다
  ② 발행 날짜 · 시각 제거 — 원문 숫자의 7% 가 바이라인에서 온다
  ③ 단위 환산 동일시    — £50m 과 5,000만은 같은 값이다
"""
from __future__ import annotations
import re
from bullet_in.adapters.fmkorea import PUBLISH_DT_RE

RETENTION_THRESHOLD = 0.75    # 스펙 §6.5 — 재시도 횟수를 정하는 값 (본문 생사 아님)
NGRAM = 8                     # 글자 8-gram — 어절 n-gram 은 조사 변경에 과민 (§2.4)

_URL_RE = re.compile(r"https?://\S+")
# 뒤를 \b 로 끊으면 '8,000만' 에서 실패한다 — 한글 음절도 \w 라 경계가 생기지 않는다.
_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
_NUM_RE = re.compile(r"\d+")
_WS_RE = re.compile(r"\s+")


def _strip_noise(text: str) -> str:
    """숫자 집계 대상에서 URL 과 발행 날짜 · 시각을 뺀다 (보정 ① · ②)."""
    return PUBLISH_DT_RE.sub(" ", _URL_RE.sub(" ", text or ""))


def number_tokens(text: str) -> list[str]:
    """비교용 숫자 토큰 — 천단위 쉼표를 지운 뒤 연속 숫자를 뽑는다."""
    return _NUM_RE.findall(_THOUSANDS_RE.sub("", _strip_noise(text)))


def _variants(tok: str) -> set[str]:
    """단위 환산 후보 (보정 ③) — ×10 · ×100 · ×1000 · ÷100."""
    out = {tok}
    n = int(tok)
    for f in (10, 100, 1000):
        out.add(str(n * f))
    if n % 100 == 0:
        out.add(str(n // 100))
    return out


def missing_numbers(source: str, output: str) -> list[str]:
    """원문에 있고 산출물에 없는 숫자. 보정 3종을 적용한 뒤 비교한다."""
    out_tokens = set(number_tokens(output))
    missing: list[str] = []
    for tok in number_tokens(source):
        if tok in missing:
            continue
        if not (_variants(tok) & out_tokens):
            missing.append(tok)
    return missing


def _ngrams(text: str, n: int) -> set[str]:
    s = _WS_RE.sub(" ", text or "").strip()
    return {s[i:i + n] for i in range(len(s) - n + 1)} if len(s) >= n else set()


def char_ngram_retention(source: str, output: str, n: int = NGRAM) -> float:
    """산출물 글자 n-gram 중 원문에도 있는 것의 비율. 산출물이 n 자 미만이면 0.0."""
    out_grams = _ngrams(output, n)
    if not out_grams:
        return 0.0
    src_grams = _ngrams(source, n)
    return len(out_grams & src_grams) / len(out_grams)


def gate_verdict(source: str, output: str,
                 threshold: float = RETENTION_THRESHOLD) -> dict:
    """{"missing": [...], "retention": float, "ok": bool} — ok 는 두 게이트 동시 통과."""
    missing = missing_numbers(source, output)
    retention = char_ngram_retention(source, output)
    return {"missing": missing, "retention": retention,
            "ok": not missing and retention <= threshold}


def select_best(attempts: list[dict]) -> dict:
    """세 시도 중 최선 — 누락 없는 것 중 잔존율 최소.
    전부 누락이 있으면 누락 수가 가장 적은 것, 그중 잔존율이 낮은 것.
    본문을 버리지 않으므로 항상 하나를 돌려준다."""
    return min(attempts, key=lambda a: (len(a["missing"]), a["retention"]))
