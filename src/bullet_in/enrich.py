from __future__ import annotations
import json

PROMPT = ("Translate the football news title to natural Korean and write a one-line "
          "Korean summary. Return ONLY JSON: "
          '{{"title_ko": "...", "summary_ko": "..."}}\n\nTitle: {title}\nBody: {body}')

def enrich_rows(rows: list[dict], client, model: str) -> dict[str, tuple[str, str]]:
    """rows: content_hash, title_original, body_excerpt 를 가진 dict 목록.
    이미 번역이 없는 행만 전달받는 전제 → 호출 구조상 멱등."""
    result: dict[str, tuple[str, str]] = {}
    for r in rows:
        msg = client.messages.create(
            model=model, max_tokens=300,
            messages=[{"role": "user", "content": PROMPT.format(
                title=r["title_original"], body=r.get("body_excerpt") or "")}])
        data = json.loads(msg.content[0].text)
        result[r["content_hash"]] = (data["title_ko"], data["summary_ko"])
    return result
