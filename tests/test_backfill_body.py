import asyncio
import httpx, respx
from bullet_in import backfill_body as bb

_ARTICLE_HTML = """
<meta property="og:image" content="https://img.test/hero.jpg">
<article><p>Gossip line one.</p>
<img src="/inline.jpg"><p>Gossip line two.</p></article>
"""

def test_body_update_extracts_body_images_and_hero():
    upd = bb.body_update(_ARTICLE_HTML, "https://b.test/a", "article")
    assert "Gossip line one." in upd["body"] and "Gossip line two." in upd["body"]
    assert upd["image"] == "https://img.test/hero.jpg"
    assert "https://b.test/inline.jpg" in upd["images_json"]

def test_body_update_returns_none_when_selector_misses():
    assert bb.body_update("<div>no article tag</div>", "https://b.test/a", "article") is None

# --- backfill() 루프 — DB · 네트워크 전부 모킹 (test_backfill_image 선례) ---

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
        if params and "b" in params:
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

_SRC = {"bbc_gossip": {"source_id": "bbc_gossip", "adapter": "html",
                       "config": {"body_selector": "article"}}}

@respx.mock
def test_backfill_updates_only_rows_with_body(monkeypatch):
    rows = [{"content_hash": "h1", "url": "https://b.test/1"},
            {"content_hash": "h2", "url": "https://b.test/2"}]
    eng = _FakeEngine(rows)
    monkeypatch.setattr(bb, "create_engine", lambda *a, **k: eng)
    monkeypatch.setattr(bb, "load_sources", lambda *_: _SRC)
    monkeypatch.setattr(bb, "REQUEST_GAP_SEC", 0)
    monkeypatch.setenv("MARIADB_URL", "mysql://unused")
    respx.get("https://b.test/1").mock(return_value=httpx.Response(200, text=_ARTICLE_HTML))
    respx.get("https://b.test/2").mock(return_value=httpx.Response(200, text="<html></html>"))
    stats = asyncio.run(bb.backfill("bbc_gossip"))
    assert stats == {"ok": 1, "fail": 1}          # 본문 미추출은 fail · 빈 값 유지
    assert len(eng.updates) == 1 and eng.updates[0]["h"] == "h1"

def test_backfill_aborts_on_non_body_source(monkeypatch):
    monkeypatch.setattr(bb, "load_sources", lambda *_: {
        "fmkorea": {"source_id": "fmkorea", "adapter": "fmkorea", "config": {}}})
    monkeypatch.setenv("MARIADB_URL", "mysql://unused")
    assert asyncio.run(bb.backfill("fmkorea")) == {"ok": 0, "fail": 0}
