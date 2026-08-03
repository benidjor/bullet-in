from bullet_in.backfill_rewrite import run


class _Mart:
    def __init__(self, rows):
        self._rows = rows
        self.saved = {}
        self.retentions = {}

    def rows_rewritten(self):
        return list(self._rows)

    def set_translation(self, h, t, s, s3, b):
        self.saved[h] = (t, s, s3, b)

    def set_rewrite_retention(self, h, r):
        self.retentions[h] = r


class _Msg:
    def __init__(self, text):
        self.text = text


class _Models:
    def __init__(self):
        self.calls = 0

    def generate_content(self, model, contents, config):
        self.calls += 1
        return _Msg('{"title_ko":"새 제목","summary_ko":"새 요약",'
                    '"summary3_ko":["1","2","3"],'
                    '"body_ko":"아스날이 영입을 마무리한다.","players":[]}')


class _Client:
    def __init__(self):
        self.models = _Models()


ROWS = [{"content_hash": "h1", "source_id": "fmkorea", "title_original": "아스날 영입",
         "body_source": "아스날이 영입을 마무리한다.", "body_level": 1,
         "summary_ko": "옛 요약", "body_excerpt": None, "url": "u", "outlet": "BBC"},
        {"content_hash": "h2", "source_id": "fmkorea", "title_original": "아스날 잔류",
         "body_source": "아스날이 잔류를 확정한다.", "body_level": 1,
         "summary_ko": "옛 요약", "body_excerpt": None, "url": "u", "outlet": "BBC"}]


def test_backfill_rewrites_and_saves():
    mart, client = _Mart(ROWS), _Client()
    done, total = run(mart, client, "m", glossary={}, name_map={}, club_map={})
    assert (done, total) == (2, 2)
    assert mart.saved["h1"][0] == "새 제목"
    assert "h1" in mart.retentions


def test_backfill_limit_caps_rows():
    mart, client = _Mart(ROWS), _Client()
    done, total = run(mart, client, "m", glossary={}, name_map={}, club_map={},
                      limit=1)
    assert (done, total) == (1, 1)
    assert list(mart.saved) == ["h1"]


def test_backfill_dry_run_saves_nothing():
    mart, client = _Mart(ROWS), _Client()
    done, total = run(mart, client, "m", glossary={}, name_map={}, club_map={},
                      dry_run=True)
    assert (done, total) == (2, 2)
    assert mart.saved == {}
    assert mart.retentions == {}
