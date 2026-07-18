import asyncio
import httpx, respx
from bullet_in import backfill_image as bi

def test_thumbnail_source_ids_picks_flagged_sources():
    sources = {
        "bbc_gossip": {"source_id": "bbc_gossip",
                       "config": {"list_url": "x", "thumbnail_only": True}},
        "bbc_sport": {"source_id": "bbc_sport",
                      "config": {"list_url": "x", "body_selector": "article"}},
        "guardian": {"source_id": "guardian", "config": {}},
    }
    assert bi.thumbnail_source_ids(sources) == ["bbc_gossip"]

# --- backfill() 루프 — DB · 네트워크 전부 모킹 (test_backfill_journalist 선례) ---

class _FakeResult:
    def __init__(self, rows):
        self._rows = rows
    def mappings(self):
        return self
    def all(self):
        return self._rows

class _FakeConn:
    def __init__(self, eng):
        self._eng = eng
    def execute(self, sql, params=None):
        if params and "img" in params:
            self._eng.updates.append(params)
        return _FakeResult(self._eng.rows)
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False

class _FakeEngine:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []
    def connect(self):
        return _FakeConn(self)
    def begin(self):
        return _FakeConn(self)

@respx.mock
def test_backfill_updates_only_rows_with_og_image(monkeypatch):
    rows = [{"content_hash": "h1", "url": "https://b.test/1"},
            {"content_hash": "h2", "url": "https://b.test/2"}]
    eng = _FakeEngine(rows)
    monkeypatch.setattr(bi, "create_engine", lambda *a, **k: eng)
    monkeypatch.setattr(bi, "load_sources", lambda *_: {
        "bbc_gossip": {"source_id": "bbc_gossip", "config": {"thumbnail_only": True}}})
    monkeypatch.setattr(bi, "REQUEST_GAP_SEC", 0)
    monkeypatch.setenv("MARIADB_URL", "mysql://unused")
    respx.get("https://b.test/1").mock(return_value=httpx.Response(
        200, text='<meta property="og:image" content="https://img.test/1.jpg">'))
    respx.get("https://b.test/2").mock(return_value=httpx.Response(200, text="<html></html>"))
    stats = asyncio.run(bi.backfill())
    assert stats == {"ok": 1, "fail": 1}          # og:image 부재는 fail · NULL 유지
    assert eng.updates == [{"img": "https://img.test/1.jpg", "h": "h1"}]

@respx.mock
def test_backfill_dry_run_writes_nothing(monkeypatch):
    rows = [{"content_hash": "h1", "url": "https://b.test/1"}]
    eng = _FakeEngine(rows)
    monkeypatch.setattr(bi, "create_engine", lambda *a, **k: eng)
    monkeypatch.setattr(bi, "load_sources", lambda *_: {
        "bbc_gossip": {"source_id": "bbc_gossip", "config": {"thumbnail_only": True}}})
    monkeypatch.setattr(bi, "REQUEST_GAP_SEC", 0)
    monkeypatch.setenv("MARIADB_URL", "mysql://unused")
    respx.get("https://b.test/1").mock(return_value=httpx.Response(
        200, text='<meta property="og:image" content="https://img.test/1.jpg">'))
    stats = asyncio.run(bi.backfill(dry_run=True))
    assert stats == {"ok": 1, "fail": 0}
    assert eng.updates == []
