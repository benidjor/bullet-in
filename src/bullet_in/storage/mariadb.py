from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.engine import Engine
from bullet_in.models import Article
from bullet_in.quality import SourceFreshness

_SCHEMA = Path(__file__).with_name("schema.sql")

def _article_row(a: Article) -> dict:
    """Article → upsert 파라미터 행. images 는 JSON 직렬화, 빈 목록은 NULL."""
    row = a.model_dump(exclude={"images"})
    row["images_json"] = json.dumps(a.images) if a.images else None
    return row

class MartStore:
    def __init__(self, engine: Engine):
        self.engine = engine
    def ensure_schema(self) -> None:
        """schema.sql 을 멱등 적용(CREATE TABLE IF NOT EXISTS)해 첫 실행 전
        테이블을 보장한다. run.py 가 호출하므로 수동 스키마 적용이 불필요."""
        stmts = [s.strip() for s in _SCHEMA.read_text().split(";") if s.strip()]
        with self.engine.begin() as c:
            for s in stmts:
                c.execute(text(s))
    def upsert(self, articles: list[Article]) -> int:
        if not articles:  # 신규 없는 회차 → 빈 executemany는 SQLAlchemy가 거부
            return 0
        sql = text("""
          INSERT INTO articles
            (content_hash,url,source_id,author,tier,confidence_score,
             title_original,title_ko,summary_ko,body_excerpt,
             summary3_ko,body_ko,body_source,image_url,images_json,outlet,journalist,team,
             transfer_stage,
             published_at,fetched_at,revision)
          VALUES (:content_hash,:url,:source_id,:author,:tier,:confidence_score,
             :title_original,:title_ko,:summary_ko,:body_excerpt,
             :summary3_ko,:body_ko,:body_source,:image_url,:images_json,:outlet,:journalist,:team,
             :transfer_stage,
             :published_at,:fetched_at,:revision)
          ON DUPLICATE KEY UPDATE
             title_ko=IF(articles.content_hash=VALUES(content_hash), articles.title_ko, NULL),
             summary_ko=IF(articles.content_hash=VALUES(content_hash), articles.summary_ko, NULL),
             summary3_ko=IF(articles.content_hash=VALUES(content_hash), articles.summary3_ko, NULL),
             body_ko=IF(articles.content_hash=VALUES(content_hash), articles.body_ko, NULL),
             title_original=VALUES(title_original),
             body_excerpt=VALUES(body_excerpt),
             body_source=VALUES(body_source),
             image_url=VALUES(image_url),
             images_json=VALUES(images_json),
             outlet=VALUES(outlet),
             journalist=VALUES(journalist),
             team=VALUES(team),
             published_at=VALUES(published_at),
             tier=VALUES(tier),
             confidence_score=VALUES(confidence_score),
             fetched_at=VALUES(fetched_at),
             revision=VALUES(revision),
             content_hash=VALUES(content_hash)""")
        rows = [_article_row(a) for a in articles]
        with self.engine.begin() as c:
            c.execute(sql, rows)
        return len(rows)
    def count(self) -> int:
        with self.engine.connect() as c:
            return c.execute(text("SELECT COUNT(*) FROM articles")).scalar_one()
    def seen_map(self) -> dict[str, tuple[str, int]]:
        with self.engine.connect() as c:
            rows = c.execute(text("SELECT url,content_hash,revision FROM articles")).all()
        return {u: (h, rev) for u, h, rev in rows}
    def rows_missing_translation(self) -> list[dict]:
        with self.engine.connect() as c:
            rows = c.execute(text(
                "SELECT content_hash,source_id,title_original,body_excerpt,"
                "body_source,outlet,summary_ko "
                "FROM articles WHERE title_ko IS NULL")).mappings().all()
        return [dict(r) for r in rows]
    def set_translation(self, content_hash: str, title_ko: str, summary_ko: str,
                        summary3_ko: str | None = None, body_ko: str | None = None):
        with self.engine.begin() as c:
            c.execute(text("UPDATE articles SET title_ko=:t, summary_ko=:s, "
                           "summary3_ko=:s3, body_ko=:b WHERE content_hash=:h"),
                      {"t": title_ko, "s": summary_ko, "s3": summary3_ko,
                       "b": body_ko, "h": content_hash})
    def rows_missing_stage(self) -> list[dict]:
        with self.engine.connect() as c:
            rows = c.execute(text(
                "SELECT content_hash,source_id,title_original,summary_ko "
                "FROM articles WHERE transfer_stage IS NULL")).mappings().all()
        return [dict(r) for r in rows]

    def set_stage(self, content_hash: str, stage: str) -> None:
        with self.engine.begin() as c:
            c.execute(text("UPDATE articles SET transfer_stage=:s WHERE content_hash=:h"),
                      {"s": stage, "h": content_hash})

    def rows_enriched_summaries(self) -> list[dict]:
        """요약이 이미 생성된 행 — 말투 백필 후보 풀."""
        with self.engine.connect() as c:
            rows = c.execute(text(
                "SELECT content_hash,title_original,title_ko,body_excerpt,"
                "body_ko,summary_ko,summary3_ko "
                "FROM articles WHERE summary_ko IS NOT NULL")).mappings().all()
        return [dict(r) for r in rows]

    def set_summary(self, content_hash: str, summary_ko: str,
                    summary3_ko: str | None = None) -> None:
        """요약 필드만 갱신 — summary3_ko 가 None 이면 기존 값을 보존한다."""
        with self.engine.begin() as c:
            if summary3_ko is None:
                c.execute(text("UPDATE articles SET summary_ko=:s "
                               "WHERE content_hash=:h"),
                          {"s": summary_ko, "h": content_hash})
            else:
                c.execute(text("UPDATE articles SET summary_ko=:s, "
                               "summary3_ko=:s3 WHERE content_hash=:h"),
                          {"s": summary_ko, "s3": summary3_ko, "h": content_hash})

    def source_watermarks(self) -> dict[str, datetime]:
        """소스별 MAX(fetched_at) 워터마크. 기사 0건 소스는 키가 없다."""
        with self.engine.connect() as c:
            rows = c.execute(text(
                "SELECT source_id, MAX(fetched_at) FROM articles "
                "GROUP BY source_id")).all()
        return {sid: wm for sid, wm in rows}

    def db_now(self) -> datetime:
        """UTC 기준 DB 시각. fetched_at (어댑터가 UTC 저장) 과 같은 시계로 비교."""
        with self.engine.connect() as c:
            return c.execute(text("SELECT UTC_TIMESTAMP()")).scalar_one()

    def record_freshness(self, run_id: str, checked_at: datetime,
                         records: list[SourceFreshness]) -> None:
        if not records:  # 빈 executemany 는 SQLAlchemy 가 거부
            return
        with self.engine.begin() as c:
            c.execute(text(
                "INSERT INTO source_freshness (run_id,checked_at,source_id,"
                "last_fetched_at,age_hours,threshold_hours,stale) "
                "VALUES (:rid,:at,:sid,:wm,:age,:thr,:stale)"),
                [{"rid": run_id, "at": checked_at, "sid": r.source_id,
                  "wm": r.last_fetched_at, "age": r.age_hours,
                  "thr": r.threshold_hours, "stale": r.stale}
                 for r in records])

    def ops_snapshot(self, chart_runs: int = 30, trend_runs: int = 12) -> dict:
        """운영 뷰 (ops.html) 집계 스냅샷. 지표 정의는 spec §5 표가 기준.
        pending 은 rows_missing_translation/stage 와 동일 술어로 카운트."""
        with self.engine.connect() as c:
            runs = [dict(r) for r in c.execute(text(
                "SELECT run_id,started_at,duration_sec,fetch_duration_sec,"
                "source_counts,new_count,dup_count,error_count,success_rate "
                "FROM pipeline_runs ORDER BY started_at DESC LIMIT :n"),
                {"n": chart_runs}).mappings().all()]
            freshness = [dict(r) for r in c.execute(text(
                "SELECT run_id,checked_at,source_id,last_fetched_at,"
                "age_hours,threshold_hours,stale FROM source_freshness "
                "WHERE run_id IN (SELECT run_id FROM ("
                " SELECT DISTINCT run_id, checked_at FROM source_freshness"
                " ORDER BY checked_at DESC LIMIT :n) w) "
                "ORDER BY checked_at, source_id"),
                {"n": trend_runs}).mappings().all()]
            tier_rows = c.execute(text(
                "SELECT tier, COUNT(*) FROM articles GROUP BY tier")).all()
            pending_rows = c.execute(text(
                "SELECT source_id, SUM(title_ko IS NULL), "
                "SUM(transfer_stage IS NULL) FROM articles "
                "GROUP BY source_id")).all()
        for r in runs:
            r["source_counts"] = (json.loads(r["source_counts"])
                                  if r["source_counts"] else {})
        return {"runs": runs, "freshness": freshness,
                "tier_counts": {t: int(n) for t, n in tier_rows},
                "pending": {sid: {"translate": int(tr), "stage": int(st)}
                            for sid, tr, st in pending_rows}}
