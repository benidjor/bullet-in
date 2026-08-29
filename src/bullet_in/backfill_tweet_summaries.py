"""본문 없는 트윗의 저장된 요약을 비운다 (소급 · 안건 2η).

회차 경로는 이제 이 행들에 요약을 만들지 않는다 (enrich.TWEET_PROMPT).
그런데 이미 적재된 행은 title_ko 가 차 있어 rows_missing_translation 에 안 걸리므로
회차가 영원히 다시 안 본다 — 지어낸 요약이 화면에 그대로 남는다.

Gemini 를 부르지 않는다. 지우기만 한다. body_ko 는 건드리지 않는다 — 트윗 전문을
옮긴 값이고 게이트로 재 보면 이 축의 주입이 0건이다 (2026-08-29 실측 252건 중
요약 두 필드 11건 · body_ko 0건).

대상 판정은 회차와 같은 함수 (partition_bodyless_tweets) 를 부른다 — 술어를 SQL 로
옮겨 적으면 두 경로가 갈린다.
멱등 — 재실행 시 요약이 남아 있는 행만 다시 본다.

실행 전 `set -a; source .env; set +a` 필수 (이 프로젝트는 dotenv 미사용).
    uv run python -m bullet_in.backfill_tweet_summaries --dry-run
    uv run python -m bullet_in.backfill_tweet_summaries
"""
from __future__ import annotations
import argparse, logging, os
from sqlalchemy import create_engine, text
from bullet_in.enrich import BODY_AS_TITLE_SOURCES, partition_bodyless_tweets

log = logging.getLogger(__name__)

_SELECT_SQL = text(
    "SELECT content_hash, source_id, body_source, body_excerpt, summary_ko, "
    "summary3_ko FROM articles WHERE source_id IN :sids")
_UPDATE_SQL = text("UPDATE articles SET summary_ko=NULL, summary3_ko=NULL "
                   "WHERE content_hash=:h")


def targets(rows: list[dict]) -> list[dict]:
    """비울 행 — 본문 없는 트윗 중 요약이 하나라도 남아 있는 것."""
    tweets, _ = partition_bodyless_tweets(rows)
    return [r for r in tweets
            if (r.get("summary_ko") or "").strip()
            or (r.get("summary3_ko") or "").strip()]


def backfill(dry_run: bool = False) -> tuple[int, int]:
    """(트윗 소스 전체, 비운 행). dry-run 이면 두 번째는 비울 예정 건수."""
    engine = create_engine(os.environ["MARIADB_URL"])
    with engine.connect() as c:
        rows = [dict(r) for r in c.execute(
            _SELECT_SQL.bindparams(sids=tuple(sorted(BODY_AS_TITLE_SOURCES)))
        ).mappings().all()]
    hit = targets(rows)
    log.info("트윗 소스 %d건 중 요약을 비울 행 %d건", len(rows), len(hit))
    if not dry_run:
        with engine.begin() as c:
            for r in hit:
                c.execute(_UPDATE_SQL, {"h": r["content_hash"]})
    return len(rows), len(hit)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="본문 없는 트윗의 요약 비우기 (멱등)")
    ap.add_argument("--dry-run", action="store_true", help="DB 쓰기 없이 집계만")
    args = ap.parse_args()
    total, cleared = backfill(dry_run=args.dry_run)
    verb = "비울 예정" if args.dry_run else "비움"
    print(f"트윗 소스 {total}건 · {verb} {cleared}건")


if __name__ == "__main__":
    main()
