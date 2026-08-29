from bullet_in.enrich import apply_glossary, enrich_rows, extract_players_rows

class FullClient:
    """백필 테스트용 — 사전 payload 반환 클라이언트."""
    def __init__(self, payload):
        self.models = self
        self.payload = payload

    def generate_content(self, **kw):
        class R: pass
        r = R()
        r.text = __import__('json').dumps(self.payload)
        return r

class FakeModels:
    def generate_content(self, **kw):
        class R: pass
        r = R(); r.text = '{"title_ko":"제목","summary_ko":"요약","summary3_ko":["①","②","③"],"body_ko":"본문"}'
        return r
class FakeClient:
    def __init__(self): self.models = FakeModels()

def test_enrich_translates_missing_rows():
    rows = [{"content_hash": "h1", "title_original": "Title", "body_excerpt": "Body"}]
    out = enrich_rows(rows, client=FakeClient(), model="gemini-2.5-flash-lite")
    assert out["h1"]["title_ko"] == "제목"
    assert out["h1"]["summary_ko"] == "요약"
    assert out["h1"]["summary3_ko"] == "①\n②\n③"
    assert out["h1"]["body_ko"] == "본문"

def test_enrich_skips_when_no_rows():
    assert enrich_rows([], client=FakeClient(), model="gemini-2.5-flash-lite") == {}

def test_enrich_handles_code_fenced_json():
    class M:
        def generate_content(self, **kw):
            class R: pass
            r = R(); r.text = '```json\n{"title_ko":"제","summary_ko":"요","summary3_ko":["a","b","c"],"body_ko":"b"}\n```'
            return r
    class C:
        def __init__(self): self.models = M()
    out = enrich_rows([{"content_hash":"h","title_original":"T","body_excerpt":""}], C(), "gemini-2.5-flash-lite")
    assert out["h"]["title_ko"] == "제"
    assert out["h"]["summary_ko"] == "요"
    assert out["h"]["summary3_ko"] == "a\nb\nc"
    assert out["h"]["body_ko"] == "b"

def test_enrich_skips_bad_row_without_aborting_batch():
    class M:
        def __init__(self): self.n = 0
        def generate_content(self, **kw):
            self.n += 1
            class R: pass
            r = R()
            # 재시도 셋을 다 쓰고도 못 읽는 행이라야 스킵된다 (안건 ψ 이후)
            r.text = "garbage no json" if self.n <= 3 else '{"title_ko":"제","summary_ko":"요","summary3_ko":["a","b","c"],"body_ko":"b"}'
            return r
    class C:
        def __init__(self): self.models = M()
    rows = [{"content_hash":"bad","title_original":"A","body_excerpt":""},
            {"content_hash":"ok","title_original":"B","body_excerpt":""}]
    out = enrich_rows(rows, C(), "gemini-2.5-flash-lite")
    assert "bad" not in out
    assert out["ok"]["title_ko"] == "제"
    assert out["ok"]["summary_ko"] == "요"
    assert out["ok"]["summary3_ko"] == "a\nb\nc"
    assert out["ok"]["body_ko"] == "b"

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

class _RateLimit(Exception):
    code = 429

def test_enrich_stops_and_logs_on_rate_limit(caplog):
    # 429를 만나면 그 회차는 즉시 중단하고 남은 행은 호출하지 않는다(다음 사이클 누적).
    class M:
        def __init__(self): self.n = 0
        def generate_content(self, **kw):
            self.n += 1
            raise _RateLimit("429 RESOURCE_EXHAUSTED")
    class C:
        def __init__(self): self.models = M()
    c = C()
    rows = [{"content_hash":"a","title_original":"A","body_excerpt":""},
            {"content_hash":"b","title_original":"B","body_excerpt":""}]
    with caplog.at_level(logging.WARNING):
        out = enrich_rows(rows, c, "m")
    assert out == {}
    assert c.models.n == 1  # 둘째 행은 호출조차 안 함
    assert any("429" in r.message or "rate limit" in r.message.lower()
               for r in caplog.records)

def test_summarize_ko_rows_stops_and_logs_on_rate_limit(caplog):
    class M:
        def __init__(self): self.n = 0
        def generate_content(self, **kw):
            self.n += 1
            raise _RateLimit("429")
    class C:
        def __init__(self): self.models = M()
    c = C()
    rows = [{"content_hash":"a","title_original":"A","body_excerpt":""},
            {"content_hash":"b","title_original":"B","body_excerpt":""}]
    with caplog.at_level(logging.WARNING):
        out = summarize_ko_rows(rows, c, "m")
    assert out == {}
    assert c.models.n == 1
    assert any("429" in r.message or "rate limit" in r.message.lower()
               for r in caplog.records)

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

import json as _json

class FullModels:
    def __init__(self, payload): self._p = payload; self.n = 0
    def generate_content(self, **kw):
        self.n += 1
        class R: pass
        r = R(); r.text = _json.dumps(self._p, ensure_ascii=False); return r
class FullClient:
    def __init__(self, payload): self.models = FullModels(payload)

def test_enrich_returns_four_fields():
    payload = {"title_ko": "아스날, 요케레스 영입", "summary_ko": "6천만에 영입",
               "summary3_ko": ["발표", "이적료 6천만", "5년 계약"], "body_ko": "전체 본문"}
    rows = [{"content_hash": "h1", "title_original": "Arsenal sign", "body_source": "Body"}]
    out = enrich_rows(rows, FullClient(payload), "m")
    assert out["h1"]["title_ko"] == "아스날, 요케레스 영입"
    assert out["h1"]["summary_ko"] == "6천만에 영입"
    assert out["h1"]["summary3_ko"] == "발표\n이적료 6천만\n5년 계약"  # 배열 → \n join
    assert out["h1"]["body_ko"] == "전체 본문"

def test_enrich_skips_row_missing_keys():
    payload = {"title_ko": "제목"}  # 키 부족
    out = enrich_rows([{"content_hash": "h", "title_original": "T", "body_source": ""}],
                      FullClient(payload), "m")
    assert "h" not in out

def test_enrich_paraphrase_mode_uses_paraphrase_prompt():
    payload = {"title_ko": "T", "summary_ko": "S", "summary3_ko": ["a", "b", "c"], "body_ko": "B"}
    client = FullClient(payload)
    rows = [{"content_hash": "h", "title_original": "[디 애슬레틱] 제목", "body_source": "한국어 본문"}]
    out = enrich_rows(rows, client, "m", mode="paraphrase")
    assert out["h"]["body_ko"] == "B"  # 정상 처리됨

from bullet_in.enrich import classify_stage_rows


class _StageModels:
    def __init__(self, text, exc=None):
        self._t = text; self._exc = exc; self.n = 0
    def generate_content(self, **kw):
        self.n += 1
        if self._exc:
            raise self._exc
        class R: pass
        r = R(); r.text = self._t; return r


class _StageClient:
    def __init__(self, text, exc=None): self.models = _StageModels(text, exc)


def test_classify_returns_stage_and_direction():
    payload = ('[{"content_hash":"a","stage":"negotiating","direction":"in"},'
               '{"content_hash":"b","stage":"agreed","direction":"out"}]')
    rows = [{"content_hash": "a", "title_original": "Arsenal in talks", "summary_ko": "협상"},
            {"content_hash": "b", "title_original": "Trossard exit agreed", "summary_ko": "합의"}]
    out = classify_stage_rows(rows, _StageClient(payload), "m")
    assert out == {"a": ("negotiating", "in"), "b": ("agreed", "out")}


def test_classify_demotes_invalid_stage_to_other():
    payload = '[{"content_hash":"a","stage":"bogus","direction":"in"}]'
    out = classify_stage_rows([{"content_hash": "a", "title_original": "T", "summary_ko": ""}],
                              _StageClient(payload), "m")
    assert out == {"a": ("other", "in")}


def test_classify_demotes_invalid_or_missing_direction_to_none():
    # direction 이 허용 밖 값이거나 응답에 아예 없으면 none 강등 (모호 → 무표시가 안전)
    payload = ('[{"content_hash":"a","stage":"rumour","direction":"sideways"},'
               '{"content_hash":"b","stage":"rumour"}]')
    rows = [{"content_hash": "a", "title_original": "A", "summary_ko": ""},
            {"content_hash": "b", "title_original": "B", "summary_ko": ""}]
    out = classify_stage_rows(rows, _StageClient(payload), "m")
    assert out == {"a": ("rumour", "none"), "b": ("rumour", "none")}


def test_classify_demotes_official_to_done():
    """프롬프트에 없어도 모델이 official을 뱉으면 done으로 강등 — 타 매체의 "오피셜"
    보도는 새 체계에서 완료 계열이다 (단계 재정의 스펙 2026-08-10 §4)."""
    payload = '[{"content_hash":"h1","stage":"official","direction":"in"}]'
    rows = [{"content_hash": "h1", "title_original": "t", "summary_ko": "s"}]
    out = classify_stage_rows(rows, _StageClient(payload), "m")
    assert out == {"h1": ("done", "in")}


def test_classify_omits_missing_hashes():
    payload = '[{"content_hash":"a","stage":"rumour","direction":"none"}]'   # b 누락
    rows = [{"content_hash": "a", "title_original": "A", "summary_ko": ""},
            {"content_hash": "b", "title_original": "B", "summary_ko": ""}]
    out = classify_stage_rows(rows, _StageClient(payload), "m")
    assert out == {"a": ("rumour", "none")}   # b는 NULL 유지 (다음 사이클 재시도)


def test_classify_skips_unparseable_batch():
    out = classify_stage_rows([{"content_hash": "a", "title_original": "A", "summary_ko": ""}],
                              _StageClient("not json"), "m")
    assert out == {}


def test_classify_batches_by_size():
    payload = '[{"content_hash":"a","stage":"rumour"}]'
    client = _StageClient(payload)
    rows = [{"content_hash": f"h{i}", "title_original": "T", "summary_ko": ""} for i in range(5)]
    classify_stage_rows(rows, client, "m", batch_size=2)
    assert client.models.n == 3   # 5건 → 2+2+1 = 3 배치


def test_classify_stops_on_rate_limit():
    class _RL(Exception):
        code = 429
    client = _StageClient("", exc=_RL("429"))
    rows = [{"content_hash": f"h{i}", "title_original": "T", "summary_ko": ""} for i in range(5)]
    out = classify_stage_rows(rows, client, "m", batch_size=2)
    assert out == {}
    assert client.models.n == 1   # 첫 배치에서 중단


def test_stage_prompt_lists_llm_stages_and_excludes_official():
    """STAGE_PROMPT는 LLM 분류 대상 enum 전부를 포함하되 official은 제외한다.
    official은 공홈 소스 규칙 전용 (spec §4.1) — 프롬프트에 등장하면 규칙 분리가 깨진 것."""
    from bullet_in import transfer_stage as ts
    from bullet_in.enrich import STAGE_PROMPT
    for enum in sorted(ts.VALID_STAGES - {"official"}):
        assert enum in STAGE_PROMPT, f"STAGE_PROMPT가 {enum} 단계를 누락 — transfer_stage와 동기화 필요"
    assert "official" not in STAGE_PROMPT

def test_stage_prompt_disambiguates_reached_agreement_as_agreed():
    """'합의 도달' 표현(구두 합의·원칙적 합의 등)이 negotiating이 아니라 agreed로 가도록
    프롬프트가 경계를 명확화한다 (B2 — cc2c7b58 오분류 방지)."""
    from bullet_in.enrich import STAGE_PROMPT
    assert "구두 합의" in STAGE_PROMPT
    assert "원칙적 합의" in STAGE_PROMPT

def test_stage_prompt_splits_agreement_by_party():
    """합의 보도는 당사자로 가른다 — 구단 간이면 agreed, 선수-구단이면 personal_terms
    (2026-07-27 사용자 확정 기준). 구두 합의만 보고 한쪽으로 몰리던 오분류 방지."""
    from bullet_in.enrich import STAGE_PROMPT
    assert "구단과 구단이면 agreed, 선수와 구단이면 personal_terms" in STAGE_PROMPT
    assert "구두 합의라도 당사자가 선수-구단이면 여기" in STAGE_PROMPT

def test_stage_prompt_keeps_other_for_non_transfer_only():
    """other 는 이적 무관 글 전용 — 무산 · 몸값 · 분쟁 · 대안 후보 보도는 단계를 받는다.
    2026-08-02 실측 16건 (other 버킷에 남은 이적 기사) 의 경계 유형 보강."""
    from bullet_in.enrich import STAGE_PROMPT
    assert "other 는 이적과 정말 무관한 글에만 쓴다" in STAGE_PROMPT
    # 잔류 확정은 2026-08-10 재정의로 collapsed 소관이 되어 이 목록에서 빠졌다
    for boundary in ("무산 · 결렬 · 포기 · 이적설 부인",
                     "몸값 · 이적료 책정 보도",
                     "분쟁 · 법적 절차",
                     "대안 후보군 · 연쇄 반응"):
        assert boundary in STAGE_PROMPT, f"STAGE_PROMPT 가 경계 유형 '{boundary}' 를 누락"


def test_stage_prompt_keeps_roundups_and_non_transfer_news_as_other():
    """other 완화가 이적 아닌 글까지 끌어가지 않도록 제외 목록을 함께 못 박는다.
    2026-08-02 표적 재분류에서 스폰서십 계약 2건 · 재계약 1건 · 서비스 공지 1건이
    단계를 받은 과교정을 실측해 추가한 규칙이다."""
    from bullet_in.enrich import STAGE_PROMPT
    assert "시장 라운드업 · 총평 · 칼럼은 대표 단계가 성립하지 않으므로 other" in STAGE_PROMPT
    for excluded in ("스폰서십 · 유니폼 · 중계권 같은 상업 계약",
                     "소속 구단과의 재계약 · 계약 연장",
                     "감독 · 스태프 인사",
                     "기사가 아닌 공지 · 안내 · 목록 링크"):
        assert excluded in STAGE_PROMPT, f"STAGE_PROMPT 가 이적 아닌 유형 '{excluded}' 를 누락"


def test_stage_prompt_covers_non_arsenal_transfers():
    """타 구단 간 이적 기사도 그 이적의 단계로 분류한다 — 아스날이 주체가 아니라는 이유로
    other · negotiating 으로 새던 오분류 방지 (79b99b1b · 2f556abe 사례)."""
    from bullet_in.enrich import STAGE_PROMPT
    assert "이적 주체가 {club} 이 아니어도" in STAGE_PROMPT

def test_stage_prompt_keeps_done_and_collapsed_boundaries():
    """done · collapsed 신설 경계의 핵심 문장 회귀 가드 (단계 재정의 스펙 §4 · dry-run
    v1c 채택 — 문장을 고치면 소표본 재검증을 다시 거쳐야 한다, 시소 트러블슈팅 2026-08-08)."""
    from bullet_in.enrich import STAGE_PROMPT
    assert "명단은 보조 근거다" in STAGE_PROMPT                       # done 의 시차 원칙 (§5)
    assert "진행 중인 잔류·재계약 협상은 collapsed 가 아니다" in STAGE_PROMPT
    assert "거부한다는 방침 보도도 종결이 아니다" in STAGE_PROMPT      # 로메로 유형 차단
    assert "하이재킹 완결" in STAGE_PROMPT                            # §3.2 재조정 규칙
    assert "임박·근접 보도는 agreed 가 아니라 negotiating 이다" in STAGE_PROMPT

def test_stage_prompt_lists_directions_and_tie_rule():
    """프롬프트가 방향 3값 정의 · 임대 포괄 · 대등 혼합 out 우선을 담는다 (방향 축 스펙 §4.2)."""
    from bullet_in.enrich import STAGE_PROMPT
    for d in ("- in:", "- out:", "- none:"):
        assert d in STAGE_PROMPT, f"STAGE_PROMPT 가 방향 {d} 정의를 누락"
    assert "임대" in STAGE_PROMPT
    assert "대등" in STAGE_PROMPT

from bullet_in.enrich import resummarize_rows

def test_resummarize_returns_summary_fields_only():
    class M:
        def generate_content(self, **kw):
            class R: pass
            r = R(); r.text = '{"summary_ko":"확정했다.","summary3_ko":["a","b","c"]}'
            return r
    class C:
        def __init__(self): self.models = M()
    rows = [{"content_hash": "h", "title_original": "T",
             "title_ko": "제목", "body_ko": "본문"}]
    out = resummarize_rows(rows, C(), "gemini-2.5-flash-lite")
    assert out["h"] == {"summary_ko": "확정했다.", "summary3_ko": "a\nb\nc"}

def test_resummarize_stops_and_logs_on_rate_limit(caplog):
    class M:
        def __init__(self): self.n = 0
        def generate_content(self, **kw):
            self.n += 1
            raise _RateLimit("429")
    class C:
        def __init__(self): self.models = M()
    c = C()
    rows = [{"content_hash": "a", "title_original": "A", "body_ko": "b"},
            {"content_hash": "b", "title_original": "B", "body_ko": "b"}]
    with caplog.at_level(logging.WARNING):
        out = resummarize_rows(rows, c, "m")
    assert out == {}
    assert c.models.n == 1
    assert any("429" in r.message or "rate limit" in r.message.lower()
               for r in caplog.records)

def test_resummarize_skips_unparseable_row_without_aborting():
    class M:
        def __init__(self): self.n = 0
        def generate_content(self, **kw):
            self.n += 1
            class R: pass
            r = R()
            r.text = "garbage" if self.n == 1 else '{"summary_ko":"됐다.","summary3_ko":["a","b","c"]}'
            return r
    class C:
        def __init__(self): self.models = M()
    rows = [{"content_hash": "bad", "title_original": "A", "body_ko": "b"},
            {"content_hash": "ok", "title_original": "B", "body_ko": "b"}]
    out = resummarize_rows(rows, C(), "gemini-2.5-flash-lite")
    assert "bad" not in out
    assert out["ok"]["summary_ko"] == "됐다."

def test_all_prompts_carry_polite_ban_example():
    # 존댓말 금지 대비 예시가 프롬프트에서 빠지면 회귀 — 4종 모두 검사
    from bullet_in.enrich import (SUMMARY_PROMPT, TRANSLATE_PROMPT,
                                  PARAPHRASE_PROMPT, RESUMMARY_PROMPT)
    for p in (SUMMARY_PROMPT, TRANSLATE_PROMPT, PARAPHRASE_PROMPT, RESUMMARY_PROMPT):
        assert "했습니다" in p and "했다" in p

def test_resummarize_skips_empty_or_null_summary():
    # 빈/비문자열 summary_ko가 기존 요약을 덮어쓰지 않도록 행 단위 스킵 (M2 가드)
    class M:
        def __init__(self): self.n = 0
        def generate_content(self, **kw):
            self.n += 1
            class R: pass
            r = R()
            r.text = ('{"summary_ko":"","summary3_ko":["a","b","c"]}' if self.n == 1
                      else '{"summary_ko":null,"summary3_ko":["a","b","c"]}')
            return r
    class C:
        def __init__(self): self.models = M()
    rows = [{"content_hash": "empty", "title_original": "A", "body_ko": "b"},
            {"content_hash": "null", "title_original": "B", "body_ko": "b"}]
    out = resummarize_rows(rows, C(), "gemini-2.5-flash-lite")
    assert out == {}

def test_body_prompts_carry_plain_style_boilerplate_and_markdown_rules():
    # body_ko 평어체 대비 예시 · 인용문 예외 · 무관 문구 제외 · 경량 마크다운 지시가
    # 프롬프트에서 빠지면 회귀 — 번역 · 패러프레이즈 2종 모두 검사
    from bullet_in.enrich import TRANSLATE_PROMPT, PARAPHRASE_PROMPT
    for p in (TRANSLATE_PROMPT, PARAPHRASE_PROMPT):
        assert "갖고 있습니다" in p and "갖고 있다" in p
        assert "인용문" in p
        assert "무관한 문구" in p
        assert "###" in p and "**" in p and "> " in p

def test_body_prompts_instruct_paragraph_breaks():
    # 추출 평문화로 원문 문단이 소실되므로 번역이 2~4문장 문단으로 재구성해야 함
    from bullet_in.enrich import TRANSLATE_PROMPT, PARAPHRASE_PROMPT
    for p in (TRANSLATE_PROMPT, PARAPHRASE_PROMPT):
        assert "2~4문장" in p and "줄바꿈" in p

def test_apply_glossary_replaces_all_ko_fields():
    from bullet_in.enrich import apply_glossary
    mapping = {"메슬리에": "멜리에", "스캇": "스콧"}
    parsed = {"title_ko": "메슬리에 영입 임박", "summary_ko": "알렉스 스캇 관심.",
              "summary3_ko": "메슬리에가 온다.\n스캇도 온다.", "body_ko": "메슬리에는 골키퍼다."}
    out = apply_glossary(parsed, mapping)
    assert out["title_ko"] == "멜리에 영입 임박"
    assert out["summary_ko"] == "알렉스 스콧 관심."
    assert out["summary3_ko"] == "멜리에가 온다.\n스콧도 온다."
    assert out["body_ko"] == "멜리에는 골키퍼다."

def test_apply_glossary_ignores_missing_fields_and_empty_mapping():
    from bullet_in.enrich import apply_glossary
    parsed = {"title_ko": "제목", "summary_ko": None}
    assert apply_glossary(parsed, {}) == parsed
    assert apply_glossary(parsed, {"스캇": "스콧"})["summary_ko"] is None

def test_paragraphize_splits_long_block_at_sentence_ends():
    from bullet_in.enrich import paragraphize
    sent = "아스날이 여름 이적 시장에서 미드필더 보강을 위해 여러 후보를 검토하고 있는 것으로 알려졌다."  # 약 50자
    block = " ".join([sent] * 12)  # 600자 초과 단일 블록
    out = paragraphize(block)
    lines = out.split("\n")
    assert len(lines) >= 2
    assert all(len(l) <= 400 for l in lines)
    # 내용 보존: 공백 정규화 후 동일
    assert " ".join(out.split()) == " ".join(block.split())

def test_paragraphize_keeps_short_blocks_and_markdown():
    from bullet_in.enrich import paragraphize
    long_quote = "> " + "인용문이다. " * 60  # 400자 초과 인용 블록
    header = "### " + "소제목이다. " * 60   # 400자 초과 소제목 블록
    text = "짧은 문단이다.\n" + long_quote + "\n" + header
    assert paragraphize(text) == text

def test_paragraphize_does_not_split_on_decimal_point():
    from bullet_in.enrich import paragraphize
    sent = "이적료는 총 2.5천만 파운드에 이르는 것으로 전해졌으며 협상은 막바지 단계다."
    block = " ".join([sent] * 12)
    out = paragraphize(block)
    assert not any(l.rstrip().endswith("2.") for l in out.split("\n"))

def test_split_sentences_breaks_after_closing_curly_quote():
    """굽은따옴표로 끝나는 문장도 분할된다.
    이 경로가 조용히 깨진 적이 있다 (2026-08-03) — 전 테스트가 통과하는 채로."""
    from bullet_in.enrich import _split_sentences
    assert _split_sentences('그는 말했다.” 그리고 떠났다.') == [
        '그는 말했다.”', '그리고 떠났다.']

def test_paragraphize_passthrough_none_empty_and_unsplittable():
    from bullet_in.enrich import paragraphize
    assert paragraphize(None) is None
    assert paragraphize("") == ""
    one_sentence = "가" * 500 + "."  # 문장 경계 없는 500자
    assert paragraphize(one_sentence) == one_sentence

def test_detect_title_hallucination_flags_name_absent_from_source():
    from bullet_in.enrich import detect_title_hallucination
    name_map = {"펠레그리니": "Pellegrini", "촐리스": "Tzolis"}
    # 실사례 (id 365): 원문에 없는 펠레그리니가 제목에 생성
    title_ko = "아스날, 펠레그리니 영입 위해 펠레그리니 포함 제안 검토"
    src = "Arsenal weigh player-plus-cash offer for Christos Tzolis. Arsenal are ..."
    assert detect_title_hallucination(title_ko, src, name_map) == ["펠레그리니"]

def test_detect_title_hallucination_passes_when_source_has_name():
    from bullet_in.enrich import detect_title_hallucination
    name_map = {"요케레스": "Gyokeres", "트로사르": "Trossard"}
    # 원문 diacritics (Gyökeres) 도 정규화 후 매치돼야 함
    title_ko = "요케레스, 아스날 이적 임박"
    src = "Viktor Gyökeres is close to joining Arsenal."
    assert detect_title_hallucination(title_ko, src, name_map) == []

def test_detect_title_hallucination_passes_korean_source():
    from bullet_in.enrich import detect_title_hallucination
    name_map = {"펠레그리니": "Pellegrini"}
    # 한국어 원문 (fmkorea paraphrase 경로): 한글 표기가 원문에 있으면 통과
    title_ko = "펠레그리니, 아스날행 루머"
    src = "[오피셜] 펠레그리니 아스날 이적 협상 중이라고 함"
    assert detect_title_hallucination(title_ko, src, name_map) == []

def test_detect_title_hallucination_empty_inputs():
    from bullet_in.enrich import detect_title_hallucination
    assert detect_title_hallucination(None, "src", {"a": "b"}) == []
    assert detect_title_hallucination("제목", "src", {}) == []

def test_detect_roundup_omission_flags_missing_attribution_item():
    from bullet_in.enrich import detect_roundup_omission
    src = ("A move. (Teamtalk) , external B move. (Sky Sports) , external "
           "C move. (Guardian) , external")
    ko = "A 이적. (Teamtalk)\nC 이적. (Guardian)"
    assert detect_roundup_omission(src, ko) == ["Sky Sports"]

def test_detect_roundup_omission_passes_when_all_kept_and_non_roundup():
    from bullet_in.enrich import detect_roundup_omission
    src = "A move. (Teamtalk) , external B move. (Sky Sports) , external"
    ko = "A 이적. (Teamtalk)\nB 이적. (Sky Sports)"
    assert detect_roundup_omission(src, ko) == []
    # 비 라운드업 (', external' 표지 없음) — 일반 괄호 (£50.9m) 는 무시
    assert detect_roundup_omission("fee of 60m euros (£50.9m).", "번역문") == []
    assert detect_roundup_omission(None, None) == []

def test_detect_roundup_omission_strips_attribution_suffix():
    from bullet_in.enrich import detect_roundup_omission
    src = "A move. (Corriere dello Sport - in Italian) , external"
    ko = "A 이적. (Corriere dello Sport)"
    assert detect_roundup_omission(src, ko) == []

def test_detect_roundup_omission_counts_duplicate_outlets():
    from bullet_in.enrich import detect_roundup_omission
    src = "A. (Sky Sports) , external B. (Sky Sports) , external"
    ko = "A. (Sky Sports)"   # 같은 출처 단신 2건 중 1건 누락
    assert detect_roundup_omission(src, ko) == ["Sky Sports"]

def test_detect_roundup_omission_normalizes_attribution_variants():
    from bullet_in.enrich import detect_roundup_omission
    src = ("A. (L'Equipe, in French) , external "
           "B. (Corriere dello Sport via Football Italia) , external "
           "C. (Football Insider) , external")
    ko = "A. (L'Equipe)\nB. (Corriere dello Sport)\nC. (Football Insider)"
    assert detect_roundup_omission(src, ko) == []

def test_detect_title_mistranslation_flags_missing_registered_name():
    from bullet_in.enrich import detect_title_mistranslation
    name_map = {"촐리스": "Tzolis"}
    # 실사례 (id 385): 원문 제목의 Tzolis 가 번역 제목에서 '조르제' 로 창작
    out = detect_title_mistranslation(
        "아스날, 클럽 브뤼허 공격수 조르제 영입 근접",
        "Arsenal close in on £34m deal for Club Brugge forward Christos Tzolis",
        name_map)
    assert out == ["인명 누락:Tzolis"]

def test_detect_title_mistranslation_word_boundary_avoids_price_rice():
    from bullet_in.enrich import detect_title_mistranslation
    name_map = {"라이스": "Rice"}
    # 'price' 안의 'rice' 는 단어 경계 밖 — 오탐 금지
    assert detect_title_mistranslation(
        "아스날, 이적료 책정", "Arsenal told asking price for star", name_map) == []

def test_detect_title_mistranslation_flags_unfounded_loan():
    from bullet_in.enrich import detect_title_mistranslation
    # 실사례 (id 392): permanent deal → '임대 이적 확정'
    out = detect_title_mistranslation(
        "트로사르, 베식타스 임대 이적 확정",
        "Trossard leaves Arsenal for Besiktas in permanent deal", {})
    assert out == ["임대 무근거"]
    # 원문에 loan 있으면 통과
    assert detect_title_mistranslation(
        "선수, 임대 이적", "Player joins on loan", {}) == []
    # 한국어 원문 (fmkorea) 에 '임대' 있으면 통과
    assert detect_title_mistranslation(
        "선수, 임대 이적", "[오피셜] 선수 임대 이적 확정", {}) == []

def test_detect_title_mistranslation_passes_variant_spelling_same_person():
    from bullet_in.enrich import detect_title_mistranslation
    name_map = {"래시포드": "Rashford", "라시포드": "Rashford"}
    # 같은 인물의 다른 등재 표기가 제목에 있으면 통과
    assert detect_title_mistranslation(
        "라시포드, 아스날행?", "Rashford to Arsenal?", name_map) == []

def test_detect_title_mistranslation_empty_inputs():
    from bullet_in.enrich import detect_title_mistranslation
    assert detect_title_mistranslation(None, "t", {"a": "B"}) == []
    assert detect_title_mistranslation("제목", None, {"a": "B"}) == []

def test_detect_title_mistranslation_passes_partial_name_condensation():
    from bullet_in.enrich import detect_title_mistranslation
    name_map = {"아르테타": "Arteta", "로저스": "Rogers"}
    # 다절 제목 (트윗 · 리스트클) 의 축약 — 매핑 인명 일부라도 유지되면 통과
    assert detect_title_mistranslation(
        "아스날, 로저스 영입 경쟁서 첼시에 밀려",
        "talkSPORT understands that Mikel Arteta met Morgan Rogers for talks",
        name_map) == []

def test_detect_title_mistranslation_ignores_surname_without_fullname_context():
    from bullet_in.enrich import detect_title_mistranslation
    name_map = {"화이트": "White"}
    # 실사례 3740329594: 'white flag' 관용구를 벤 화이트로 오인해 하루 8회 재큐됐다.
    # 원문 어디에도 '이름 + 성' 형태가 없으므로 인명으로 세지 않는다.
    assert detect_title_mistranslation(
        "백기: 아스날, 비니시우스 주니오르 영입 포기",
        "White flag: Arsenal give up on Vinicius Junior deal",
        name_map) == []

def test_detect_title_mistranslation_ignores_stopword_before_surname():
    from bullet_in.enrich import detect_title_mistranslation
    name_map = {"아르테타": "Arteta"}
    # 실사례 7341690b: 문장 첫머리 'With' 를 이름의 일부로 세던 오탐.
    # 2026-07-23 재번역 5회 진단에서 좋은 제목이 거부되는 것이 확인됐다.
    assert detect_title_mistranslation(
        "아스날 · 첼시 · 맨유 노리는 알렉스 스콧, 리버풀 영입전 가세",
        "With Arteta's Backing: Liverpool Compete Strongly to Snatch "
        "Target of Chelsea, Arsenal and United",
        name_map) == []

def test_detect_title_mistranslation_flags_when_fullname_in_body():
    from bullet_in.enrich import detect_title_mistranslation
    name_map = {"화이트": "White"}
    # 본문에 'Ben White' 가 있으면 인명 근거가 서므로 축이 그대로 작동해야 한다.
    out = detect_title_mistranslation(
        "아스날, 수비수 계약 임박",
        "White nears new Arsenal deal",
        name_map,
        "Ben White is closing in on fresh terms at the Emirates.")
    assert out == ["인명 누락:White"]

def test_detect_title_mistranslation_name_context_ignores_diacritics():
    from bullet_in.enrich import detect_title_mistranslation
    name_map = {"기마랑이스": "Guimaraes"}
    # 원문이 발음 부호로 쓰더라도 'Bruno Guimarães' 는 인명 근거로 인정한다
    # (_fold_latin 은 casefold 까지 해서 앞 단어의 대문자 여부를 못 가린다).
    out = detect_title_mistranslation(
        "아스날, 뉴캐슬 미드필더 영입 근접",
        "Arsenal close on Bruno Guimarães deal",
        name_map)
    assert out == ["인명 누락:Guimaraes"]

def test_detect_club_injection_flags_unfounded_club():
    from bullet_in.enrich import detect_club_injection
    club_map = {"미들즈브러": ["Middlesbrough", "Boro"],
                "아스톤 빌라": ["Aston Villa", "Villa"]}
    # 실사례 (9956234a): 원문은 Aston Villa 소속 명시, 번역이 학습 지식 (전 소속) 주입
    parsed = {"title_ko": "아스날, 3000만 파운드 미들즈브러 FW 영입 임박",
              "summary_ko": None,
              "summary3_ko": "미들즈브러의 모건 로저스가 링크됐다.",
              "body_ko": "아스톤 빌라가 로저스의 몸값을 책정했다."}
    src = "Aston Villa, who reportedly value Rogers at £130m. Arsenal are keen."
    assert detect_club_injection(parsed, src, club_map) == ["미들즈브러"]

def test_detect_club_injection_passes_on_english_alias():
    from bullet_in.enrich import detect_club_injection
    club_map = {"미들즈브러": ["Middlesbrough", "Boro"]}
    # 원문이 통칭 (Boro) 으로만 표기해도 근거로 인정 — 별칭 누락 = 오탐 방지
    parsed = {"title_ko": "미들즈브러, 유망주 영입 완료", "summary_ko": None,
              "summary3_ko": None, "body_ko": None}
    src = "Boro have completed the signing of the youngster."
    assert detect_club_injection(parsed, src, club_map) == []

def test_detect_club_injection_passes_folded_diacritics_alias():
    from bullet_in.enrich import detect_club_injection
    club_map = {"베식타스": ["Besiktas"]}
    # 원문 분음부호 표기 (Beşiktaş) 도 fold 후 매치 (기존 Gyökeres 테스트와 동일 계열)
    parsed = {"title_ko": "트로사르, 베식타스 이적", "summary_ko": None,
              "summary3_ko": None, "body_ko": None}
    src = "Trossard joins Beşiktaş for £15.3m."
    assert detect_club_injection(parsed, src, club_map) == []

def test_detect_club_injection_passes_korean_source():
    from bullet_in.enrich import detect_club_injection
    club_map = {"미들즈브러": ["Middlesbrough", "Boro"]}
    # ko 경로 (fmkorea): 원문 자체가 한국어 — 한글 표기 근거로 통과 (오탐 실측 cc2c7b58 재현 회귀)
    parsed = {"title_ko": None, "summary_ko": None, "summary3_ko": None,
              "body_ko": "미들즈브러 시절부터 주목받던 로저스가 빌라에서 성장했다."}
    src = "[해외축구] 미들즈브러 출신 로저스, 아스톤 빌라에서 폼 절정이라고 함"
    assert detect_club_injection(parsed, src, club_map) == []

def test_detect_club_injection_leading_hangul_guard():
    from bullet_in.enrich import detect_club_injection
    club_map = {"리즈": ["Leeds"]}
    # 선행 문자 한글이면 불인정: '시리즈' 는 '리즈' 매치 아님 (등장 · 근거 양쪽)
    parsed = {"title_ko": None, "summary_ko": None, "summary3_ko": None,
              "body_ko": "이번 시리즈 경기에서 아스날이 승리했다."}
    assert detect_club_injection(parsed, "Arsenal win again.", club_map) == []
    # 조사 결합 (직후 한글) 은 정상 검출 유지: '리즈가' → 원문에 Leeds 없음 → 검출
    parsed2 = {"title_ko": None, "summary_ko": None, "summary3_ko": None,
               "body_ko": "리즈가 영입 경쟁에 뛰어들었다."}
    assert detect_club_injection(parsed2, "Arsenal win again.", club_map) == ["리즈"]
    # 근거 대조에도 같은 가드: 원문의 '시리즈' 는 '리즈' 의 근거가 아님
    assert detect_club_injection(parsed2, "월드컵 시리즈 특집 기사", club_map) == ["리즈"]

def test_detect_club_injection_empty_inputs():
    from bullet_in.enrich import detect_club_injection
    club_map = {"미들즈브러": ["Middlesbrough"]}
    assert detect_club_injection({}, "src", club_map) == []
    assert detect_club_injection({"title_ko": None, "body_ko": None}, "src", club_map) == []
    assert detect_club_injection({"title_ko": "미들즈브러 소식"}, "src", {}) == []

def test_detect_club_injection_passes_korean_synonym_key():
    from bullet_in.enrich import detect_club_injection
    club_map = {"맨유": ["Manchester United", "Man United", "Man Utd"],
                "맨체스터 유나이티드": ["Manchester United", "Man United", "Man Utd"]}
    # ko 원문의 동의 표기 (맨체스터 유나이티드) 가 축약 표기 (맨유) 의 근거로 인정돼야 함
    parsed = {"title_ko": None, "summary_ko": None, "summary3_ko": None,
              "body_ko": "맨유가 영입 경쟁에 뛰어들었다고 함."}
    src = "[오피셜] 맨체스터 유나이티드가 윙어 영입에 근접했다고 함"
    assert detect_club_injection(parsed, src, club_map) == []

def _real_club_map():
    import yaml
    from pathlib import Path
    cfg = Path(__file__).parent.parent / "config" / "club_map.yaml"
    return (yaml.safe_load(cfg.read_text()) or {}).get("clubs", {})

def test_detect_club_injection_real_config_bbc_st_germain_style():
    """실사례 (mart 2026-07-20 전수 실측): BBC 는 'Paris St-Germain' 으로 표기한다.
    별칭에 축약 표기가 없으면 라운드업 대부분이 오탐 (21건) — 실제 config 로 재현."""
    from bullet_in.enrich import detect_club_injection
    parsed = {"title_ko": None, "summary_ko": "아스날과 리버풀이 파리 생제르맹의 23세 공격수 영입 경쟁에 합류했다.",
              "summary3_ko": None, "body_ko": None}
    src = "Arsenal and Liverpool have joined the race for Paris St-Germain's 23-year-old forward."
    assert detect_club_injection(parsed, src, _real_club_map()) == []

def test_detect_club_injection_real_config_portuguese_adjective():
    """실사례: 원문 형용사 'Portuguese' → 번역 '포르투갈' 이 포르투 키에 후행 결합.
    Portugal 별칭은 단어 경계라 형용사형을 못 접지 — 실제 config 로 재현."""
    from bullet_in.enrich import detect_club_injection
    parsed = {"title_ko": None, "summary_ko": None, "summary3_ko": None,
              "body_ko": "레알 마드리드도 21세 포르투갈 선수에게 관심을 보이고 있다."}
    src = "Real Madrid are also interested in the 21-year-old Portuguese player."
    assert detect_club_injection(parsed, src, _real_club_map()) == []

def test_detect_club_injection_real_config_fortuna_dusseldorf():
    """실사례: 원문 'Fortuna Dusseldorf' → 번역 '포르투나 뒤셀도르프' 가 포르투 키에 후행 결합."""
    from bullet_in.enrich import detect_club_injection
    parsed = {"title_ko": None, "summary_ko": None, "summary3_ko": None,
              "body_ko": "그는 네덜란드의 트벤테와 독일의 포르투나 뒤셀도르프에서 임대 생활을 했다."}
    src = "He had loan spells at Twente and Fortuna Dusseldorf."
    assert detect_club_injection(parsed, src, _real_club_map()) == []

def test_detect_club_injection_real_config_still_flags_unfounded():
    """접지 별칭을 늘려도 검출력 유지 — 원문에 없는 구단명 (Hull City 단신을 울버햄튼으로
    바꿔치기한 실사례) 은 실제 config 로도 계속 잡혀야 한다."""
    from bullet_in.enrich import detect_club_injection
    parsed = {"title_ko": None, "summary_ko": None,
              "summary3_ko": "울버햄튼은 애스턴 빌라의 레온 베일리 영입을 시도하고 있다.",
              "body_ko": None}
    src = "Hull City are in talks with Aston Villa over a deal for winger Leon Bailey."
    assert detect_club_injection(parsed, src, _real_club_map()) == ["울버햄튼"]

def test_detect_name_injection_flags_body_only_name():
    from bullet_in.enrich import detect_name_injection
    parsed = {"title_ko": "아스날, 미드필더 영입 임박",
              "summary_ko": "아스날이 영입에 근접했다.",
              "summary3_ko": "", "body_ko": "외데고르가 주장으로 남는다."}
    src = "Arsenal are closing in on a midfielder."
    assert detect_name_injection(parsed, src, {"외데고르": "Odegaard"}) == ["외데고르"]


def test_detect_name_injection_passes_korean_source():
    from bullet_in.enrich import detect_name_injection
    parsed = {"title_ko": "외데고르 잔류", "summary_ko": "",
              "summary3_ko": "", "body_ko": ""}
    src = "외데고르가 아스날에 남는다."
    assert detect_name_injection(parsed, src, {"외데고르": "Odegaard"}) == []


def test_detect_name_injection_passes_english_source():
    from bullet_in.enrich import detect_name_injection
    parsed = {"title_ko": "아스날 소식", "summary_ko": "",
              "summary3_ko": "", "body_ko": "외데고르가 주장으로 남는다."}
    src = "Odegaard stays as captain."
    assert detect_name_injection(parsed, src, {"외데고르": "Odegaard"}) == []


def test_detect_name_injection_empty_map_is_off():
    from bullet_in.enrich import detect_name_injection
    parsed = {"title_ko": "외데고르", "summary_ko": "",
              "summary3_ko": "", "body_ko": ""}
    assert detect_name_injection(parsed, "", {}) == []

def test_roundup_attrib_counts_extracts_cores_with_counts():
    from bullet_in.enrich import roundup_attrib_counts
    src = ("A move. (Sun) , external Another. (Athletic - subscription required) , external "
           "Third. (Sun) , external Fixture list (Emirates Stadium, London, 14:00)")
    # ', external' 이 붙은 표지만 출처 — 경기장 · 시각 괄호는 제외
    assert roundup_attrib_counts(src) == {"Sun": 2, "Athletic": 1}

def test_roundup_attrib_counts_empty_source():
    from bullet_in.enrich import roundup_attrib_counts
    assert roundup_attrib_counts(None) == {}
    assert roundup_attrib_counts("일반 기사 본문") == {}

def test_roundup_attrib_counts_handles_inner_external_form():
    # BBC 표지 두 형태 실측 (2026-07-20): "(X) , external" 와 "( X , external )"
    # — 후자는 ', external' 이 괄호 안. 기존 정규식은 전자만 잡아 절반이 미탐.
    from bullet_in.enrich import roundup_attrib_counts
    src = ("A. ( Athletic - subscription required , external ) B. ( Talksport , external ) "
           "C. (Teamtalk) , external")
    assert roundup_attrib_counts(src) == {"Athletic": 1, "Talksport": 1, "Teamtalk": 1}

def test_detect_roundup_omission_sees_inner_external_form():
    from bullet_in.enrich import detect_roundup_omission
    src = "Item one. ( Talksport , external ) Item two. (Sun) , external"
    ko = "첫 단신이다. (Sun)"   # Talksport 단신 누락
    assert detect_roundup_omission(src, ko) == ["Talksport"]

def _fin_row(**kw):
    row = {"content_hash": "h1", "source_id": "goal", "title_original": "Arsenal move",
           "body_source": "Arsenal are in talks.", "body_excerpt": ""}
    row.update(kw)
    return row

def test_finalize_translation_queues_retranslation_on_first_detection():
    # 1차 검출 (summary_ko 없음 = 신규 행) → title_ko NULL 저장 → 다음 사이클 재선별
    from bullet_in.enrich import finalize_translation
    v = {"title_ko": "펠레그리니 영입", "summary_ko": "요약", "summary3_ko": "①\n②\n③",
         "body_ko": "본문이다."}
    title_ko, _, _, _, _ = finalize_translation(
        v, _fin_row(), {}, {"펠레그리니": "Pellegrini"}, {})
    assert title_ko is None

def test_finalize_translation_adopts_title_on_retry_instead_of_requeue():
    # 종착 상태 (설계 5.2): 재시도 행에 의심이 남아도 번역 제목을 채택하고 경고만 남긴다.
    # NULL 재큐는 게이트가 충족 불가능한 요구를 하면 회차마다 무한 반복됐다.
    from bullet_in.enrich import finalize_translation
    v = {"title_ko": "펠레그리니 영입", "summary_ko": "요약", "summary3_ko": "①\n②\n③",
         "body_ko": "본문이다."}
    title_ko, _, _, _, flagged = finalize_translation(
        v, _fin_row(summary_ko="기존 요약"), {}, {"펠레그리니": "Pellegrini"}, {})
    assert title_ko == "펠레그리니 영입"
    assert flagged == ["펠레그리니"]

def test_finalize_translation_leaves_flagged_empty_on_clean_rows():
    # 게이트에 안 걸린 행은 flagged 가 비어 있어야 한다 (집계가 채택으로 세지 않도록).
    from bullet_in.enrich import finalize_translation
    v = {"title_ko": "아스날 협상", "summary_ko": "요약", "summary3_ko": "①\n②\n③",
         "body_ko": "본문이다."}
    _, _, _, _, flagged = finalize_translation(
        v, _fin_row(summary_ko="기존 요약"), {}, {}, {})
    assert flagged == []

def test_retranslation_summary_counts_new_adopted_resolved():
    # 관측 ②: 가운데 값은 '재시도 행이 의심을 남긴 채 제목을 확정' 한 건수 (수동 확인 대상).
    # 종착이 채택으로 바뀌어 '재시도 행이 NULL 로 남는' 상태가 구조적으로 사라졌다.
    from bullet_in.enrich import retranslation_summary
    finals = {"n": (None, "s", None, None, []),            # 신규 행 → NULL 큐 진입
              "a": ("채택된 제목", "s", None, None, ["펠레그리니"]),  # 재시도 → 채택
              "r": ("해소된 제목", "s", None, None, []),     # 재시도 → 해소
              "ok": ("정상 제목", "s", None, None, [])}      # 신규 성공 (미집계)
    by_hash = {"n": {"summary_ko": ""}, "a": {"summary_ko": "기존"},
               "r": {"summary_ko": "기존"}, "ok": {"summary_ko": ""}}
    assert retranslation_summary(finals, by_hash) == (1, 1, 1)

def test_finalize_translation_applies_glossary_and_paragraphize():
    # 게이트 무결 행: 표기 사전 치환 + 400자 초과 무분할 블록 재분할이 모두 걸린다
    from bullet_in.enrich import finalize_translation
    body = " ".join(["아스널이 협상을 이어갔다."] * 40)
    v = {"title_ko": "아스널 협상", "summary_ko": "아스널이 협상했다.",
         "summary3_ko": "①\n②\n③", "body_ko": body}
    title_ko, summary_ko, _, body_ko, _ = finalize_translation(
        v, _fin_row(), {"아스널": "아스날"}, {}, {})
    assert title_ko == "아스날 협상"
    assert summary_ko == "아스날이 협상했다."
    assert "아스널" not in body_ko
    assert len(body_ko.split("\n")) > 1

def test_glossary_file_normalizes_brugge_variants_in_order():
    # 사전은 YAML 기재 순서대로 치환된다 — 짧은 표기가 앞서면 긴 표기 규칙이 안 걸린다.
    # 실제 config 를 읽어 순서 계약을 고정한다 (주석만으로는 재발을 막지 못함).
    import yaml
    from pathlib import Path
    from bullet_in.enrich import apply_glossary
    g = (yaml.safe_load(Path("config/glossary.yaml").read_text()) or {})["replacements"]
    out = apply_glossary({"body_ko": "클럽 브뤼헤와 클뤼프 브뤼헤, 그리고 브뤼헤"}, g)
    assert out["body_ko"] == "클뤼프 브뤼허와 클뤼프 브뤼허, 그리고 브뤼허"

def test_club_map_key_matches_glossary_normal_form():
    # 사전이 만들어 내는 정규형과 club_map 등록 키가 어긋나면 구단명 게이트가 침묵한다.
    #
    # 2026-08-29 (안건 υ) 에 계약을 좁혔다. 그전에는 「club_map 키가 사전의 교정 대상이면
    # 안 된다」 로 통째로 막았는데, 그러면 원문 쪽 표기를 등재할 길이 없다.
    # club_map 키는 역할이 둘이고 검사도 둘로 갈려야 한다.
    #   ① 검출 — 번역문에 그 표기가 있는가 (_ko_present(joined, ko))
    #   ② 근거 — 원문에 같은 별칭 목록의 다른 표기가 있는가 (_ko_present(src, k2))
    # 사전이 번역문만 통일하고 원문 (한국어 원문인 fmkorea) 은 그대로 두므로, 원문 쪽
    # 표기를 ② 용으로 등재해야 근거가 안 끊긴다 (전량 대조 실측 — 의심 27 → 45 → 30).
    #
    # 그래서 지킬 것은 「교집합이 비었는가」 가 아니라 「정규형이 등재돼 있고 별칭 목록이
    # 같은가」 다. 별칭이 다르면 동의 그룹이 갈라져 ② 가 도로 끊긴다.
    import yaml
    from pathlib import Path
    clubs = (yaml.safe_load(Path("config/club_map.yaml").read_text()) or {})["clubs"]
    glossary = (yaml.safe_load(Path("config/glossary.yaml").read_text()) or {})["replacements"]
    assert "클뤼프 브뤼허" in clubs
    for wrong in set(glossary) & set(clubs):
        right = glossary[wrong]
        assert right in clubs, f"{wrong} 의 정규형 {right} 가 club_map 에 없어 게이트가 침묵한다"
        assert clubs[wrong] == clubs[right], (
            f"{wrong} 와 {right} 의 별칭 목록이 달라 동의 그룹이 갈라진다")

    # 위 루프는 **이미 club_map 에 있는 키만** 돈다. 그래서 「구단으로 수렴하는데 원문 쪽
    # 표기가 club_map 에 아예 없는」 항목을 못 본다 — 검사가 없는 자리를 못 보는 모양이다.
    # 2026-08-29 회차 저널이 그 구멍을 잡았다: 사전에 「베식타시 → 베식타스」 를 넣고
    # club_map 짝을 빠뜨려, fmkorea 원문이 「베식타시」 로 적은 기사에서 번역만 바뀌자
    # ko 경로 근거가 끊겼고 title_ko 가 NULL 로 재번역 큐에 들어갔다 (실측 1건).
    for wrong, right in glossary.items():
        if right in clubs:
            assert wrong in clubs, (
                f"「{wrong} → {right}」 는 구단으로 수렴하는데 {wrong} 가 club_map 에 없다 "
                f"— 원문이 {wrong} 로 적으면 게이트가 근거를 못 찾아 오탐한다 (규칙 ④)")
            assert clubs[wrong] == clubs[right], (
                f"{wrong} 와 {right} 의 별칭 목록이 달라 동의 그룹이 갈라진다")

    # 이 검사가 안 보는 것 (넓히려는 사람이 먼저 읽을 자리라 여기 적는다).
    # **정규형이 구단인 항목만 본다.** 사전에는 사람 · 기자 · 매체 항목도 있고 그쪽 정본은
    # config/credibility.yaml 의 별칭 · players 테이블에 있는데, 그 두 파일과의 정합은
    # 여기서 안 걸린다. 예컨대 사전이 매체명을 통일해도 credibility 별칭이 옛 표기로
    # 남아 있으면 사이드바 표기 접기가 어긋날 수 있다.
    # 2026-08-29 실측으로는 어긋난 항목이 0 이다 (credibility 별칭이 사전의 오표기 쪽인
    # 항목 없음 · 「레퀴프 → 레키프」 는 통용 값 쪽이 별칭에 있어 정합). **잠재 구멍이고
    # 지금 난 고장이 아니다** — 다만 아무도 안 보므로 어긋나도 조용하다.
    # 위 두 루프가 「검사가 없는 자리를 못 본다」 로 한 번 깨진 자리라 같은 모양을 적어 둔다.

def test_glossary_is_idempotent_over_all_keys_and_values():
    # 사전은 단순 문자열 치환이라, 교정 결과가 다른 규칙의 대상이 되면 두 번째 적용에서 또 바뀐다.
    # 실사례로 막은 것: '라일리' → '오라일리' 를 넣었다면 '오라일리' 가 '오오라일리' 가 된다.
    # 모든 키와 교정형을 한 줄에 담아 두 번 돌려, 1회차와 2회차가 같은지 확인한다.
    import yaml
    from pathlib import Path
    from bullet_in.enrich import apply_glossary
    g = (yaml.safe_load(Path("config/glossary.yaml").read_text()) or {})["replacements"]
    text = " ".join(list(g) + list(g.values()))
    once = apply_glossary({"body_ko": text}, g)
    twice = apply_glossary(once, g)
    assert twice["body_ko"] == once["body_ko"]

def _tweet_row(**kw):
    # 트윗은 별도 제목이 없어 title_original 에 본문 전문이 들어간다 (실사례 e1348256 축약).
    row = {"content_hash": "t1", "source_id": "x_afcstuff",
           "title_original": ("Arsenal have held discussions over Alex Scott & Ayyoub Bouaddi. "
                              "Their main target has been Julian Alvarez & they are set to step "
                              "up interest in Bruno Guimaraes. Arsenal also remain in talks for "
                              "Ezri Konsa."),
           "body_source": "", "body_excerpt": ""}
    row.update(kw)
    return row

_TWEET_NAMES = {"기마랑이스": "Guimaraes", "콘사": "Konsa", "알바레스": "Alvarez"}

def test_finalize_translation_keeps_tweet_title_despite_name_omission():
    # 트윗 제목이 본문의 등재 인명을 전부 빼도 정상이다 — 여섯 건짜리 묶음의 제목은 원래 추린다.
    from bullet_in.enrich import finalize_translation
    v = {"title_ko": "아스날, 알렉스 스콧 · 아유브 부아디 영입 논의", "summary_ko": "요약",
         "summary3_ko": "①\n②\n③", "body_ko": "본문이다."}
    title_ko, _, _, _, _ = finalize_translation(v, _tweet_row(), {}, _TWEET_NAMES, {})
    assert title_ko == "아스날, 알렉스 스콧 · 아유브 부아디 영입 논의"

def test_finalize_translation_keeps_ornstein_tweet_title_despite_name_omission():
    # 온스테인 (x_ornstein) 도 x_afcstuff 와 동일한 '제목 = 본문 전문' 트윗 구조라
    # 인명 누락 축을 걸러야 한다 (BODY_AS_TITLE_SOURCES 누락 시 재큐 루프 회귀 방지).
    from bullet_in.enrich import finalize_translation
    v = {"title_ko": "아스날, 알렉스 스콧 · 아유브 부아디 영입 논의", "summary_ko": "요약",
         "summary3_ko": "①\n②\n③", "body_ko": "본문이다."}
    row = _tweet_row(source_id="x_ornstein")
    title_ko, _, _, _, _ = finalize_translation(v, row, {}, _TWEET_NAMES, {})
    assert title_ko == "아스날, 알렉스 스콧 · 아유브 부아디 영입 논의"

def test_finalize_translation_still_flags_unfounded_loan_on_tweets():
    # 인명 누락만 걸러낸다 — '임대 무근거' 는 원문 대조가 유효하므로 트윗에서도 살아 있어야 한다.
    from bullet_in.enrich import finalize_translation
    v = {"title_ko": "아스날, 콘사 임대 영입 추진", "summary_ko": "요약",
         "summary3_ko": "①\n②\n③", "body_ko": "본문이다."}
    title_ko, _, _, _, _ = finalize_translation(v, _tweet_row(), {}, _TWEET_NAMES, {})
    assert title_ko is None      # 1차 검출 → 재번역 큐

def test_finalize_translation_keeps_name_omission_axis_for_normal_sources():
    # 일반 기사는 원문 제목이 헤드라인이라 축이 그대로 성립한다 (회귀 방지).
    from bullet_in.enrich import finalize_translation
    v = {"title_ko": "아스날, 수비 보강 추진", "summary_ko": "요약",
         "summary3_ko": "①\n②\n③", "body_ko": "본문이다."}
    row = _tweet_row(source_id="football_london",
                     title_original="Arsenal step up interest in Bruno Guimaraes")
    title_ko, _, _, _, _ = finalize_translation(v, row, {}, _TWEET_NAMES, {})
    assert title_ko is None


def test_finalize_translation_guard_uses_body_as_name_context():
    # 배선 확인: 제목에만 성이 있고 본문에 풀네임이 있으면 축이 그대로 작동한다.
    # detect_title_mistranslation 에 src_text 를 안 넘기면 이 테스트가 깨진다.
    from bullet_in.enrich import finalize_translation
    v = {"title_ko": "아스날, 수비수 계약 임박", "summary_ko": "요약",
         "summary3_ko": "①\n②\n③", "body_ko": "본문이다."}
    row = {"content_hash": "h1", "source_id": "goal",
           "title_original": "White nears new Arsenal deal",
           "body_source": "Ben White is closing in on fresh terms.",
           "body_excerpt": ""}
    title_ko, _, _, _, _ = finalize_translation(v, row, {}, {"화이트": "White"}, {})
    assert title_ko is None      # 1차 검출 → 재번역 큐


def test_partition_by_body_level_routes_post_body_to_rewrite():
    from bullet_in.enrich import partition_by_body_level
    rows = [
        {"content_hash": "h1", "body_level": 1, "outlet": "The Telegraph"},
        {"content_hash": "h2", "body_level": 2, "outlet": "BBC"},
        {"content_hash": "h3", "body_level": 0, "outlet": None},
    ]
    rewrite, translate = partition_by_body_level(rows)
    assert [r["content_hash"] for r in rewrite] == ["h1"]
    assert [r["content_hash"] for r in translate] == ["h2", "h3"]


def test_partition_by_body_level_ignores_outlet_string():
    """매체명으로 가르면 표기 변종 (더 선 · 더선 · 더썬) 마다 갈린다 (스펙 §4.2)."""
    from bullet_in.enrich import partition_by_body_level
    rows = [{"content_hash": "h1", "body_level": 2, "outlet": "The Athletic"}]
    rewrite, translate = partition_by_body_level(rows)
    assert rewrite == []
    assert len(translate) == 1


def test_partition_by_body_level_treats_null_level_as_translate():
    """백필 전 레거시 행 (NULL) 은 재작성 모드로 보내지 않는다 — 한국어 여부를 모른다."""
    from bullet_in.enrich import partition_by_body_level
    rewrite, translate = partition_by_body_level([{"content_hash": "h1", "body_level": None}])
    assert rewrite == [] and len(translate) == 1


def test_paraphrase_prompt_carries_completeness_and_no_injection_rules():
    """다섯 판본 비교에서 이 조합이 주입 4개 → 1개 · 없던 소제목 33개 → 9개로
    줄인 판본이다 (스펙 §6.3). 조항이 빠지면 측정 근거가 무효가 된다.

    2026-08-03 (E안) 개정 — 완전성 조항이 '모든 문단을 순서대로 빠짐없이' 에서
    '사실 단위를 하나도 빠뜨리지 않고' 로 바뀌었다. 정보 단위 재작성은 문단 대응을
    일부러 버리므로 순서 조항을 유지할 수 없다. 나머지 여섯 조항은 그대로다.
    바뀐 조항의 효과는 §6.3 측정이 덮지 않는다 — 표본 검수로 확인한다."""
    from bullet_in.enrich import PARAPHRASE_PROMPT
    for clause in ["사실 단위를 하나도 빠뜨리지 않고",
                   "모든 숫자",
                   "원문에 없는 소제목을 만들지 않는다",
                   "역할 명칭",
                   "시간 · 정도 표현",
                   "원문 표기를 그대로",
                   "추측으로"]:
        assert clause in PARAPHRASE_PROMPT, clause


def test_paraphrase_prompt_is_information_unit_two_stage():
    from bullet_in.enrich import PARAPHRASE_PROMPT
    # 1단계 = 사실 단위 추출 · 2단계 = 목록만 재료로 재편
    assert "사실 단위" in PARAPHRASE_PROMPT
    assert "문장 단위로 대응" in PARAPHRASE_PROMPT
    assert "목록에 없는" in PARAPHRASE_PROMPT
    # 인용문은 재작성 제외 — 게이트 인용 축과 계약이 같아야 한다
    assert "인용문" in PARAPHRASE_PROMPT
    # JSON 계약 유지
    for key in ("title_ko", "summary_ko", "summary3_ko", "body_ko", "players"):
        assert key in PARAPHRASE_PROMPT


class _FakeGemini:
    """정해진 응답을 순서대로 돌려주는 가짜 클라이언트 — 호출 프롬프트를 기록한다."""
    def __init__(self, bodies):
        self._bodies = list(bodies)
        self.prompts = []
        self.models = self

    def generate_content(self, model, contents, config):
        self.prompts.append(contents)
        body = self._bodies.pop(0)
        payload = {"title_ko": "제목", "summary_ko": "요약",
                   "summary3_ko": ["1", "2", "3"], "body_ko": body}
        return type("R", (), {"text": _json.dumps(payload, ensure_ascii=False)})()


_SRC = "아스날이 £50m 을 제안했다. 계약 기간은 2031년까지로 알려졌다."


def _row(h="h1"):
    return {"content_hash": h, "title_original": "제목", "body_source": _SRC,
            "body_level": 1}


def test_rewrite_rows_guarded_adopts_first_attempt_when_gate_passes():
    from bullet_in.enrich import rewrite_rows_guarded
    clean = "아스날은 £50m 규모 제안을 건넸으며, 계약은 2031년까지로 전해진다."
    client = _FakeGemini([clean])
    results, reports = rewrite_rows_guarded([_row()], client, "m", threshold=0.9)
    assert results["h1"]["body_ko"] == clean
    assert reports["h1"]["attempts"] == 1
    assert len(client.prompts) == 1


def test_rewrite_rows_guarded_retries_with_missing_number_reason():
    from bullet_in.enrich import rewrite_rows_guarded
    dropped = "아스날이 제안을 건넸다."
    fixed = "아스날은 £50m 제안을 건넸고 계약은 2031년까지로 전해진다."
    client = _FakeGemini([dropped, fixed])
    results, reports = rewrite_rows_guarded([_row()], client, "m", threshold=0.9)
    assert results["h1"]["body_ko"] == fixed
    assert reports["h1"]["attempts"] == 2
    assert "누락" in client.prompts[1]
    assert "2031" in client.prompts[1]


def test_rewrite_rows_guarded_retries_with_duplication_reason():
    from bullet_in.enrich import rewrite_rows_guarded
    fixed = "아스날은 £50m 제안을 건넸고 계약은 2031년까지로 전해진다."
    client = _FakeGemini([_SRC, fixed])          # 1회차는 원문 그대로 복제
    results, reports = rewrite_rows_guarded([_row()], client, "m", threshold=0.75)
    assert results["h1"]["body_ko"] == fixed
    assert "복제" in client.prompts[1]
    assert "새로 넣지 않는다" in client.prompts[1]   # 주입 금지 동반 (스펙 §4.4)


def test_rewrite_rows_guarded_stops_at_max_attempts_and_keeps_best():
    from bullet_in.enrich import rewrite_rows_guarded
    # 세 시도 모두 게이트에 걸려도 본문을 버리지 않는다 (스펙 §4.4)
    client = _FakeGemini([_SRC, _SRC, "아스날이 £50m 을 제안했고 2031년까지 계약한다."])
    results, reports = rewrite_rows_guarded([_row()], client, "m", threshold=0.10)
    assert len(client.prompts) == 3
    assert results["h1"]["body_ko"] == "아스날이 £50m 을 제안했고 2031년까지 계약한다."
    assert reports["h1"]["attempts"] == 3
    assert reports["h1"]["retention"] < 1.0


def test_rewrite_rows_guarded_uses_body_excerpt_when_body_source_empty():
    from bullet_in.enrich import rewrite_rows_guarded
    row = {"content_hash": "h2", "title_original": "제목", "body_source": "",
           "body_excerpt": _SRC, "body_level": 1}
    client = _FakeGemini(["아스날은 £50m 제안을 건넸고 계약은 2031년까지다."])
    results, _ = rewrite_rows_guarded([row], client, "m", threshold=0.9)
    assert "h2" in results


def test_rewrite_rows_guarded_breaks_on_rate_limit():
    from bullet_in.enrich import rewrite_rows_guarded

    class _Boom:
        models = None
        def generate_content(self, model, contents, config):
            raise RuntimeError("429 RESOURCE_EXHAUSTED")

    c = _Boom()
    c.models = c
    results, reports = rewrite_rows_guarded([_row(), _row("h9")], c, "m")
    assert results == {} and reports == {}


def test_partition_generatable_drops_row_without_material():
    from bullet_in.enrich import partition_generatable
    rows = [{"content_hash": "h1", "source_id": "fmkorea",
             "body_source": "", "body_excerpt": None},
            {"content_hash": "h2", "source_id": "fmkorea",
             "body_source": "본문 있음", "body_excerpt": None}]
    gen, title_only = partition_generatable(rows)
    assert [r["content_hash"] for r in gen] == ["h2"]
    assert [r["content_hash"] for r in title_only] == ["h1"]


def test_partition_generatable_keeps_tweet_sources():
    """트윗은 title_original 에 전문이 있어 재료가 갖춰져 있다 (스펙 §3.1 · §4.5)."""
    from bullet_in.enrich import partition_generatable
    rows = [{"content_hash": "t1", "source_id": "x_afcstuff",
             "body_source": "", "body_excerpt": None},
            {"content_hash": "t2", "source_id": "x_ornstein",
             "body_source": None, "body_excerpt": ""}]
    gen, title_only = partition_generatable(rows)
    assert len(gen) == 2 and title_only == []


def test_partition_generatable_accepts_excerpt_only_row():
    from bullet_in.enrich import partition_generatable
    gen, title_only = partition_generatable(
        [{"content_hash": "h3", "source_id": "goal",
          "body_source": None, "body_excerpt": "발췌 있음"}])
    assert len(gen) == 1 and title_only == []


def test_title_only_rows_returns_title_and_null_body_fields():
    from bullet_in.enrich import title_only_rows
    class _C:
        models = None
        def generate_content(self, model, contents, config):
            return type("R", (), {"text": '{"title_ko": "아스날 소식"}'})()
    c = _C(); c.models = c
    out = title_only_rows([{"content_hash": "h1", "title_original": "Arsenal news"}],
                          c, "m")
    assert out["h1"]["title_ko"] == "아스날 소식"
    assert out["h1"]["summary_ko"] is None
    assert out["h1"]["summary3_ko"] is None
    assert out["h1"]["body_ko"] is None


def test_finalize_translation_survives_title_only_result():
    """title_only_rows 산출물 (본문 · 요약 None) 이 회차 저장 경로를 통과해야 한다.
    죽으면 run.py 의 enrich 단계가 통째로 중단된다 (스펙 §4.5 배선)."""
    from bullet_in.enrich import finalize_translation
    v = {"title_ko": "아스날 소식", "summary_ko": None,
         "summary3_ko": None, "body_ko": None}
    row = {"content_hash": "h1", "title_original": "Arsenal news",
           "body_source": None, "body_excerpt": None,
           "source_id": "fmkorea", "summary_ko": None}
    assert finalize_translation(v, row, {}, {}, {}) == ("아스날 소식", None, None, None, [])


def test_enrich_returns_players_pairs():
    payload = {"title_ko": "T", "summary_ko": "S", "summary3_ko": ["a", "b", "c"],
               "body_ko": "B",
               "players": [{"full_name": "Bruno Guimaraes", "ko": "기마랑이스",
                            "stage": "personal_terms"}]}
    rows = [{"content_hash": "h1", "title_original": "T", "body_source": "Body"}]
    out = enrich_rows(rows, FullClient(payload), "m")
    assert out["h1"]["players"] == payload["players"]


def test_enrich_players_field_defaults_to_empty_list():
    payload = {"title_ko": "T", "summary_ko": "S", "summary3_ko": ["a"], "body_ko": "B"}
    out = enrich_rows([{"content_hash": "h", "title_original": "T", "body_source": "B"}],
                      FullClient(payload), "m")
    assert out["h"]["players"] == []


def test_translate_prompts_list_player_stages():
    # 단계 값 세트가 프롬프트와 동기 (STAGE_PROMPT 동기 테스트와 같은 취지)
    from bullet_in.enrich import TRANSLATE_PROMPT, PARAPHRASE_PROMPT
    for prompt in (TRANSLATE_PROMPT, PARAPHRASE_PROMPT):
        assert '"players"' in prompt
        for stage in ("rumour", "interest", "negotiating", "personal_terms",
                      "medical", "agreed", "other"):
            assert stage in prompt
        assert "official" not in prompt


def test_extract_players_rows_returns_pairs_and_stops_on_429(caplog):
    import logging as _logging
    payload = {"players": [{"full_name": "Nico Williams", "ko": "니코 윌리엄스",
                            "stage": "rumour"}]}
    rows = [{"content_hash": "h1", "title_original": "T", "body_source": "B"}]
    out = extract_players_rows(rows, FullClient(payload), "m")
    assert out["h1"] == payload["players"]

    class _Boom:
        class models:
            @staticmethod
            def generate_content(**kw):
                raise RuntimeError("429 RESOURCE_EXHAUSTED")
    with caplog.at_level(_logging.WARNING):
        out = extract_players_rows(rows, _Boom, "m")
    assert out == {} and "429" in caplog.text


def test_extract_players_prompt_lists_stages():
    from bullet_in.enrich import EXTRACT_PLAYERS_PROMPT
    for stage in ("rumour", "interest", "negotiating", "personal_terms",
                  "medical", "agreed", "done", "collapsed", "other"):
        assert stage in EXTRACT_PLAYERS_PROMPT
    assert "official" not in EXTRACT_PLAYERS_PROMPT


def test_rewrite_retries_with_reason_notes_and_reports_axes():
    from bullet_in.enrich import rewrite_rows_guarded

    class _Msg:
        def __init__(self, text):
            self.text = text

    class _Models:
        def __init__(self):
            self.prompts = []

        def generate_content(self, model, contents, config):
            self.prompts.append(contents)
            # 1차는 원문에 없는 구단 (첼시) 과 숫자 (5) 를 만든다 · 2차는 깨끗하다.
            # 2차 본문을 원문과 다른 문장으로 두어야 잔존율 축에 걸리지 않는다.
            if len(self.prompts) == 1:
                body = '아스날이 첼시에서 5년 계약으로 영입한다.'
            else:
                body = '영입이 곧 마무리될 전망이다.'
            return _Msg('{"title_ko":"제목","summary_ko":"요약",'
                        '"summary3_ko":["1","2","3"],"body_ko":"' + body + '",'
                        '"players":[]}')

    class _Client:
        def __init__(self):
            self.models = _Models()

    client = _Client()
    rows = [{"content_hash": "h1", "title_original": "아스날 영입",
             "body_source": "아스날이 영입을 마무리한다."}]
    results, reports = rewrite_rows_guarded(
        rows, client, "m", club_map={"첼시": ["Chelsea"]})
    assert "[구단 주입]" in client.models.prompts[1]
    assert "[신규 수치]" in client.models.prompts[1]
    assert reports["h1"]["clubs"] == []
    assert reports["h1"]["attempts"] == 2
    assert results["h1"]["body_ko"] == "영입이 곧 마무리될 전망이다."


def test_retry_note_omits_untriggered_injection_axis():
    from bullet_in.enrich import rewrite_rows_guarded

    class _Msg:
        def __init__(self, text):
            self.text = text

    class _Models:
        def __init__(self):
            self.prompts = []

        def generate_content(self, model, contents, config):
            self.prompts.append(contents)
            # 1차는 구단 축만 위반한다 (숫자 · 인용 · 인명 위반 없음)
            body = ('아스날이 첼시에서 영입한다.' if len(self.prompts) == 1
                    else '영입이 곧 마무리될 전망이다.')
            return _Msg('{"title_ko":"제목","summary_ko":"요약",'
                        '"summary3_ko":["1","2","3"],"body_ko":"' + body + '",'
                        '"players":[]}')

    class _Client:
        def __init__(self):
            self.models = _Models()

    client = _Client()
    rows = [{"content_hash": "h1", "title_original": "아스날 영입",
             "body_source": "아스날이 영입을 마무리한다."}]
    rewrite_rows_guarded(rows, client, "m", club_map={"첼시": ["Chelsea"]})
    # 재생성 호출은 기본 프롬프트 + 사유 note 라 뒤에 덧붙은 부분만 본다
    note = client.models.prompts[1][len(client.models.prompts[0]):]
    assert "[구단 주입]" in note
    assert "[인명 주입]" not in note
    assert "없음" not in note


def test_retry_note_carries_both_injection_axes():
    from bullet_in.enrich import rewrite_rows_guarded

    class _Msg:
        def __init__(self, text):
            self.text = text

    class _Models:
        def __init__(self):
            self.prompts = []

        def generate_content(self, model, contents, config):
            self.prompts.append(contents)
            body = ('아스날이 첼시에서 외데고르를 영입한다.'
                    if len(self.prompts) == 1 else '영입이 곧 마무리될 전망이다.')
            return _Msg('{"title_ko":"제목","summary_ko":"요약",'
                        '"summary3_ko":["1","2","3"],"body_ko":"' + body + '",'
                        '"players":[]}')

    class _Client:
        def __init__(self):
            self.models = _Models()

    client = _Client()
    rows = [{"content_hash": "h1", "title_original": "아스날 영입",
             "body_source": "아스날이 영입을 마무리한다."}]
    rewrite_rows_guarded(rows, client, "m",
                         name_map={"외데고르": "Odegaard"},
                         club_map={"첼시": ["Chelsea"]})
    note = client.models.prompts[1]
    assert "[구단 주입]" in note
    assert "[인명 주입]" in note


def test_rewrite_gate_grounds_injection_on_title_too():
    """제목에만 나오는 인명 · 수치는 주입이 아니다 — 프롬프트가 제목도 재료로 준다."""
    from bullet_in.enrich import rewrite_rows_guarded

    class _Msg:
        def __init__(self, text):
            self.text = text

    class _Models:
        def __init__(self):
            self.prompts = []

        def generate_content(self, model, contents, config):
            self.prompts.append(contents)
            return _Msg('{"title_ko":"제목","summary_ko":"요약",'
                        '"summary3_ko":["1","2","3"],'
                        '"body_ko":"외데고르가 2031년까지 남는다.","players":[]}')

    class _Client:
        def __init__(self):
            self.models = _Models()

    client = _Client()
    rows = [{"content_hash": "h1",
             "title_original": "외데고르, 2031년까지 아스날 잔류",
             "body_source": "잔류가 확정됐다."}]
    _, reports = rewrite_rows_guarded(rows, client, "m",
                                      name_map={"외데고르": "Odegaard"})
    assert reports["h1"]["names"] == []
    assert reports["h1"]["extra"] == []
    assert reports["h1"]["attempts"] == 1      # 오탐이 없으니 재시도하지 않는다


# ---------------------------------------------------------------- 프롬프트 개정 (2026-08-12)

def test_players_clause_scopes_stage_to_arsenal():
    # 선수 축이 아스날 밖으로 새는 것을 막는다 — 나열 속 타 구단 완료가 실물이었다
    from bullet_in.enrich import PLAYERS_CLAUSE
    assert "stage 는 언제나 아스날 건 기준이다" in PLAYERS_CLAUSE
    assert "아스날과 무관한 딜뿐이면 other" in PLAYERS_CLAUSE


def test_players_clause_limits_done_to_arsenal_transfer():
    from bullet_in.enrich import PLAYERS_CLAUSE
    assert "done(이미 완료된 아스날 이적의 후속" in PLAYERS_CLAUSE
    assert "타 구단 간 완료 이적이 문장 안에 나열된 것은 other" in PLAYERS_CLAUSE


def test_players_clause_excludes_own_player_contract_from_collapsed():
    # 아스날이 자기 유망주와 맺는 신규 계약이 종결로 잡히던 유형 (업슨)
    from bullet_in.enrich import PLAYERS_CLAUSE
    assert "아스날이 자기 소속 선수와 맺는 신규 · 연장 계약은 종결이 아니다" in PLAYERS_CLAUSE


def test_players_clause_defines_role():
    from bullet_in.enrich import PLAYERS_CLAUSE
    assert "role 은 이 기사가 그 인물을 하나의 소식으로 다루는지다" in PLAYERS_CLAUSE
    assert "지면에서 차지하는 자리로 정한다" in PLAYERS_CLAUSE


def test_all_three_prompts_ask_for_role():
    # JSON 뼈대는 조항 밖에 있어 세 프롬프트가 각자 들고 있다 — 한 곳만 고치면 샌다
    from bullet_in.enrich import (EXTRACT_PLAYERS_PROMPT, PARAPHRASE_PROMPT,
                                  TRANSLATE_PROMPT)
    for prompt in (TRANSLATE_PROMPT, PARAPHRASE_PROMPT, EXTRACT_PLAYERS_PROMPT):
        assert '"role":"subject 또는 mention"' in prompt


def test_collection_prompts_carry_confirmed_roster():
    # 아스날이 안 나오는 기사에서 영입 대상인지 판단할 근거를 수집 시점에도 준다
    from bullet_in.enrich import (PARAPHRASE_PROMPT, ROSTER_CLAUSE,
                                  TRANSLATE_PROMPT)
    for prompt in (TRANSLATE_PROMPT, PARAPHRASE_PROMPT):
        assert ROSTER_CLAUSE in prompt
    assert TRANSLATE_PROMPT.format(title="T", body="B", roster="촐리스(Tzolis)")


def test_extract_players_rows_raises_output_cap_above_observed_max():
    # 상한 1024 에서 인물이 많은 기사가 MAX_TOKENS 로 잘려 조용히 누락됐다
    # (실측: 9명 기사의 출력 1105 토큰 · 6명 기사 1118 토큰)
    seen = {}

    class _Recorder:
        models = None

        def generate_content(self, **kw):
            seen.update(kw["config"])

            class R:
                text = '{"players":[]}'
            return R()

    client = _Recorder()
    client.models = client
    extract_players_rows([{"content_hash": "h1", "title_original": "T",
                           "body_source": "B"}], client, "m")
    assert seen["max_output_tokens"] >= 4096


# --- 안건 ψ · 회차 내 재시도 (번역 파싱 실패) -------------------------------
# 파싱 실패는 지금까지 행을 다음 회차로 넘겨 「번역 대기」 배지를 최대 한 회차 살렸다.
# 재작성 게이트와 같은 방식 (max_attempts + 실패 유형별 피드백) 으로 회차 안에서 받는다.

from bullet_in.enrich import parse_failure_note

_GOOD = ('{"title_ko":"제","summary_ko":"요","summary3_ko":["a","b","c"],'
         '"body_ko":"본문"}')


class _Scripted:
    """호출마다 정해진 응답을 돌려주고 받은 프롬프트를 기록한다."""
    def __init__(self, texts):
        self.texts, self.n, self.prompts = list(texts), 0, []
        self.models = self

    def generate_content(self, **kw):
        self.prompts.append(kw["contents"])
        text = self.texts[min(self.n, len(self.texts) - 1)]
        self.n += 1
        if isinstance(text, Exception):
            raise text
        class R: pass
        r = R(); r.text = text
        return r


def _prow(h="h"):
    return {"content_hash": h, "title_original": "T", "body_excerpt": "B"}


def test_parse_failure_note_classifies_truncated_response():
    note, label = parse_failure_note('{"title_ko":"제","summary_ko":"요"')
    assert label == "응답 잘림"
    assert "잘림" in note


def test_parse_failure_note_classifies_missing_json():
    note, label = parse_failure_note("설명만 있고 JSON 이 없다")
    assert label == "JSON 없음"
    assert "JSON" in note


def test_parse_failure_note_names_the_missing_keys():
    note, label = parse_failure_note('{"title_ko":"제","summary_ko":"요"}')
    assert label == "키 누락"
    assert "summary3_ko" in note and "body_ko" in note


def test_parse_failure_note_classifies_broken_json_syntax():
    _, label = parse_failure_note('{"title_ko":"제",}')
    assert label == "JSON 문법"


def test_enrich_retries_parse_failure_inside_the_cycle():
    client = _Scripted(["쓰레기 응답", _GOOD])
    out = enrich_rows([_prow()], client, "m")
    assert out["h"]["title_ko"] == "제"
    assert client.n == 2


def test_enrich_retry_prompt_carries_the_failure_reason():
    client = _Scripted(['{"title_ko":"제"', _GOOD])
    enrich_rows([_prow()], client, "m")
    assert "[응답 잘림]" in client.prompts[1]
    assert "[응답 잘림]" not in client.prompts[0]


def test_enrich_gives_up_after_max_attempts_and_logs_the_reason(caplog):
    client = _Scripted(["쓰레기 응답"])
    with caplog.at_level(logging.WARNING):
        out = enrich_rows([_prow()], client, "m", max_attempts=3)
    assert out == {}
    assert client.n == 3
    assert any("JSON 없음" in r.message and "시도=3" in r.message
               for r in caplog.records)


def test_enrich_rate_limit_during_retry_still_stops_the_cycle():
    client = _Scripted(["쓰레기 응답", _RateLimit("429 RESOURCE_EXHAUSTED")])
    out = enrich_rows([_prow("a"), _prow("b")], client, "m")
    assert out == {}
    assert client.n == 2   # 둘째 행은 호출조차 안 함


def test_enrich_successful_first_attempt_costs_one_call():
    client = _Scripted([_GOOD])
    enrich_rows([_prow()], client, "m")
    assert client.n == 1


def test_glossary_maps_both_tyjon_misspellings():
    # 저장된 오표기가 둘이었다 — 공홈 번역이 「티존」 · afcstuff 번역이 「티욘」 (2026-08-29).
    import yaml
    from pathlib import Path
    g = (yaml.safe_load(Path("config/glossary.yaml").read_text()) or {})["replacements"]
    assert g["티존"] == "타이욘" and g["티욘"] == "타이욘"


def test_glossary_does_not_touch_city_match_wording():
    # 「티전」 은 「맨시티전」 · 「스완지 시티전」 의 일부다 (실측 8건) — 사전에 넣으면 안 된다.
    import yaml
    from pathlib import Path
    g = (yaml.safe_load(Path("config/glossary.yaml").read_text()) or {})["replacements"]
    assert "티전" not in g
    fixed = apply_glossary({"body_ko": "맨체스터 시티전 결승골"}, g)
    assert fixed["body_ko"] == "맨체스터 시티전 결승골"


def test_glossary_correction_is_idempotent_for_tyjon():
    # 「타이욘」 은 「티욘」 을 부분 문자열로 품지 않아 두 번 걸려도 안 망가진다.
    import yaml
    from pathlib import Path
    g = (yaml.safe_load(Path("config/glossary.yaml").read_text()) or {})["replacements"]
    once = apply_glossary({"title_ko": "이고르 티욘 영입"}, g)
    twice = apply_glossary(once, g)
    assert once["title_ko"] == "이고르 타이욘 영입" == twice["title_ko"]


def _glossary():
    import yaml
    from pathlib import Path
    return (yaml.safe_load(Path("config/glossary.yaml").read_text()) or {})["replacements"]


# ── 표기 흔들림 정리 (2026-08-29 · 안건 υ) ──────────────────────────────────
# 서빙 858행을 전량 대조해 갈린 표기 55종을 찾았고 61항목을 등재했다. 아래 넷은 그
# 과정에서 「넣었으면 깨졌을 것」 을 실측으로 걸러낸 자리다 — 주석만으로는 재발을 못 막는다.

def test_glossary_does_not_touch_sporting_director_or_kansas_city():
    # 「스포팅」 을 Sporting CP 로 모으려다 전량 대조에서 걸렀다 — 4자리가 전부 다른 뜻이었다
    # (「스포팅 캔자스 시티」 2 · 「스포팅 디렉터」 2). 「티전」 과 같은 갈래다.
    g = _glossary()
    assert "스포팅" not in g
    out = apply_glossary(
        {"body_ko": "베르타 스포팅 디렉터는 스포팅 캔자스 시티와 접촉했다"}, g)
    assert out["body_ko"] == "베르타 스포팅 디렉터는 스포팅 캔자스 시티와 접촉했다"


def test_glossary_normalizes_stadium_but_leaves_airline_alone():
    # 「에미레이트」 홑말은 사전에 넣으면 안 된다 — 실측 86자리 중 21자리가 항공사이고
    # 「에미레이트 항공」 이 그 회사의 공식 한글명이다. 경기장 구절만 잡는다.
    g = _glossary()
    assert "에미레이트" not in g
    out = apply_glossary(
        {"body_ko": "에미레이트 스타디움에서 열렸다. 에미레이트 항공은 스폰서다."}, g)
    assert out["body_ko"] == "에미레이츠 스타디움에서 열렸다. 에미레이트 항공은 스폰서다."


def test_glossary_nico_williams_does_not_touch_neco_williams():
    # 스페인 Nico Williams 를 「니코 윌리암스」 로 모은다 (사용자 확정 · players#142 선언).
    # 노팅엄의 Neco Williams 는 다른 사람인데, 「네코 윌리엄스」 가 「니코 윌리엄스」 를
    # 품지 않아 안 걸린다. 원문 대조로 8행을 전수 확인한 자리라 계약으로 고정한다.
    g = _glossary()
    out = apply_glossary(
        {"body_ko": "니코 윌리엄스와 네코 윌리엄스는 다른 선수다"}, g)
    assert out["body_ko"] == "니코 윌리암스와 네코 윌리엄스는 다른 선수다"


def test_glossary_folds_mourinho_and_leaves_jose_sa_alone():
    # José Mourinho 는 「주제 무리뉴」 로 모은다 (사용자 확정 2026-08-29 · 포르투갈어 José).
    # 두 가지를 함께 고정한다.
    #  ① 역방향 규칙이 없어야 한다 — 「주제 무리뉴 → 조제 무리뉴」 를 남기면 사전이 순환한다.
    #  ② 키는 「무리뉴」 를 붙인 전체 구절이다 — 홑말 「조제」 는 울브스 골키퍼 조제 사
    #     (José Sá) 를 가리키는 자리가 실측 1자리 있어 함께 바꾸면 남의 이름이 깨진다.
    g = _glossary()
    assert "조제" not in g and "주제" not in g
    out = apply_glossary(
        {"body_ko": "조제 무리뉴와 조세 무리뉴, 호세 무리뉴는 같은 사람이다. "
                    "울브스는 조제 사를 지켰다."}, g)
    assert out["body_ko"] == ("주제 무리뉴와 주제 무리뉴, 주제 무리뉴는 같은 사람이다. "
                              "울브스는 조제 사를 지켰다.")


def test_glossary_folds_prestianni_from_every_direction():
    # 「지안루카 프레스티아니」 로 모은다 (사용자 확정 2026-08-29 · 처음에 반대로 넣었다 뒤집음).
    # 이 이름은 표기가 셋이었는데 (지안루카 프레스티안니 · 지안루카 프레스티아니 ·
    # 잔루카 프레스티아니) 처음에 사용자가 준 짝만 보고 군을 닫아 셋째를 놓쳤다.
    # 성을 홑말로 먼저 고치는 순서라야 「잔루카 프레스티안니」 도 한 번에 수렴한다.
    g = _glossary()
    for before in ("지안루카 프레스티안니", "잔루카 프레스티아니",
                   "잔루카 프레스티안니", "지안루카 프레스티아니"):
        out = apply_glossary({"body_ko": f"벤피카의 {before}가 논란이 됐다"}, g)
        assert out["body_ko"] == "벤피카의 지안루카 프레스티아니가 논란이 됐다", before
    # 성만 나와도 잡힌다
    assert apply_glossary({"body_ko": "프레스티안니는 6경기 징계"}, g)["body_ko"] \
        == "프레스티아니는 6경기 징계"


def test_glossary_bernardo_is_a_bare_word_replacement_with_a_known_limit():
    # 「베르나르도 → 베르나르두」 는 홑말 치환이라 근거를 계약으로 남긴다.
    # 코퍼스의 Bernardo 는 베르나르두 실바 하나뿐이고 (「베르나르도」 2자리 · 「베르나르두」
    # 20자리 · 전부 같은 사람) 스페인 · 이탈리아계 Bernardo 는 0이다.
    # 어말 -o 를 「우」 로 바꾸는 일반 규칙은 세우지 않았다 — 걸면 「브루노 기마랑이스」
    # 193행 702자리가 함께 뒤집히는데 그쪽은 국내 통용도 players 정본도 「오」 쪽이다.
    g = _glossary()
    out = apply_glossary(
        {"body_ko": "베르나르도가 도착한다. 브루노 기마랑이스는 남는다."}, g)
    assert out["body_ko"] == "베르나르두가 도착한다. 브루노 기마랑이스는 남는다."


def test_glossary_folds_club_spelling_variants():
    # 구단 축이 가장 무거웠다 (갈린 10종 · 비통용 표기가 낀 행 158). 통용 값은 내가 고르지
    # 않고 club_map.yaml 키에서 가져왔다 — 정본은 그 파일이 갖고 이 사전은 집행만 한다.
    g = _glossary()
    out = apply_glossary({"body_ko": "아스널, 애스턴 빌라, 에버튼, 브라이튼, "
                                     "브렌트포드, 코벤트리 시티"}, g)
    assert out["body_ko"] == ("아스날, 아스톤 빌라, 에버턴, 브라이턴, "
                              "브렌트퍼드, 코번트리 시티")


# --- 안건 2η · 본문 없는 트윗은 요약을 만들지 않는다 -------------------------------

def test_tweet_mode_leaves_summary_fields_empty():
    # 트윗 경로는 요약 두 필드를 아예 안 받는다 — 재료가 트윗 한 줄뿐이라 요구하면
    # 모델이 배경지식으로 채운다 (실측: 아홉 단어 트윗에서 「현지 소식통에 따르면」).
    payload = {"title_ko": "아스날, 알바레스 영입 가능성",
               "body_ko": "아스날이 알바레스를 영입할 가능성이 커지고 있다.",
               "players": []}
    rows = [{"content_hash": "t1", "source_id": "x_afcstuff",
             "title_original": "Arsenal are increasingly likely to sign Julian Alvarez."}]
    out = enrich_rows(rows, FullClient(payload), "m", mode="tweet")
    assert out["t1"]["title_ko"] == "아스날, 알바레스 영입 가능성"
    assert out["t1"]["summary_ko"] is None
    assert out["t1"]["summary3_ko"] is None


def test_translate_mode_still_requires_summary_fields():
    # 트윗 키 완화가 번역 경로로 새면 요약 없는 응답이 조용히 채택된다.
    payload = {"title_ko": "제목", "body_ko": "본문"}
    out = enrich_rows([{"content_hash": "h", "title_original": "T", "body_source": "B"}],
                      FullClient(payload), "m", mode="translate")
    assert "h" not in out


def test_tweet_prompt_bans_added_context_and_asks_no_summary():
    from bullet_in.enrich import TWEET_PROMPT
    assert "summary_ko" not in TWEET_PROMPT and "summary3_ko" not in TWEET_PROMPT
    assert "덧붙이지" in TWEET_PROMPT and "분량을 채우려" in TWEET_PROMPT
    assert "players" in TWEET_PROMPT      # 선수 추출은 트윗에서도 계속 받는다


def test_partition_bodyless_tweets_keeps_tweets_that_have_a_body():
    from bullet_in.enrich import partition_bodyless_tweets
    rows = [{"content_hash": "bare", "source_id": "x_afcstuff", "body_source": ""},
            {"content_hash": "quoted", "source_id": "x_afcstuff",
             "body_source": "인용 트윗 본문"},
            {"content_hash": "article", "source_id": "bbc_sport",
             "body_source": "기사 본문"}]
    tweets, rest = partition_bodyless_tweets(rows)
    assert [r["content_hash"] for r in tweets] == ["bare"]
    assert [r["content_hash"] for r in rest] == ["quoted", "article"]


def test_parse_full_keeps_null_summary3_as_none_not_the_string_none():
    # str(None) 이 "None" 으로 저장되면 화면에 그 글자가 그대로 뜬다.
    from bullet_in.enrich import _parse_full
    parsed, label, _ = _parse_full('{"title_ko":"T","summary_ko":"S",'
                                   '"summary3_ko":null,"body_ko":"B"}')
    assert label == "" and parsed["summary3_ko"] is None


# --- 안건 2η · 재시도에 사유를 싣는다 ---------------------------------------------

def test_retry_note_revives_injected_club_from_stored_output():
    # 직전 회차가 남긴 산출물에 같은 게이트를 다시 대면 사유가 그대로 나온다 —
    # 사유를 저장할 컬럼을 새로 두지 않아도 된다.
    from bullet_in.enrich import retry_note
    row = {"content_hash": "h", "title_original": "Arsenal want Alvarez.",
           "summary_ko": "맨체스터 시티의 공격수 알바레스가 아스날행에 근접했다.",
           "summary3_ko": None, "body_ko": None}
    note = retry_note(row, {}, {"맨체스터 시티": ["Manchester City", "Man City"]})
    assert "[구단 주입]" in note and "맨체스터 시티" in note


def test_retry_note_is_empty_on_the_first_pass():
    from bullet_in.enrich import retry_note
    row = {"content_hash": "h", "title_original": "Arsenal want Alvarez.",
           "summary_ko": None, "summary3_ko": None, "body_ko": None}
    assert retry_note(row, {}, {"맨체스터 시티": ["Manchester City"]}) == ""


def test_enrich_rows_appends_the_retry_reason_to_the_prompt():
    seen = {}

    class _NoteModels:
        def generate_content(self, **kw):
            seen["contents"] = kw["contents"]
            class R: pass
            r = R()
            r.text = ('{"title_ko":"T","summary_ko":"S",'
                      '"summary3_ko":["a"],"body_ko":"B"}')
            return r

    class _NoteClient:
        def __init__(self): self.models = _NoteModels()

    enrich_rows([{"content_hash": "h", "title_original": "T", "body_source": "B"}],
                _NoteClient(), "m", notes={"h": "\n\n[구단 주입] 사유"})
    assert seen["contents"].endswith("[구단 주입] 사유")


# --- 안건 2η · 재작성 잔존은 다음 회차에 한 번 더 -----------------------------------

def test_already_generated_counts_a_row_that_has_only_a_body():
    # 트윗 경로는 요약을 안 만든다 — 요약만 보면 영원히 첫 회차로 읽혀 회차마다
    # 같은 행을 다시 부른다.
    from bullet_in.enrich import already_generated
    assert already_generated({"summary_ko": None, "body_ko": "본문"}) is True
    assert already_generated({"summary_ko": "요약", "body_ko": None}) is True
    assert already_generated({"summary_ko": None, "body_ko": None}) is False


def test_rewrite_requeue_fires_once_and_not_twice():
    from bullet_in.enrich import rewrite_requeue
    reports = {"first": {"residual": True}, "second": {"residual": True},
               "clean": {"residual": False}}
    by_hash = {"first": {"summary_ko": None, "body_ko": None},        # 첫 회차
               "second": {"summary_ko": "요약", "body_ko": "본문"},   # 이미 한 번 돌았다
               "clean": {"summary_ko": None, "body_ko": None}}
    assert rewrite_requeue(reports, by_hash) == {"first"}


def test_rewrite_report_marks_residual_when_a_number_is_missing():
    # 재큐 판정과 경고 로그가 같은 값을 보게 하는 필드다.
    from bullet_in.enrich import rewrite_rows_guarded
    payload = {"title_ko": "제목", "summary_ko": "요약", "summary3_ko": ["a"],
               "body_ko": "아스날이 선수를 영입했다."}
    rows = [{"content_hash": "h", "title_original": "제목",
             "body_source": "아스날이 5000만 파운드에 선수를 영입했다."}]
    _, reports = rewrite_rows_guarded(rows, FullClient(payload), "m")
    assert reports["h"]["residual"] is True
    assert reports["h"]["missing"]
