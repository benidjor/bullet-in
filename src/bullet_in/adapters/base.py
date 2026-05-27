from __future__ import annotations
from typing import Protocol, runtime_checkable
from bullet_in.models import RawItem

@runtime_checkable
class SourceAdapter(Protocol):
    source_id: str
    source_type: str
    async def fetch(self) -> list[RawItem]: ...
