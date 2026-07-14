import asyncio
import pytest
from bullet_in.metrics import benchmark, speedup_pct


class FakeAdapter:
    """asyncio.sleep 기반 페이크 — 지연·실패를 조절해 benchmark 계약을 검증."""
    def __init__(self, source_id: str, delay: float, fail: bool = False):
        self.source_id = source_id
        self._delay = delay
        self._fail = fail

    async def fetch(self):
        await asyncio.sleep(self._delay)
        if self._fail:
            raise RuntimeError("boom")
        return []


def test_speedup_pct_computes_reduction():
    assert speedup_pct(sequential_sec=10.0, parallel_sec=3.0) == 70.0


def test_benchmark_sequential_sums_and_parallel_maxes():
    adapters = [FakeAdapter("a", 0.1), FakeAdapter("b", 0.1), FakeAdapter("c", 0.1)]
    r = asyncio.run(benchmark(adapters, gap_sec=0))
    # 순차 = Σ지연 ≈ 0.3s, 병렬 = max지연 ≈ 0.1s — 여유 있는 경계로 flaky 방지
    assert r["sequential_sec"] >= 0.28
    assert r["parallel_sec"] < r["sequential_sec"]
    assert r["parallel_sec"] < 0.25
    assert r["speedup_pct"] == pytest.approx(
        (1 - r["parallel_sec"] / r["sequential_sec"]) * 100, abs=0.11)


def test_benchmark_per_source_breakdown():
    adapters = [FakeAdapter("fast", 0.01), FakeAdapter("slow", 0.1)]
    r = asyncio.run(benchmark(adapters, gap_sec=0))
    assert set(r["per_source"]) == {"fast", "slow"}
    assert r["per_source"]["slow"] > r["per_source"]["fast"]


def test_benchmark_isolates_error_sources_per_pass():
    adapters = [FakeAdapter("ok", 0.01), FakeAdapter("bad", 0.01, fail=True)]
    r = asyncio.run(benchmark(adapters, gap_sec=0))
    assert "bad" in r["errors_seq"] and "bad" in r["errors_par"]
    assert "ok" not in r["errors_seq"] and "ok" not in r["errors_par"]


def test_benchmark_empty_adapters_marks_invalid():
    r = asyncio.run(benchmark([], gap_sec=0))
    assert r["sequential_sec"] == 0
    assert r["speedup_pct"] is None
