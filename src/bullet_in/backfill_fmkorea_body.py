"""본문 빈 fmkorea 행에 게시글 본문 채우기 (1회성 · 멱등).

원문 기사 URL 재수집은 26건 중 1건만 성공했다 (스펙 §6.2). 게시글 본문이 유일하게
남은 재료인데, 게시글 URL 은 저장되지 않으므로 검색 페이징으로 후보를 모아 저장된
제목과 정확히 일치하는 것만 골라 받는다.

채운 행은 번역 4필드를 NULL 로 되돌려 다음 회차 enrich 가 본문 기반으로 재생성하게
한다 (backfill_body 와 같은 멱등 패턴).

실행 전 `set -a; source .env; set +a` 필수 (이 프로젝트는 dotenv 미사용).
라이브 사이트에 접촉하므로 출력은 tee 로 남기고 재실행하지 않는다.
    uv run python -m bullet_in.backfill_fmkorea_body --pages 3 --dry-run 2>&1 | tee ~/bf.log
    uv run python -m bullet_in.backfill_fmkorea_body --pages 3 2>&1 | tee ~/bf.log
"""
from __future__ import annotations
import argparse, asyncio, logging, os, re
from pathlib import Path
from urllib.parse import quote

import httpx
import yaml
from sqlalchemy import create_engine, text

from bullet_in.adapters.fmkorea import (_body_text, _is_repost_blocked,
                                        _post_url_from_href,
                                        extract_body_journalist,
                                        strip_publish_datetime)
from bullet_in.backfill_fmkorea import check_page_placeholder
from bullet_in.collect_fmkorea import (STATE_PATH, build_fmkorea_adapter,
                                       read_last_contact, should_supplement,
                                       tunnel_alive, write_last_contact)
from bullet_in.storage.mariadb import MartStore

log = logging.getLogger(__name__)

REQUEST_GAP_SEC = 1.5      # 라이브 사이트 부담 회피 (다른 백필과 같은 기준)
MAX_POSTS = 120            # 검색 후보 상한 — 대상 제목을 놓치지 않을 만큼 넉넉히
POST_BODY_LEVEL = 1

_SELECT_SQL = text(
    "SELECT content_hash, title_original FROM articles "
    "WHERE source_id='fmkorea' AND COALESCE(body_source,'')='' "
    "ORDER BY published_at DESC")
# journalist 는 이미 값이 있으면 보존한다 (말머리 값 우선 · 스펙 §4.1).
# 번역 4필드는 NULL 로 되돌려 다음 회차가 본문 기반으로 재생성한다.
_UPDATE_SQL = text(
    "UPDATE articles SET body_source=:b, body_level=:lv, "
    "journalist=COALESCE(journalist, :j), "
    "title_ko=NULL, summary_ko=NULL, summary3_ko=NULL, body_ko=NULL "
    "WHERE content_hash=:h")


_BRACKET_RE = re.compile(r"^\s*\[([^\]]+)\]\s*")
# 조사를 떼야 사람이 실제로 성공시킨 질의와 같아진다 ('에미레이츠와' → '에미레이츠').
_PARTICLE_RE = re.compile(r"(을|를|이|가|은|는|와|과|의|에서|에|으로|로|도|만)$")
_TOKEN_SPLIT_RE = re.compile(r"[\s,./·'\"()\[\]]+")


def _debracket(title: str) -> str:
    return _BRACKET_RE.sub("", title).strip()


def _outlet_of(title: str) -> str:
    """말머리의 매체명 — 기자명이 붙어 있으면 앞부분만."""
    m = _BRACKET_RE.match(title)
    return re.split(r"\s*-\s*", m.group(1))[0].strip() if m else ""


def _longest_token(title: str) -> str:
    toks = [t for t in _TOKEN_SPLIT_RE.split(_debracket(title)) if len(t) >= 2]
    return _PARTICLE_RE.sub("", max(toks, key=len)) if toks else ""


def search_candidates(title: str) -> list[tuple[str, str]]:
    """(search_target, keyword) 후보를 시도 순서대로.

    수집용 고정 키워드 (아스날 · 온스테인 등) 로는 오래 전에 올라간 글이 첫 페이지에
    없어 못 찾는다. 백필은 찾을 제목을 이미 알고 있으므로 제목에서 검색어를 만든다.

    fmkorea 검색의 매칭 의미론 (부분 문자열인지 토큰 AND 인지) 을 아직 실측하지
    못했다 — 430 으로 예행이 막혔다. 그래서 한 규칙에 걸지 않고 특정적인 것부터
    차례로 시도하고 제목이 정확히 일치하면 멈춘다."""
    out: list[tuple[str, str]] = []
    body, outlet, tok = _debracket(title), _outlet_of(title), _longest_token(title)
    for cand in ((("title", body) if body else None),
                 ((("title_content", f"{outlet} {tok}")) if outlet and tok else None),
                 (("title", tok) if tok else None),
                 (("title_content", outlet) if outlet else None)):
        if cand and cand[1].strip() and cand not in out:
            out.append(cand)
    return out


BLOCK_STATUS = 430      # fmkorea 차단 신호 — 남은 후보를 더 두드리지 않는다


async def find_post_url(client: httpx.AsyncClient, title: str, search_url: str,
                        item_selector: str, base_url: str,
                        gap_sec: float = REQUEST_GAP_SEC) -> tuple[str | None, int]:
    """제목에서 만든 검색어로 글 주소를 찾는다 → (글 URL 또는 None, 시도한 검색 수).

    제목이 정확히 일치하는 결과에서 멈춘다 — 부분 일치를 받으면 다른 글 본문이 들어간다.
    차단 (430) 을 만나면 남은 후보를 포기한다."""
    from bs4 import BeautifulSoup

    want = title.strip()
    tried = 0
    for i, (target, keyword) in enumerate(search_candidates(title)):
        if i and gap_sec:
            await asyncio.sleep(gap_sec)
        url = search_url.format(target=target, keyword=quote(keyword), page=1)
        tried += 1
        try:
            r = await client.get(url)
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == BLOCK_STATUS:
                log.warning("fmkorea 검색 차단 %s — 남은 후보 포기 kw=%s",
                            BLOCK_STATUS, keyword)
                return None, tried
            log.warning("fmkorea 검색 HTTP %s kw=%s — 다음 후보",
                        e.response.status_code, keyword)
            continue
        except httpx.HTTPError as e:
            log.warning("fmkorea 검색 실패 kw=%s err=%r — 다음 후보", keyword, e)
            continue
        for a in BeautifulSoup(r.text, "html.parser").select(item_selector):
            if a.get_text(strip=True) == want:
                post_url = _post_url_from_href(a.get("href", ""), base_url)
                if post_url:
                    log.info("글 주소 확인 kw=%s → %s", keyword, post_url)
                    return post_url, tried
    return None, tried


def match_targets(targets: dict[str, str],
                  found: list[tuple[str, str]]) -> dict[str, str]:
    """{content_hash: 제목} × [(제목, 글 URL)] → {content_hash: 글 URL}.
    제목 완전 일치만 인정한다 — 부분 일치를 허용하면 다른 글의 본문이 들어간다."""
    by_title = {t.strip(): u for t, u in found}
    return {h: by_title[title.strip()] for h, title in targets.items()
            if title.strip() in by_title}


def row_update(html: str, body_selector: str) -> dict | None:
    """게시글 HTML → 저장할 body_source · body_level · journalist.
    퍼가기 금지거나 본문이 비면 None — 행을 건드리지 않고 재실행 몫으로 남긴다."""
    if _is_repost_blocked(html):
        return None
    body = strip_publish_datetime(_body_text(html, body_selector))
    if not body:
        return None
    return {"body": body, "body_level": POST_BODY_LEVEL,
            "journalist": extract_body_journalist(body)}


async def backfill(pages: int = 3, limit: int | None = None,
                   dry_run: bool = False, force: bool = False,
                   by_title: bool = False) -> dict[str, int]:
    stats = {"target": 0, "matched": 0, "filled": 0, "blocked": 0, "failed": 0}
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
    src = next(s for s in cfg["sources"] if s["source_id"] == "fmkorea")
    if not by_title:                    # 대상별 검색은 page=1 만 쓴다
        check_page_placeholder(src["config"]["search_url"], pages)
    proxy = os.environ.get("FMKOREA_PROXY")
    if proxy and not tunnel_alive(proxy):
        log.info("fmkorea 터널 미접속 — 백필 중단 (접촉 없음)")
        return stats

    engine = create_engine(os.environ["MARIADB_URL"])
    mart = MartStore(engine)
    now = mart.db_now()
    marks = [t for t in (read_last_contact(STATE_PATH),
                         mart.source_watermarks().get("fmkorea")) if t]
    if not force and not should_supplement(max(marks) if marks else None, now):
        log.info("fmkorea 백필 중단 — 3h 이내 접촉 (--force 로 우회)")
        return stats

    with engine.connect() as c:
        targets = {r["content_hash"]: r["title_original"]
                   for r in c.execute(_SELECT_SQL).mappings().all()}
    if limit:
        targets = dict(list(targets.items())[:limit])
    stats["target"] = len(targets)
    log.info("본문 빈 fmkorea 행 %d건", len(targets))
    if not targets:
        return stats

    # exclude_titles 를 비워야 이미 적재된 글이 후보에 남는다 (정기 회차와 반대 방향).
    adapter = build_fmkorea_adapter(cfg, proxy, pages=pages,
                                    request_gap_sec=REQUEST_GAP_SEC,
                                    exclude_titles=set(),
                                    max_posts=MAX_POSTS)
    if by_title:
        matched, searches = {}, 0
        async with adapter._client() as c:
            for i, (h, title) in enumerate(targets.items()):
                if i:
                    await asyncio.sleep(REQUEST_GAP_SEC)
                post_url, tried = await find_post_url(
                    c, title, adapter.search_url, adapter.item_selector,
                    adapter.base_url)
                searches += tried
                if post_url:
                    matched[h] = post_url
                else:
                    log.info("글 주소 못 찾음 (검색 %d회) — %s", tried, title[:40])
        write_last_contact(STATE_PATH, now)
        log.info("대상별 검색 %d회 · 주소 확인 %d/%d건",
                 searches, len(matched), len(targets))
    else:
        found = await adapter.discover()
        write_last_contact(STATE_PATH, now)     # 후보 0건이어도 접촉 스탬프
        log.info("검색 후보 %d건", len(found))
        matched = match_targets(targets, found)
        log.info("제목 일치 %d/%d건", len(matched), len(targets))
    stats["matched"] = len(matched)

    async with adapter._client() as c:
        for i, (h, post_url) in enumerate(matched.items()):
            if i:
                await asyncio.sleep(REQUEST_GAP_SEC)
            try:
                r = await c.get(post_url)
                r.raise_for_status()
            except httpx.HTTPError as e:
                stats["failed"] += 1
                log.warning("글 fetch 실패 %s: %r", post_url, e)
                continue
            upd = row_update(r.text, adapter.body_selector)
            if upd is None:
                stats["blocked"] += 1
                log.info("퍼가기 금지 또는 본문 없음 — 건너뜀 %s", post_url)
                continue
            if dry_run:
                log.info("[dry-run] %s → 본문 %d자 · 기자 %s",
                         h[:8], len(upd["body"]), upd["journalist"])
            else:
                with engine.begin() as conn:
                    conn.execute(_UPDATE_SQL, {"b": upd["body"], "lv": upd["body_level"],
                                               "j": upd["journalist"], "h": h})
            stats["filled"] += 1
    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="본문 빈 fmkorea 행 본문 채우기 (멱등)")
    ap.add_argument("--pages", type=int, default=3, help="검색 페이지 수")
    ap.add_argument("--limit", type=int, default=None, help="대상 상한 (드라이런 검증용)")
    ap.add_argument("--dry-run", action="store_true", help="DB 쓰기 없이 결과만 로깅")
    ap.add_argument("--force", action="store_true", help="3h 접촉 간격 가드 우회")
    ap.add_argument("--by-title", action="store_true",
                    help="대상 제목에서 만든 검색어로 글 주소를 찾는다 "
                         "(고정 키워드 첫 페이지에 없는 오래된 글용 · 대상당 검색 1~4회)")
    args = ap.parse_args()
    s = asyncio.run(backfill(pages=args.pages, limit=args.limit,
                             dry_run=args.dry_run, force=args.force,
                             by_title=args.by_title))
    print(f"대상 {s['target']} · 일치 {s['matched']} · 채움 {s['filled']} "
          f"· 금지·본문없음 {s['blocked']} · 실패 {s['failed']}")


if __name__ == "__main__":
    main()
