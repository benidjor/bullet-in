from __future__ import annotations
import json, re

PROMPT = ("Translate the football news title to natural Korean and write a one-line "
          "Korean summary. Return ONLY JSON: "
          '{{"title_ko": "...", "summary_ko": "..."}}\n\nTitle: {title}\nBody: {body}')

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
    한 행이 실패해도 배치 전체를 중단하지 않는다 (멱등은 호출 구조로 보장)."""
    result: dict[str, tuple[str, str]] = {}
    for r in rows:
        try:
            msg = client.messages.create(
                model=model, max_tokens=300,
                messages=[{"role": "user", "content": PROMPT.format(
                    title=r["title_original"], body=r.get("body_excerpt") or "")}])
            parsed = _extract(msg.content[0].text)
        except Exception:
            parsed = None
        if parsed is not None:
            result[r["content_hash"]] = parsed
    return result
