"""안건 2η 재측정 — 배포 뒤에 재작성된 행만 잰다 (읽기 전용).

**재고를 통째로 재면 안 된다.** 기준선 18.1% 는 배포 전 재고 166건을 잰 값이고,
재큐는 앞으로 재작성되는 행에만 든다. 기존 166건은 회차가 다시 안 보므로
재고를 재면 거의 같은 값이 나오고 「효과 없음」 이라는 틀린 결론이 난다.

가르는 축은 **배포 전 해시 목록**이다.
`updated_at` 은 어떤 갱신에도 움직여서 (`ON UPDATE CURRENT_TIMESTAMP`) 못 쓴다.

    uv run python -m bullet_in.remeasure_rewrite [기준선.json]

기준선을 안 주면 `docs/superpowers/specs/assets/2026-08-30-rewrite-baseline.json` 을 쓴다.
그 파일에 모집단 · 판정 술어 · 예측치가 함께 들어 있어 실험 정의 노릇을 한다.
"""
import json
import os
import sys
from pathlib import Path

import yaml
from sqlalchemy import create_engine, text

from bullet_in.enrich import POST_BODY_LEVEL, detect_club_injection, detect_name_injection
from bullet_in.fidelity import RETENTION_THRESHOLD, gate_verdict
from bullet_in.storage.players import PlayerStore

DEFAULT_BASELINE = Path("docs/superpowers/specs/assets/2026-08-30-rewrite-baseline.json")


def missing_of(r, name_map, club_map):
    src = r.get("body_source") or r.get("body_excerpt") or ""
    g = " ".join(filter(None, (r.get("title_original"), src)))
    v = gate_verdict(src, r.get("body_ko") or "", RETENTION_THRESHOLD, grounding=g)
    n = detect_name_injection(r, g, name_map)
    cl = detect_club_injection(r, g, club_map)
    residual = bool(v["missing"] or v["extra"] or v["quotes"] or n or cl
                    or v["retention"] > RETENTION_THRESHOLD)
    return v["missing"], residual


def report(label, rs, name_map, club_map):
    if not rs:
        print(f"{label:<26} 0건 — 아직 잴 표본이 없다")
        return
    miss = [r for r in rs if missing_of(r, name_map, club_map)[0]]
    res = [r for r in rs if missing_of(r, name_map, club_map)[1]]
    print(f"{label:<26} {len(rs):>4}건 · 수치 누락 {len(miss):>3}건 "
          f"({len(miss)/len(rs):.1%}) · 잔존 전체 {len(res)}건")


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_BASELINE
    base = json.loads(path.read_text(encoding="utf-8"))
    before = set(base["before_hashes"])

    eng = create_engine(os.environ["MARIADB_URL"])
    with eng.connect() as c:
        rows = [dict(r) for r in c.execute(text(
            "SELECT content_hash,title_original,body_source,body_excerpt,body_ko,"
            "title_ko,summary_ko,summary3_ko FROM articles "
            "WHERE body_level=:lv AND title_ko IS NOT NULL"),
            {"lv": POST_BODY_LEVEL}).mappings().all()]
        name_map = PlayerStore(eng).gate_name_map()
    club_map = (yaml.safe_load(Path("config/club_map.yaml").read_text(encoding="utf-8"))
                or {}).get("clubs", {})

    new = [r for r in rows if r["content_hash"] not in before]
    old = [r for r in rows if r["content_hash"] in before]

    print(f"기준선 (2026-08-30 배포 전) : {base['baseline']['population']}건 중 "
          f"{base['baseline']['missing_rows']}건 = {base['baseline']['missing_pct']}%")
    print(f"실험 예측                   : {base['experiment_prediction_pct']}%")
    print()
    report("배포 뒤 새로 재작성된 행", new, name_map, club_map)      # 재측정 대상
    report("배포 전부터 있던 행 (참고)", old, name_map, club_map)     # 대조군
    print()
    print("판정 — 위 줄의 비율을 18.1% 와 댄다. 아래 줄은 대조군이라 그대로여야 정상이다.")
    print("표본이 20건 아래면 아직 이르다 (회차당 재작성 행이 적다).")


if __name__ == "__main__":
    main()
