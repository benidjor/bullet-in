from __future__ import annotations
import argparse, asyncio, json, logging, os, time, uuid, yaml
from pathlib import Path
from pymongo import MongoClient
from sqlalchemy import create_engine, text
from google import genai
from bullet_in.adapters.factory import build_adapters
from bullet_in.ingest import gather_all
from bullet_in.canonical import content_hash, canonical_url
from bullet_in.pipeline import to_articles
from bullet_in.score import load_sources
from bullet_in.credibility import load_registry
from bullet_in.storage.mongo import RawStore
from bullet_in.storage.mariadb import MartStore
from bullet_in.enrich import enrich_rows, classify_stage_rows
from bullet_in.serve.render import write_site, write_ops
from bullet_in.quality import success_rate, volume_anomalies, evaluate_freshness
from bullet_in import notify

GEMINI_MODEL = "gemini-2.5-flash-lite"

async def main(concurrency: int):
    run_id = str(uuid.uuid4())
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
    sources = load_sources("config/sources.yaml")
    registry = load_registry("config/credibility.yaml")
    adapters = build_adapters(cfg)

    t0 = time.perf_counter()
    started_epoch = time.time()
    raw, errors = await gather_all(adapters, concurrency=concurrency)
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
    mart.upsert(arts)

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    from bullet_in.enrich import partition_by_paywall
    missing = mart.rows_missing_translation()
    paraphrase_rows, translate_rows = partition_by_paywall(missing)
    results: dict[str, dict] = {}
    results.update(enrich_rows(translate_rows, client, GEMINI_MODEL, mode="translate"))
    results.update(enrich_rows(paraphrase_rows, client, GEMINI_MODEL, mode="paraphrase"))
    for h, v in results.items():
        mart.set_translation(h, v["title_ko"], v["summary_ko"],
                             v["summary3_ko"], v["body_ko"])

    # 분류 패스: 미태깅 행 분류 및 저장
    stage_rows = mart.rows_missing_stage()
    for h, stage in classify_stage_rows(stage_rows, client, GEMINI_MODEL).items():
        mart.set_stage(h, stage)

    with engine.connect() as c:
        rows = [dict(r) for r in c.execute(text(
            "SELECT content_hash,url,source_id,title_original,title_ko,summary_ko,"
            "summary3_ko,body_ko,image_url,outlet,journalist,team,transfer_stage,tier,"
            "confidence_score,published_at "
            "FROM articles")).mappings().all()]
    write_site(rows, sources, "site")

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
        c.execute(text(
            "INSERT INTO pipeline_runs (run_id,dag_run_id,started_at,finished_at,"
            "duration_sec,source_counts,new_count,dup_count,error_count,success_rate) "
            "VALUES (:rid,:drid,FROM_UNIXTIME(:t0),NOW(),:dur,:counts,:new,:dup,:err,:sr)"),
            {"rid": run_id,
             "drid": os.environ.get("AIRFLOW_CTX_DAG_RUN_ID", "manual"),
             "t0": int(started_epoch), "dur": summary["elapsed_sec"],
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
