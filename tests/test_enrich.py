from bullet_in.enrich import enrich_rows

class FakeModels:
    def generate_content(self, **kw):
        class R: pass
        r = R(); r.text = '{"title_ko":"제목","summary_ko":"요약"}'
        return r
class FakeClient:
    def __init__(self): self.models = FakeModels()

def test_enrich_translates_missing_rows():
    rows = [{"content_hash": "h1", "title_original": "Title", "body_excerpt": "Body"}]
    out = enrich_rows(rows, client=FakeClient(), model="gemini-2.5-flash-lite")
    assert out["h1"] == ("제목", "요약")

def test_enrich_skips_when_no_rows():
    assert enrich_rows([], client=FakeClient(), model="gemini-2.5-flash-lite") == {}

def test_enrich_handles_code_fenced_json():
    class M:
        def generate_content(self, **kw):
            class R: pass
            r = R(); r.text = '```json\n{"title_ko":"제","summary_ko":"요"}\n```'
            return r
    class C:
        def __init__(self): self.models = M()
    out = enrich_rows([{"content_hash":"h","title_original":"T","body_excerpt":""}], C(), "gemini-2.5-flash-lite")
    assert out["h"] == ("제", "요")

def test_enrich_skips_bad_row_without_aborting_batch():
    class M:
        def __init__(self): self.n = 0
        def generate_content(self, **kw):
            self.n += 1
            class R: pass
            r = R()
            r.text = "garbage no json" if self.n == 1 else '{"title_ko":"제","summary_ko":"요"}'
            return r
    class C:
        def __init__(self): self.models = M()
    rows = [{"content_hash":"bad","title_original":"A","body_excerpt":""},
            {"content_hash":"ok","title_original":"B","body_excerpt":""}]
    out = enrich_rows(rows, C(), "gemini-2.5-flash-lite")
    assert "bad" not in out and out["ok"] == ("제", "요")
