"""오염 · 누락 행의 단건 URL 재수집 (멱등).

같은 소스의 재수집은 URL 정합 가드의 "changed" 경로로 통과한다 — cross-source 오염 행을
원문 값 (제목 · 기자 · 본문) 으로 복원하고 번역을 리셋해 다음 enrich 회차가 수렴한다.
첫 사용처는 BBC 오염 3행 복구 (spec 2026-07-26 §7).

실행 전 `set -a; source .env; set +a` 필수 (이 프로젝트는 dotenv 미사용).
    uv run python -m bullet_in.refetch_urls --source-id bbc_sport --url https://... --dry-run
    uv run python -m bullet_in.refetch_urls --source-id bbc_sport --url https://... --url https://...
"""
from __future__ import annotations
import argparse, asyncio, logging, os
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import create_engine

from bullet_in.adapters.meta import (extract_authors, extract_body_images,
                                     extract_og_image, extract_og_title,
                                     extract_published_at)
from bullet_in.collect_fmkorea import persist
from bullet_in.models import RawItem
from bullet_in.score import load_sources
from bullet_in.storage.mariadb import MartStore

log = logging.getLogger(__name__)

REQUEST_GAP_SEC = 1.5   # backfill_journalist 와 같은 기준 (라이브 사이트 부담 회피)


def build_item(source_id: str, url: str, html: str,
               body_selector: str | None, now: datetime) -> RawItem | None:
    """기사 HTML → 정기 수집 (html 어댑터 상세 경로) 과 동형인 RawItem.
    제목 추출 실패 시 None — 불완전한 값으로 기존 행을 덮지 않는다."""
    title = extract_og_title(html)
    if not title:
        return None
    payload: dict = {"title": title}
    el = (BeautifulSoup(html, "html.parser").select_one(body_selector)
          if body_selector else None)
    payload["body"] = el.get_text(" ", strip=True) if el else ""
    payload["image_url"] = extract_og_image(html)
    payload["images"] = extract_body_images(html, body_selector, base_url=url)
    payload["authors"] = extract_authors(html)
    pub = extract_published_at(html)
    if pub:
        payload["published"] = pub[0].isoformat()
        payload["published_precision"] = pub[1]
    return RawItem(source_id=source_id, source_type="html", url=url,
                   fetched_at=now, raw_payload=payload)


async def refetch(source_id: str, urls: list[str], dry_run: bool = False) -> tuple[int, int, int]:
    sources = load_sources("config/sources.yaml")
    if source_id not in sources:
        raise SystemExit(f"미등록 소스: {source_id}")
    body_selector = sources[source_id].get("config", {}).get("body_selector")
    now = datetime.now(timezone.utc)
    items: list[RawItem] = []
    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 headers={"User-Agent": "bullet-in/0.1"}) as c:
        for i, url in enumerate(urls):
            try:
                try:
                    r = await c.get(url)
                    r.raise_for_status()
                except httpx.HTTPError as e:
                    log.warning("fetch 실패 %s: %r", url, e)
                    continue
                item = build_item(source_id, url, r.text, body_selector, now)
                if item is None:
                    log.warning("제목 추출 실패 — 스킵 %s", url)
                    continue
                items.append(item)
            finally:
                if i < len(urls) - 1:
                    await asyncio.sleep(REQUEST_GAP_SEC)
    if dry_run:
        for it in items:
            log.info("[dry-run] %s → title=%r body=%d자 authors=%s", it.url,
                     it.raw_payload["title"], len(it.raw_payload["body"]),
                     it.raw_payload["authors"])
        return len(items), 0, 0
    mart = MartStore(create_engine(os.environ["MARIADB_URL"]))
    mart.ensure_schema()
    return persist(items, mart)


def format_result(n: int, dup: int, blocked: int, dry_run: bool) -> str:
    """CLI 출력 문구 — dry-run 은 미적재임을 명시해 실제 적재와 혼동을 막는다."""
    if dry_run:
        return f"[dry-run] 검증 {n}건 (미적재)"
    return f"적재 {n} · 동일 내용 생략 {dup} · 기존 기사 유지 {blocked}"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="단건 URL 재수집 (멱등)")
    ap.add_argument("--source-id", required=True)
    ap.add_argument("--url", action="append", required=True, help="반복 지정 가능")
    ap.add_argument("--dry-run", action="store_true", help="DB 쓰기 없이 추출 결과만 로깅")
    args = ap.parse_args()
    n, dup, blocked = asyncio.run(refetch(args.source_id, args.url, dry_run=args.dry_run))
    print(format_result(n, dup, blocked, args.dry_run))


if __name__ == "__main__":
    main()
