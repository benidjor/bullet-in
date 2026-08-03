"""게시글 본문 기반 행의 소급 재작성 — 정보 단위 프롬프트 · 게이트 4축 재적용.

번역 4필드를 NULL 로 비우고 회차를 기다리지 않는다.
비우는 창에 재렌더가 겹치면 빈 페이지가 공개되기 때문이다 (2026-08-02 실사고).
행별로 계산을 마친 뒤 갱신하므로 NULL 창이 없다.
"""
from __future__ import annotations
import argparse, logging, os
from pathlib import Path

import yaml
from google import genai
from sqlalchemy import create_engine

from bullet_in.enrich import finalize_translation, rewrite_rows_guarded
from bullet_in.storage.mariadb import MartStore
from bullet_in.storage.players import PlayerStore

log = logging.getLogger(__name__)


def run(mart, client, model: str, *, glossary: dict, name_map: dict,
        club_map: dict, limit: int | None = None, offset: int = 0,
        dry_run: bool = False) -> tuple[int, int]:
    """대상 행을 재작성해 저장한다 → (저장 건수, 이번 실행 대상 건수).

    대상 전체를 한 번에 넘기는 이유는 429 중단이 회차 단위로 걸리게 하기
    위해서다 — 행별로 부르면 속도 한도에 걸린 뒤에도 남은 행을 계속 두드린다.
    중단 시점까지의 결과는 그대로 반환되므로 잃는 것은 없다.

    재작성은 멱등이 아니다 (표현이 매번 달라진다). 그리고 대상 조건이 저장
    뒤에도 참이라 처리한 행이 대상에서 빠지지 않는다 — 나눠 돌 때는 --limit
    과 --offset 을 함께 써서 구간을 옮겨야 한다. --limit 만 반복하면 같은
    앞쪽 구간을 계속 다시 만든다.

    DB 쓰기는 재작성과 후처리가 모두 끝난 뒤에만 일어난다. 번역 필드를 비우는
    창이 생기면 그 사이 재렌더가 빈 페이지를 공개한다 (2026-08-02 실사고).
    """
    rows = mart.rows_rewritten()
    total = len(rows)
    rows = rows[offset:]
    if limit is not None:
        rows = rows[:limit]
    log.info("소급 재작성 대상 %d건 · 이번 실행 %d건 (건너뜀 %d)",
             total, len(rows), offset)
    if not rows:
        return 0, 0
    results, reports = rewrite_rows_guarded(
        rows, client, model, name_map=name_map, club_map=club_map)
    done = 0
    for r in rows:
        h = r["content_hash"]
        v = results.get(h)
        if v is None:
            log.warning("재작성 실패 — 건너뜀 content_hash=%s", h)
            continue
        title_ko, s_ko, s3_ko, body_ko, _ = finalize_translation(
            v, r, glossary, name_map, club_map)
        if dry_run:
            log.info("[dry-run] %s 제목=%s 잔존율=%.3f",
                     h[:8], title_ko, reports[h]["retention"])
            done += 1
            continue
        mart.set_translation(h, title_ko, s_ko, s3_ko, body_ko)
        mart.set_rewrite_retention(h, reports[h]["retention"])
        done += 1
    return done, len(rows)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="처리할 행 수 상한")
    ap.add_argument("--offset", type=int, default=0,
                    help="앞에서 건너뛸 행 수 (--limit 과 함께 구간을 옮긴다)")
    ap.add_argument("--dry-run", action="store_true", help="저장 없이 결과만 출력")
    a = ap.parse_args()

    engine = create_engine(os.environ["MARIADB_URL"])
    mart = MartStore(engine)
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    from bullet_in.run import GEMINI_MODEL

    def _cfg(path: str, key: str) -> dict:
        return (yaml.safe_load(Path(path).read_text()) or {}).get(key, {})

    name_map = PlayerStore(engine).gate_name_map()
    if not name_map:
        log.warning("players 사전이 비어 있음 — 인명 게이트가 꺼진 채 소급 재작성이 돈다")

    done, total = run(mart, client, GEMINI_MODEL,
                      glossary=_cfg("config/glossary.yaml", "replacements"),
                      name_map=name_map,
                      club_map=_cfg("config/club_map.yaml", "clubs"),
                      limit=a.limit, offset=a.offset, dry_run=a.dry_run)
    print(f"소급 재작성: {done} / {total} 행")


if __name__ == "__main__":
    main()
