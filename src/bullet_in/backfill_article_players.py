"""기존 기사 article_players 백필 (1회성 · 스펙 §7).

Gemini 약 500건 호출 — Tier 1 선불 과금이라 실행 전 사용자 확인 필수.
15 RPM 속도 한도 기준 약 35분. 429 중단 시 재실행하면 이어서 처리한다.
state 파일은 추출 결과 0명 행의 재과금을 막는다 (article_players 만으로는 구분 불가).
일괄 호출 방식 — extract_players_rows 에 targets 전체를 한 번에 넘기고, 반환된
hash 만 등재 · state 기록한다. 파싱 실패 행은 state 에 안 남아 재시도되고,
429 중단 시 뒷행이 반환에 없어 자연히 state 에 남지 않는다.

실행 전 `set -a; source .env; set +a` 필수.
    uv run python -m bullet_in.backfill_article_players --limit 5 --dry-run
    uv run python -m bullet_in.backfill_article_players
"""
from __future__ import annotations
import argparse, logging, os
from pathlib import Path
from sqlalchemy import create_engine, text
from bullet_in import notify, roster
from bullet_in.enrich import extract_players_rows
from bullet_in.run import GEMINI_MODEL
from bullet_in.storage.players import PlayerStore

log = logging.getLogger(__name__)

_TARGET_SQL = text(
    "SELECT content_hash, title_original, body_source, body_excerpt, url "
    "FROM articles WHERE NOT EXISTS (SELECT 1 FROM article_players ap "
    "WHERE ap.content_hash = articles.content_hash) ORDER BY published_at, id")


def load_state(path: Path) -> set[str]:
    return set(path.read_text().split()) if path.exists() else set()


def append_state(path: Path, content_hash: str) -> None:
    with path.open("a") as f:
        f.write(content_hash + "\n")


def filter_targets(rows: list[dict], done: set[str]) -> list[dict]:
    return [r for r in rows if r["content_hash"] not in done]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--state", type=Path, default=Path("backfill_players_state.txt"))
    args = ap.parse_args(argv)

    engine = create_engine(os.environ["MARIADB_URL"])
    with engine.connect() as c:
        rows = [dict(r) for r in c.execute(_TARGET_SQL).mappings().all()]
    targets = filter_targets(rows, load_state(args.state))
    if args.limit:
        targets = targets[:args.limit]
    print(f"대상: {len(targets)} 행 (미링크 {len(rows)} · state 제외 {len(rows) - len(targets)})")
    if args.dry_run:
        return

    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    pstore = PlayerStore(engine)
    by_hash = {r["content_hash"]: r for r in targets}
    new_candidates: list[dict] = []

    extracted = extract_players_rows(targets, client, GEMINI_MODEL)
    done = 0
    for h, raw in extracted.items():
        try:
            pairs = roster.normalize_pairs(raw)
            for cand in roster.record_article_players(pstore, h, pairs):
                row = by_hash[h]
                new_candidates.append({**cand, "title": row.get("title_original"),
                                       "url": row.get("url")})
            append_state(args.state, h)
            done += 1
        except Exception:
            log.warning(
                "등재 실패 — 건너뜀 content_hash=%s (부분 커밋 시 재실행 대상에서 "
                "빠질 수 있음 — 로그로 추적)", h, exc_info=True)

    if new_candidates:
        notify.send_alert(**notify.build_candidate_alert(
            new_candidates, run_id="backfill"))
    print(f"처리 {done} / {len(targets)} · 신규 후보 {len(new_candidates)}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
