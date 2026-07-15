import asyncio
from pathlib import Path
import httpx, respx
from bullet_in import backfill_journalist as bf
from bullet_in.backfill_journalist import journalist_update
from bullet_in.credibility import load_registry

REG = load_registry(Path("config/credibility.yaml"))
SOURCES = {
    "skysports": {"source_id": "skysports", "tier": 4, "outlet": "Sky Sports"},
    "football_london": {"source_id": "football_london", "tier": 4, "outlet": "football.london"},
    "goal": {"source_id": "goal", "tier": 4, "outlet": "Goal.com"},
}

def _ld(*names):
    people = ",".join('{"@type":"Person","name":"%s"}' % n for n in names)
    return ('<script type="application/ld+json">'
            '{"@type":"NewsArticle","author":[%s]}</script>' % people)

def test_update_promotes_tier_for_affiliated_journalist():
    out = journalist_update(_ld("Dharmesh Sheth"), "skysports", "https://x/1", SOURCES, REG)
    assert out == {"journalist": "Dharmesh Sheth", "tier": 1.5, "confidence_score": 0.625}

def test_update_keeps_source_tier_for_unregistered():
    out = journalist_update(_ld("Raff Tindale"), "football_london", "https://x/2", SOURCES, REG)
    assert out == {"journalist": "Raff Tindale", "tier": 4.0, "confidence_score": 0.0}

def test_update_keeps_source_tier_for_freelancer():
    # Watts 는 소속 미지정 → 표시만, tier 무조정 (사용자 결정)
    out = journalist_update(_ld("Charles Watts"), "goal", "https://x/3", SOURCES, REG)
    assert out == {"journalist": "Charles Watts", "tier": 4.0, "confidence_score": 0.0}

def test_update_picks_registered_author_among_many():
    out = journalist_update(_ld("Alastair Telfer", "Dharmesh Sheth"), "skysports",
                            "https://x/4", SOURCES, REG)
    assert out["journalist"] == "Dharmesh Sheth"

def test_update_journalist_none_when_no_author():
    out = journalist_update("<html><body>no author</body></html>", "goal",
                            "https://x/5", SOURCES, REG)
    assert out["journalist"] is None and out["tier"] == 4.0

# --- backfill() 재fetch 루프 — 실패 건도 요청 간격을 지키는지 (DB · 네트워크는 전부 모킹) ---

class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
    def mappings(self):
        return self
    def all(self):
        return self._rows

class _FakeConn:
    def __init__(self, rows):
        self._rows = rows
    def execute(self, *a, **k):
        return _FakeCursor(self._rows)
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False

class _FakeEngine:
    """engine.begin() 은 호출되면 실패 — 이 테스트는 실패 건만 다뤄 UPDATE 를 타면 안 된다."""
    def __init__(self, rows):
        self._rows = rows
    def connect(self):
        return _FakeConn(self._rows)
    def begin(self):
        raise AssertionError("실패 건만 있는 테스트에서 engine.begin() 이 호출됨")

_FETCH_SOURCES = {
    "testsrc": {"source_id": "testsrc", "tier": 4, "outlet": "Test Outlet",
                "adapter": "html", "config": {"body_selector": "article"}},
}
_ROWS = [
    {"content_hash": "h1", "url": "https://x.test/1", "source_id": "testsrc"},
    {"content_hash": "h2", "url": "https://x.test/2", "source_id": "testsrc"},
    {"content_hash": "h3", "url": "https://x.test/3", "source_id": "testsrc"},
]

@respx.mock
def test_backfill_sleeps_after_failed_rows(monkeypatch):
    """404 · 저자 부재로 continue 되는 건도 성공 건과 동일하게 간격을 지켜야 한다
    (마지막 건은 기존 의도대로 sleep 생략)."""
    respx.get("https://x.test/1").mock(return_value=httpx.Response(404))
    respx.get("https://x.test/2").mock(return_value=httpx.Response(200, text="<html>no author</html>"))
    respx.get("https://x.test/3").mock(return_value=httpx.Response(404))

    monkeypatch.setenv("MARIADB_URL", "sqlite://dummy")
    monkeypatch.setattr(bf, "load_sources", lambda path: _FETCH_SOURCES)
    monkeypatch.setattr(bf, "load_registry", lambda path: REG)
    monkeypatch.setattr(bf, "create_engine", lambda url: _FakeEngine(_ROWS))

    sleep_calls = []
    async def fake_sleep(sec):
        sleep_calls.append(sec)
    monkeypatch.setattr(bf.asyncio, "sleep", fake_sleep)

    stats = asyncio.run(bf.backfill())

    assert stats["testsrc"] == {"ok": 0, "fail": 3}
    # i=0 (404) · i=1 (저자 부재) 는 마지막이 아니므로 각각 sleep, i=2 (404) 는 마지막이라 생략.
    assert len(sleep_calls) == 2
