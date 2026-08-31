"""회차 전후로 주소별 해시를 떠서 비교한다 — 해시가 갈렸는지를 로그와 무관하게 잰다.

로그가 안 뜬 것은 「코드가 안 돌았다」 와 「대상이 없었다」 를 안 가른다.
그래서 회차 전후로 해시를 통째로 떠서 대조한다 (게이트 런북 §4.2).

    uv run python -m bullet_in.hash_snapshot save   # 회차 전
    uv run python -m bullet_in.hash_snapshot diff   # 회차 후

스냅숏은 `~/backups/hash_snapshot.json` 에 남는다 (생성물이라 버전 관리 대상이 아니다).
"""
import json
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

SNAP = Path.home() / "backups" / "hash_snapshot.json"

ORPHAN_SQL = text(
    "SELECT COUNT(*) FROM article_players ap"
    " LEFT JOIN articles a ON a.content_hash = ap.content_hash"
    " WHERE a.content_hash IS NULL")


def read(c) -> dict:
    return {r["url"]: r["content_hash"] for r in
            c.execute(text("SELECT url, content_hash FROM articles")).mappings().all()}


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "save"
    engine = create_engine(os.environ["MARIADB_URL"])
    with engine.connect() as c:
        now = read(c)
        orphans = c.execute(ORPHAN_SQL).scalar()
    if mode == "save":
        SNAP.parent.mkdir(parents=True, exist_ok=True)
        SNAP.write_text(json.dumps({"hashes": now, "orphans": orphans}))
        print("떠 둔 기사 =", len(now), "· 고아 =", orphans)
        return
    before = json.loads(SNAP.read_text())
    old, old_orphans = before["hashes"], before["orphans"]
    rehashed = [(u, old[u], now[u]) for u in now if u in old and old[u] != now[u]]
    print("기사 수 =", len(old), "→", len(now))
    print("고아 =", old_orphans, "→", orphans)
    print("해시가 갈린 기사 =", len(rehashed))
    for u, o, n in rehashed[:10]:
        print(f"    {u}\n      {o[:12]} → {n[:12]}")


if __name__ == "__main__":
    main()
