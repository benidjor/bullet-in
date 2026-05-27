from __future__ import annotations
import time
from bullet_in.ingest import gather_all

def speedup_pct(sequential_sec: float, parallel_sec: float) -> float:
    return round((1 - parallel_sec / sequential_sec) * 100, 1)

async def benchmark(adapters) -> dict:
    t = time.perf_counter(); await gather_all(adapters, concurrency=1)
    seq = time.perf_counter() - t
    t = time.perf_counter(); await gather_all(adapters, concurrency=len(adapters) or 1)
    par = time.perf_counter() - t
    return {"sequential_sec": round(seq, 2), "parallel_sec": round(par, 2),
            "speedup_pct": speedup_pct(seq, par)}
