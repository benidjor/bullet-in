"""주소 정정을 「신원 이전」 으로 다루는 배치 (멱등).

`content_hash = sha256(원문 제목 | canonical_url(url))` 이라 주소가 바뀌면 해시도 바뀐다.
그 해시를 `article_players` (PK 의 한 축) · `players.first_seen` · 상세 페이지 파일명이
참조하므로, **주소만 고치면 다음 회차가 해시를 갈아 치우고 참조가 고아로 남는다.**
2026-08-29 에 실제로 그렇게 됐다 — 주소 110행을 고치고 회차를 두 번 돌렸더니 여덟 행의
해시가 갈리고 귀속 43건이 고아가 됐다 (`docs/troubleshooting/2026-08-29-the-rule-moved-but-the-stored-addresses-did-not.md`).

그래서 이 배치는 한 트랜잭션에서 넷을 함께 한다.

- **병합** — 정규화하면 한 키가 되는 묶음에서 한 행만 남긴다 (등급이 높은 쪽 · 같으면 먼저 들어온 쪽)
- **참조 이동** — `article_players` 와 `players.first_seen` 을 남는 해시로 옮긴다
- **주소 갱신** — `url` 을 `canonical_url` 값으로
- **해시 갱신** — `content_hash` 를 새 주소로 다시 계산한 값으로

**이 배치는 `canonical_url` 을 그대로 믿는다.** 규칙이 틀린 채로 돌리면 틀린 주소를
저장값으로 굳힌다 — 2026-08-29 dry-run 에서 스카이 46행을 죽은 주소로 쓸 뻔했다.
정규화 규칙을 고쳐야 하는 상황이면 **규칙을 먼저 고쳐 배포하고 그다음에 돌린다.**

멱등이다 — 다시 돌리면 대상이 0건이 된다.
`--purge-orphans` 는 어느 기사도 안 가리키는 `article_players` 행을 지운다 (기본은 안 지움).

실행 전 `set -a; source .env; set +a` 필수 (이 프로젝트는 dotenv 미사용).
    uv run python -m bullet_in.migrate_url_identity --dry-run
    uv run python -m bullet_in.migrate_url_identity --apply
"""
from __future__ import annotations
import argparse
import logging
import os
from collections import defaultdict
from sqlalchemy import create_engine, text

from bullet_in.canonical import canonical_url, content_hash
from bullet_in.storage.mariadb import move_hash_refs

log = logging.getLogger(__name__)

_SELECT_SQL = text(
    "SELECT content_hash, url, source_id, title_original, created_at,"
    " COALESCE(body_level, IF(COALESCE(body_source,'')<>'',2,0)) body_level"
    " FROM articles")

_ORPHAN_SQL = text(
    "SELECT COUNT(*) FROM article_players ap"
    " LEFT JOIN articles a ON a.content_hash = ap.content_hash"
    " WHERE a.content_hash IS NULL")


def _survivor_key(row: dict) -> tuple:
    """남길 행 고르는 순서 — 본문 등급이 높은 쪽 · 같으면 먼저 들어온 쪽 (dedup 규칙과 같다)."""
    return (-int(row["body_level"] or 0), row["created_at"])


def plan(rows: list[dict]) -> tuple[list[tuple[str, list[str]]], list[tuple[str, str, str]]]:
    """(병합, 이전) 을 만든다. DB 를 안 만지는 순수 함수라 사본 없이 검증할 수 있다.

    병합 = [(남길 해시, [지울 해시들])] · 이전 = [(지금 해시, 새 주소, 새 해시)].
    이전 목록에는 주소나 해시 중 하나라도 달라지는 행만 담는다.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[canonical_url(r["url"])].append(r)

    merges: list[tuple[str, list[str]]] = []
    migrations: list[tuple[str, str, str]] = []
    for new_url, members in sorted(groups.items()):
        ranked = sorted(members, key=_survivor_key)
        keep = ranked[0]
        if len(ranked) > 1:
            merges.append((keep["content_hash"], [r["content_hash"] for r in ranked[1:]]))
        new_hash = content_hash(keep["title_original"] or "", new_url)
        if keep["url"] != new_url or keep["content_hash"] != new_hash:
            migrations.append((keep["content_hash"], new_url, new_hash))
    return merges, migrations


def _move_refs(c, old: str, new: str) -> None:
    """해시를 가리키는 두 자리를 옮긴다 — 규칙은 회차 적재와 한 곳에서 공유한다.

    회차의 `MartStore.upsert` 도 해시가 갈릴 때 같은 일을 해야 하므로 (2026-08-31),
    본체를 `bullet_in.storage.mariadb.move_hash_refs` 에 두고 여기서는 부르기만 한다.
    """
    move_hash_refs(c, old, new)


def migrate(engine, *, dry_run: bool = True, purge_orphans: bool = False) -> dict:
    with engine.connect() as c:
        rows = [dict(r) for r in c.execute(_SELECT_SQL).mappings().all()]
        orphans_before = c.execute(_ORPHAN_SQL).scalar()
    merges, migrations = plan(rows)
    stats = {"articles": len(rows), "merge_groups": len(merges),
             "dropped_rows": sum(len(v) for _k, v in merges),
             "migrations": len(migrations), "orphans_before": orphans_before,
             "purged": 0}
    if dry_run:
        return stats

    with engine.begin() as c:
        for keep, drops in merges:
            for old in drops:
                _move_refs(c, old, keep)
                c.execute(text("DELETE FROM articles WHERE content_hash=:h"), {"h": old})
        for old, new_url, new_hash in migrations:
            # 참조를 먼저 옮기고 행을 갱신한다 — 순서가 뒤바뀌면 그 사이에 고아가 생긴다.
            if new_hash != old:
                _move_refs(c, old, new_hash)
            c.execute(text("UPDATE articles SET url=:u, content_hash=:h WHERE content_hash=:o"),
                      {"u": new_url, "h": new_hash, "o": old})
        if purge_orphans:
            res = c.execute(text(
                "DELETE ap FROM article_players ap"
                " LEFT JOIN articles a ON a.content_hash = ap.content_hash"
                " WHERE a.content_hash IS NULL"))
            stats["purged"] = res.rowcount
    with engine.connect() as c:
        stats["orphans_after"] = c.execute(_ORPHAN_SQL).scalar()
    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="주소 · 해시 신원 이전 (멱등)")
    ap.add_argument("--dry-run", action="store_true", help="DB 쓰기 없이 계획만")
    ap.add_argument("--apply", action="store_true", help="실제로 쓴다")
    ap.add_argument("--purge-orphans", action="store_true",
                    help="어느 기사도 안 가리키는 article_players 행을 지운다")
    args = ap.parse_args()
    if args.apply == args.dry_run:
        ap.error("--dry-run 과 --apply 중 하나를 고른다")
    engine = create_engine(os.environ["MARIADB_URL"])
    stats = migrate(engine, dry_run=args.dry_run, purge_orphans=args.purge_orphans)
    for k, v in stats.items():
        log.info("%s = %s", k, v)


if __name__ == "__main__":
    main()
