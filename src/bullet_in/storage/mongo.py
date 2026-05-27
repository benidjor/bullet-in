from __future__ import annotations
from pymongo import ASCENDING
from pymongo.errors import BulkWriteError
from bullet_in.models import RawItem

class RawStore:
    def __init__(self, db):
        self.col = db["raw_items"]
        self.col.create_index([("content_hash", ASCENDING)], unique=True, sparse=True)
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
