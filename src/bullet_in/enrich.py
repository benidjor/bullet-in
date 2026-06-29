from __future__ import annotations
import json, logging, re

log = logging.getLogger(__name__)

PAYWALLED_OUTLETS = {"The Athletic"}

def _is_rate_limit(exc: Exception) -> bool:
    if getattr(exc, "code", None) == 429:
        return True
    s = str(exc)
    return "429" in s or "RESOURCE_EXHAUSTED" in s

PROMPT = ("아스날 FC 축구 뉴스를 한국어로 번역·요약한다. 규칙:\n"
          "- title_ko: 한국 스포츠 기사 제목체로 간결하게(명사형 위주, 불필요한 조사 생략). "
          "예: '케이틀린 포드, 재계약 체결'.\n"
          "- summary_ko: 한 문장, 신문 평어체(종결어미 '~다'), 사실 중심, 추측·과장 금지.\n"
          "- 고유명사는 통용 한글 표기. Arsenal=아스날, 선수·구단명은 널리 쓰는 한글 표기.\n"
          'ONLY JSON 반환: {{"title_ko": "...", "summary_ko": "..."}}\n\nTitle: {title}\nBody: {body}')

SUMMARY_PROMPT = ("다음 한국어 축구 뉴스를 한 문장으로 요약한다. "
                  "신문 평어체(종결어미 '~다'), 사실 중심, 추측·과장 금지. "
                  "고유명사는 통용 한글 표기(Arsenal=아스날). "
                  'JSON만 반환: {{"summary_ko": "..."}}\n\n제목: {title}\n본문: {body}')

TRANSLATE_PROMPT = (
    "아스날 FC 축구 뉴스를 한국어로 번역·요약한다. 규칙:\n"
    "- title_ko: 한국 스포츠 기사 제목체로 간결하게 (명사형 위주).\n"
    "- summary_ko: 한 문장, 신문 평어체(종결어미 '~다'), 사실 중심.\n"
    "- summary3_ko: 핵심을 3문장으로, 각 문장 평어체. 문자열 3개 배열.\n"
    "- body_ko: 본문 전체를 자연스러운 한국어로 번역. 단락 유지.\n"
    "- 고유명사는 통용 한글 표기(Arsenal=아스날).\n"
    'ONLY JSON: {{"title_ko":"...","summary_ko":"...","summary3_ko":["...","...","..."],"body_ko":"..."}}'
    "\n\nTitle: {title}\nBody: {body}")

PARAPHRASE_PROMPT = (
    "다음은 한국어로 번역된 아스날 FC 축구 기사다. 의미·사실·수치·고유명사·인용은 "
    "절대 바꾸지 말고 문장 표현만 자연스럽게 바꿔 다시 쓴다 (paraphrase). 규칙:\n"
    "- title_ko: 제목을 간결한 기사 제목체로 다시 쓴다(말머리 대괄호 제거).\n"
    "- summary_ko: 한 문장 요약, 평어체.\n"
    "- summary3_ko: 핵심 3문장 배열, 평어체.\n"
    "- body_ko: 본문 전체를 문장 표현만 바꿔 다시 쓴다. 내용 추가·삭제 금지.\n"
    'ONLY JSON: {{"title_ko":"...","summary_ko":"...","summary3_ko":["...","...","..."],"body_ko":"..."}}'
    "\n\nTitle: {title}\nBody: {body}")

def _extract(text: str) -> tuple[str, str] | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        return d["title_ko"], d["summary_ko"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None

def _extract_full(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        s3 = d["summary3_ko"]
        s3 = "\n".join(s3) if isinstance(s3, list) else str(s3)
        return {"title_ko": d["title_ko"], "summary_ko": d["summary_ko"],
                "summary3_ko": s3, "body_ko": d["body_ko"]}
    except (json.JSONDecodeError, KeyError, TypeError):
        return None

def partition_by_paywall(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    para, trans = [], []
    for r in rows:
        (para if r.get("outlet") in PAYWALLED_OUTLETS else trans).append(r)
    return para, trans

def enrich_rows(rows: list[dict], client, model: str, mode: str = "translate"
                ) -> dict[str, dict]:
    prompt = PARAPHRASE_PROMPT if mode == "paraphrase" else TRANSLATE_PROMPT
    result: dict[str, dict] = {}
    for r in rows:
        h = r["content_hash"]
        try:
            msg = client.models.generate_content(
                model=model,
                contents=prompt.format(title=r["title_original"],
                                       body=r.get("body_source") or r.get("body_excerpt") or ""),
                config={"max_output_tokens": 2048,
                        "response_mime_type": "application/json"})
        except Exception as e:
            if _is_rate_limit(e):
                log.warning("Gemini rate limit(429), enrich 중단 — 남은 행 다음 사이클")
                break
            log.warning("Gemini 호출 실패, 스킵 content_hash=%s: %s", h, e)
            continue
        parsed = _extract_full(msg.text)
        if parsed is None:
            log.warning("Gemini 응답 파싱 실패, 스킵 content_hash=%s", h)
            continue
        result[h] = parsed
    return result

def partition_translation_rows(rows: list[dict], sources: dict[str, dict]
                               ) -> tuple[list[dict], list[dict]]:
    """소스 lang 기준으로 (ko_rows, en_rows) 로 분리. lang 미지정은 en 취급."""
    ko, en = [], []
    for r in rows:
        lang = sources.get(r.get("source_id"), {}).get("lang", "en")
        (ko if lang == "ko" else en).append(r)
    return ko, en

def _extract_summary(text: str) -> str | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))["summary_ko"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None

def summarize_ko_rows(rows: list[dict], client, model: str) -> dict[str, str]:
    """한국어 행을 번역 없이 한국어 한 줄 요약만 생성. content_hash -> summary_ko.
    한 행이 실패해도 배치 전체를 중단하지 않는다 (run 측에서 본문 발췌로 폴백)."""
    result: dict[str, str] = {}
    for r in rows:
        h = r["content_hash"]
        try:
            msg = client.models.generate_content(
                model=model,
                contents=SUMMARY_PROMPT.format(title=r["title_original"],
                                               body=r.get("body_excerpt") or ""),
                config={"max_output_tokens": 200,
                        "response_mime_type": "application/json"})
        except Exception as e:
            if _is_rate_limit(e):
                log.warning("Gemini rate limit(429), 요약 중단 — 남은 행은 다음 사이클 누적")
                break
            log.warning("Gemini 호출 실패, 요약 스킵 content_hash=%s: %s", h, e)
            continue
        s = _extract_summary(msg.text)
        if s is None:
            log.warning("Gemini 응답 파싱 실패, 요약 스킵 content_hash=%s", h)
            continue
        result[h] = s
    return result
