from bullet_in.metrics import speedup_pct

def test_speedup_pct_computes_reduction():
    assert speedup_pct(sequential_sec=10.0, parallel_sec=3.0) == 70.0
