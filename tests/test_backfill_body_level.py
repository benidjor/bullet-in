from bullet_in import backfill_body_level as bl


def test_level_zero_when_body_empty():
    assert bl.level_for("fmkorea", "The Athletic", "") == 0
    assert bl.level_for("bbc_sport", "BBC", None) == 0


def test_level_one_for_paywalled_fmkorea_row():
    # 페이월 소스는 원문을 못 받아 게시글 본문을 채택했다 — 커뮤니티가 옮긴 본문
    assert bl.level_for("fmkorea", "The Athletic", "옮긴 본문") == 1


def test_level_two_for_free_fmkorea_row():
    # 페이월이 아니면 원문 URL 에서 본문을 받았다
    assert bl.level_for("fmkorea", "BBC", "Arsenal news.") == 2


def test_level_two_for_other_sources():
    assert bl.level_for("bbc_gossip", None, "Gossip line.") == 2
    assert bl.level_for("x_afcstuff", "The Telegraph", "Article body.") == 2


def test_paywalled_rule_comes_from_adapter_constant():
    # 규칙을 옮겨 적지 않는다 — 어댑터 상수를 그대로 쓴다
    from bullet_in.adapters.fmkorea import PAYWALLED_OUTLETS
    assert bl.PAYWALLED_OUTLETS is PAYWALLED_OUTLETS


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
        if params and "lv" in params:
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


_ROWS = [{"content_hash": "h1", "source_id": "fmkorea", "outlet": "The Athletic",
          "body_source": "옮긴 본문"},
         {"content_hash": "h2", "source_id": "fmkorea", "outlet": "BBC",
          "body_source": "Arsenal news."},
         {"content_hash": "h3", "source_id": "fmkorea", "outlet": "The Telegraph",
          "body_source": None}]


def test_backfill_writes_one_level_per_row(monkeypatch):
    eng = _FakeEngine(_ROWS)
    monkeypatch.setattr(bl, "create_engine", lambda *a, **k: eng)
    monkeypatch.setenv("MARIADB_URL", "mysql://unused")
    stats = bl.backfill()
    assert stats == {0: 1, 1: 1, 2: 1}
    assert [(u["h"], u["lv"]) for u in eng.updates] == [("h1", 1), ("h2", 2), ("h3", 0)]


def test_backfill_dry_run_writes_nothing(monkeypatch):
    eng = _FakeEngine(_ROWS)
    monkeypatch.setattr(bl, "create_engine", lambda *a, **k: eng)
    monkeypatch.setenv("MARIADB_URL", "mysql://unused")
    assert bl.backfill(dry_run=True) == {0: 1, 1: 1, 2: 1}
    assert eng.updates == []
