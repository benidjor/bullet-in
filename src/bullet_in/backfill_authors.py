"""기존 기사의 authors_json 백필 (1회성).

공저 기사가 저자 각각의 기자 필터에서 나오게 하려면 저자 전원이 저장돼 있어야 한다.
재료는 이미 다 있어서 **Gemini 호출도 외부 접속도 없다** — mongo raw_items 의 authors,
fmkorea 는 저장된 body_source 재파싱, 나머지는 저장된 journalist 문자열 분해다.
멱등 — 재실행하면 authors_json IS NULL 인 행만 다시 만진다.

실행 전 `set -a; source .env; set +a` 필수 (이 프로젝트는 dotenv 미사용).
    uv run python -m bullet_in.backfill_authors --dry-run
    uv run python -m bullet_in.backfill_authors
"""
from __future__ import annotations
import argparse
import json
import logging
import os
from collections import Counter

from pymongo import MongoClient
from sqlalchemy import create_engine, text

from bullet_in.adapters.fmkorea import extract_body_authors
from bullet_in.adapters.meta import split_authors

log = logging.getLogger(__name__)

_SELECT_SQL = text(
    "SELECT content_hash, source_id, journalist, body_source FROM articles "
    "WHERE authors_json IS NULL ORDER BY published_at DESC")
_UPDATE_SQL = text("UPDATE articles SET authors_json=:a WHERE content_hash=:h")
_FIX_JOURNALIST_SQL = text("UPDATE articles SET journalist=:j WHERE content_hash=:h")


def authors_for(row: dict, raw_authors: list[str] | None) -> list[str]:
    """기사 1건의 저자 전원 — 소스별로 이미 있는 재료만 쓴다.

    fmkorea 는 원문 바이라인이 journalist 컬럼이 아니라 본문 앞머리에만 있어서
    저장된 본문을 다시 읽는다. 그때 저장된 대표값이 본문 저자의 오염된 판본이면
    (월 축약형이 붙은 'David Ornstein Aug') 버리고 다시 읽은 쪽을 쓴다."""
    journalist = (row.get("journalist") or "").strip()
    if raw_authors:
        names = list(raw_authors)
    elif row.get("source_id") == "fmkorea":
        names = extract_body_authors(row.get("body_source") or "")
        if journalist and not any(journalist.startswith(a) for a in names):
            names = [journalist] + names       # 말머리 기자명 — 본문 바이라인과 다른 값
    else:
        names = []
    if not names and journalist:
        names = [journalist]
    out: list[str] = []
    for raw in names:
        for n in split_authors(raw):
            if n not in out:
                out.append(n)
    return out


def cleaned_journalist(row: dict, names: list[str]) -> str | None:
    """저장된 대표값을 정정할 이름 — 정정할 것이 없으면 None.

    파서를 고쳐도 이미 적재된 행은 안 바뀐다 (월 축약형이 이름에 붙은 6행).
    저자가 한 명인데 저장값이 그 이름에 조각을 덧붙인 판본일 때만 갈아 끼운다.
    표기가 아예 다른 값 (말머리 한글명) 은 다른 재료라서 건드리지 않고,
    여러 이름을 이어 붙인 문자열도 그대로 둔다 — 그것을 첫 저자로 바꾸면 등재 기자를
    대표로 올리던 규칙이 죽는다 ('잭 로서, 사이먼 콜링스' 의 대표는 사이먼 콜링스다)."""
    j = (row.get("journalist") or "").strip()
    if len(names) != 1:
        return None
    return names[0] if j != names[0] and j.startswith(names[0]) else None


def _mongo_authors() -> dict[str, list[str]]:
    """content_hash → 수집 시점 저자 목록 (원문 소스의 공저 재료)."""
    client = MongoClient(os.environ["MONGO_URI"])
    col = client[os.environ.get("MONGO_DB", "bulletin")]["raw_items"]
    out: dict[str, list[str]] = {}
    for d in col.find({"raw_payload.authors": {"$exists": True, "$ne": []}},
                      {"content_hash": 1, "raw_payload.authors": 1}):
        h = d.get("content_hash")
        if h:
            out.setdefault(h, d["raw_payload"]["authors"])
    return out


def backfill(dry_run: bool = False, limit: int | None = None) -> dict:
    engine = create_engine(os.environ["MARIADB_URL"])
    raw = _mongo_authors()
    with engine.connect() as c:
        rows = [dict(r) for r in c.execute(_SELECT_SQL).mappings().all()]
    if limit:
        rows = rows[:limit]
    log.info("대상 %d행 · mongo 저자 보유 %d건", len(rows), len(raw))

    stats: Counter = Counter()
    updates, fixes = [], []
    for row in rows:
        names = authors_for(row, raw.get(row["content_hash"]))
        if not names:
            stats["미상"] += 1
            continue
        stats["공저" if len(names) > 1 else "단독"] += 1
        updates.append({"h": row["content_hash"],
                        "a": json.dumps(names, ensure_ascii=False)})
        fixed = cleaned_journalist(row, names)
        if fixed:
            stats["대표 정정"] += 1
            fixes.append({"h": row["content_hash"], "j": fixed})
            log.info("대표 정정 %s %r → %r", row["content_hash"][:8], row["journalist"], fixed)
    if not dry_run and updates:
        with engine.begin() as c:
            c.execute(_UPDATE_SQL, updates)
            if fixes:
                c.execute(_FIX_JOURNALIST_SQL, fixes)
    log.info("%s 단독 %d · 공저 %d · 미상 %d · 대표 정정 %d",
             "[dry-run]" if dry_run else "반영", stats["단독"], stats["공저"],
             stats["미상"], stats["대표 정정"])
    return dict(stats)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int)
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    backfill(dry_run=a.dry_run, limit=a.limit)


if __name__ == "__main__":
    main()
