from __future__ import annotations
import json, logging, re

log = logging.getLogger(__name__)

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

def _extract(text: str) -> tuple[str, str] | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        return d["title_ko"], d["summary_ko"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None

def enrich_rows(rows: list[dict], client, model: str) -> dict[str, tuple[str, str]]:
    """rows: content_hash, title_original, body_excerpt 를 가진 (번역 누락) dict 목록.
    한 행이 실패해도 배치 전체를 중단하지 않는다 (멱등은 호출 구조로 보장).
    client 는 google-genai 의 genai.Client 모양(client.models.generate_content)을 기대한다.
    response_mime_type 로 JSON 출력을 유도하되, 모델이 코드펜스 등으로 감싸는
    경우를 대비해 _extract 정규식을 안전망으로 둔다."""
    result: dict[str, tuple[str, str]] = {}
    for r in rows:
        h = r["content_hash"]
        try:
            msg = client.models.generate_content(
                model=model,
                contents=PROMPT.format(title=r["title_original"],
                                       body=r.get("body_excerpt") or ""),
                config={"max_output_tokens": 300,
                        "response_mime_type": "application/json"})
        except Exception as e:
            if _is_rate_limit(e):
                log.warning("Gemini rate limit(429), 번역 중단 — 남은 행은 다음 사이클 누적")
                break
            log.warning("Gemini 호출 실패, 번역 스킵 content_hash=%s: %s", h, e)
            continue
        parsed = _extract(msg.text)
        if parsed is None:
            log.warning("Gemini 응답 파싱 실패, 번역 스킵 content_hash=%s", h)
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
