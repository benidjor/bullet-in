"""잘린 채 저장된 트윗 원문을 전문으로 바꾼다 — 신원 이전 (멱등).

타임라인이 접은 트윗을 어댑터가 접힌 채로 읽어 (2026-08-30 이전 수집분) 원문이
문장 중간에서 끊긴 행이 있다. 그 행들은 타임라인에서 이미 밀려나 다시 수집되지
않으므로 회차가 스스로 못 고친다.

`content_hash = sha256(원문 제목 | canonical_url(url))` 이라 제목을 고치면 해시가
갈린다. 그 해시를 `article_players` (PK 의 한 축) · `players.first_seen` · 상세 페이지
파일명이 참조하므로 **제목만 고치면 참조가 고아로 남는다** — 주소 축에서 실제로
그렇게 됐다 (`migrate_url_identity` 의 머리말 · 2026-08-29 귀속 43건 고아).
그래서 참조 이동을 같은 트랜잭션에서 한다 (그 배치의 `_move_refs` 를 그대로 쓴다).

번역 4필드는 NULL 로 민다 — 원문이 달라졌으니 옛 번역은 다른 글의 번역이다.
다음 회차가 새 원문으로 다시 만든다. **잘린 재료가 부른 환각은 그때 사라진다.**

전문은 미리 받아 둔 파일에서 읽는다 (`{content_hash: 전문}` 형태의 JSON).
여기서 다시 긁지 않는다 — 이미 받은 것을 확인 목적으로 또 받으면 차단 위험만 는다.

실행 전 `set -a; source .env; set +a` 필수 (이 프로젝트는 dotenv 미사용).
    uv run python -m bullet_in.backfill_tweet_full_text --texts full.json --dry-run
    uv run python -m bullet_in.backfill_tweet_full_text --texts full.json
"""
from __future__ import annotations
import argparse, json, logging, os
from sqlalchemy import create_engine, text

from bullet_in.canonical import content_hash
from bullet_in.migrate_url_identity import _move_refs

log = logging.getLogger(__name__)

_SELECT_SQL = text(
    "SELECT content_hash, url, title_original FROM articles"
    " WHERE content_hash IN :hashes")
_EXISTS_SQL = text("SELECT content_hash FROM articles WHERE content_hash IN :hashes")
_UPDATE_SQL = text(
    "UPDATE articles SET title_original=:t, content_hash=:h,"
    " title_ko=NULL, summary_ko=NULL, summary3_ko=NULL, body_ko=NULL"
    " WHERE content_hash=:o")


def plan(rows: list[dict], texts: dict[str, str],
         existing: set[str]) -> tuple[list[dict], list[dict]]:
    """(적용 목록, 건너뛴 목록). DB 를 안 만지는 순수 함수라 사본 없이 검증할 수 있다.

    건너뛰는 세 경우 — 전문이 더 짧거나 같음 (이미 반영됐거나 잘린 적 없음) ·
    새 해시가 이미 다른 행의 것 (그 자리로 옮기면 남의 행을 덮는다) ·
    전문을 안 받은 행."""
    apply_, skip = [], []
    for r in rows:
        full = texts.get(r["content_hash"])
        old = r["content_hash"]
        if not full:
            skip.append({**r, "why": "전문 없음"})
            continue
        if len(full) <= len(r["title_original"] or ""):
            skip.append({**r, "why": "전문이 더 길지 않음 (멱등)"})
            continue
        new = content_hash(full, r["url"])
        if new != old and new in existing:
            skip.append({**r, "why": f"새 해시가 이미 있음 {new[:8]}"})
            continue
        apply_.append({**r, "full": full, "new_hash": new})
    return apply_, skip


def backfill(engine, texts: dict[str, str], *, dry_run: bool = True) -> dict:
    hashes = tuple(texts)
    if not hashes:
        return {"targets": 0, "applied": 0, "skipped": 0}
    with engine.connect() as c:
        rows = [dict(r) for r in c.execute(
            _SELECT_SQL.bindparams(hashes=hashes)).mappings().all()]
        existing = {h for (h,) in c.execute(text(
            "SELECT content_hash FROM articles")).all()}
    apply_, skip = plan(rows, texts, existing)
    for s in skip:
        log.info("건너뜀 %s — %s", s["content_hash"][:8], s["why"])
    stats = {"targets": len(rows), "applied": len(apply_), "skipped": len(skip),
             "hash_changed": sum(1 for a in apply_ if a["new_hash"] != a["content_hash"])}
    if dry_run:
        return stats
    with engine.begin() as c:
        for a in apply_:
            # 참조를 먼저 옮기고 행을 갱신한다 — 순서가 뒤바뀌면 그 사이에 고아가 생긴다.
            if a["new_hash"] != a["content_hash"]:
                _move_refs(c, a["content_hash"], a["new_hash"])
            c.execute(_UPDATE_SQL, {"t": a["full"], "h": a["new_hash"],
                                    "o": a["content_hash"]})
    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="잘린 트윗 원문을 전문으로 (멱등)")
    ap.add_argument("--texts", required=True,
                    help="{content_hash: 전문} 형태의 JSON 파일")
    ap.add_argument("--dry-run", action="store_true", help="DB 쓰기 없이 집계만")
    args = ap.parse_args()
    texts = json.load(open(args.texts, encoding="utf-8"))
    engine = create_engine(os.environ["MARIADB_URL"])
    st = backfill(engine, texts, dry_run=args.dry_run)
    verb = "적용 예정" if args.dry_run else "적용"
    print(f"대상 {st['targets']}건 · {verb} {st['applied']}건 "
          f"(해시 갈림 {st['hash_changed']}건) · 건너뜀 {st['skipped']}건")


if __name__ == "__main__":
    main()
