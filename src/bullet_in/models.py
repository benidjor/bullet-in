from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel

SourceType = Literal["rss", "api", "html", "playwright", "x"]

class RawItem(BaseModel):
    source_id: str
    source_type: SourceType
    url: str
    fetched_at: datetime
    raw_payload: dict[str, Any]
    content_hash: str | None = None

class Article(BaseModel):
    content_hash: str
    url: str
    source_id: str
    author: str | None = None
    tier: float | None = None
    confidence_score: float | None = None
    title_original: str
    title_ko: str | None = None
    summary_ko: str | None = None
    body_excerpt: str | None = None
    published_at: datetime
    revision: int = 1
