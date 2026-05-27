from bullet_in.quality import success_rate, volume_anomaly

def test_success_rate_excludes_errored_sources():
    assert success_rate(total_sources=5, errored=1) == 0.8

def test_volume_anomaly_flags_drop_beyond_threshold():
    assert volume_anomaly(today=2, history=[20, 22, 18, 21], sigma=2.0) is True

def test_volume_anomaly_ok_within_band():
    assert volume_anomaly(today=20, history=[20, 22, 18, 21], sigma=2.0) is False
