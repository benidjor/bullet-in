from __future__ import annotations
import argparse, asyncio, json, logging, os, time, uuid, yaml
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from pymongo import MongoClient
from sqlalchemy import create_engine, text
from google import genai
from bullet_in.adapters.factory import build_adapters
from bullet_in.ingest import gather_all
from bullet_in.adapters.fmkorea import is_arsenal_relevant
from bullet_in.canonical import content_hash, canonical_url
from bullet_in.pipeline import to_articles
from bullet_in.score import load_sources
from bullet_in.credibility import load_registry, journalist_directory, outlet_directory
from bullet_in.storage.mongo import RawStore
from bullet_in.storage.mariadb import MartStore
from bullet_in.storage.players import PlayerStore
from bullet_in.enrich import (enrich_rows, classify_stage_rows, resummarize_rows,
                              apply_glossary, finalize_translation,
                              retranslation_summary)
from bullet_in.tone import select_tone_backfill
from bullet_in import transfer_stage
from bullet_in import roster
from bullet_in.serve.render import write_site, write_ops, unmatched_articles
from bullet_in.quality import (success_rate, volume_anomalies, evaluate_freshness,
                               evaluate_coverage, candidate_cliffs, filter_miss_suspects,
                               roster_axis_staleness)
from bullet_in import notify

GEMINI_MODEL = "gemini-3.1-flash-lite"

# 서빙 렌더 입력 — write_site 가 읽는 컬럼 전부. 런북의 사이트 재생성 절차도 이 상수를
# import 해서 쓴다 (스니펫에 컬럼을 옮겨 적으면 서빙 코드와 어긋난다 — 실제 4회 재발,
# docs/troubleshooting/2026-07-19-runbook-snippet-logic-drift.md).
SERVING_SELECT_SQL = (
    "SELECT content_hash,url,source_id,title_original,title_ko,summary_ko,"
    "summary3_ko,body_ko,body_source,image_url,images_json,outlet,journalist,team,"
    "transfer_stage,transfer_direction,tier,confidence_score,published_at,"
    "published_precision,fetched_at,"
    # 링크 선수 배지 입력 (B안 2026-08-01 · 소속 제외 · 비이적 한정 · 이름 공급 2026-08-02)
    # — 비이적 기사 (other) 이면서 아스날 소속 (squad · manager · director) 확정 인물
    # 연결이 없는 글에 한해, 연결된 영입 링크 선수의 ko_name 을 id 순으로 넘긴다.
    # 이적 기사는 링크되어 있다는 사실 자체가 맥락이고, 소속 인물이 함께 연결된 글은
    # 그 자체로 아스날 글이라 배지가 설명할 게 없다. 연결이 없으면 NULL — 배지도 없다.
    "CASE WHEN articles.transfer_stage='other' "
    "AND NOT EXISTS(SELECT 1 FROM article_players ap2 JOIN players p2 ON p2.id=ap2.player_id "
    "WHERE ap2.content_hash=articles.content_hash AND p2.status='confirmed' "
    "AND p2.category IN ('squad','manager','director')) "
    "THEN (SELECT GROUP_CONCAT(p.ko_name ORDER BY p.id SEPARATOR '|') "
    "FROM article_players ap JOIN players p ON p.id=ap.player_id "
    "WHERE ap.content_hash=articles.content_hash AND p.status='confirmed' "
    "AND p.transfer_status='in_link') END AS linked_players "
    "FROM articles")

# started_at 은 Python UTC 바인딩 · finished_at 은 UTC_TIMESTAMP() — 세션 TZ 무관 (spec §5)
RUN_INSERT_SQL = (
    "INSERT INTO pipeline_runs (run_id,dag_run_id,started_at,finished_at,"
    "duration_sec,fetch_duration_sec,source_counts,candidate_counts,new_count,"
    "dup_count,blocked_count,error_count,success_rate) "
    "VALUES (:rid,:drid,:started,UTC_TIMESTAMP(),:dur,:fetch,:counts,:cands,"
    ":new,:dup,:blocked,:err,:sr)")

# 후보 절벽 판정 재료 (차단 알림 스펙 §3.1): [0] 이 직전 회차 · 나머지는 알림 표시용.
# 이번 회차 행은 파이프라인 마지막에 적재되므로 이 시점의 최신 행이 곧 직전 회차다.
CANDIDATE_HISTORY_SQL = ("SELECT candidate_counts FROM pipeline_runs "
                         "ORDER BY started_at DESC LIMIT 5")


# 서빙 제외 판정에 쓰는 확정 선수 연결 — 추출이 붙인 기사만 남는다.
# 역할이 언급인 귀속은 근거로 안 쓴다: 스치는 언급 하나로 아스날이 한 글자도 안 나오는
# 기사가 남아 있었다 (실측 2건 — 서머빌의 알 힐랄 이적 · 첼시의 차바리아 영입).
# 미기입 (NULL) 은 옛 판정대로 남긴다 — 값을 만드는 쪽이 응답을 못 내거나 회차가 끊기면
# 상시로 다시 생기는데, 그때 언급으로 읽으면 본인 기사가 화면에서 조용히 사라진다
# (선수 목록의 전환 규칙과 같은 취급 · docs/runbook/2026-08-12-serving-rule-swap-with-unfilled-field.md).
LINKED_HASHES_SQL = ("SELECT DISTINCT ap.content_hash FROM article_players ap "
                     "JOIN players p ON p.id = ap.player_id "
                     "WHERE p.status = 'confirmed' "
                     "AND (ap.role IS NULL OR ap.role <> 'mention')")

# 성 매칭 최소 길이 — 두 글자 성 (고든 · 스콧) 은 다른 낱말에 섞여 오탐한다.
SURNAME_MIN_LEN = 3


def roster_surnames(player_names) -> set[str]:
    """명단 이름에서 한글 성만 추린다 — 두 어절 이상 이름의 마지막 어절.

    한 어절 이름 (케파 · 누사) 은 이미 풀네임 매칭 대상이라 뺀다.
    성이 필요한 이유는 게시글 제목이 성만 쓰는 일이 잦기 때문이다
    (`[레퀴프]디오망데와 PSG의 계약…` — 명단은 `얀 디오망데`)."""
    out = set()
    for n in player_names:
        parts = (n or "").split()
        if len(parts) > 1 and len(parts[-1]) >= SURNAME_MIN_LEN:
            out.add(parts[-1])
    return out


def _serving_kept(row: dict, terms, names, surnames, linked) -> bool:
    """fmkorea 글을 화면에 남길지 — 네 신호 중 하나라도 걸리면 남긴다."""
    title_o = row.get("title_original") or ""
    title_k = row.get("title_ko") or ""
    # ① 수집 때와 같은 판정 (구단 키워드는 제목 · 본문, 풀네임은 제목)
    if is_arsenal_relevant(title_o, row.get("body_ko") or "", terms, names):
        return True
    # ② 번역 제목 — 번역이 아스날 맥락이나 풀네임을 복원하는 경우가 있다
    if is_arsenal_relevant(title_k, "", terms, names):
        return True
    # ③ 제목이 성만 쓴 경우 (동명이인 포함) — 어느 쪽이든 명단 선수 기사다
    if surnames and is_arsenal_relevant(f"{title_o} {title_k}", "", [], surnames):
        return True
    # ④ 추출이 확정 선수를 붙인 기사 — 언급뿐인 귀속은 위 SQL 이 뺀다 (미기입은 남긴다)
    return row.get("content_hash") in linked


def serving_rows(rows: list[dict], *, relevance_terms, player_names,
                 linked: set[str] | None = None) -> tuple[list[dict], int]:
    """서빙 목록에서 fmkorea 무관 글을 뺀다 — 렌더 입력만 거르고 DB 는 그대로 둔다.

    수집 단계 무관 글 필터 (워치리스트 스펙 §3.2) 도입 전에 적재된 타 구단 이적 기사가
    화면에 남아 있다 (2026-08-04 실측 10건 · 전건 노출 · 대부분 온스테인 키워드 유입).
    서빙 판정은 수집보다 관대하다 — 적재 뒤에야 생기는 번역 제목과 확정 선수 연결을
    함께 볼 수 있기 때문이다. 본문 이름 매칭은 쓰지 않는다 (실측 결과 스치는 언급으로
    타 구단 기사 4건이 딸려 왔다).
    fmkorea 외 소스는 아스날 전용 피드라 대상이 아니다."""
    surnames = roster_surnames(player_names)
    linked = linked or set()
    keep, hidden = [], 0
    for r in rows:
        if r.get("source_id") != "fmkorea" or _serving_kept(
                r, relevance_terms, player_names, surnames, linked):
            keep.append(r)
        else:
            hidden += 1
    return keep, hidden


def cliff_alert_payload(candidate_counts: dict, history: list[dict], *,
                        adapters, sources: dict, success_rate: float,
                        run_id: str) -> dict | None:
    """절벽이 있으면 알림 payload · 없으면 None (차단 알림 스펙 §3.1 · §5.1)."""
    if not history:
        return None
    cliffs = candidate_cliffs(candidate_counts, history[0])
    if not cliffs:
        return None
    failure_codes = {a.source_id: dict(getattr(a, "search_failure_codes", {}) or {})
                     for a in adapters}
    return notify.build_cliff_alert(
        cliffs, history=history, sources=sources,
        failure_codes=failure_codes, success_rate=success_rate, run_id=run_id)


async def main(concurrency: int):
    run_id = str(uuid.uuid4())
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
    sources = load_sources("config/sources.yaml")
    registry = load_registry("config/credibility.yaml")

    engine = create_engine(os.environ["MARIADB_URL"])
    mart = MartStore(engine)
    mart.ensure_schema()
    pstore = PlayerStore(engine)
    # fmkorea 무관 글 필터 인정 집합 주입 (워치리스트 스펙 §3.2) — 배치와 동일 집합
    adapters = build_adapters(cfg, fmkorea_player_names=pstore.confirmed_ko_names())

    t0 = time.perf_counter()
    started_at_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    raw, errors = await gather_all(adapters, concurrency=concurrency)
    fetch_sec = round(time.perf_counter() - t0, 2)

    # 소스별 후보 계수 (dedup 전) — 신규 적재만 세는 source_counts 와 달리
    # 수집 끊김 (후보 0) 과 전부 기존 기사 (후보 N · 신규 0) 를 가른다 (SLO-5 오진 수정)
    candidate_counts = dict(Counter(it.source_id for it in raw))
    logging.getLogger(__name__).info(
        "소스별 후보 계수: %s", json.dumps(candidate_counts, ensure_ascii=False))

    # 수집 후보 절벽 알림 (차단 알림 스펙 §3.1): 번역 · 렌더를 기다리지 않고 먼저 보낸다.
    # 판정 · 발송 실패가 회차를 멈추지 않게 감싼다 (ops 뷰 생성과 같은 격리).
    try:
        with engine.connect() as c:
            cand_hist = [json.loads(s) for s in
                         c.execute(text(CANDIDATE_HISTORY_SQL)).scalars().all() if s]
        payload = cliff_alert_payload(
            candidate_counts, cand_hist, adapters=adapters, sources=sources,
            success_rate=success_rate(len(adapters), len(errors)), run_id=run_id)
        if payload:
            notify.send_alert(**payload)
    except Exception:
        logging.getLogger(__name__).warning(
            "후보 절벽 판정 실패 — 이번 회차 건너뜀 (수집에는 영향 없음)", exc_info=True)

    # 공홈 커버리지 감시: 창 후보 · Men 퍼널 불변식 위반 시 알림 (spec 2026-07-24 §5)
    for a in adapters:
        breaches = evaluate_coverage(getattr(a, "coverage", {}) or {})
        if breaches:
            notify.send_alert(**notify.build_coverage_alert(
                breaches, a.coverage, run_id=run_id))

    # 채택 누락 관측 (스펙 2026-08-07 §3.3): 이적 관련 제목인데 비채택이면 알림만 —
    # 수집 · 필터 판단은 바꾸지 않는다 (제품 결정 대기). 판정 · 발송 실패가 회차를
    # 멈추지 않게 감싼다 (후보 절벽 알림과 같은 격리 패턴).
    try:
        for a in adapters:
            rejects = getattr(a, "men_news_rejects", None) or []
            suspects = filter_miss_suspects(rejects, datetime.now(timezone.utc))
            if suspects:
                notify.send_alert(**notify.build_filter_miss_alert(suspects, run_id=run_id))
    except Exception:
        logging.getLogger(__name__).warning(
            "관측 알림 판정 실패 — 이번 회차 건너뜀 (수집에는 영향 없음)", exc_info=True)

    for it in raw:
        it.content_hash = content_hash(
            it.raw_payload.get("title") or it.raw_payload.get("text") or "",
            canonical_url(it.url))

    mongo = MongoClient(os.environ["MONGO_URI"])[os.environ.get("MONGO_DB", "bulletin")]
    RawStore(mongo).insert_many(raw)

    arts, stats = to_articles(raw, sources, seen=mart.seen_map(), registry=registry)
    logging.getLogger(__name__).info(
        "drop 집계 — 동일 내용 생략 %d · 기존 기사 유지 %d · 여자팀 %d · 기자 allowlist %d",
        stats["dup_count"], stats["blocked_count"], stats["women_count"],
        stats["author_drop_count"])
    mart.upsert(arts)

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    from bullet_in.enrich import (partition_by_body_level, partition_generatable,
                                  rewrite_rows_guarded, title_only_rows)
    glossary = (yaml.safe_load(Path("config/glossary.yaml").read_text())
                or {}).get("replacements", {})
    name_map = pstore.gate_name_map()
    if not name_map:
        logging.getLogger(__name__).warning(
            "players 사전이 비어 있음 — migrate_roster 미실행이면 인명 게이트가 꺼진 채 돈다")
    club_map = (yaml.safe_load(Path("config/club_map.yaml").read_text())
                or {}).get("clubs", {})
    missing = mart.rows_missing_translation()
    generatable, title_only = partition_generatable(missing)
    if title_only:
        logging.getLogger(__name__).warning(
            "재료 없음 — 제목만 생성 %d건 (본문 · 요약 미생성)", len(title_only))
    rewrite_rows, translate_rows = partition_by_body_level(generatable)
    # 확정 링크 명단 — 아스날 미언급 기사의 판단 근거 (스펙 §6.5). 재추출 경로가 쓰던
    # 재료를 수집 시점 프롬프트에도 준다. 회차마다 한 번 만든다.
    roster_material = pstore.confirmed_link_roster()
    results: dict[str, dict] = {}
    results.update(enrich_rows(translate_rows, client, GEMINI_MODEL,
                               mode="translate", roster=roster_material))
    rewritten, gate_reports = rewrite_rows_guarded(
        rewrite_rows, client, GEMINI_MODEL, name_map=name_map, club_map=club_map,
        roster=roster_material)
    results.update(rewritten)
    results.update(title_only_rows(title_only, client, GEMINI_MODEL))

    by_hash = {r["content_hash"]: r for r in missing}
    finals = {h: finalize_translation(v, by_hash.get(h, {}), glossary, name_map, club_map)
              for h, v in results.items()}

    # 추출 쌍 반영 (스펙 §4.1 · §4.2): 저장은 번역 채택 여부와 무관 — 원문 근거 추출이고
    # 재시도 회차의 재추출은 upsert 멱등이다.
    # finalize_translation 뒤에 둔다 — 역할 규칙이 제목 · 소제목을 재료로 쓰는데,
    # 재추출 경로는 저장된 본문을 읽으므로 여기서도 저장될 문자열 (표기 교정 사전
    # 적용분) 을 넘겨야 두 경로의 판정이 갈리지 않는다.
    try:
        new_candidates: list[dict] = []
        for h, v in results.items():
            row = by_hash.get(h, {})
            pairs = roster.normalize_pairs(v.get("players"), row.get("source_id"),
                                           glossary)
            title_ko, _, _, body_ko, _ = finals[h]
            article = {"title_ko": title_ko,
                       "title_original": row.get("title_original"),
                       "body_ko": body_ko}
            for cand in roster.record_article_players(pstore, h, pairs, article):
                new_candidates.append({**cand, "title": row.get("title_original"),
                                       "url": row.get("url")})
        if new_candidates:
            notify.send_alert(**notify.build_candidate_alert(new_candidates, run_id=run_id))
    except Exception:
        logging.getLogger(__name__).warning(
            "추출 쌍 저장 실패 — 이번 회차 건너뜀 (번역 저장에는 영향 없음)", exc_info=True)

    # 명단 축 낡음 관측 (스펙 2026-08-10): 이번 회차에 만진 기사의 귀속이 확정 선수의
    # 이적 축 값과 어긋나면 알림만 보낸다 — 값 판단은 사람 몫 (명단 런북 §6).
    # 판정 · 발송 실패가 회차를 멈추지 않게 감싼다 (관측 알림 공통 격리).
    try:
        if results:
            cycle_rows = pstore.cycle_pairs(list(results))
            recent = pstore.recent_stage_counts(
                sorted({r["player_id"] for r in cycle_rows}))
            cases = roster_axis_staleness(cycle_rows, recent)
            if cases:
                notify.send_alert(**notify.build_roster_staleness_alert(
                    cases, run_id=run_id))
    except Exception:
        logging.getLogger(__name__).warning(
            "명단 축 관측 판정 실패 — 이번 회차 건너뜀 (수집 · 번역에는 영향 없음)",
            exc_info=True)

    for h, (title_ko, s_ko, s3_ko, body_ko, _) in finals.items():
        mart.set_translation(h, title_ko, s_ko, s3_ko, body_ko)
    for h, rep in gate_reports.items():
        mart.set_rewrite_retention(h, rep["retention"])
    if finals:  # 관측 ②: 재번역 큐 추이 한 줄 (신규 진입 · 채택 · 해소)
        logging.getLogger(__name__).warning(
            "재번역 큐 요약: 신규 %d · 채택 %d · 해소 %d",
            *retranslation_summary(finals, by_hash))

    # 분류 패스 (방향 축 스펙 §4): 규칙 경로 2형태 — 가십은 stage · direction 둘 다
    # 고정 (LLM 제외), 공홈은 stage 만 고정하고 방향은 LLM 배치에서 받는다 (stage 응답은 버림)
    llm_rows = []
    stage_ruled: dict[str, str] = {}
    for r in mart.rows_missing_stage():
        stage_fixed, direction_fixed = transfer_stage.rule_stage(r["source_id"])
        if stage_fixed and direction_fixed:
            mart.set_stage(r["content_hash"], stage_fixed, direction_fixed)
            continue
        if stage_fixed:
            stage_ruled[r["content_hash"]] = stage_fixed
        llm_rows.append(r)
    for h, (stage, direction) in classify_stage_rows(llm_rows, client, GEMINI_MODEL).items():
        mart.set_stage(h, stage_ruled.get(h, stage), direction)

    # 말투 백필: 요약에 존댓말이 남은 행을 회차 상한 내에서 재생성 (멱등 — 검출 기반 재선별)
    tone_limit = int(cfg.get("tone_backfill_limit", 20))
    tone_rows = select_tone_backfill(mart.rows_enriched_summaries(), tone_limit)
    if tone_rows:
        fixed = resummarize_rows(tone_rows, client, GEMINI_MODEL)
        for h, v in fixed.items():
            v = apply_glossary(v, glossary)
            orig = next(r for r in tone_rows if r["content_hash"] == h)
            mart.set_summary(h, v["summary_ko"],
                             v["summary3_ko"] if orig.get("summary3_ko") else None)
        logging.getLogger(__name__).info(
            "말투 백필: 대상 %d건 중 %d건 재생성", len(tone_rows), len(fixed))

    with engine.connect() as c:
        rows = [dict(r) for r in c.execute(text(SERVING_SELECT_SQL)).mappings().all()]
    # 수집 필터 도입 전 적재된 fmkorea 무관 글을 서빙에서만 제외 (DB 는 보존).
    # 어댑터가 들고 있는 인정 집합을 그대로 써서 수집 · 서빙 기준을 하나로 묶는다.
    # 목록에서 빠지면 sweep_orphan_pages 가 상세 페이지도 함께 정리한다.
    fm = next((a for a in adapters if a.source_id == "fmkorea"), None)
    if fm is not None:
        with engine.connect() as c:
            linked = set(c.execute(text(LINKED_HASHES_SQL)).scalars().all())
        rows, hidden = serving_rows(rows, relevance_terms=fm.relevance_terms,
                                    player_names=fm.player_names, linked=linked)
        if hidden:
            logging.getLogger(__name__).info("fmkorea 무관 글 서빙 제외 %d건", hidden)
    write_site(rows, sources, "site",
               directory=journalist_directory("config/credibility.yaml"),
               registry=registry,
               outlet_dir=outlet_directory("config/credibility.yaml"))

    # 수집량 이상탐지 (SLO-6): 지난 12회 source_counts 대비 소스별 드롭 · 스파이크 알림
    with engine.connect() as c:
        hist = [json.loads(s) for s in c.execute(text(
            "SELECT source_counts FROM pipeline_runs "
            "ORDER BY started_at DESC LIMIT 12")).scalars().all() if s]
    anomalies = volume_anomalies(stats["source_counts"], hist)
    if anomalies:
        notify.send_alert(**notify.build_anomaly_alert(
            anomalies, len(hist), hist=hist, sources=sources, run_id=run_id))

    # 신선도 워터마크 감시 (SLO-5): 소스별 MAX(fetched_at) 경과가 임계 초과면 알림
    default_hours = cfg.get("freshness_default_hours", 48)
    overrides = {sid: float(s["freshness_hours"])
                 for sid, s in sources.items() if "freshness_hours" in s}
    checked_at = mart.db_now()
    wm = mart.source_watermarks()
    records = evaluate_freshness({sid: wm.get(sid) for sid in sources},
                                 checked_at, default_hours, overrides)
    mart.record_freshness(run_id, checked_at, records)
    if notify.freshness_alert_targets(records, candidate_counts, errors):
        notify.send_alert(**notify.build_freshness_alert(
            records, default_hours, sources=sources, run_id=run_id,
            checked_at=checked_at, candidates=candidate_counts,
            fetch_errors=errors))

    summary = {"new_or_changed": len(arts), "errors": errors,
               "success_rate": success_rate(len(adapters), len(errors)),
               "elapsed_sec": round(time.perf_counter() - t0, 2)}
    with engine.begin() as c:
        c.execute(text(RUN_INSERT_SQL),
            {"rid": run_id,
             "drid": os.environ.get("AIRFLOW_CTX_DAG_RUN_ID", "manual"),
             "started": started_at_utc, "dur": summary["elapsed_sec"],
             "fetch": fetch_sec,
             "counts": json.dumps(stats["source_counts"]),
             "cands": json.dumps(candidate_counts),
             "new": len(arts), "dup": stats["dup_count"],
             "blocked": stats["blocked_count"],
             "err": len(errors), "sr": summary["success_rate"]})

    # 운영 뷰 (ops.html): pipeline_runs 기록 후 DB 한 경로로 집계 · 렌더.
    # 실패해도 파이프라인은 계속 (spec §4 실패 격리).
    try:
        write_ops(mart.ops_snapshot(), sources, "site",
                  anomaly_count=len(anomalies), now=mart.db_now(),
                  unmatched=unmatched_articles(rows, pstore.linked_hashes()))
    except Exception:
        logging.getLogger(__name__).warning(
            "ops 뷰 생성 실패 — 파이프라인은 계속 진행", exc_info=True)

    print(summary)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=8)
    asyncio.run(main(ap.parse_args().concurrency))
