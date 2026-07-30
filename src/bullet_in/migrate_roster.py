"""name_map 39명 → players 이관 CLI (멱등 · 스펙 §7).

실행 전 `set -a; source .env; set +a` 필수 (이 프로젝트는 dotenv 미사용).
    uv run python -m bullet_in.migrate_roster
"""
from __future__ import annotations
import logging, os
from sqlalchemy import create_engine
from bullet_in.roster_seed import ROSTER
from bullet_in.storage.mariadb import MartStore
from bullet_in.storage.players import PlayerStore


def main() -> None:
    engine = create_engine(os.environ["MARIADB_URL"])
    MartStore(engine).ensure_schema()
    store = PlayerStore(engine)
    inserted = store.seed(ROSTER)
    print(f"이관: 신규 {inserted} / 명단 {len(ROSTER)} · 사전 {len(store.gate_name_map())}명")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
