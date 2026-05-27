from bullet_in.enrich import enrich_rows

class FakeMessages:
    def create(self, **kw):
        class R: pass
        r = R(); r.content = [type("B", (), {"text": '{"title_ko":"제목","summary_ko":"요약"}'})()]
        return r
class FakeClient:
    def __init__(self): self.messages = FakeMessages()

def test_enrich_translates_missing_rows():
    rows = [{"content_hash": "h1", "title_original": "Title", "body_excerpt": "Body"}]
    out = enrich_rows(rows, client=FakeClient(), model="claude-haiku-4-5")
    assert out["h1"] == ("제목", "요약")

def test_enrich_skips_when_no_rows():
    assert enrich_rows([], client=FakeClient(), model="claude-haiku-4-5") == {}

def test_enrich_handles_code_fenced_json():
    class M:
        def create(self, **kw):
            class R: pass
            r = R(); r.content = [type("B", (), {"text": '```json\n{"title_ko":"제","summary_ko":"요"}\n```'})()]
            return r
    class C:
        def __init__(self): self.messages = M()
    out = enrich_rows([{"content_hash":"h","title_original":"T","body_excerpt":""}], C(), "claude-haiku-4-5")
    assert out["h"] == ("제", "요")

def test_enrich_skips_bad_row_without_aborting_batch():
    class M:
        def __init__(self): self.n = 0
        def create(self, **kw):
            self.n += 1
            class R: pass
            r = R()
            txt = "garbage no json" if self.n == 1 else '{"title_ko":"제","summary_ko":"요"}'
            r.content = [type("B", (), {"text": txt})()]
            return r
    class C:
        def __init__(self): self.messages = M()
    rows = [{"content_hash":"bad","title_original":"A","body_excerpt":""},
            {"content_hash":"ok","title_original":"B","body_excerpt":""}]
    out = enrich_rows(rows, C(), "claude-haiku-4-5")
    assert "bad" not in out and out["ok"] == ("제", "요")
