"""기사 상세 페이지에서 본문 · 이미지 · 저자 · 발행 시각을 뽑는다.

HTML 어댑터와 RSS 어댑터가 함께 쓴다 (설계 2026-10-05 §2.4).
BBC Sport 가 RSS 로 옮겨도 본문과 저자를 HTML 시절과 같은 코드로 읽어야
전담 기자 (Mokbel) 의 등급 승격이 그대로 유지된다."""
from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

from bullet_in.adapters.meta import (extract_authors, extract_body_images,
                                     extract_og_image, extract_published_at)


async def fetch_article_detail(client: httpx.AsyncClient, url: str,
                               body_selector: str) -> dict:
    """상세 페이지 한 장 → payload 에 더할 값. HTTP 오류면 본문만 비운다 (다음 회차 재시도)."""
    try:
        rb = await client.get(url)
        rb.raise_for_status()
    except httpx.HTTPError:
        return {"body": ""}
    el = BeautifulSoup(rb.text, "html.parser").select_one(body_selector)
    out = {"body": el.get_text(" ", strip=True) if el else "",
           "image_url": extract_og_image(rb.text),
           "images": extract_body_images(rb.text, body_selector, base_url=url),
           "authors": extract_authors(rb.text)}
    pub = extract_published_at(rb.text)
    if pub:
        out["published"] = pub[0].isoformat()
        out["published_precision"] = pub[1]
    return out
