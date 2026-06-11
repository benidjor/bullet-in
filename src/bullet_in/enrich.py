from __future__ import annotations
import json, re

PROMPT = ("Translate the football news title to natural Korean and write a one-line "
          "Korean summary. Return ONLY JSON: "
          '{{"title_ko": "...", "summary_ko": "..."}}\n\nTitle: {title}\nBody: {body}')

SUMMARY_PROMPT = ("다음 한국어 축구 뉴스를 한 문장으로 요약하세요. "
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
        try:
            msg = client.models.generate_content(
                model=model,
                contents=PROMPT.format(
                    title=r["title_original"], body=r.get("body_excerpt") or ""),
                config={"max_output_tokens": 300,
                        "response_mime_type": "application/json"})
            parsed = _extract(msg.text)
        except Exception:
            parsed = None
        if parsed is not None:
            result[r["content_hash"]] = parsed
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
        try:
            msg = client.models.generate_content(
                model=model,
                contents=SUMMARY_PROMPT.format(
                    title=r["title_original"], body=r.get("body_excerpt") or ""),
                config={"max_output_tokens": 200,
                        "response_mime_type": "application/json"})
            s = _extract_summary(msg.text)
        except Exception:
            s = None
        if s is not None:
            result[r["content_hash"]] = s
    return result
