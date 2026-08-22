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
                # 타임아웃 계열은 str(e) 가 비어 예외 형태까지 사라진다. 그러면 저널로
                # 원인을 못 잡고, 신선도 알림은 빈 문자열을 "오류 없음" 으로 읽어
                # 어댑터 힌트 (셀렉터 드리프트) 를 근거 없이 붙인다 (2026-08-22 실측).
                errors[a.source_id] = str(e) or type(e).__name__
    await asyncio.gather(*(run(a) for a in adapters))
    return items, errors
