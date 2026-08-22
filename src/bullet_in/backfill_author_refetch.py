"""저자 회수 소급 — 원문에 다시 붙어 구조화 저자만 취한다 (1회성 · 안건 y).

전재글은 수집 당시 원문 페이지를 받아 놓고 저자를 읽지 않았다.
어댑터는 고쳤지만 이미 적재된 행은 그대로라 원문에 한 번 더 붙어야 한다
(docs/troubleshooting/2026-08-13-parser-fix-does-not-reach-stored-rows.md).

**기여자 명단은 바이라인이 아니다** — 원문이 돌려준 이름이 여섯을 넘으면 안 쓴다
(라이브 블로그가 그날 글을 쓴 사람 전원을 싣는다 · 실측 2건).

**본문은 건드리지 않는다** — UPDATE 는 authors_json 한 컬럼뿐이다.
저자를 얻으려다 본문까지 갈아 끼우면 body_level 이 흔들려 화면이 바뀐다.
대표 기자도 안 쓴다 — 서빙이 저자 목록에서 같은 규칙으로 골라낸다
(serve.render.article_journalists).

대상은 fmkorea 전재글 중 **정식 표기를 못 가진 행**이다 — 값이 비어 있는 행과
게시자가 옮긴 한글 이름만 든 행 둘 다다 (안건 λ · 처음에는 앞의 것만 봐서 51행을 놓쳤다).
직수집 소스 (skysports · goal) 는 표본 10건 전건에서 원문에도 저자가 없었다
(구조화 정보 0 · 화면 바이라인 0 · 2026-08-19 실측) — 붙어 봐야 얻을 것이 없다.

Gemini 호출 0 · 과금 0 · 외부 접속은 언론사 도메인뿐이다.
state 파일은 이미 붙어 본 원문에 다시 붙지 않기 위한 것이다 — 저자를 못 얻은 행도
기록되므로 재실행이 같은 페이지를 두 번 때리지 않는다.

실행 전 `set -a; source .env; set +a` 필수 (이 프로젝트는 dotenv 미사용).
    uv run python -m bullet_in.backfill_author_refetch --dry-run --limit 5
    uv run python -m bullet_in.backfill_author_refetch --state /tmp/author_refetch.txt
"""
from __future__ import annotations
import argparse
import asyncio
import json
import logging
import os
from collections import Counter
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text

from bullet_in.adapters.meta import extract_authors

log = logging.getLogger(__name__)

_UA = "Mozilla/5.0 bullet-in/0.1"
_REQUEST_GAP_SEC = 2.0
_TIMEOUT_SEC = 25
# 원문이 돌려준 이름이 이보다 많으면 바이라인이 아니라 기여자 명단으로 본다.
# 라이브 블로그는 그날 글을 쓴 사람 전원을 구조화 정보에 싣는데, 전재글이 옮긴 것은
# 그중 한 꼭지다 — 명단을 그대로 넣으면 그 글을 안 쓴 기자가 기사에 붙는다.
# 실측 53건에서 정상 바이라인의 최대는 4명이었고, 넘은 둘은 The Athletic 의
# transfer-latest 페이지 (15명 · 16명) 로 게시자가 옮긴 바이라인은 한 명이었다.
_MAX_BYLINE_AUTHORS = 6

# 대상 조건은 「비어 있다」 가 아니라 「고칠 값이 있다」 다 (안건 λ).
# 첫 판본은 authors_json IS NULL 이었고, 게시자가 말머리에서 옮긴 한글 이름이
# 이미 들어 있던 51행이 통째로 빠졌다 — 화면에는 이름이 하나 떠 있어서 미상
# 집계에도 안 잡혀 어느 계수로도 안 보였다
# (docs/troubleshooting/2026-08-20-backfill-skipped-it-so-we-diagnosed-it-again.md).
# 영문 표기를 이미 함께 가진 행은 재접속으로 얻을 것이 없어 뺀다.
_SELECT_SQL = text(
    "SELECT content_hash, url, outlet, "
    "CASE WHEN authors_json IS NULL THEN '빈 값' ELSE '한글 폴백' END AS kind "
    "FROM articles WHERE source_id = 'fmkorea' AND ("
    "authors_json IS NULL OR "
    "(authors_json REGEXP '[가-힣]' AND authors_json NOT REGEXP '[A-Za-z]')) "
    "ORDER BY published_at DESC")
_UPDATE_SQL = text("UPDATE articles SET authors_json=:a WHERE content_hash=:h")


def load_state(path: str | None) -> set[str]:
    """이미 붙어 본 해시 — 파일이 없으면 빈 집합."""
    if not path or not Path(path).exists():
        return set()
    return {l.strip() for l in Path(path).read_text().splitlines() if l.strip()}


def append_state(path: str | None, content_hash: str) -> None:
    if path:
        with open(path, "a") as f:
            f.write(content_hash + "\n")


async def fetch_authors(client: httpx.AsyncClient, url: str) -> tuple[list[str], str]:
    """원문 1건의 구조화 저자와 결과 라벨 — 실패는 빈 목록으로 돌려 배치를 잇는다."""
    try:
        r = await client.get(url)
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        return [], f"http {e.response.status_code}"
    except httpx.HTTPError as e:
        return [], f"error {type(e).__name__}"
    names = extract_authors(r.text)
    if len(names) > _MAX_BYLINE_AUTHORS:
        return [], f"명단 과다 {len(names)}"
    return names, "회수" if names else "저자 없음"


async def _run(rows: list[dict], dry_run: bool, state: str | None,
               engine) -> Counter:
    stats: Counter = Counter()
    async with httpx.AsyncClient(timeout=_TIMEOUT_SEC, follow_redirects=True,
                                 headers={"User-Agent": _UA}) as client:
        for i, row in enumerate(rows):
            if i:
                await asyncio.sleep(_REQUEST_GAP_SEC)
            names, label = await fetch_authors(client, row["url"])
            stats[label] += 1
            log.info("[%d/%d] %s %s %s %s %s", i + 1, len(rows),
                     row["content_hash"][:8], row.get("outlet") or "?",
                     row.get("kind") or "?", label, names or "")
            if names and not dry_run:
                with engine.begin() as c:
                    c.execute(_UPDATE_SQL,
                              {"h": row["content_hash"],
                               "a": json.dumps(names, ensure_ascii=False)})
            if not dry_run:
                append_state(state, row["content_hash"])
    return stats


def backfill(dry_run: bool = False, limit: int | None = None,
             state: str | None = None) -> dict:
    engine = create_engine(os.environ["MARIADB_URL"])
    done = load_state(state)
    with engine.connect() as c:
        rows = [dict(r) for r in c.execute(_SELECT_SQL).mappings().all()]
    rows = [r for r in rows if r["content_hash"] not in done]
    if limit:
        rows = rows[:limit]
    kinds = Counter(r["kind"] for r in rows)
    log.info("대상 %d행 (빈 값 %d · 한글 폴백 %d · state 로 건너뛴 것 %d)"
             " · 요청 간격 %.1f초 · 예상 %.0f분",
             len(rows), kinds["빈 값"], kinds["한글 폴백"], len(done),
             _REQUEST_GAP_SEC, len(rows) * _REQUEST_GAP_SEC / 60)
    stats = asyncio.run(_run(rows, dry_run, state, engine))
    log.info("%s 회수 %d · 저자 없음 %d · 명단 과다 %d · 접속 실패 %d",
             "[dry-run]" if dry_run else "반영", stats["회수"], stats["저자 없음"],
             sum(v for k, v in stats.items() if k.startswith("명단 과다")),
             sum(v for k, v in stats.items() if k.startswith(("http", "error"))))
    return dict(stats)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int)
    p.add_argument("--state", help="이미 붙어 본 해시를 적어 두는 파일")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    backfill(dry_run=a.dry_run, limit=a.limit, state=a.state)


if __name__ == "__main__":
    main()
