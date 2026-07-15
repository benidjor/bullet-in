# 요약 말투 정리 구현 계획 (2026-07-15)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 요약 필드 (`summary_ko` · `summary3_ko`)의 '합니다체' 잔존을 검출기 + 프롬프트 강화 + 선별 백필로 0으로 수렴시킨다.

**Architecture:** 순수 함수 검출기 (`tone.py`)가 존댓말 종결어미를 문장 끝에서만 찾고 (인용부호 안 제외), enrich에 요약 전용 재생성 함수를 추가하며, run.py가 매 사이클 검출된 행을 상한 내에서 재생성한다.
저장된 한국어 본문 (`body_ko` 또는 `body_excerpt`)에서 요약만 다시 쓰므로 `body_ko` · `title_ko`는 불변이다.

**Tech Stack:** Python 3.11 · uv · pytest · SQLAlchemy (MariaDB) · google-genai (Gemini 2.5 Flash-Lite).

**Spec:** `docs/superpowers/specs/2026-07-15-summary-tone-cleanup-design.md`

**Branch:** `feat/summary-tone-cleanup` — main에서 분기.
분기 전 `git fetch origin main && git log origin/main..main --oneline`으로 로컬 main이 앞서 있지 않은지 확인한다 (squash 중복 함정).

## Global Constraints

- 429 규칙: 식별 시 그 회차 즉시 중단 · WARNING 로깅 (파싱 실패와 구분), per-row 백오프 금지 — 기존 `_is_rate_limit` 재사용.
- 재생성은 요약 필드만 갱신한다 — `body_ko` · `title_ko` 불변.
- `summary3_ko`가 원래 NULL이던 행은 `summary_ko`만 갱신한다.
- 대상 필드는 `summary_ko` · `summary3_ko`만 — `body_ko` (인용문 존댓말 정상) · `title_ko` (명사형)는 검출하지 않는다.
- 기존 코드 스타일 준수: 모킹은 `FakeClient`/인라인 클래스 패턴 (tests/test_enrich.py), MartStore 테스트는 tests/integration/ (DB 없으면 skip).
- 커밋: 컨벤션 §1.1 (도입 1–2문장 + 명사형 불릿) · §1.3 (트레일러 = 실제 작업 모델).
  아래 커밋 블록의 구현 모델 표기는 실제 실행 모델로 맞춘다 (설계 · 구현이 같은 모델이면 라벨 없이 한 줄).

---

### Task 1: 검출기 `has_polite_ending` (tone.py)

**Files:**
- Create: `src/bullet_in/tone.py`
- Test: `tests/test_tone.py`

**Interfaces:**
- Produces: `has_polite_ending(text: str | None) -> bool` — 존댓말 종결어미가 문장 끝에 있으면 True, 인용부호 안은 제외.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_tone.py
from bullet_in.tone import has_polite_ending

def test_detects_hamnida_ending():
    assert has_polite_ending("아스날이 기마랑이스 영입에 합의했습니다.")

def test_detects_haeyo_ending():
    assert has_polite_ending("이적료는 협상 중이에요.")

def test_passes_plain_reportive_ending():
    assert not has_polite_ending("아스날이 기마랑이스 영입에 합의했다.")

def test_quoted_polite_speech_is_ignored():
    assert not has_polite_ending('킴은 "우리는 준비돼 있습니다"라고 말했다.')

def test_multiline_summary3_detects_any_sentence():
    s3 = "아스날이 합의했다.\n메디컬이 남았습니다.\n발표는 임박했다."
    assert has_polite_ending(s3)

def test_polite_stem_mid_sentence_is_not_flagged():
    # '필요'처럼 '요'로 끝나는 명사 · 문장 중간의 존댓말 어간은 잡지 않는다
    assert not has_polite_ending("추가 보강이 필요하다는 관측이 나왔다.")

def test_none_and_empty_are_false():
    assert not has_polite_ending(None)
    assert not has_polite_ending("")
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_tone.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bullet_in.tone'`

- [ ] **Step 3: 최소 구현**

```python
# src/bullet_in/tone.py
from __future__ import annotations
import re

# 존댓말(합니다체·해요체) 종결어미 — 문장 끝에서만 검출한다.
# '니다'가 합니다/입니다/됩니다/갑니다/습니다 계열 전부를 커버한다.
_POLITE_END = re.compile(
    r"(니다|해요|예요|에요|세요|네요|군요|는데요|어요|아요|지요|죠)\s*$")

# 인용부호 안은 화자 발화라 존댓말이 정상 — 검출 전에 제거한다.
_QUOTED = re.compile(r'"[^"]*"|“[^”]*”|「[^」]*」|『[^』]*』|\'[^\']*\'')

_SENT_SPLIT = re.compile(r"[.!?…\n]+")

def has_polite_ending(text: str | None) -> bool:
    """요약 텍스트의 문장 끝에 존댓말 종결어미가 남았는지 판정한다."""
    if not text:
        return False
    cleaned = _QUOTED.sub("", text)
    for sent in _SENT_SPLIT.split(cleaned):
        if _POLITE_END.search(sent.strip()):
            return True
    return False
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_tone.py -v`
Expected: 7 passed

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/tone.py tests/test_tone.py
git commit -m "$(cat <<'EOF'
feat(enrich): 존댓말 종결어미 검출기 추가 (tone.py)

요약 필드의 '합니다체' 잔존을 선별 재생성하기 위한 첫 단계로,
문장 끝 존댓말 어미를 판정하는 순수 함수를 추가한다.

- has_polite_ending: '니다' 계열 + 해요체 어미를 문장 끝에서만 검출
- 인용부호 (곧은 · 굽은 따옴표 · 낫표) 안 발화는 제거 후 판정 — 정상
  요약의 무한 재생성 방지
- 테스트 7종: 합니다체 · 해요체 검출, 평어체 · 인용문 · 문중 어간 통과

Refs: docs/superpowers/specs/2026-07-15-summary-tone-cleanup-design.md
Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 백필 선별 `select_tone_backfill` (tone.py)

**Files:**
- Modify: `src/bullet_in/tone.py`
- Test: `tests/test_tone.py`

**Interfaces:**
- Consumes: `has_polite_ending` (Task 1).
- Produces: `select_tone_backfill(rows: list[dict], limit: int) -> list[dict]` — `summary_ko` 또는 `summary3_ko`가 검출된 행을 원본 dict 그대로, 최대 limit건 반환.

- [ ] **Step 1: 실패하는 테스트 작성 (tests/test_tone.py에 추가)**

```python
from bullet_in.tone import select_tone_backfill

def _row(h, s, s3=None):
    return {"content_hash": h, "summary_ko": s, "summary3_ko": s3}

def test_select_picks_rows_flagged_in_either_field():
    rows = [_row("a", "합의했다."),
            _row("b", "합의했습니다."),
            _row("c", "협상했다.", "발표했다.\n메디컬이 남았습니다.")]
    picked = select_tone_backfill(rows, limit=10)
    assert [r["content_hash"] for r in picked] == ["b", "c"]

def test_select_respects_limit():
    rows = [_row(str(i), "확정했습니다.") for i in range(5)]
    assert len(select_tone_backfill(rows, limit=2)) == 2

def test_select_empty_pool_returns_empty():
    assert select_tone_backfill([], limit=20) == []
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_tone.py -v`
Expected: FAIL — `ImportError: cannot import name 'select_tone_backfill'`

- [ ] **Step 3: 최소 구현 (tone.py에 추가)**

```python
def select_tone_backfill(rows: list[dict], limit: int) -> list[dict]:
    """summary_ko · summary3_ko 에 존댓말이 남은 행을 limit 건까지 선별한다."""
    picked: list[dict] = []
    for r in rows:
        if has_polite_ending(r.get("summary_ko")) or has_polite_ending(r.get("summary3_ko")):
            picked.append(r)
            if len(picked) >= limit:
                break
    return picked
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_tone.py -v`
Expected: 10 passed

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/tone.py tests/test_tone.py
git commit -m "$(cat <<'EOF'
feat(enrich): 말투 백필 대상 선별 함수 추가

검출기를 행 선별에 연결한다 — 요약 두 필드 중 하나라도 존댓말이
남은 행을 회차 상한까지만 고른다 (429 여유 확보).

- select_tone_backfill: 원본 row dict 유지 (뒤 단계가 body_ko ·
  summary3_ko 유무를 참조), limit 도달 시 즉시 중단
- 테스트 3종: 두 필드 판정 · 상한 준수 · 빈 풀

Refs: docs/superpowers/specs/2026-07-15-summary-tone-cleanup-design.md
Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 요약 재생성 `resummarize_rows` (enrich.py)

**Files:**
- Modify: `src/bullet_in/enrich.py` (SUMMARY_PROMPT 아래에 RESUMMARY_PROMPT, summarize_ko_rows 아래에 함수 2개 추가)
- Test: `tests/test_enrich.py`

**Interfaces:**
- Consumes: `_is_rate_limit` (enrich.py 기존).
- Produces: `resummarize_rows(rows: list[dict], client, model: str) -> dict[str, dict]` — content_hash → `{"summary_ko": str, "summary3_ko": str}` (summary3는 `"\n"` join된 str).
  rows의 각 dict는 `content_hash` · `title_original` 필수, `title_ko` · `body_ko` · `body_excerpt` 선택.

- [ ] **Step 1: 실패하는 테스트 작성 (tests/test_enrich.py 끝에 추가)**

```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_enrich.py -v -k resummarize`
Expected: FAIL — `ImportError: cannot import name 'resummarize_rows'`

- [ ] **Step 3: 최소 구현 (enrich.py에 추가)**

SUMMARY_PROMPT 정의 바로 아래에:

```python
RESUMMARY_PROMPT = (
    "다음 한국어 축구 기사의 요약을 다시 쓴다. 규칙:\n"
    "- summary_ko: 한 문장, 신문 평어체(종결어미 '~다'), 사실 중심.\n"
    "- summary3_ko: 핵심을 3문장으로, 각 문장 평어체. 문자열 3개 배열.\n"
    "- 존댓말 금지: '영입을 확정했습니다' ❌ → '영입을 확정했다' ⭕.\n"
    "- 고유명사는 통용 한글 표기(Arsenal=아스날).\n"
    'ONLY JSON: {{"summary_ko":"...","summary3_ko":["...","...","..."]}}'
    "\n\n제목: {title}\n본문: {body}")
```

summarize_ko_rows 함수 바로 아래에:

```python
def _extract_resummary(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        s3 = d["summary3_ko"]
        s3 = "\n".join(s3) if isinstance(s3, list) else str(s3)
        return {"summary_ko": d["summary_ko"], "summary3_ko": s3}
    except (json.JSONDecodeError, KeyError, TypeError):
        return None

def resummarize_rows(rows: list[dict], client, model: str) -> dict[str, dict]:
    """말투 백필: 저장된 한국어 본문에서 요약만 재생성한다.
    content_hash -> {summary_ko, summary3_ko}. 429는 그 회차 즉시 중단,
    파싱 실패는 행 단위 스킵 (다음 사이클에 검출 기반으로 재선별)."""
    result: dict[str, dict] = {}
    for r in rows:
        h = r["content_hash"]
        try:
            msg = client.models.generate_content(
                model=model,
                contents=RESUMMARY_PROMPT.format(
                    title=r.get("title_ko") or r["title_original"],
                    body=r.get("body_ko") or r.get("body_excerpt") or ""),
                config={"max_output_tokens": 1024,
                        "response_mime_type": "application/json"})
        except Exception as e:
            if _is_rate_limit(e):
                log.warning("Gemini rate limit(429), 말투 백필 중단 — 남은 행 다음 사이클")
                break
            log.warning("Gemini 호출 실패, 말투 백필 스킵 content_hash=%s: %s", h, e)
            continue
        parsed = _extract_resummary(msg.text)
        if parsed is None:
            log.warning("Gemini 응답 파싱 실패, 말투 백필 스킵 content_hash=%s", h)
            continue
        result[h] = parsed
    return result
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_enrich.py -v`
Expected: 기존 포함 전체 passed (신규 3개 포함)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/enrich.py tests/test_enrich.py
git commit -m "$(cat <<'EOF'
feat(enrich): 요약 전용 재생성 함수 추가 (말투 백필용)

검출된 행의 요약만 저장된 한국어 본문 (body_ko 우선, 폴백
body_excerpt) 에서 다시 쓴다 — body_ko · title_ko 는 불변.

- RESUMMARY_PROMPT: 평어체 + 존댓말 금지 대비 예시, JSON 2필드 반환
- resummarize_rows: 429 회차 중단 · 파싱 실패 행 스킵 (기존 enrich
  경로와 동일 규칙), summary3 는 배열 → 개행 join
- 테스트 3종: 정상 반환 · 429 중단 · 불량 행 스킵

Refs: docs/superpowers/specs/2026-07-15-summary-tone-cleanup-design.md
Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 기존 프롬프트 3종 존댓말 금지 예시 강화

**Files:**
- Modify: `src/bullet_in/enrich.py:16-39` (SUMMARY_PROMPT · TRANSLATE_PROMPT · PARAPHRASE_PROMPT)
- Test: `tests/test_enrich.py`

**Interfaces:**
- Produces: 4개 프롬프트 모두 "했습니다"(금지 예) · "했다"(올바름 예)를 포함 — 가드 테스트가 회귀를 잡는다.

- [ ] **Step 1: 실패하는 가드 테스트 작성 (tests/test_enrich.py 끝에 추가)**

```python
def test_all_prompts_carry_polite_ban_example():
    # 존댓말 금지 대비 예시가 프롬프트에서 빠지면 회귀 — 4종 모두 검사
    from bullet_in.enrich import (SUMMARY_PROMPT, TRANSLATE_PROMPT,
                                  PARAPHRASE_PROMPT, RESUMMARY_PROMPT)
    for p in (SUMMARY_PROMPT, TRANSLATE_PROMPT, PARAPHRASE_PROMPT, RESUMMARY_PROMPT):
        assert "했습니다" in p and "했다" in p
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_enrich.py::test_all_prompts_carry_polite_ban_example -v`
Expected: FAIL — SUMMARY_PROMPT 등 3종에 예시 없음

- [ ] **Step 3: 프롬프트 수정**

SUMMARY_PROMPT — `추측·과장 금지.` 문구 뒤에 삽입:

```python
SUMMARY_PROMPT = ("다음 한국어 축구 뉴스를 한 문장으로 요약한다. "
                  "신문 평어체(종결어미 '~다'), 사실 중심, 추측·과장 금지. "
                  "존댓말 금지: '영입을 확정했습니다' ❌ → '영입을 확정했다' ⭕. "
                  "고유명사는 통용 한글 표기(Arsenal=아스날). "
                  'JSON만 반환: {{"summary_ko": "..."}}\n\n제목: {title}\n본문: {body}')
```

TRANSLATE_PROMPT — summary3_ko 규칙 줄 다음에 규칙 줄 삽입:

```python
    "- summary3_ko: 핵심을 3문장으로, 각 문장 평어체. 문자열 3개 배열.\n"
    "- summary_ko·summary3_ko 존댓말 금지: '확정했습니다' ❌ → '확정했다' ⭕.\n"
```

PARAPHRASE_PROMPT — summary3_ko 규칙 줄 다음에 동일 규칙 줄 삽입:

```python
    "- summary3_ko: 핵심 3문장 배열, 평어체.\n"
    "- summary_ko·summary3_ko 존댓말 금지: '확정했습니다' ❌ → '확정했다' ⭕.\n"
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_enrich.py -v`
Expected: 전체 passed

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/enrich.py tests/test_enrich.py
git commit -m "$(cat <<'EOF'
feat(enrich): 프롬프트 3종에 존댓말 금지 대비 예시 추가

평어체 지시가 이미 있는데도 모델이 간헐적으로 무시하는 문제 —
규칙 서술 대신 금지/올바름 대비 예시 한 쌍으로 이탈을 줄인다.

- SUMMARY · TRANSLATE · PARAPHRASE 에 '확정했습니다 ❌ → 확정했다 ⭕'
- 가드 테스트: 4종 프롬프트 (RESUMMARY 포함) 예시 존재 검사

Refs: docs/superpowers/specs/2026-07-15-summary-tone-cleanup-design.md
Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: MartStore 백필 풀 조회 · 요약 저장

**Files:**
- Modify: `src/bullet_in/storage/mariadb.py` (`rows_missing_stage` 아래에 메서드 2개 추가)
- Test: `tests/integration/test_mariadb_store.py` (DB 없으면 자동 skip)

**Interfaces:**
- Produces: `MartStore.rows_enriched_summaries() -> list[dict]` — 키: content_hash · title_original · title_ko · body_excerpt · body_ko · summary_ko · summary3_ko (summary_ko IS NOT NULL인 행만).
- Produces: `MartStore.set_summary(content_hash: str, summary_ko: str, summary3_ko: str | None = None) -> None` — summary3_ko가 None이면 기존 값 보존.

- [ ] **Step 1: 실패하는 테스트 작성 (tests/integration/test_mariadb_store.py 끝에 추가)**

```python
def test_rows_enriched_summaries_returns_only_summarized(engine):
    from sqlalchemy import text
    store = MartStore(engine)
    store.upsert([_art(h="he", url="https://x.test/e", title="E"),
                  _art(h="hn", url="https://x.test/n", title="N")])
    store.set_translation("he", "제목", "확정했습니다.", "①\n②\n③", "본문")
    pool = {r["content_hash"]: r for r in store.rows_enriched_summaries()}
    assert "he" in pool and "hn" not in pool
    assert pool["he"]["summary_ko"] == "확정했습니다."
    assert pool["he"]["body_ko"] == "본문"
    assert pool["he"]["title_ko"] == "제목"

def test_set_summary_updates_summary_fields_only(engine):
    from sqlalchemy import text
    store = MartStore(engine)
    store.upsert([_art(h="ht", url="https://x.test/t", title="T")])
    store.set_translation("ht", "제목", "확정했습니다.", "A입니다.\nB다.\nC다.", "본문")
    store.set_summary("ht", "확정했다.", "A다.\nB다.\nC다.")
    with engine.connect() as c:
        r = dict(c.execute(text(
            "SELECT title_ko,summary_ko,summary3_ko,body_ko "
            "FROM articles WHERE content_hash='ht'")).mappings().one())
    assert r["summary_ko"] == "확정했다." and r["summary3_ko"] == "A다.\nB다.\nC다."
    assert r["title_ko"] == "제목" and r["body_ko"] == "본문"

def test_set_summary_without_s3_preserves_existing(engine):
    from sqlalchemy import text
    store = MartStore(engine)
    store.upsert([_art(h="hp", url="https://x.test/p", title="P")])
    store.set_translation("hp", "제목", "확정했습니다.", "기존3줄", "본문")
    store.set_summary("hp", "확정했다.")
    with engine.connect() as c:
        r = dict(c.execute(text(
            "SELECT summary_ko,summary3_ko FROM articles "
            "WHERE content_hash='hp'")).mappings().one())
    assert r["summary_ko"] == "확정했다." and r["summary3_ko"] == "기존3줄"
```

- [ ] **Step 2: 실패 확인**

Run: `docker compose up -d && uv run pytest tests/integration/test_mariadb_store.py -v`
Expected: 신규 3개 FAIL — `AttributeError: 'MartStore' object has no attribute 'rows_enriched_summaries'`
(DB 미기동 환경이면 skip — 그 경우 라이브 검증은 Task 7에서)

- [ ] **Step 3: 최소 구현 (mariadb.py `rows_missing_stage` 아래에 추가)**

```python
    def rows_enriched_summaries(self) -> list[dict]:
        """요약이 이미 생성된 행 — 말투 백필 후보 풀."""
        with self.engine.connect() as c:
            rows = c.execute(text(
                "SELECT content_hash,title_original,title_ko,body_excerpt,"
                "body_ko,summary_ko,summary3_ko "
                "FROM articles WHERE summary_ko IS NOT NULL")).mappings().all()
        return [dict(r) for r in rows]

    def set_summary(self, content_hash: str, summary_ko: str,
                    summary3_ko: str | None = None) -> None:
        """요약 필드만 갱신 — summary3_ko 가 None 이면 기존 값을 보존한다."""
        with self.engine.begin() as c:
            if summary3_ko is None:
                c.execute(text("UPDATE articles SET summary_ko=:s "
                               "WHERE content_hash=:h"),
                          {"s": summary_ko, "h": content_hash})
            else:
                c.execute(text("UPDATE articles SET summary_ko=:s, "
                               "summary3_ko=:s3 WHERE content_hash=:h"),
                          {"s": summary_ko, "s3": summary3_ko, "h": content_hash})
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/integration/test_mariadb_store.py -v`
Expected: 전체 passed (또는 DB 없으면 skip)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/storage/mariadb.py tests/integration/test_mariadb_store.py
git commit -m "$(cat <<'EOF'
feat(enrich): MartStore 말투 백필 조회 · 요약 저장 메서드

백필 파이프라인의 DB 양끝 — 후보 풀 조회와 요약 필드 한정 갱신을
추가한다.

- rows_enriched_summaries: summary_ko 존재 행만 (백필 후보 풀),
  재생성 입력용 title_ko · body_ko · body_excerpt 동봉
- set_summary: 요약 2필드만 UPDATE, summary3_ko None 이면 보존
  (ko 요약 전용 행이 3줄 요약을 새로 얻지 않도록)
- 통합 테스트 3종: 풀 경계 · 타 필드 불변 · s3 보존

Refs: docs/superpowers/specs/2026-07-15-summary-tone-cleanup-design.md
Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: run.py 백필 패스 연결 + config 상한

**Files:**
- Modify: `src/bullet_in/run.py:16` (import) · `src/bullet_in/run.py:67-71` (분류 패스 직후, 서빙 SELECT 이전)
- Modify: `config/sources.yaml:1` 근처 (`freshness_default_hours` 옆)

**Interfaces:**
- Consumes: `select_tone_backfill` (Task 2) · `resummarize_rows` (Task 3) · `rows_enriched_summaries` / `set_summary` (Task 5).
- Produces: 사이클당 최대 `tone_backfill_limit`건 재생성 — 서빙 SELECT 이전에 실행되므로 고친 요약이 같은 사이클에 렌더된다.

- [ ] **Step 1: config 키 추가 (config/sources.yaml 최상단, freshness_default_hours 아래)**

```yaml
tone_backfill_limit: 20       # 말투 백필 회차 상한 (429 여유 내, 라이브 실측 후 조정)
```

- [ ] **Step 2: run.py import 수정 (16행)**

```python
from bullet_in.enrich import enrich_rows, classify_stage_rows, resummarize_rows
from bullet_in.tone import select_tone_backfill
```

- [ ] **Step 3: 분류 패스 (`mart.set_stage` 루프) 직후 · 서빙 SELECT 이전에 삽입**

```python
    # 말투 백필: 요약에 존댓말이 남은 행을 회차 상한 내에서 재생성 (멱등 — 검출 기반 재선별)
    tone_limit = int(cfg.get("tone_backfill_limit", 20))
    tone_rows = select_tone_backfill(mart.rows_enriched_summaries(), tone_limit)
    if tone_rows:
        fixed = resummarize_rows(tone_rows, client, GEMINI_MODEL)
        for h, v in fixed.items():
            orig = next(r for r in tone_rows if r["content_hash"] == h)
            mart.set_summary(h, v["summary_ko"],
                             v["summary3_ko"] if orig.get("summary3_ko") else None)
        logging.getLogger(__name__).info(
            "말투 백필: 대상 %d건 중 %d건 재생성", len(tone_rows), len(fixed))
```

- [ ] **Step 4: 전체 테스트 · 임포트 확인**

Run: `uv run pytest -q && uv run python -c "import bullet_in.run"`
Expected: 전체 passed (통합은 DB 없으면 skip) · 임포트 에러 없음

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/run.py config/sources.yaml
git commit -m "$(cat <<'EOF'
feat(enrich): 말투 백필 패스를 run 사이클에 연결

분류 패스 직후 · 서빙 SELECT 이전에 백필을 실행해, 고친 요약이
같은 사이클의 정적 사이트에 바로 렌더되게 한다.

- run.py: 검출 선별 → 재생성 → set_summary, 회차 결과 INFO 로깅
- summary3_ko 가 원래 없던 행 (ko 요약 전용) 은 summary_ko 만 갱신
- config: tone_backfill_limit 20 (라이브 실측 후 조정)

Refs: docs/superpowers/specs/2026-07-15-summary-tone-cleanup-design.md
Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: 라이브 잔존 실측 · 상한 확정 · 수렴 검증

라이브 DB · `.env`가 필요한 운영 단계 — 머지 전 실측 1회 (상한 판단), 머지 후 수렴 확인.

**Files:**
- 없음 (판단 결과에 따라 `config/sources.yaml`의 `tone_backfill_limit`만 조정 가능)

- [ ] **Step 1: 잔존 규모 실측**

```bash
set -a; source .env; set +a
uv run python - <<'EOF'
import os
from sqlalchemy import create_engine
from bullet_in.storage.mariadb import MartStore
from bullet_in.tone import has_polite_ending
mart = MartStore(create_engine(os.environ["MARIADB_URL"]))
rows = mart.rows_enriched_summaries()
bad = [r for r in rows
       if has_polite_ending(r.get("summary_ko")) or has_polite_ending(r.get("summary3_ko"))]
print(f"잔존 {len(bad)} / 전체 {len(rows)}")
for r in bad[:5]:
    print("-", r["content_hash"][:8], (r.get("summary_ko") or "")[:60])
EOF
```

Expected: `잔존 N / 전체 M` 출력.
샘플 5건을 눈으로 확인해 오검출 (인용문 등)이 없는지 본다 — 오검출이 있으면 Task 1 어미 목록을 테스트와 함께 조정.

- [ ] **Step 2: 상한 판단**

N ≤ 80이면 (20건 × 하루 4회 = 하루 내 수렴) 기본값 20 유지.
N > 80이면 `tone_backfill_limit`를 상향 (예: 40) — 429는 분당 속도 한도라 회차 내 직렬 호출 수십 건은 안전, 근거는 CLAUDE.md 함정 절.

- [ ] **Step 3: 1사이클 스모크**

```bash
uv run python -m bullet_in.run --concurrency 8
```

Expected: 로그에 `말투 백필: 대상 k건 중 j건 재생성` INFO — 429 발생 시 WARNING 후 정상 종료.

- [ ] **Step 4: 수렴 확인 (백필 사이클 경과 후)**

Step 1 스크립트 재실행.
Expected: `잔존 0 / 전체 M` — 이 트랙의 종료 조건이자 v1 완성 선언 조건의 일부.
0이 아니면 남은 건의 요약을 눈으로 확인 — 모델이 반복 실패하는 행이면 해당 건만 수동 재생성 또는 어미 목록 재검토.

---

## Self-Review 결과

- Spec 커버리지: 검출기 (Task 1) · 인용 예외 (Task 1) · 프롬프트 강화 (Task 3 · 4) · 선별 백필 (Task 2 · 5 · 6) · 429 규칙 (Task 3 · Global) · 요약 필드만 갱신 (Task 5 · 6) · 상한 실측 조정 (Task 7) · 완료 기준 검출 0건 (Task 7) — 갭 없음.
- 열어 둔 판단 해소: summary_ko와 summary3_ko는 **한 호출**로 재생성 (RESUMMARY_PROMPT가 2필드 동시 반환) — 429 예산 절약.
  summary3가 원래 NULL이던 행은 summary_ko만 저장해 범위를 지킨다.
- 타입 정합: `select_tone_backfill`이 반환하는 원본 row dict의 키 (title_ko · body_ko · body_excerpt · summary3_ko)를 Task 3 · 6이 그대로 소비 — `rows_enriched_summaries`의 SELECT 목록과 일치 확인.
