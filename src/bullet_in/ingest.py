from __future__ import annotations
import asyncio
from bullet_in.models import RawItem
from bullet_in.adapters.base import SourceAdapter

async def gather_all(adapters: list[SourceAdapter],
                     concurrency: int = 8) -> tuple[list[RawItem], dict[str, str]]:
    sem = asyncio.Semaphore(concurrency)
    items: list[RawItem] = []
    errors: dict[str, str] = {}
    async def run(a: SourceAdapter):
        async with sem:
            try:
                items.extend(await a.fetch())
            except Exception as e:  # 소스별 격리
                errors[a.source_id] = str(e)
    await asyncio.gather(*(run(a) for a in adapters))
    return items, errors
