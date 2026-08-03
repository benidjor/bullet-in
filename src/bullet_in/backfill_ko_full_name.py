"""선수 한글 풀네임 1회 적재 — players.ko_full_name.

표시용 컬럼이라 ko_name · ko_candidate 는 건드리지 않는다.
값을 정할 수 없는 행은 비워 두고, 화면이 ko_name → full_name 으로 떨어진다.
"""
from __future__ import annotations
import argparse
import os
from sqlalchemy import create_engine, text

# 사용자 승인 표기 (2026-08-03) — ko_candidate 규칙으로는 나오지 않는 값만 담는다.
# 앞의 22건은 새로 승인받은 표기, 마지막 Kyran Thompson 은 규칙이 후보를 고르는 것을
# 막기 위한 예외다 (ko_name 쪽이 사용자 확정 값).
APPROVED: dict[str, str] = {
    "Anthony Gordon": "앤서니 고든",
    "Axel Donczew": "악셀 돈체프",
    "Bradley Barcola": "브래들리 바르콜라",
    "Bruno Guimaraes": "브루노 기마랑이스",
    "Charles Sagoe Jr": "찰스 세이고 주니어",
    "Christos Tzolis": "크리스토스 촐리스",
    "Eberechi Eze": "에베레치 에제",
    "Eli Junior Kroupi": "엘리 주니오르 크루피",
    "Elliot Anderson": "엘리엇 앤더슨",
    "Ezri Konsa": "에즈리 콘사",
    "Illan Meslier": "일란 멜리에",
    "Jacobo Ramon": "하코보 라몬",
    "Jakub Kiwior": "야쿠프 키비오르",
    "Julian Alvarez": "훌리안 알바레스",
    "Leandro Trossard": "레안드로 트로사르",
    "Marcus Rashford": "마커스 래시포드",
    "Morgan Rogers": "모건 로저스",
    "Noni Madueke": "노니 마두에케",
    "Ollie Watkins": "올리 왓킨스",
    "Piero Hincapie": "피에로 인카피에",
    "Sandro Tonali": "산드로 토날리",
    "Viktor Gyokeres": "빅토르 요케레스",
    "Kyran Thompson": "키란 톰슨",
}


def resolve(full_name: str, ko_name: str | None,
            ko_candidate: str | None) -> str | None:
    """적재할 한글 풀네임. 정할 수 없으면 None.

    승인 표기가 최우선이고, 그 다음은 ko_name 보다 긴 ko_candidate 다.
    길이 조건이 없으면 성만 담긴 후보 (Jon Martin 의 '마르틴') 가 풀네임을 밀어낸다.
    """
    if full_name in APPROVED:
        return APPROVED[full_name]
    if not ko_candidate:
        return None
    if ko_name is None:
        return ko_candidate
    return ko_candidate if len(ko_candidate) > len(ko_name) else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    engine = create_engine(os.environ["MARIADB_URL"])
    with engine.connect() as c:
        rows = [dict(r) for r in c.execute(text(
            "SELECT id, full_name, ko_name, ko_candidate, ko_full_name "
            "FROM players")).mappings().all()]
    updates = []
    for r in rows:
        value = resolve(r["full_name"], r["ko_name"], r["ko_candidate"])
        if value and value != r["ko_full_name"]:
            updates.append({"id": r["id"], "v": value})
    print(f"대상 {len(rows)}행 · 적재 {len(updates)}행")
    if args.dry_run:
        for u in updates[:10]:
            print(" ", u)
        return
    if updates:
        with engine.begin() as c:
            c.execute(text("UPDATE players SET ko_full_name=:v WHERE id=:id"),
                      updates)
    print("적재 완료")


if __name__ == "__main__":
    main()
