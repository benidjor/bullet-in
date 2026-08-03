import asyncio
from datetime import datetime, timezone
from bullet_in import watchlist_fmkorea
from bullet_in.models import RawItem
from bullet_in.watchlist_fmkorea import (read_cursor, write_cursor, next_slice,
                                         build_keywords, next_cursor)

IDS = [10, 20, 30, 40, 50]


class _FakeAdapter:
    def __init__(self, raw, search_failures=0, search_failure_codes=None):
        self._raw = raw
        self.search_failures = search_failures
        self.search_failure_codes = search_failure_codes or {}
        self.relevance_dropped = 0
        self.relevance_terms = []
        self.player_names = set()
    async def fetch(self):
        return self._raw

class _FakeMart:
    def __init__(self):
        pass
    def ensure_schema(self):
        pass
    def db_now(self):
        return datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    def source_watermarks(self):
        return {}

class _FakePStore:
    def __init__(self, players):
        self._players = players
    def active_link_players(self):
        return self._players
    def confirmed_ko_names(self):
        return {"디오망데"}


def _run_main(monkeypatch, tmp_path, *, adapter, players, dry_run=False,
              persisted=None):
    monkeypatch.setenv("MARIADB_URL", "fake://")
    monkeypatch.setattr(watchlist_fmkorea, "create_engine", lambda url: None)
    monkeypatch.setattr(watchlist_fmkorea, "MartStore", lambda e: _FakeMart())
    monkeypatch.setattr(watchlist_fmkorea, "PlayerStore", lambda e: _FakePStore(players))
    monkeypatch.setattr(watchlist_fmkorea, "build_fmkorea_adapter",
                        lambda cfg, proxy, **kw: adapter)
    monkeypatch.setattr(watchlist_fmkorea, "persist",
                        lambda raw, mart: (persisted or []).append(raw) or (len(raw), 0, 0))
    monkeypatch.setattr(watchlist_fmkorea, "STATE_PATH", tmp_path / "stamp")
    monkeypatch.setattr(watchlist_fmkorea, "CURSOR_PATH", tmp_path / "cursor")
    monkeypatch.delenv("FMKOREA_PROXY", raising=False)
    asyncio.run(watchlist_fmkorea.main(dry_run=dry_run, force=True))


_RAW = [RawItem(source_id="fmkorea", source_type="html", url="https://fm.test/1",
                fetched_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                raw_payload={"title": "[BBC] 디오망데", "body": "b", "body_level": 1})]
_PLAYERS = [(10, "디오망데"), (20, "히메네스")]


def test_main_advances_cursor_on_success(monkeypatch, tmp_path):
    _run_main(monkeypatch, tmp_path, adapter=_FakeAdapter(_RAW), players=_PLAYERS)
    assert watchlist_fmkorea.read_cursor(tmp_path / "cursor") == 20
    assert (tmp_path / "stamp").exists()          # 접촉 스탬프 공유 기록

def test_main_holds_cursor_on_search_failure(monkeypatch, tmp_path):
    _run_main(monkeypatch, tmp_path,
              adapter=_FakeAdapter(_RAW, search_failures=1), players=_PLAYERS)
    assert watchlist_fmkorea.read_cursor(tmp_path / "cursor") is None

def test_main_dry_run_no_persist_no_cursor(monkeypatch, tmp_path):
    persisted = []
    _run_main(monkeypatch, tmp_path, adapter=_FakeAdapter(_RAW), players=_PLAYERS,
              dry_run=True, persisted=persisted)
    assert persisted == []                        # 적재 없음
    assert watchlist_fmkorea.read_cursor(tmp_path / "cursor") is None
    assert (tmp_path / "stamp").exists()          # 실접촉이므로 스탬프는 기록

def test_main_zero_active_links_exits_clean(monkeypatch, tmp_path):
    _run_main(monkeypatch, tmp_path, adapter=_FakeAdapter([]), players=[])
    assert not (tmp_path / "stamp").exists()      # 검색 0회 — 접촉 없음

def test_watchlist_guard_uses_60min_gap():
    # 가드 60분 (스펙 §3.1) — collect 의 should_supplement 를 GAP_HOURS 로 재사용
    from bullet_in.collect_fmkorea import should_supplement
    now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    from datetime import timedelta
    assert should_supplement(now - timedelta(minutes=30), now,
                             gap_hours=watchlist_fmkorea.GAP_HOURS) is False
    assert should_supplement(now - timedelta(minutes=61), now,
                             gap_hours=watchlist_fmkorea.GAP_HOURS) is True

def test_next_slice_from_start_when_no_cursor():
    assert next_slice(IDS, None, size=3) == [10, 20, 30]

def test_next_slice_starts_after_cursor():
    assert next_slice(IDS, 20, size=2) == [30, 40]

def test_next_slice_wraps_around():
    assert next_slice(IDS, 40, size=3) == [50, 10, 20]

def test_next_slice_restarts_when_cursor_is_last():
    assert next_slice(IDS, 50, size=2) == [10, 20]

def test_next_slice_cursor_id_removed_uses_next_id():
    # 커서 25 가 명단에서 사라짐 → 그다음 id (30) 부터 (스펙 §6)
    assert next_slice(IDS, 25, size=2) == [30, 40]

def test_next_slice_small_roster_no_duplicates():
    assert next_slice([10, 20], 10, size=10) == [20, 10]

def test_next_slice_empty_roster():
    assert next_slice([], None) == []

def test_cursor_roundtrip(tmp_path):
    p = tmp_path / "state" / "watchlist_cursor"
    write_cursor(p, 42)                  # 부모 디렉토리 자동 생성
    assert read_cursor(p) == 42

def test_read_cursor_missing_or_corrupt(tmp_path):
    assert read_cursor(tmp_path / "absent") is None
    p = tmp_path / "cursor"
    p.write_text("not-a-number")
    assert read_cursor(p) is None

def test_build_keywords_title_target():
    assert build_keywords(["디오망데", "히메네스"]) == [
        {"keyword": "디오망데", "target": "title"},
        {"keyword": "히메네스", "target": "title"}]

def test_next_cursor_advances_to_slice_end():
    assert next_cursor([30, 40, 50], search_failures=0) == 50

def test_next_cursor_holds_on_search_failure():
    # 검색 실패 시 커서 유지 — 같은 슬라이스 재시도 (스펙 §6)
    assert next_cursor([30, 40, 50], search_failures=1) is None

def test_next_cursor_none_on_empty_slice():
    assert next_cursor([], search_failures=0) is None

def test_watchlist_batch_uses_request_gap():
    import yaml
    from pathlib import Path
    from bullet_in.collect_fmkorea import build_fmkorea_adapter
    from bullet_in.watchlist_fmkorea import REQUEST_GAP_SEC

    # 회차 밀도 (분당 약 33요청, 24요청/43초 실측) 수준으로 낮추는 값이어야 한다
    assert REQUEST_GAP_SEC >= 1.0
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
    a = build_fmkorea_adapter(cfg, None, request_gap_sec=REQUEST_GAP_SEC,
                              search_keywords=[{"keyword": "k", "target": "title"}])
    assert a.request_gap_sec == REQUEST_GAP_SEC


_BLACKOUT_PLAYERS = [(10, "케파"), (20, "누사"), (30, "딕슨"),
                     (40, "스톤스"), (50, "일디즈")]


def test_blackout_alert_sent_when_every_search_fails(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(watchlist_fmkorea.notify, "send_alert",
                        lambda **kw: sent.append(kw))
    adapter = _FakeAdapter([], search_failures=5, search_failure_codes={430: 5})
    _run_main(monkeypatch, tmp_path, adapter=adapter, players=_BLACKOUT_PLAYERS)
    assert len(sent) == 1
    assert "전멸" in sent[0]["title"]


def test_no_alert_on_partial_failure(monkeypatch, tmp_path):
    """부분 실패는 알리지 않는다 (스펙 §3.2)."""
    sent = []
    monkeypatch.setattr(watchlist_fmkorea.notify, "send_alert",
                        lambda **kw: sent.append(kw))
    adapter = _FakeAdapter([], search_failures=2, search_failure_codes={430: 2})
    _run_main(monkeypatch, tmp_path, adapter=adapter, players=_BLACKOUT_PLAYERS)
    assert sent == []


def test_no_alert_on_dry_run(monkeypatch, tmp_path):
    """dry-run 은 적재도 알림도 하지 않는다."""
    sent = []
    monkeypatch.setattr(watchlist_fmkorea.notify, "send_alert",
                        lambda **kw: sent.append(kw))
    adapter = _FakeAdapter([], search_failures=5, search_failure_codes={430: 5})
    _run_main(monkeypatch, tmp_path, adapter=adapter, dry_run=True,
              players=_BLACKOUT_PLAYERS)
    assert sent == []
