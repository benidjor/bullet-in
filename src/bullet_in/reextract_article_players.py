"""연결 기사 article_players 재추출 (1회성 · 재추출 스펙 §5).

추출 프롬프트 개정 (근거 조건 · 스펙 §3.1) 과 재료 폴백 (§3.2) 을 기존 연결
기사에 소급 적용한다. 백필 (backfill_article_players) 의 변형 — 대상 술어가
반대다 (연결 없는 기사가 아니라 연결 있는 기사 전건).

- Gemini 약 500건 호출 — Tier 1 선불 과금이라 실행 전 사용자 확인 필수.
  15 RPM 속도 한도 기준 약 40분. 429 중단 시 재실행하면 이어서 처리한다.
- 기사 단위로 기존 쌍을 지우고 새 추출 결과를 넣는다 — 개정 프롬프트가
  탈락시킨 인물이 남지 않아야 하므로 upsert 가 아니라 삭제 후 재삽입이다.
- state 파일이 처리 완료 기사를 기록한다 — 재실행 시 state 에 있는 기사는
  대상에서 빠져 재과금 · 이중 삭제가 없다.
- articles 에 없는 고아 귀속 쌍 (스펙 §1.3) 은 재추출 불가라 실행 초입에
  삭제한다 (멱등 — 재실행 시 0건).
- 신규 후보 등재 내역은 롤백 시 수동 보관 처리 대상이라 (스펙 §5.3)
  Discord 알림과 별개로 JSONL 파일에도 남긴다.

실행 전 `set -a; source .env; set +a` 필수.
    uv run python -m bullet_in.reextract_article_players --limit 5 --dry-run
    uv run python -m bullet_in.reextract_article_players
"""
from __future__ import annotations
import argparse, json, logging, os
from pathlib import Path
import yaml
from sqlalchemy import create_engine, text
from bullet_in import notify, roster
from bullet_in.backfill_article_players import append_state, filter_targets, load_state
from bullet_in.enrich import extract_players_rows
from bullet_in.run import GEMINI_MODEL
from bullet_in.storage.players import PlayerStore

log = logging.getLogger(__name__)

_TARGET_SQL = text(
    "SELECT content_hash, source_id, accept_path, title_original, title_ko, "
    "body_source, body_excerpt, body_ko, url FROM articles WHERE EXISTS (SELECT 1 FROM "
    "article_players ap WHERE ap.content_hash = articles.content_hash) "
    "ORDER BY published_at, id")

_ORPHAN_DELETE_SQL = text(
    "DELETE ap FROM article_players ap LEFT JOIN articles a "
    "ON a.content_hash = ap.content_hash WHERE a.content_hash IS NULL")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--state", type=Path, default=Path("reextract_players_state.txt"))
    ap.add_argument("--candidates-log", type=Path,
                    default=Path("reextract_new_candidates.jsonl"))
    args = ap.parse_args(argv)

    engine = create_engine(os.environ["MARIADB_URL"])
    with engine.connect() as c:
        rows = [dict(r) for r in c.execute(_TARGET_SQL).mappings().all()]
    targets = filter_targets(rows, load_state(args.state))
    if args.limit:
        targets = targets[:args.limit]
    print(f"대상: {len(targets)} 행 (연결 기사 {len(rows)} · state 제외 {len(rows) - len(targets)})")
    if args.dry_run:
        return

    with engine.begin() as c:
        orphans = c.execute(_ORPHAN_DELETE_SQL).rowcount
    print(f"고아 귀속 쌍 삭제: {orphans}")

    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    pstore = PlayerStore(engine)
    by_hash = {r["content_hash"]: r for r in targets}
    new_candidates: list[dict] = []
    glossary = (yaml.safe_load(Path("config/glossary.yaml").read_text())
                or {}).get("replacements", {})

    extracted = extract_players_rows(targets, client, GEMINI_MODEL,
                                     roster=pstore.confirmed_link_roster())
    done = 0
    for h, raw in extracted.items():
        try:
            row = by_hash[h]
            pairs = roster.normalize_pairs(raw, row.get("source_id"), glossary,
                                           row.get("accept_path"))
            with engine.begin() as c:
                c.execute(text("DELETE FROM article_players WHERE content_hash=:h"),
                          {"h": h})
            for cand in roster.record_article_players(pstore, h, pairs, row):
                cand = {**cand, "title": row.get("title_original"),
                        "url": row.get("url")}
                new_candidates.append(cand)
                with args.candidates_log.open("a") as f:
                    f.write(json.dumps(cand, ensure_ascii=False) + "\n")
            append_state(args.state, h)
            done += 1
        except Exception:
            log.warning(
                "재삽입 실패 — 건너뜀 content_hash=%s (state 미기록이라 재실행 시 "
                "재추출로 복원됨)", h, exc_info=True)

    if new_candidates:
        notify.send_alert(**notify.build_candidate_alert(
            new_candidates, run_id="reextract"))
    print(f"처리 {done} / {len(targets)} · 신규 후보 {len(new_candidates)}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
