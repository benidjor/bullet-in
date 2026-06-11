from __future__ import annotations
import argparse, asyncio, json, os, time, uuid, yaml
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
from bullet_in.enrich import enrich_rows, partition_translation_rows
from bullet_in.serve.render import write_page
from bullet_in.quality import success_rate

async def main(concurrency: int):
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
    arts = to_articles(raw, sources, seen=mart.seen_map(), registry=registry)
    mart.upsert(arts)

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    ko_rows, en_rows = partition_translation_rows(
        mart.rows_missing_translation(), sources)
    for r in ko_rows:
        mart.set_translation(r["content_hash"], r["title_original"],
                             (r.get("body_excerpt") or "")[:200])
    translations = enrich_rows(en_rows, client, "gemini-2.5-flash-lite")
    for h, (tk, sk) in translations.items():
        mart.set_translation(h, tk, sk)

    with engine.connect() as c:
        rows = [dict(r) for r in c.execute(text(
            "SELECT title_original,title_ko,summary_ko,url,source_id,tier,confidence_score "
            "FROM articles")).mappings().all()]
    write_page(rows, "site/index.html")

    summary = {"new_or_changed": len(arts), "errors": errors,
               "success_rate": success_rate(len(adapters), len(errors)),
               "elapsed_sec": round(time.perf_counter() - t0, 2)}
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO pipeline_runs (run_id,dag_run_id,started_at,finished_at,"
            "duration_sec,source_counts,new_count,dup_count,error_count,success_rate) "
            "VALUES (:rid,:drid,FROM_UNIXTIME(:t0),NOW(),:dur,:counts,:new,0,:err,:sr)"),
            {"rid": str(uuid.uuid4()),
             "drid": os.environ.get("AIRFLOW_CTX_DAG_RUN_ID", "manual"),
             "t0": int(started_epoch), "dur": summary["elapsed_sec"],
             "counts": json.dumps({a.source_id: 0 for a in adapters}),
             "new": len(arts), "err": len(errors), "sr": summary["success_rate"]})
    print(summary)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=8)
    asyncio.run(main(ap.parse_args().concurrency))
