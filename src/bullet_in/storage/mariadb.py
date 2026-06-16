from __future__ import annotations
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.engine import Engine
from bullet_in.models import Article

_SCHEMA = Path(__file__).with_name("schema.sql")

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
        sql = text("""
          INSERT INTO articles
            (content_hash,url,source_id,author,tier,confidence_score,
             title_original,title_ko,summary_ko,body_excerpt,published_at,fetched_at,revision)
          VALUES (:content_hash,:url,:source_id,:author,:tier,:confidence_score,
             :title_original,:title_ko,:summary_ko,:body_excerpt,:published_at,:fetched_at,:revision)
          ON DUPLICATE KEY UPDATE
             title_ko=IF(articles.content_hash=VALUES(content_hash), articles.title_ko, NULL),
             summary_ko=IF(articles.content_hash=VALUES(content_hash), articles.summary_ko, NULL),
             title_original=VALUES(title_original),
             body_excerpt=VALUES(body_excerpt),
             published_at=VALUES(published_at),
             tier=VALUES(tier),
             confidence_score=VALUES(confidence_score),
             fetched_at=VALUES(fetched_at),
             revision=VALUES(revision),
             content_hash=VALUES(content_hash)""")
        rows = [a.model_dump() for a in articles]
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
                "SELECT content_hash,source_id,title_original,body_excerpt FROM articles "
                "WHERE title_ko IS NULL")).mappings().all()
        return [dict(r) for r in rows]
    def set_translation(self, content_hash: str, title_ko: str, summary_ko: str):
        with self.engine.begin() as c:
            c.execute(text("UPDATE articles SET title_ko=:t, summary_ko=:s "
                           "WHERE content_hash=:h"),
                      {"t": title_ko, "s": summary_ko, "h": content_hash})
