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


class Silent:
    """메시지 없는 예외 — 타임아웃 계열이 실제로 이 모양이다.

    httpx.ReadTimeout · httpx.ConnectTimeout · TimeoutError 는 str(e) 가 빈 문자열이라
    저장하면 예외 형태까지 사라진다 (2026-08-22 실측)."""
    source_id = "silent"
    async def fetch(self):
        raise TimeoutError()


def test_gather_keeps_exception_type_when_message_is_empty():
    _, errors = asyncio.run(gather_all([Silent()]))
    assert errors == {"silent": "TimeoutError"}
