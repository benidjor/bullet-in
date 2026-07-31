"""후보 선수 확정 CLI — 승격 → 게이트 재검사 → 재번역 → 재렌더 (스펙 §4.3).

실행 전 `set -a; source .env; set +a` 필수 (이 프로젝트는 dotenv 미사용).
    uv run python -m bullet_in.confirm_player --name "Nico Williams" --ko "니코 윌리엄스" \
        --category external --transfer-status in_link
    uv run python -m bullet_in.confirm_player --name "Nico Williams" --ko "니코 윌리엄스" --dry-run
"""
from __future__ import annotations
import argparse
import logging
import os
from bullet_in.enrich import (BODY_AS_TITLE_SOURCES, NAME_MISSING_PREFIX,
                              detect_title_hallucination, detect_title_mistranslation)

log = logging.getLogger(__name__)


def surname_warning(surname: str) -> str | None:
    """두 단어 성 경고 (스펙 §3.3) — 풀네임 근거 가드 축이 조용히 꺼진다."""
    if " " in surname.strip():
        return (f"surname '{surname}' 이 두 단어 — _has_name_context 가드가 근거를 못 찾아 "
                "이 축의 보호 없이 등재된다 (가드의 두 단어 성 지원은 범위 밖)")
    return None


def recheck_titles(rows: list[dict], name_map: dict[str, str]) -> list[str]:
    """저장된 번역 제목을 확장된 사전으로 재검사 — 의심 행 content_hash 목록 (스펙 §4.3).
    축 구성은 finalize_translation 1차 검출에서 사전 무관 축을 뺀 조합이다 (환각 + 역방향 인명 누락 · 라운드업 제외 · 트윗 예외).
    임대 무근거 축은 사전과 무관해 여기서 제외한다 (확정 시 새 선수 무관 행이 재번역되지 않도록)."""
    suspects = []
    for row in rows:
        if not row.get("title_ko"):
            continue
        src_text = " ".join(filter(None, [row.get("title_original"),
                                          row.get("body_source"),
                                          row.get("body_excerpt")]))
        reasons = detect_title_hallucination(row["title_ko"], src_text, name_map)
        if row.get("source_id") != "bbc_gossip":
            rev = detect_title_mistranslation(row["title_ko"], row.get("title_original"),
                                              name_map, src_text)
            # 임대 무근거 제외: 인명 누락 사유만 유지 (사전과 무관한 축 제거)
            rev = [r for r in rev if r.startswith(NAME_MISSING_PREFIX)]
            if row.get("source_id") in BODY_AS_TITLE_SOURCES:
                # BODY_AS_TITLE_SOURCES에서는 인명 누락도 제외
                rev = [r for r in rev if not r.startswith(NAME_MISSING_PREFIX)]
            reasons += rev
        if reasons:
            log.warning("재검사 의심 content_hash=%s 사유=%s", row["content_hash"], reasons)
            suspects.append(row["content_hash"])
    return suspects


def _converge(mart, pstore, engine, targets: set[str]) -> None:
    """대상 행만 재번역 수렴 — 런북 2026-07-19 §3 의 함수 조합을 대상 축소로 재사용."""
    import yaml
    from pathlib import Path
    from google import genai
    from bullet_in.enrich import (enrich_rows, finalize_translation,
                                  partition_by_body_level, partition_generatable,
                                  rewrite_rows_guarded, title_only_rows)
    from bullet_in.run import GEMINI_MODEL
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    glossary = (yaml.safe_load(Path("config/glossary.yaml").read_text())
                or {}).get("replacements", {})
    club_map = (yaml.safe_load(Path("config/club_map.yaml").read_text())
                or {}).get("clubs", {})
    name_map = pstore.gate_name_map()
    for _ in range(3):
        missing = [r for r in mart.rows_missing_translation()
                   if r["content_hash"] in targets]
        if not missing:
            break
        by_hash = {r["content_hash"]: r for r in missing}
        generatable, title_only = partition_generatable(missing)
        rewrite_rows, translate_rows = partition_by_body_level(generatable)
        results = {}
        results.update(enrich_rows(translate_rows, client, GEMINI_MODEL, mode="translate"))
        rewritten, gate_reports = rewrite_rows_guarded(rewrite_rows, client, GEMINI_MODEL)
        results.update(rewritten)
        results.update(title_only_rows(title_only, client, GEMINI_MODEL))
        for h, v in results.items():
            t, s, s3, b, _ = finalize_translation(v, by_hash.get(h, {}),
                                                  glossary, name_map, club_map)
            mart.set_translation(h, t, s, s3, b)
        for h, rep in gate_reports.items():
            mart.set_rewrite_retention(h, rep["retention"])


def _render(engine) -> None:
    """run.py 서빙 경로와 1:1 재렌더 (SERVING_SELECT_SQL import — 런북 스니펫 드리프트 방지)."""
    from sqlalchemy import text
    from bullet_in.run import SERVING_SELECT_SQL
    from bullet_in.score import load_sources
    from bullet_in.credibility import load_registry, journalist_directory, outlet_directory
    from bullet_in.serve.render import write_site
    with engine.connect() as c:
        rows = [dict(r) for r in c.execute(text(SERVING_SELECT_SQL)).mappings().all()]
    write_site(rows, load_sources("config/sources.yaml"), "site",
               directory=journalist_directory("config/credibility.yaml"),
               registry=load_registry("config/credibility.yaml"),
               outlet_dir=outlet_directory("config/credibility.yaml"))
    print(f"site 재생성: {len(rows)} 행")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="players.full_name")
    ap.add_argument("--ko", required=True, help="검출용 한글 표기 (사람 확정 값)")
    ap.add_argument("--category", choices=["squad", "manager", "external"])
    ap.add_argument("--transfer-status", dest="transfer_status",
                    choices=["none", "in_link", "in_done", "out_link", "out_done",
                             "link_dropped", "other_club", "loan_in", "loan_out"])
    ap.add_argument("--club")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    from sqlalchemy import create_engine
    from bullet_in.storage.mariadb import MartStore
    from bullet_in.storage.players import PlayerStore
    engine = create_engine(os.environ["MARIADB_URL"])
    mart, pstore = MartStore(engine), PlayerStore(engine)
    player = pstore.get_player(args.name)
    if player is None:
        print(f"선수 없음: {args.name}")
        return 1
    if (w := surname_warning(player["surname"])):
        log.warning(w)

    holder = pstore.ko_name_holder(args.ko)
    if holder is not None and holder != player["id"]:
        print(f"ko_name 충돌: '{args.ko}' 는 이미 다른 선수 (id={holder}) 의 확정 표기")
        return 1

    hashes = pstore.articles_for(player["id"])
    if args.dry_run:
        trial_map = {**pstore.gate_name_map(), args.ko: player["surname"]}
        suspects = recheck_titles(mart.rows_for_hashes(hashes), trial_map)
        print(f"[dry-run] 등장 기사 {len(hashes)} · 재번역 대상 {len(suspects)}")
        return 0

    pstore.confirm(player["id"], ko_name=args.ko, category=args.category,
                   transfer_status=args.transfer_status, club=args.club)
    suspects = recheck_titles(mart.rows_for_hashes(hashes),
                              pstore.gate_name_map())
    remaining = 0
    if suspects:
        mart.clear_translation(suspects)
        _converge(mart, pstore, engine, set(suspects))
        targets = set(suspects)
        remaining = sum(1 for r in mart.rows_missing_translation()
                        if r["content_hash"] in targets)
        if remaining:
            log.warning("재번역 잔존 %d건 — 429 등으로 중단, 다음 회차가 수렴 (원문 제목 폴백으로 렌더됨)",
                        remaining)
    _render(engine)
    print(f"확정: {args.name} → {args.ko} · 등장 기사 {len(hashes)} · 재번역 {len(suspects)} (잔존 {remaining})")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(main())
