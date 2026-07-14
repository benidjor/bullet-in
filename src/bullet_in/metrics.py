from __future__ import annotations
import asyncio, time
from bullet_in.ingest import gather_all

def speedup_pct(sequential_sec: float, parallel_sec: float) -> float:
    return round((1 - parallel_sec / sequential_sec) * 100, 1)

async def benchmark(adapters, *, gap_sec: float = 60) -> dict:
    """순차(어댑터별 계측) → gap 대기 → 병렬 1세트 벤치마크 (SLO-1, spec §4.1).

    순차 패스를 어댑터별로 나눠 재면 소스별 분해(per_source)가 나와
    최장 소스 지배 여부를 판단할 수 있다. 두 패스의 에러 소스가 다르면
    비교 무효 — 호출자가 errors_seq/errors_par 로 판정한다."""
    per_source: dict[str, float] = {}
    errors_seq: dict[str, str] = {}
    for a in adapters:
        t = time.perf_counter()
        _, errs = await gather_all([a], concurrency=1)
        per_source[a.source_id] = round(time.perf_counter() - t, 2)
        errors_seq.update(errs)
    seq = round(sum(per_source.values()), 2)
    if gap_sec:
        await asyncio.sleep(gap_sec)         # 소스 연속 타격 완화
    t = time.perf_counter()
    _, errors_par = await gather_all(adapters, concurrency=len(adapters) or 1)
    par = round(time.perf_counter() - t, 2)
    return {"sequential_sec": seq, "parallel_sec": par,
            "speedup_pct": speedup_pct(seq, par) if seq > 0 else None,
            "per_source": per_source,
            "errors_seq": errors_seq, "errors_par": errors_par}
