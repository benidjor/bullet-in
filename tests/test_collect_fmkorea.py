import socket
from datetime import datetime, timedelta, timezone
from bullet_in.collect_fmkorea import (should_supplement, read_last_contact,
                                       write_last_contact, tunnel_alive,
                                       build_fmkorea_adapter)

_NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)

def test_supplement_when_no_record():
    assert should_supplement(None, _NOW) is True

def test_skip_when_within_gap():
    assert should_supplement(_NOW - timedelta(hours=2), _NOW) is False

def test_supplement_when_gap_exceeded():
    assert should_supplement(_NOW - timedelta(hours=4), _NOW) is True

def test_supplement_at_exact_gap():
    assert should_supplement(_NOW - timedelta(hours=3), _NOW) is True

def test_last_contact_roundtrip(tmp_path):
    p = tmp_path / "state" / "fmkorea_last_contact"
    write_last_contact(p, _NOW)          # 부모 디렉토리 자동 생성
    assert read_last_contact(p) == _NOW

def test_read_last_contact_missing(tmp_path):
    assert read_last_contact(tmp_path / "absent") is None

def test_read_last_contact_corrupt(tmp_path):
    p = tmp_path / "stamp"
    p.write_text("not-a-date")
    assert read_last_contact(p) is None

def test_tunnel_alive_when_port_listening():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert tunnel_alive(f"socks5://127.0.0.1:{port}") is True
    finally:
        srv.close()

def test_tunnel_dead_when_port_closed():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.close()                          # 닫힌 포트 = 터널 없음
    assert tunnel_alive(f"socks5://127.0.0.1:{port}", timeout=0.5) is False

_CFG = {"sources": [
    {"source_id": "bbc_sport", "adapter": "html", "config": {}},
    {"source_id": "fmkorea", "adapter": "fmkorea", "config": {
        "search_url": "https://fm.test/s?t={target}&kw={keyword}",
        "search_keywords": [{"keyword": "아스날", "target": "title"}],
        "max_posts": 15}}]}

def test_build_fmkorea_adapter_reads_config_and_proxy():
    a = build_fmkorea_adapter(_CFG, "socks5://127.0.0.1:1080")
    assert a.source_id == "fmkorea"
    assert a.proxy == "socks5://127.0.0.1:1080"
    assert a.max_posts == 15
    assert a.search_keywords == [{"keyword": "아스날", "target": "title"}]

def test_build_fmkorea_adapter_none_proxy():
    a = build_fmkorea_adapter(_CFG, None)
    assert a.proxy is None
