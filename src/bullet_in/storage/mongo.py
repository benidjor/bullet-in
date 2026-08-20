from __future__ import annotations
from datetime import datetime, timezone
from pymongo import ASCENDING
from pymongo.errors import BulkWriteError
from bullet_in.models import RawItem

class RawStore:
    def __init__(self, db):
        self.col = db["raw_items"]
        self.col.create_index([("content_hash", ASCENDING)], unique=True, sparse=True)
        self.col.create_index([("source_id", ASCENDING), ("fetched_at", ASCENDING)])
    def insert_many(self, items: list[RawItem]) -> int:
        docs = [i.model_dump(mode="json") for i in items if i.content_hash]
        if not docs:
            return 0
        try:
            res = self.col.insert_many(docs, ordered=False)
            return len(res.inserted_ids)
        except BulkWriteError as e:  # 중복은 건너뜀, 치명적 아님
            return e.details.get("nInserted", 0)
    def count(self) -> int:
        return self.col.count_documents({})

    def source_watermarks(self) -> dict[str, datetime]:
        """소스별 MAX(fetched_at) 워터마크 — 원본 문서가 없는 소스는 키가 없다.

        insert_many 가 content_hash 중복을 건너뛰므로 이 값은 "그 소스에서 처음 보는
        내용을 마지막으로 받은 때" 다. 흡수돼 기사 행이 안 되는 소스도 여기서는 움직인다
        (설계 2026-08-20 §3.1).
        fetched_at 은 model_dump(mode="json") 을 거쳐 ISO-8601 문자열로 저장되고 전부
        같은 형식이라 사전식 최대값이 시간순 최대값과 같다.
        MartStore.db_now() 와 같은 시계로 비교하도록 tz-naive UTC 로 돌려준다."""
        rows = self.col.aggregate([
            {"$group": {"_id": "$source_id", "wm": {"$max": "$fetched_at"}}}])
        return {r["_id"]: _naive_utc(r["wm"]) for r in rows if r["wm"]}


def _naive_utc(iso: str) -> datetime:
    return datetime.fromisoformat(iso).astimezone(timezone.utc).replace(tzinfo=None)
