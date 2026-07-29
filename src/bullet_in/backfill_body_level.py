"""기존 행의 body_level 백필 (1회성).

ALTER 로 추가한 컬럼은 기존 행에서 NULL 이라, 가드가 등급을 비교할 근거가 없다.
등급은 그 행의 본문을 무엇에서 받았는지로 정한다 — fmkorea 의 페이월 소스는
원문을 받을 수 없어 게시글 본문을 채택했고 (1), 나머지는 원문 URL 에서 받았다 (2).
페이월 판정은 어댑터 상수를 그대로 import 한다 (규칙을 SQL 에 옮겨 적지 않는다).

앞으로 들어오는 행은 어댑터가 재료 기준으로 등급을 싣는다 — 이 스크립트는
그 배선 이전에 적재된 행만 메운다.
멱등 — 재실행 시 body_level IS NULL 인 행만 다시 본다.

실행 전 `set -a; source .env; set +a` 필수 (이 프로젝트는 dotenv 미사용).
    uv run python -m bullet_in.backfill_body_level --dry-run
    uv run python -m bullet_in.backfill_body_level
"""
from __future__ import annotations
import argparse, logging, os
from collections import Counter
from sqlalchemy import create_engine, text
from bullet_in.adapters.fmkorea import PAYWALLED_OUTLETS

log = logging.getLogger(__name__)


def level_for(source_id: str, outlet: str | None, body: str | None) -> int:
    """본문 출처 등급 — 0 본문 없음 · 1 게시글 본문 · 2 언론사 본문."""
    if not body:
        return 0
    if source_id == "fmkorea" and outlet in PAYWALLED_OUTLETS:
        return 1
    return 2


_SELECT_SQL = text(
    "SELECT content_hash, source_id, outlet, body_source FROM articles "
    "WHERE body_level IS NULL")
_UPDATE_SQL = text("UPDATE articles SET body_level=:lv WHERE content_hash=:h")


def backfill(dry_run: bool = False) -> dict[int, int]:
    engine = create_engine(os.environ["MARIADB_URL"])
    with engine.connect() as c:
        rows = [dict(r) for r in c.execute(_SELECT_SQL).mappings().all()]
    log.info("body_level 미지정 %d건", len(rows))
    counts: Counter = Counter()
    for row in rows:
        lv = level_for(row["source_id"], row["outlet"], row["body_source"])
        counts[lv] += 1
        if not dry_run:
            with engine.begin() as c:
                c.execute(_UPDATE_SQL, {"lv": lv, "h": row["content_hash"]})
    return dict(counts)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="기존 행 body_level 백필 (멱등)")
    ap.add_argument("--dry-run", action="store_true", help="DB 쓰기 없이 집계만")
    args = ap.parse_args()
    counts = backfill(dry_run=args.dry_run)
    print(" · ".join(f"등급 {lv} {counts.get(lv, 0)}건" for lv in (0, 1, 2)))


if __name__ == "__main__":
    main()
