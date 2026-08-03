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


def extra_numbers(source: str, output: str) -> list[str]:
    """산출물에 있고 원문에 없는 숫자 — 재작성이 만들어낸 수치.

    missing_numbers 의 역방향이고 보정 3종을 똑같이 적용한다.
    단위 환산 후보가 원문에 있으면 주입으로 보지 않는다 (£50m ↔ 5,000만)."""
    src_tokens = set(number_tokens(source))
    extra: list[str] = []
    for tok in number_tokens(output):
        if tok in extra:
            continue
        if not (_variants(tok) & src_tokens):
            extra.append(tok)
    return extra


def _ngrams(text: str, n: int) -> set[str]:
    s = _WS_RE.sub(" ", text or "").strip()
    return {s[i:i + n] for i in range(len(s) - n + 1)} if len(s) >= n else set()


# 짧은 따옴표 쌍 (강조 표기 · 약어) 은 발화로 보지 않는다 — 4자 이상만 인용으로 센다.
_QUOTE_RE = re.compile("[\u0022\u201c]([^\u0022\u201c\u201d]{4,}?)[\u0022\u201d]")


def quote_spans(text: str) -> list[str]:
    """따옴표 안 발화 목록 — 공백을 하나로 줄인 비교용 정규형."""
    return [_WS_RE.sub(" ", m.group(1)).strip()
            for m in _QUOTE_RE.finditer(text or "")]


def missing_quotes(source: str, output: str) -> list[str]:
    """원문 인용문 중 산출물에 원형으로 남지 않은 것.

    인용문은 재작성 대상에서 제외이므로 (E안 요소 ②) 글자 그대로 남아야 한다.
    공백 차이는 훼손으로 보지 않는다."""
    out = _WS_RE.sub(" ", output or "")
    return [q for q in quote_spans(source) if q not in out]


def char_ngram_retention(source: str, output: str, n: int = NGRAM) -> float:
    """산출물 글자 n-gram 중 원문에도 있는 것의 비율. 산출물이 n 자 미만이면 0.0."""
    out_grams = _ngrams(output, n)
    if not out_grams:
        return 0.0
    src_grams = _ngrams(source, n)
    return len(out_grams & src_grams) / len(out_grams)


def gate_verdict(source: str, output: str,
                 threshold: float = RETENTION_THRESHOLD,
                 grounding: str | None = None) -> dict:
    """사전이 필요 없는 축의 판정 — 숫자 누락 · 신규 수치 · 인용 훼손 · 원문 복제.
    사전이 필요한 축 (구단 · 인명) 은 호출측이 따로 대조해 합친다.

    grounding 은 주입 판정의 근거가 되는 원문이다 (기본값은 source).
    재작성 경로는 제목까지 포함한 재료 전부를 넘긴다 — 제목에만 나오는 수치를
    신규 주입으로 오탐하지 않게 하기 위해서다. 누락 · 복제 축은 재작성 대상인
    본문만 보므로 source 를 그대로 쓴다."""
    ground = source if grounding is None else grounding
    missing = missing_numbers(source, output)
    extra = extra_numbers(ground, output)
    quotes = missing_quotes(source, output)
    retention = char_ngram_retention(source, output)
    return {"missing": missing, "extra": extra, "quotes": quotes,
            "retention": retention,
            "ok": not missing and not extra and not quotes
            and retention <= threshold}


def select_best(attempts: list[dict],
                threshold: float = RETENTION_THRESHOLD) -> dict:
    """위반이 가장 적은 시도 — 동률이면 잔존율이 낮은 것.

    원문 복제도 위반 1건으로 센다. 그러지 않으면 축을 하나도 어기지 않는
    복제본이 위반 1건짜리 진짜 재작성을 언제나 이긴다 — 표현을 바꾸려고 만든
    장치가 안 바꾼 쪽을 고르게 된다.

    본문을 버리지 않으므로 항상 하나를 돌려준다.
    축 키가 없는 시도도 받는다 (누락 축만 쓰던 호출측 호환)."""
    def violations(a: dict) -> int:
        n = sum(len(a.get(k) or []) for k in
                ("missing", "extra", "quotes", "names", "clubs"))
        return n + (1 if a["retention"] > threshold else 0)
    return min(attempts, key=lambda a: (violations(a), a["retention"]))
