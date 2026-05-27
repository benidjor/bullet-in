import asyncio
from datetime import datetime, timezone
from bullet_in.ingest import gather_all
from bullet_in.models import RawItem

class Ok:
    source_id = "ok"
    async def fetch(self):
        await asyncio.sleep(0.01)
        return [RawItem(source_id="ok", source_type="api", url="https://x.test/1",
                        fetched_at=datetime.now(timezone.utc), raw_payload={})]

class Boom:
    source_id = "boom"
    async def fetch(self):
        raise RuntimeError("down")

def test_gather_isolates_failures():
    items, errors = asyncio.run(gather_all([Ok(), Boom()]))
    assert len(items) == 1 and items[0].source_id == "ok"
    assert errors == {"boom": "down"}
