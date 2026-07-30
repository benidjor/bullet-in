import socket
from datetime import datetime, timedelta, timezone
from bullet_in import collect_fmkorea
from bullet_in.canonical import content_hash
from bullet_in.collect_fmkorea import (should_supplement, read_last_contact,
                                       write_last_contact, tunnel_alive,
                                       build_fmkorea_adapter, persist)
from bullet_in.models import RawItem

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

def test_build_fmkorea_adapter_passes_backfill_options():
    a = build_fmkorea_adapter(_CFG, None, pages=3, request_gap_sec=1.5,
                              exclude_titles={"[BBC] 기존"}, max_posts=60)
    assert a.pages == 3
    assert a.request_gap_sec == 1.5
    assert a.exclude_titles == {"[BBC] 기존"}
    assert a.max_posts == 60


def test_build_fmkorea_adapter_defaults_match_regular_round():
    a = build_fmkorea_adapter(_CFG, None)
    assert (a.pages, a.request_gap_sec, a.exclude_titles) == (1, 0.0, set())
    assert a.max_posts == 15          # config 값 유지


class _FakeMongoClient:
    """MongoClient 대역 — persist() 는 실 Mongo 접촉 없이 dedup 집계만 검증하면 된다."""
    def __init__(self, uri):
        pass
    def __getitem__(self, name):
        return "fake-db"

class _FakeRawStore:
    def __init__(self, db):
        pass
    def insert_many(self, items):
        return len(items)

class _FakeMart:
    def __init__(self, seen):
        self._seen = seen
        self.upserted = None
    def seen_map(self):
        return self._seen
    def upsert(self, arts):
        self.upserted = arts
        return len(arts)


def test_persist_returns_load_dup_blocked_3tuple(monkeypatch):
    """persist() 는 (적재수, dup_count, blocked_count) 3-튜플을 돌려준다 —
    dup 는 같은 소스 재적재, blocked 는 완전체 보호 가드가 다른 소스를 막는 경로."""
    monkeypatch.setenv("MONGO_URI", "mongodb://fake/")
    monkeypatch.setattr(collect_fmkorea, "MongoClient", _FakeMongoClient)
    monkeypatch.setattr(collect_fmkorea, "RawStore", _FakeRawStore)

    dup_title = "[무명] 기존 글"
    dup_url = "https://fm.test/dup"
    blocked_url = "https://bbc.test/blocked"
    new_url = "https://fm.test/new"

    seen = {
        dup_url: (content_hash(dup_title, dup_url), 1, "fmkorea", 1),
        blocked_url: (content_hash("완전체 원문", blocked_url), 1, "bbc_sport", 2),
    }
    mart = _FakeMart(seen)
    now = datetime.now(timezone.utc)
    raw = [
        RawItem(source_id="fmkorea", source_type="html", url=dup_url,
                fetched_at=now, raw_payload={"title": dup_title, "body": "본문", "body_level": 1}),
        RawItem(source_id="fmkorea", source_type="html", url=blocked_url,
                fetched_at=now, raw_payload={"title": "다른 소스 스텁", "body": "본문",
                                            "body_level": 1}),
        RawItem(source_id="fmkorea", source_type="html", url=new_url,
                fetched_at=now, raw_payload={"title": "신규 글", "body": "본문",
                                            "body_level": 1}),
    ]

    result = persist(raw, mart)
    assert result == (1, 1, 1)          # 적재 1 · 동일 내용 생략 1 · 기존 기사 유지 1
    assert len(mart.upserted) == 1
    assert mart.upserted[0].url == new_url
