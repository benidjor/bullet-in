from __future__ import annotations
from sqlalchemy import text
from sqlalchemy.engine import Engine
from bullet_in.models import Article

class MartStore:
    def __init__(self, engine: Engine):
        self.engine = engine
    def upsert(self, articles: list[Article]) -> int:
        sql = text("""
          INSERT INTO articles
            (content_hash,url,source_id,author,tier,confidence_score,
             title_original,title_ko,summary_ko,body_excerpt,published_at,fetched_at,revision)
          VALUES (:content_hash,:url,:source_id,:author,:tier,:confidence_score,
             :title_original,:title_ko,:summary_ko,:body_excerpt,:published_at,:fetched_at,:revision)
          ON DUPLICATE KEY UPDATE
             revision=VALUES(revision), title_original=VALUES(title_original)""")
        rows = [a.model_dump() for a in articles]
        for r in rows:
            r.setdefault("fetched_at", None)
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
                "SELECT content_hash,title_original,body_excerpt FROM articles "
                "WHERE title_ko IS NULL")).mappings().all()
        return [dict(r) for r in rows]
    def set_translation(self, content_hash: str, title_ko: str, summary_ko: str):
        with self.engine.begin() as c:
            c.execute(text("UPDATE articles SET title_ko=:t, summary_ko=:s "
                           "WHERE content_hash=:h"),
                      {"t": title_ko, "s": summary_ko, "h": content_hash})
