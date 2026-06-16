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

from bullet_in.enrich import partition_translation_rows

def test_partition_splits_ko_and_en_by_source_lang():
    rows = [
        {"content_hash": "k", "source_id": "fmkorea", "title_original": "한글", "body_excerpt": "본문"},
        {"content_hash": "e", "source_id": "bbc_sport", "title_original": "Eng", "body_excerpt": "b"},
    ]
    sources = {"fmkorea": {"lang": "ko"}, "bbc_sport": {"tier": 1}}
    ko, en = partition_translation_rows(rows, sources)
    assert [r["content_hash"] for r in ko] == ["k"]
    assert [r["content_hash"] for r in en] == ["e"]

from bullet_in.enrich import summarize_ko_rows

import logging
import bullet_in.enrich as enrich_mod

class _RateLimit(Exception):
    code = 429

def test_enrich_retries_rate_limit_then_succeeds(monkeypatch):
    monkeypatch.setattr(enrich_mod.time, "sleep", lambda s: None)
    class M:
        def __init__(self): self.n = 0
        def generate_content(self, **kw):
            self.n += 1
            if self.n == 1:
                raise _RateLimit("429 RESOURCE_EXHAUSTED")
            class R: pass
            r = R(); r.text = '{"title_ko":"제","summary_ko":"요"}'
            return r
    class C:
        def __init__(self): self.models = M()
    c = C()
    out = enrich_rows([{"content_hash":"h","title_original":"T","body_excerpt":""}], c, "m")
    assert out["h"] == ("제", "요")
    assert c.models.n == 2  # 429 후 재시도해 성공

def test_enrich_skips_and_logs_persistent_rate_limit(monkeypatch, caplog):
    monkeypatch.setattr(enrich_mod.time, "sleep", lambda s: None)
    class M:
        def generate_content(self, **kw):
            raise _RateLimit("429 RESOURCE_EXHAUSTED")
    class C:
        def __init__(self): self.models = M()
    with caplog.at_level(logging.WARNING):
        out = enrich_rows([{"content_hash":"h","title_original":"T","body_excerpt":""}], C(), "m")
    assert out == {}
    assert any("429" in r.message or "rate limit" in r.message.lower()
               for r in caplog.records)

def test_summarize_ko_rows_retries_rate_limit_then_succeeds(monkeypatch):
    monkeypatch.setattr(enrich_mod.time, "sleep", lambda s: None)
    class M:
        def __init__(self): self.n = 0
        def generate_content(self, **kw):
            self.n += 1
            if self.n == 1:
                raise _RateLimit("429")
            class R: pass
            r = R(); r.text = '{"summary_ko":"요약"}'
            return r
    class C:
        def __init__(self): self.models = M()
    c = C()
    out = summarize_ko_rows([{"content_hash":"h","title_original":"T","body_excerpt":""}], c, "m")
    assert out == {"h": "요약"} and c.models.n == 2

def test_summarize_ko_rows_returns_korean_summary():
    class M:
        def generate_content(self, **kw):
            class R: pass
            r = R(); r.text = '{"summary_ko":"사카 재계약 임박"}'
            return r
    class C:
        def __init__(self): self.models = M()
    rows = [{"content_hash": "h", "title_original": "사카 재계약", "body_excerpt": "본문"}]
    out = summarize_ko_rows(rows, C(), "gemini-2.5-flash-lite")
    assert out == {"h": "사카 재계약 임박"}

def test_summarize_ko_rows_skips_bad_row_without_aborting_batch():
    class M:
        def __init__(self): self.n = 0
        def generate_content(self, **kw):
            self.n += 1
            class R: pass
            r = R()
            r.text = "garbage no json" if self.n == 1 else '{"summary_ko":"요약"}'
            return r
    class C:
        def __init__(self): self.models = M()
    rows = [{"content_hash": "bad", "title_original": "A", "body_excerpt": ""},
            {"content_hash": "ok", "title_original": "B", "body_excerpt": ""}]
    out = summarize_ko_rows(rows, C(), "gemini-2.5-flash-lite")
    assert "bad" not in out and out["ok"] == "요약"
