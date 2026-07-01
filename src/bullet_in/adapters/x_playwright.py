from __future__ import annotations
import re
from datetime import datetime
from bullet_in.models import RawItem

_CITE_RE = re.compile(r"\[\s*@([A-Za-z0-9_]{1,15})\s*\]")


def parse_afcstuff_tweets(source_id: str, handle: str,
                          raw_tweets: list[dict], now: datetime) -> list[RawItem]:
    """DOM에서 뽑은 트윗 dict → 인용(`[ @handle ]`) 있는 것만 RawItem."""
    out: list[RawItem] = []
    for t in raw_tweets:
        text = t.get("text") or ""
        cited = ["@" + h for h in _CITE_RE.findall(text)]
        if not cited:
            continue
        sid = t.get("status_id") or ""
        out.append(RawItem(
            source_id=source_id, source_type="x",
            url=f"https://x.com/{handle}/status/{sid}", fetched_at=now,
            raw_payload={"text": text, "created_at": t.get("created_at"),
                         "journalist": cited[-1], "handles": cited,
                         "image_url": t.get("image_url")}))
    return out
