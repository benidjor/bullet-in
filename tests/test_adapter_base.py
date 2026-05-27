import asyncio
from datetime import datetime, timezone
from bullet_in.adapters.base import SourceAdapter
from bullet_in.models import RawItem

class FakeAdapter:
    source_id = "fake"
    source_type = "api"
    async def fetch(self) -> list[RawItem]:
        return [RawItem(source_id="fake", source_type="api", url="https://x.test/a",
                        fetched_at=datetime.now(timezone.utc), raw_payload={})]

def test_fake_adapter_satisfies_protocol():
    a = FakeAdapter()
    assert isinstance(a, SourceAdapter)
    items = asyncio.run(a.fetch())
    assert items[0].source_id == "fake"
