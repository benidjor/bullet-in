from __future__ import annotations
import argparse, asyncio, json, logging, os, time, uuid, yaml
from datetime import datetime, timezone
from pathlib import Path
from pymongo import MongoClient
from sqlalchemy import create_engine, text
from google import genai
from bullet_in.adapters.factory import build_adapters
from bullet_in.ingest import gather_all
from bullet_in.canonical import content_hash, canonical_url
from bullet_in.pipeline import to_articles
from bullet_in.score import load_sources
from bullet_in.credibility import load_registry, journalist_directory, outlet_directory
from bullet_in.storage.mongo import RawStore
from bullet_in.storage.mariadb import MartStore
from bullet_in.enrich import (enrich_rows, classify_stage_rows, resummarize_rows,
                              apply_glossary, paragraphize,
                              detect_title_hallucination)
from bullet_in.tone import select_tone_backfill
from bullet_in import transfer_stage
from bullet_in.serve.render import write_site, write_ops
from bullet_in.quality import success_rate, volume_anomalies, evaluate_freshness
from bullet_in import notify

GEMINI_MODEL = "gemini-2.5-flash-lite"

# started_at 은 Python UTC 바인딩 · finished_at 은 UTC_TIMESTAMP() — 세션 TZ 무관 (spec §5)
RUN_INSERT_SQL = (
    "INSERT INTO pipeline_runs (run_id,dag_run_id,started_at,finished_at,"
    "duration_sec,fetch_duration_sec,source_counts,new_count,dup_count,"
    "error_count,success_rate) "
    "VALUES (:rid,:drid,:started,UTC_TIMESTAMP(),:dur,:fetch,:counts,"
    ":new,:dup,:err,:sr)")

async def main(concurrency: int):
    run_id = str(uuid.uuid4())
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
    sources = load_sources("config/sources.yaml")
    registry = load_registry("config/credibility.yaml")
    adapters = build_adapters(cfg)

    t0 = time.perf_counter()
    started_at_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    raw, errors = await gather_all(adapters, concurrency=concurrency)
    fetch_sec = round(time.perf_counter() - t0, 2)
    for it in raw:
        it.content_hash = content_hash(
            it.raw_payload.get("title") or it.raw_payload.get("text") or "",
            canonical_url(it.url))

    mongo = MongoClient(os.environ["MONGO_URI"])[os.environ.get("MONGO_DB", "bulletin")]
    RawStore(mongo).insert_many(raw)

    engine = create_engine(os.environ["MARIADB_URL"])
    mart = MartStore(engine)
    mart.ensure_schema()
    arts, stats = to_articles(raw, sources, seen=mart.seen_map(), registry=registry)
    logging.getLogger(__name__).info(
        "drop 집계 — 중복 %d · 여자팀 %d · 기자 allowlist %d",
        stats["dup_count"], stats["women_count"], stats["author_drop_count"])
    mart.upsert(arts)

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    from bullet_in.enrich import partition_by_paywall
    missing = mart.rows_missing_translation()
    paraphrase_rows, translate_rows = partition_by_paywall(missing)
    results: dict[str, dict] = {}
    results.update(enrich_rows(translate_rows, client, GEMINI_MODEL, mode="translate"))
    results.update(enrich_rows(paraphrase_rows, client, GEMINI_MODEL, mode="paraphrase"))
    glossary = (yaml.safe_load(Path("config/glossary.yaml").read_text())
                or {}).get("replacements", {})
    name_map = (yaml.safe_load(Path("config/name_map.yaml").read_text())
                or {}).get("names", {})
    by_hash = {r["content_hash"]: r for r in missing}
    for h, v in results.items():
        v = apply_glossary(v, glossary)
        # 제목 환각 검출 (설계 ②-A): 1차 검출 = 재번역 큐 (title NULL 저장 → 다음
        # 사이클 재선별), 재검출 (summary_ko 기저장 = 재시도 행) = 원문 제목 폴백.
        r0 = by_hash.get(h, {})
        src_text = " ".join(filter(None, [r0.get("title_original"),
                                          r0.get("body_source"),
                                          r0.get("body_excerpt")]))
        suspects = detect_title_hallucination(v["title_ko"], src_text, name_map)
        title_ko = v["title_ko"]
        if suspects and r0.get("summary_ko"):
            logging.getLogger(__name__).warning(
                "제목 환각 재발 — 원문 제목 폴백 content_hash=%s 의심=%s", h, suspects)
            title_ko = r0.get("title_original")
        elif suspects:
            logging.getLogger(__name__).warning(
                "제목 환각 의심 — 재번역 큐 content_hash=%s 의심=%s", h, suspects)
            title_ko = None
        mart.set_translation(h, title_ko, v["summary_ko"],
                             v["summary3_ko"], paragraphize(v["body_ko"]))

    # 분류 패스: 공홈은 소스 규칙으로 직접 태깅 (official 은 규칙 경로 전용), 나머지만 LLM 분류
    llm_rows = []
    for r in mart.rows_missing_stage():
        ruled = transfer_stage.rule_stage(r["source_id"])
        if ruled:
            mart.set_stage(r["content_hash"], ruled)
        else:
            llm_rows.append(r)
    for h, stage in classify_stage_rows(llm_rows, client, GEMINI_MODEL).items():
        mart.set_stage(h, stage)

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
        rows = [dict(r) for r in c.execute(text(
            "SELECT content_hash,url,source_id,title_original,title_ko,summary_ko,"
            "summary3_ko,body_ko,image_url,images_json,outlet,journalist,team,transfer_stage,tier,"
            "confidence_score,published_at "
            "FROM articles")).mappings().all()]
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
    breaches = [r for r in records if r.stale]
    if breaches:
        notify.send_alert(**notify.build_freshness_alert(
            records, default_hours, sources=sources, run_id=run_id,
            checked_at=checked_at))

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
             "new": len(arts), "dup": stats["dup_count"],
             "err": len(errors), "sr": summary["success_rate"]})

    # 운영 뷰 (ops.html): pipeline_runs 기록 후 DB 한 경로로 집계 · 렌더.
    # 실패해도 파이프라인은 계속 (spec §4 실패 격리).
    try:
        write_ops(mart.ops_snapshot(), sources, "site",
                  anomaly_count=len(anomalies), now=mart.db_now())
    except Exception:
        logging.getLogger(__name__).warning(
            "ops 뷰 생성 실패 — 파이프라인은 계속 진행", exc_info=True)

    print(summary)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=8)
    asyncio.run(main(ap.parse_args().concurrency))
