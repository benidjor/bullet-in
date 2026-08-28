"""선수 카드 사진을 손으로 고정한다 (2026-08-28 사용자 확정).

    uv run python -m bullet_in.set_player_photo --list
    uv run python -m bullet_in.set_player_photo --name "Alex Scott" --url https://…
    uv run python -m bullet_in.set_player_photo --name "Alex Scott" --clear

색인 카드의 사진은 기본적으로 그 선수의 가장 최근 기사에서 자동으로 고른다.
새 기사가 들어오면 갈아타므로 회차마다 얼굴이 바뀐다 (30일에 177회 · 선수당 3.2회
실측). 대개는 그 편이 낫지만, 주역이 여럿인 기사에서 온 사진은 그 선수가 안 찍혀
있을 수 있다 (실측 55장 중 19장). 그런 몇 명만 여기서 박는다.

박고 나면 자동 선택이 그 선수를 건드리지 않고, 다른 선수도 같은 사진을 못 가져간다.
**화면 반영은 재렌더 시점이다** — 다음 정기 회차가 알아서 하고, 급하면 `--render`.
"""
import argparse
import logging
import os

log = logging.getLogger(__name__)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", help="players.full_name (예: \"Alex Scott\")")
    ap.add_argument("--url", help="박을 사진 주소")
    ap.add_argument("--clear", action="store_true", help="고정을 풀어 자동 선택으로")
    ap.add_argument("--list", action="store_true", dest="listing",
                    help="지금 고정된 것 전부")
    ap.add_argument("--render", action="store_true",
                    help="바로 site 재생성 (안 주면 다음 정기 회차가 반영)")
    args = ap.parse_args(argv)

    from sqlalchemy import create_engine
    from bullet_in.storage.players import PlayerStore
    engine = create_engine(os.environ["MARIADB_URL"])
    store = PlayerStore(engine)

    if args.listing:
        pinned = store.pinned_photos()
        print(f"고정된 사진 {len(pinned)}건")
        for p in pinned:
            print(f"  {(p['ko_name'] or p['full_name']):20s} {p['photo_url']}")
        return 0

    if not args.name:
        print("--name 이 필요하다 (--list 는 예외)")
        return 1
    if not args.url and not args.clear:
        print("--url 이나 --clear 중 하나가 필요하다")
        return 1

    player = store.get_player(args.name)
    if player is None:
        print(f"선수 없음: {args.name}")
        return 1

    store.set_photo(player["id"], None if args.clear else args.url)
    who = player.get("ko_name") or player["full_name"]
    print(f"{'고정 해제' if args.clear else '고정'}: {who} → {args.url or '(자동 선택)'}")

    if args.render:
        from bullet_in.confirm_player import _render
        _render(engine)
    else:
        print("화면 반영은 다음 정기 회차의 재렌더 (급하면 --render)")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(main())
