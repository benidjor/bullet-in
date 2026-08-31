"""고아 귀속 삭제 전 백업 — 어느 기사도 안 가리키는 article_players 행을 JSON 으로 뜬다.

읽기 전용이다. 고아를 지우는 절차 (게이트 런북 §4.3) 가 이것을 먼저 부르도록 되어 있다.
해시는 두 값 사이를 왕복할 수 있어서, 지운 귀속이 나중에 되살릴 재료가 된다.

    uv run python -m bullet_in.backup_orphans

결과는 `~/backups/orphan_attributions_<시각>.json` 에 남는다 (생성물).
"""
import json
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text

SQL = text(
    "SELECT ap.content_hash, ap.player_id, ap.role, ap.stage, ap.extracted_at,"
    " p.ko_name, p.full_name"
    " FROM article_players ap"
    " LEFT JOIN articles a ON a.content_hash = ap.content_hash"
    " LEFT JOIN players p ON p.id = ap.player_id"
    " WHERE a.content_hash IS NULL"
    " ORDER BY ap.extracted_at")


def main() -> None:
    engine = create_engine(os.environ["MARIADB_URL"])
    with engine.connect() as c:
        rows = [dict(r) for r in c.execute(SQL).mappings().all()]
    for r in rows:
        if isinstance(r.get("extracted_at"), datetime):
            r["extracted_at"] = r["extracted_at"].isoformat()
    out_dir = Path.home() / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"orphan_attributions_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    print("백업 행수 =", len(rows))
    print("고유 기사 해시 =", len({r["content_hash"] for r in rows}))
    print("파일 =", out)


if __name__ == "__main__":
    main()
