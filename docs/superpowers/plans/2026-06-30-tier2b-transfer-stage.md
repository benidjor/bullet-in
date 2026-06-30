# Tier 2-b 영입 단계 분류 · 필터 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 각 기사를 LLM이 6개 영입 단계 (+`other`) 중 하나로 태깅하고, 사이드바 단계 필터를 활성화하며 카드 · 상세 페이지에 단계 배지를 표시한다.

**Architecture:** 단계 enum ↔ 한국어 라벨 ↔ css 클래스를 신규 모듈 `transfer_stage.py` 한 곳에 정의 (단일 출처). 번역과 분리된 **분류 전용 패스** (`enrich.classify_stage_rows`) 가 `transfer_stage IS NULL` 행을 배치로 분류해 신규 · 기존 203건을 균일 처리. 서빙은 기존 정적 HTML 패턴 (Jinja 템플릿 + 정적 CSS/JS) 에 단계 필터 · 배지를 얹는다.

**Tech Stack:** Python 3.11, uv, pydantic v2, SQLAlchemy (MariaDB), Jinja2, google-genai (Gemini), pytest.

## Global Constraints

- Python 3.11 · uv · pydantic v2 · 신규 외부 의존성 없음 (요청 범위 밖 추가 금지).
- 산출물 · 주석 · 커밋 · 문서는 한국어. 단계 enum 값만 영문 (`official` · `medical` · `personal_terms` · `negotiating` · `interest` · `rumour` · `other`).
- 커밋: `<type>(<scope>): 한국어 제목` + 본문 (왜) + `Refs:` + 트레일러. scope는 세트 (`infra adapters ingest pipeline storage enrich credibility score serve dbt slo airflow env`, docs는 토픽 scope) 에서 고름.
- 커밋 트레일러: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. author/git 신원은 `benidjor <94089198+benidjor@users.noreply.github.com>`.
- 기호 간격 (§2.2): 산문에서 `·` · `+` · 여는 괄호 `(` 양옆 띄움 (코드 · 인라인 코드 · URL · 경로 · SQL 제외).
- karpathy 4원칙: 문제 푸는 최소 코드 · 수술적 변경 · 요청 범위 밖 기능 금지.
- 429 전략 재사용: 분류 패스도 429 식별 시 그 회차 중단 · WARNING 로깅, 남은 배치는 다음 사이클 누적 (기존 `_is_rate_limit` 재사용).
- 작업 브랜치: `feat/tier2b-transfer-stage` (이미 생성됨, spec 커밋 `d6e00fc` 위에 쌓음).
- 통합 테스트 (`tests/integration/`) 는 MariaDB 없으면 skip. docker `mariadb`가 떠 있으면 실제 실행됨.

---

## 파일 구조

**신규**
- `src/bullet_in/transfer_stage.py` — 단계 enum ↔ 라벨 ↔ css ↔ 사이드바 순서 단일 출처. `normalize` · `label_for` · `css_for` · `is_displayable` 헬퍼.
- `tests/test_transfer_stage.py` — 위 모듈 단위 테스트.

**수정**
- `src/bullet_in/models.py` — `Article.transfer_stage` 필드.
- `src/bullet_in/storage/schema.sql` — `transfer_stage` 컬럼 (CREATE + ALTER).
- `src/bullet_in/storage/mariadb.py` — upsert INSERT 컬럼 · `rows_missing_stage()` · `set_stage()`.
- `src/bullet_in/enrich.py` — `STAGE_PROMPT` · `_extract_stages` · `classify_stage_rows`.
- `src/bullet_in/serve/render.py` — `_env` globals · `_decorate` 단계 필드 · `facet_counts` stage · `render_article` 폴백.
- `src/bullet_in/serve/templates/_layout.html.j2` — 단계 필터 활성화 · 타 구단 자리 삭제.
- `src/bullet_in/serve/templates/index.html.j2` — `data-stage` · 단계 배지.
- `src/bullet_in/serve/templates/detail.html.j2` — 단계 배지.
- `src/bullet_in/serve/static/style.css` — `.s-personal` · `.s-interest` · `.chip.stagebadge`.
- `src/bullet_in/serve/static/app.js` — `okStage` 필터.
- `src/bullet_in/run.py` — 분류 패스 연결 · `transfer_stage` SELECT.
- `tests/test_enrich.py` · `tests/test_serve_layout.py` · `tests/test_serve_render.py` · `tests/integration/test_mariadb_store.py` — 테스트 추가/갱신.

---

## Task 1: 영입 단계 단일 출처 모듈

**Files:**
- Create: `src/bullet_in/transfer_stage.py`
- Test: `tests/test_transfer_stage.py`

**Interfaces:**
- Consumes: (없음 — 순수 상수/헬퍼)
- Produces:
  - `SIDEBAR_STAGES: list[tuple[str, str, str]]` — `(enum, 한국어 라벨, css 클래스)`, 사이드바 표시 순서.
  - `STAGE_ENUMS: list[str]` — 6개 enum.
  - `OTHER: str = "other"`, `VALID_STAGES: set[str]`.
  - `normalize(value: str | None) -> str` — 허용 enum이면 그대로, 아니면 `"other"`.
  - `label_for(stage: str | None) -> str` · `css_for(stage: str | None) -> str` — 6개 enum만 매핑, 그 외 `""`.
  - `is_displayable(stage: str | None) -> bool` — 6개 enum이면 True (other · None은 False).

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_transfer_stage.py`:

```python
import bullet_in.transfer_stage as ts


def test_sidebar_stages_order_and_count():
    enums = [e for e, _, _ in ts.SIDEBAR_STAGES]
    assert enums == ["official", "medical", "personal_terms",
                     "negotiating", "interest", "rumour"]


def test_label_and_css_lookup():
    assert ts.label_for("official") == "오피셜"
    assert ts.label_for("personal_terms") == "개인 합의"
    assert ts.css_for("interest") == "s-interest"
    assert ts.label_for("other") == ""   # other는 라벨 없음


def test_normalize_keeps_valid_else_other():
    assert ts.normalize("medical") == "medical"
    assert ts.normalize("other") == "other"
    assert ts.normalize("bogus") == "other"
    assert ts.normalize(None) == "other"


def test_is_displayable_excludes_other_and_none():
    assert ts.is_displayable("rumour") is True
    assert ts.is_displayable("other") is False
    assert ts.is_displayable(None) is False
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_transfer_stage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bullet_in.transfer_stage'`

- [ ] **Step 3: 모듈 구현**

Create `src/bullet_in/transfer_stage.py`:

```python
"""영입 단계 단일 출처 — enum ↔ 한국어 라벨 ↔ css 클래스 ↔ 사이드바 순서.

enrich (프롬프트 · 검증) · render (라벨 · 클래스) · 서빙 템플릿이 이 모듈을
공유해 단계 정의가 한 곳에만 존재하도록 한다.
"""
from __future__ import annotations

# (enum, 한국어 라벨, css 클래스) — 사이드바 표시 순서 (위 → 아래, 진행 단계 높은 순)
SIDEBAR_STAGES: list[tuple[str, str, str]] = [
    ("official", "오피셜", "s-off"),
    ("medical", "메디컬", "s-med"),
    ("personal_terms", "개인 합의", "s-personal"),
    ("negotiating", "협상 중", "s-talk"),
    ("interest", "관심", "s-interest"),
    ("rumour", "루머", "s-rum"),
]

OTHER = "other"

STAGE_ENUMS: list[str] = [e for e, _, _ in SIDEBAR_STAGES]
_LABEL = {e: label for e, label, _ in SIDEBAR_STAGES}
_CSS = {e: css for e, _, css in SIDEBAR_STAGES}
VALID_STAGES = set(STAGE_ENUMS) | {OTHER}


def normalize(value: str | None) -> str:
    """LLM이 돌려준 값이 허용 enum이면 그대로, 아니면 other로 강등."""
    return value if value in VALID_STAGES else OTHER


def label_for(stage: str | None) -> str:
    return _LABEL.get(stage or "", "")


def css_for(stage: str | None) -> str:
    return _CSS.get(stage or "", "")


def is_displayable(stage: str | None) -> bool:
    """배지 표시 대상인지 (other · None · 미지정은 배지 생략)."""
    return (stage or "") in _LABEL
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_transfer_stage.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/transfer_stage.py tests/test_transfer_stage.py
git commit -F - <<'EOF'
feat(enrich): 영입 단계 enum · 라벨 · css 단일 출처 모듈 추가

분류 (enrich) · 서빙 (render · 템플릿) 이 단계 정의를 공유하되 한 곳에만
두어 표류를 막기 위해 전용 모듈을 도입함. 6개 단계 + other 강등 규칙을
normalize · label_for · css_for · is_displayable로 노출.

Refs: docs/superpowers/plans/2026-06-30-tier2b-transfer-stage.md (Task 1)
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

## Task 2: 데이터 모델 · 스키마 컬럼

**Files:**
- Modify: `src/bullet_in/models.py:33` (team 필드 다음)
- Modify: `src/bullet_in/storage/schema.sql:13` (CREATE) · `:24` (ALTER 다음)
- Test: `tests/test_models.py` (append)

**Interfaces:**
- Consumes: (없음)
- Produces: `Article.transfer_stage: str | None = None` — 이후 upsert · render가 읽음. DB `articles.transfer_stage VARCHAR(32) NULL`.

- [ ] **Step 1: 실패 테스트 작성**

Append to `tests/test_models.py`:

```python
def test_article_accepts_transfer_stage():
    from datetime import datetime, timezone
    from bullet_in.models import Article
    a = Article(content_hash="h", url="https://x/1", source_id="s",
                title_original="T", transfer_stage="rumour",
                published_at=datetime(2026, 6, 30, tzinfo=timezone.utc))
    assert a.transfer_stage == "rumour"


def test_article_transfer_stage_defaults_none():
    from datetime import datetime, timezone
    from bullet_in.models import Article
    a = Article(content_hash="h", url="https://x/1", source_id="s",
                title_original="T",
                published_at=datetime(2026, 6, 30, tzinfo=timezone.utc))
    assert a.transfer_stage is None
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_models.py -k transfer_stage -v`
Expected: FAIL — `test_article_accepts_transfer_stage` raises `ValidationError` (또는 `transfer_stage`가 모델에 없어 무시되어 AttributeError)

- [ ] **Step 3: 모델 · 스키마 구현**

In `src/bullet_in/models.py`, after line 33 (`team: str = "arsenal"`), add:

```python
    transfer_stage: str | None = None
```

In `src/bullet_in/storage/schema.sql`, in the `CREATE TABLE IF NOT EXISTS articles` block, after the `team VARCHAR(32) DEFAULT 'arsenal',` line (line 13), add:

```sql
  transfer_stage VARCHAR(32),
```

And after the team ALTER line (line 24, `ALTER TABLE articles ADD COLUMN IF NOT EXISTS team ...`), add:

```sql
ALTER TABLE articles ADD COLUMN IF NOT EXISTS transfer_stage VARCHAR(32);
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_models.py -k transfer_stage -v`
Expected: PASS (2 passed)

DB가 떠 있으면 스키마 적용도 확인:
Run: `uv run pytest tests/integration/test_schema_bootstrap.py -v`
Expected: PASS (또는 SKIP — MariaDB 없을 때)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/models.py src/bullet_in/storage/schema.sql tests/test_models.py
git commit -F - <<'EOF'
feat(storage): articles에 transfer_stage 컬럼 추가

영입 단계 태깅을 저장할 자리를 마련함. 기존 컬럼 추가 패턴대로 CREATE에
컬럼을 넣고 ALTER ... ADD COLUMN IF NOT EXISTS로 멱등 적용. 모델에도
대응 필드를 두되 기본 NULL (미태깅) 로 분류 패스가 채우게 함.

Refs: docs/superpowers/plans/2026-06-30-tier2b-transfer-stage.md (Task 2)
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

## Task 3: MartStore — 트리거 · 저장 · upsert 컬럼

**Files:**
- Modify: `src/bullet_in/storage/mariadb.py` (upsert INSERT 컬럼 + 신규 2 메서드)
- Test: `tests/integration/test_mariadb_store.py` (append)

**Interfaces:**
- Consumes: `Article.transfer_stage` (Task 2).
- Produces:
  - `MartStore.rows_missing_stage() -> list[dict]` — `transfer_stage IS NULL`인 행의 `content_hash` · `title_original` · `summary_ko`.
  - `MartStore.set_stage(content_hash: str, stage: str) -> None`.
  - upsert INSERT가 `transfer_stage`를 적재 (단, `ON DUPLICATE KEY UPDATE`에는 없어 기존 값 보존).

- [ ] **Step 1: 실패 테스트 작성**

Append to `tests/integration/test_mariadb_store.py`:

```python
def test_rows_missing_stage_and_set_stage(engine):
    from bullet_in.models import Article
    from datetime import datetime, timezone
    store = MartStore(engine)
    store.upsert([Article(content_hash="hs", url="https://x.test/s",
                          source_id="bbc_sport",
                          title_original="Arsenal close on Gyokeres",
                          summary_ko="요케레스 임박",
                          published_at=datetime(2026, 6, 30, tzinfo=timezone.utc))])
    missing = {r["content_hash"]: r for r in store.rows_missing_stage()}
    assert "hs" in missing
    assert missing["hs"]["title_original"] == "Arsenal close on Gyokeres"
    assert missing["hs"]["summary_ko"] == "요케레스 임박"
    store.set_stage("hs", "negotiating")
    assert "hs" not in {r["content_hash"] for r in store.rows_missing_stage()}


def test_upsert_preserves_stage_on_revision_change(engine):
    from bullet_in.models import Article
    from datetime import datetime, timezone
    from sqlalchemy import text
    store = MartStore(engine)
    store.upsert([Article(content_hash="h1", url="https://x.test/a", source_id="g",
                          title_original="Old",
                          published_at=datetime(2026, 5, 27, tzinfo=timezone.utc))])
    store.set_stage("h1", "rumour")
    # url 동일, hash · title 변경 (revision++) → 번역은 리셋되지만 단계는 보존
    store.upsert([Article(content_hash="h2", url="https://x.test/a", source_id="g",
                          title_original="New", revision=2,
                          published_at=datetime(2026, 5, 27, tzinfo=timezone.utc))])
    with engine.connect() as c:
        stage = c.execute(text("SELECT transfer_stage FROM articles "
                               "WHERE content_hash='h2'")).scalar_one()
    assert stage == "rumour"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/integration/test_mariadb_store.py -k "stage" -v`
Expected: FAIL — `AttributeError: 'MartStore' object has no attribute 'rows_missing_stage'` (DB 없으면 SKIP — 그 경우 이 Task는 docker DB를 띄운 뒤 검증)

- [ ] **Step 3: 구현**

In `src/bullet_in/storage/mariadb.py`, update the `upsert` INSERT column list and VALUES to include `transfer_stage`. Change the INSERT block:

```python
        sql = text("""
          INSERT INTO articles
            (content_hash,url,source_id,author,tier,confidence_score,
             title_original,title_ko,summary_ko,body_excerpt,
             summary3_ko,body_ko,body_source,image_url,outlet,journalist,team,
             transfer_stage,
             published_at,fetched_at,revision)
          VALUES (:content_hash,:url,:source_id,:author,:tier,:confidence_score,
             :title_original,:title_ko,:summary_ko,:body_excerpt,
             :summary3_ko,:body_ko,:body_source,:image_url,:outlet,:journalist,:team,
             :transfer_stage,
             :published_at,:fetched_at,:revision)
          ON DUPLICATE KEY UPDATE
             title_ko=IF(articles.content_hash=VALUES(content_hash), articles.title_ko, NULL),
             summary_ko=IF(articles.content_hash=VALUES(content_hash), articles.summary_ko, NULL),
             summary3_ko=IF(articles.content_hash=VALUES(content_hash), articles.summary3_ko, NULL),
             body_ko=IF(articles.content_hash=VALUES(content_hash), articles.body_ko, NULL),
             title_original=VALUES(title_original),
             body_excerpt=VALUES(body_excerpt),
             body_source=VALUES(body_source),
             image_url=VALUES(image_url),
             outlet=VALUES(outlet),
             journalist=VALUES(journalist),
             team=VALUES(team),
             published_at=VALUES(published_at),
             tier=VALUES(tier),
             confidence_score=VALUES(confidence_score),
             fetched_at=VALUES(fetched_at),
             revision=VALUES(revision),
             content_hash=VALUES(content_hash)""")
```

(`transfer_stage`는 `ON DUPLICATE KEY UPDATE`에 일부러 넣지 않는다 — revision 변경 시에도 기존 단계를 보존하기 위함.)

Then add two methods at the end of the `MartStore` class (after `set_translation`):

```python
    def rows_missing_stage(self) -> list[dict]:
        with self.engine.connect() as c:
            rows = c.execute(text(
                "SELECT content_hash,title_original,summary_ko "
                "FROM articles WHERE transfer_stage IS NULL")).mappings().all()
        return [dict(r) for r in rows]

    def set_stage(self, content_hash: str, stage: str) -> None:
        with self.engine.begin() as c:
            c.execute(text("UPDATE articles SET transfer_stage=:s WHERE content_hash=:h"),
                      {"s": stage, "h": content_hash})
```

- [ ] **Step 4: 통과 확인**

docker DB가 떠 있어야 함. 없으면:
Run: `docker compose up -d mariadb`

Run: `uv run pytest tests/integration/test_mariadb_store.py -v`
Expected: PASS (모든 통합 테스트 — 기존 + 신규 2개). 신규 행 INSERT는 `transfer_stage` 적재, revision 변경 케이스는 단계 보존을 확인.

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/storage/mariadb.py tests/integration/test_mariadb_store.py
git commit -F - <<'EOF'
feat(storage): 단계 분류 트리거 · 저장 메서드 추가

분류 전용 패스가 신규 · 기존 행을 한 트리거로 처리하도록 transfer_stage
IS NULL 조회 (rows_missing_stage) 와 set_stage를 추가함. upsert는 INSERT에만
transfer_stage를 실어 신규 행은 NULL로 시작하게 하고, ON DUPLICATE 절에는
넣지 않아 revision 변경 시 기존 단계를 보존.

Refs: docs/superpowers/plans/2026-06-30-tier2b-transfer-stage.md (Task 3)
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

## Task 4: enrich — 단계 배치 분류

**Files:**
- Modify: `src/bullet_in/enrich.py` (`STAGE_PROMPT` · `_extract_stages` · `classify_stage_rows`)
- Test: `tests/test_enrich.py` (append)

**Interfaces:**
- Consumes: `transfer_stage.normalize` (Task 1), 기존 `_is_rate_limit`.
- Produces: `classify_stage_rows(rows: list[dict], client, model: str, batch_size: int = 20) -> dict[str, str]` — `content_hash -> stage(enum)`. 입력 행은 `content_hash` · `title_original` · `summary_ko` (선택) 키를 가짐.

- [ ] **Step 1: 실패 테스트 작성**

Append to `tests/test_enrich.py`:

```python
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


def test_classify_returns_hash_to_stage():
    payload = ('[{"content_hash":"a","stage":"negotiating"},'
               '{"content_hash":"b","stage":"official"}]')
    rows = [{"content_hash": "a", "title_original": "Arsenal in talks", "summary_ko": "협상"},
            {"content_hash": "b", "title_original": "Arsenal confirm", "summary_ko": "발표"}]
    out = classify_stage_rows(rows, _StageClient(payload), "m")
    assert out == {"a": "negotiating", "b": "official"}


def test_classify_demotes_invalid_stage_to_other():
    payload = '[{"content_hash":"a","stage":"bogus"}]'
    out = classify_stage_rows([{"content_hash": "a", "title_original": "T", "summary_ko": ""}],
                              _StageClient(payload), "m")
    assert out == {"a": "other"}


def test_classify_omits_missing_hashes():
    payload = '[{"content_hash":"a","stage":"rumour"}]'   # b 누락
    rows = [{"content_hash": "a", "title_original": "A", "summary_ko": ""},
            {"content_hash": "b", "title_original": "B", "summary_ko": ""}]
    out = classify_stage_rows(rows, _StageClient(payload), "m")
    assert out == {"a": "rumour"}   # b는 NULL 유지 (다음 사이클 재시도)


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
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_enrich.py -k classify -v`
Expected: FAIL — `ImportError: cannot import name 'classify_stage_rows'`

- [ ] **Step 3: 구현**

In `src/bullet_in/enrich.py`, add the import near the top (after the existing imports / `PAYWALLED_OUTLETS`):

```python
from bullet_in import transfer_stage as _stage
```

Add the prompt, parser, and classifier (e.g. after `enrich_rows`):

```python
STAGE_PROMPT = (
    "다음은 아스날 FC 관련 기사 목록이다. 각 기사를 이적 진행 단계로 분류한다.\n"
    "단계 (반드시 아래 영문 값 중 하나로 답한다):\n"
    "- rumour: 근거 약한 소문 · 연결설\n"
    "- interest: 구단이 실제 관심 표명 · 스카우팅\n"
    "- negotiating: 구단 간 · 에이전트와 이적료/조건 협상 중\n"
    "- personal_terms: 선수와 개인 조건 (연봉 등) 합의\n"
    "- medical: 메디컬 테스트 진행 · 통과\n"
    "- official: 구단 공식 발표\n"
    "- other: 이적과 무관하거나 단계를 판단할 수 없음\n"
    "각 기사의 content_hash는 그대로 두고 stage만 채운다.\n"
    'ONLY JSON 배열: [{{"content_hash":"...","stage":"rumour"}}]\n\n'
    "기사 목록:\n{items}")


def _extract_stages(text: str) -> dict[str, str] | None:
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        out: dict[str, str] = {}
        for item in data:
            h, s = item.get("content_hash"), item.get("stage")
            if h and s:
                out[h] = s
        return out
    except (json.JSONDecodeError, TypeError, AttributeError):
        return None


def classify_stage_rows(rows: list[dict], client, model: str,
                        batch_size: int = 20) -> dict[str, str]:
    """미태깅 행을 batch_size 단위로 묶어 영입 단계를 분류한다.

    content_hash -> stage(enum) 를 반환한다. 허용 enum 밖 값은 other로 강등하고,
    응답에 없는 hash는 결과에서 빠져 (NULL 유지) 다음 사이클에 재시도된다.
    429를 만나면 그 회차는 즉시 중단한다 (남은 배치 다음 사이클 누적)."""
    result: dict[str, str] = {}
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        items = json.dumps(
            [{"content_hash": r["content_hash"],
              "title": r["title_original"],
              "summary": r.get("summary_ko") or ""} for r in batch],
            ensure_ascii=False)
        try:
            msg = client.models.generate_content(
                model=model,
                contents=STAGE_PROMPT.format(items=items),
                config={"max_output_tokens": 2048,
                        "response_mime_type": "application/json"})
        except Exception as e:
            if _is_rate_limit(e):
                log.warning("Gemini rate limit(429), 단계 분류 중단 — 남은 배치 다음 사이클")
                break
            log.warning("Gemini 호출 실패, 단계 분류 배치 스킵: %s", e)
            continue
        parsed = _extract_stages(msg.text)
        if parsed is None:
            log.warning("Gemini 응답 파싱 실패, 단계 분류 배치 스킵")
            continue
        for h, stage in parsed.items():
            result[h] = _stage.normalize(stage)
    return result
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_enrich.py -k classify -v`
Expected: PASS (6 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/enrich.py tests/test_enrich.py
git commit -F - <<'EOF'
feat(enrich): 영입 단계 배치 분류 패스 추가

번역과 분리된 분류 전용 패스를 도입함. 제목 (+1줄 요약) 여러 건을 한
요청에 묶어 분류해 203건 backfill을 적은 콜로 끝내 RPM 부담을 줄임.
허용 enum 밖은 other로 강등, 응답 누락 hash는 NULL 유지로 재시도,
429는 기존 회차 중단 · 누적 패턴 재사용.

Refs: docs/superpowers/plans/2026-06-30-tier2b-transfer-stage.md (Task 4)
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

## Task 5: render.py — 단계 라벨 · 패싯 · 템플릿 globals

**Files:**
- Modify: `src/bullet_in/serve/render.py` (`_env` · `_decorate` · `facet_counts` · `render_article`)
- Test: `tests/test_serve_layout.py` · `tests/test_serve_render.py` (append)

**Interfaces:**
- Consumes: `transfer_stage` 모듈 (Task 1), 행의 `transfer_stage` 키 (Task 2/3).
- Produces:
  - `_decorate` 결과에 `_stage` (data-stage 값, other/None은 `""` 또는 enum) · `_stage_badge` (bool) · `_stage_label` · `_stage_class`.
  - `facet_counts` 반환 dict에 `"stage"` 키 (6개 enum별 카운트, other · None 제외).
  - Jinja env `globals["stages"]` = `SIDEBAR_STAGES` — 템플릿이 사이드바 단계 목록을 받음.

- [ ] **Step 1: 실패 테스트 작성**

Append to `tests/test_serve_layout.py`:

```python
def test_facet_counts_includes_stage_excluding_other():
    arts = [
        {"source_id": "s", "outlet": "BBC", "tier": 1, "team": "arsenal", "transfer_stage": "rumour"},
        {"source_id": "s", "outlet": "BBC", "tier": 1, "team": "arsenal", "transfer_stage": "rumour"},
        {"source_id": "s", "outlet": "BBC", "tier": 1, "team": "arsenal", "transfer_stage": "official"},
        {"source_id": "s", "outlet": "BBC", "tier": 1, "team": "arsenal", "transfer_stage": "other"},
        {"source_id": "s", "outlet": "BBC", "tier": 1, "team": "arsenal"},   # 미태깅(None)
    ]
    f = facet_counts(arts, {})
    assert f["stage"]["rumour"] == 2
    assert f["stage"]["official"] == 1
    assert "other" not in f["stage"]      # other는 집계 제외
    assert set(f["stage"]) == {"official", "medical", "personal_terms",
                               "negotiating", "interest", "rumour"}
```

Append to `tests/test_serve_render.py` (after the existing `_decorated` helper):

```python
def test_decorate_sets_stage_fields():
    from bullet_in.serve.render import _decorate
    d = _decorate(_row(transfer_stage="medical"), SOURCES, NOW)
    assert d["_stage"] == "medical"
    assert d["_stage_badge"] is True
    assert d["_stage_label"] == "메디컬"
    assert d["_stage_class"] == "s-med"


def test_decorate_other_stage_no_badge():
    from bullet_in.serve.render import _decorate
    d = _decorate(_row(transfer_stage="other"), SOURCES, NOW)
    assert d["_stage"] == "other"
    assert d["_stage_badge"] is False
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_serve_layout.py -k stage tests/test_serve_render.py -k "decorate" -v`
Expected: FAIL — `KeyError: 'stage'` (facet_counts) · `KeyError: '_stage'` (decorate)

- [ ] **Step 3: 구현**

In `src/bullet_in/serve/render.py`, add the import after the existing imports (line 7 area):

```python
from bullet_in import transfer_stage as _stage
```

Replace `_env()` (lines 71-75) with:

```python
def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(_TPL_DIR),
        autoescape=select_autoescape(default_for_string=True, default=True),
    )
    env.globals["stages"] = _stage.SIDEBAR_STAGES
    return env
```

In `_decorate`, before `return a` (line 91), add:

```python
    st = row.get("transfer_stage")
    a["_stage"] = st or ""
    a["_stage_badge"] = _stage.is_displayable(st)
    a["_stage_label"] = _stage.label_for(st)
    a["_stage_class"] = _stage.css_for(st)
```

In `facet_counts`, change the return (lines 68-69) to compute and include stage:

```python
    stage_counts = {e: 0 for e, _, _ in _stage.SIDEBAR_STAGES}
    for a in articles:
        s = a.get("transfer_stage")
        if s in stage_counts:
            stage_counts[s] += 1
    return {"total": len(articles), "team": dict(teams),
            "outlets": outlets, "tiers": tiers, "stage": stage_counts}
```

In `render_article`, update the `facets is None` fallback (line 122) to include `stage`:

```python
        facets = {"team": {}, "outlets": [], "tiers": {t: 0 for t in range(5)},
                  "total": 0, "stage": {}}
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_serve_layout.py tests/test_serve_render.py -v`
Expected: 신규 테스트 PASS. **주의**: `test_index_renders_facet_counts_and_disabled_stage`는 아직 옛 단언 (disabled 단계 자리) 이라 **이 시점엔 통과** (템플릿은 Task 6에서 바뀜). 만약 이미 실패하면 Task 6의 갱신을 당겨 적용.

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/serve/render.py tests/test_serve_layout.py tests/test_serve_render.py
git commit -F - <<'EOF'
feat(serve): render에 영입 단계 라벨 · 패싯 반영

카드 · 상세 배지와 사이드바 카운트의 데이터 토대를 마련함. _decorate가
단계 enum을 라벨 · css · 배지 노출 여부로 풀고, facet_counts가 6개 단계
카운트를 (other 제외) 집계하며, 템플릿이 사이드바 단계 목록을 받도록
Jinja globals에 SIDEBAR_STAGES를 주입.

Refs: docs/superpowers/plans/2026-06-30-tier2b-transfer-stage.md (Task 5)
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

## Task 6: 서빙 UI — 사이드바 필터 · 배지 · 정적 자산

**Files:**
- Modify: `src/bullet_in/serve/templates/_layout.html.j2` (사이드바 팀 · 단계)
- Modify: `src/bullet_in/serve/templates/index.html.j2` (data-stage · 배지)
- Modify: `src/bullet_in/serve/templates/detail.html.j2` (배지)
- Modify: `src/bullet_in/serve/static/style.css` (점 색 2개 · 배지)
- Modify: `src/bullet_in/serve/static/app.js` (okStage)
- Test: `tests/test_serve_render.py` (갱신 1 + 추가) · `tests/test_serve_layout.py`는 변화 없음

**Interfaces:**
- Consumes: `_decorate`의 `_stage*` 필드 · `facets.stage` · Jinja `stages` global (Task 5).
- Produces: 사이드바 단계 체크박스 (`data-group="stage" data-value="<enum>"`), 카드 `data-stage` 속성 + 배지, 상세 배지, `app.js` 단계 필터.

- [ ] **Step 1: 실패 테스트 작성 / 갱신**

In `tests/test_serve_render.py`, **replace** `test_index_renders_facet_counts_and_disabled_stage` (lines 54-58) with:

```python
def test_index_renders_active_stage_filter():
    html = render_index([_row(), _row(content_hash="h2")], SOURCES, NOW)
    assert "tier 2" in html
    # 영입 단계 필터가 활성 (2-b): 체크박스 + data-group="stage"
    assert "영입 단계" in html
    assert 'data-group="stage"' in html
    assert 'data-value="official"' in html and 'data-value="rumour"' in html
    # 타 구단 자리 제거 + 단계 비활성 자리 제거 → disabled 없음
    assert "Manchester United" not in html
    assert "disabled" not in html
```

Append to `tests/test_serve_render.py`:

```python
def test_index_shows_stage_badge_and_data_attr():
    html = render_index([_row(transfer_stage="negotiating")], SOURCES, NOW)
    assert 'data-stage="negotiating"' in html
    assert "협상 중" in html
    assert "stagebadge" in html


def test_index_other_stage_has_data_attr_but_no_badge():
    html = render_index([_row(transfer_stage="other")], SOURCES, NOW)
    assert 'data-stage="other"' in html   # 속성은 있음 (필터로 제외됨)
    assert "stagebadge" not in html        # 배지는 없음


def test_detail_shows_stage_badge():
    a = _row(content_hash="cur", transfer_stage="medical")
    nb = build_neighbors([a], 0, SOURCES, NOW)
    html = render_article(_decorated(a), nb, "cur", SOURCES, NOW)
    assert "메디컬" in html and "stagebadge" in html
```

Update `test_static_assets_exist_and_nonempty` (lines 5-11) to also assert the new contracts — change its body to:

```python
def test_static_assets_exist_and_nonempty():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "data-theme" in css and "--bg" in css      # 테마 변수
    assert ".card" in css and ".side" in css
    assert "s-interest" in css and "s-personal" in css  # 신규 단계 점 색
    assert "data-outlet" in js and "data-tier" in js   # 카드 필터 계약
    assert "data-stage" in js                          # 단계 필터 계약
    assert "localStorage" in js                        # 테마 영속
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_serve_render.py -v`
Expected: FAIL — `test_index_renders_active_stage_filter` (still has disabled), `test_index_shows_stage_badge...`, `test_detail_shows_stage_badge`, `test_static_assets...` (no s-interest / data-stage yet)

- [ ] **Step 3: 템플릿 · 정적 자산 구현**

In `src/bullet_in/serve/templates/_layout.html.j2`, **replace** the team block (lines 30-35) with (Arsenal만 남김):

```html
    <h4>팀</h4>
    <label class="opt"><input type="checkbox" data-group="team" data-value="arsenal" checked> Arsenal <span class="ct">{{ facets.team.get('arsenal', 0) }}</span></label>
```

And **replace** the 영입 단계 block (lines 37-41) with the active loop:

```html
    <h4>영입 단계</h4>
    {% for enum, label, css in stages %}
    <label class="opt"><input type="checkbox" data-group="stage" data-value="{{ enum }}"><span class="stage {{ css }}"></span>{{ label }} <span class="ct">{{ facets.stage.get(enum, 0) }}</span></label>
    {% endfor %}
```

In `src/bullet_in/serve/templates/index.html.j2`, add the `data-stage` attribute to the card `<a>` (after the `data-confidence` line, line 11):

```html
     data-stage="{{ a._stage }}"
```

And add the badge inside `.chips` (after the team chip, line 20):

```html
        {% if a._stage_badge %}<span class="chip stagebadge"><span class="stage {{ a._stage_class }}"></span>{{ a._stage_label }}</span>{% endif %}
```

In `src/bullet_in/serve/templates/detail.html.j2`, add the badge inside `.chips` (after the team chip, line 13):

```html
      {% if a._stage_badge %}<span class="chip stagebadge"><span class="stage {{ a._stage_class }}"></span>{{ a._stage_label }}</span>{% endif %}
```

In `src/bullet_in/serve/static/style.css`, after the existing stage-dot line (line 49, `.s-off{...}.s-rum{...}`), add:

```css
.s-personal{background:#8b5cf6}.s-interest{background:#14b8a6}
.chip.stagebadge{display:inline-flex;align-items:center;gap:5px;background:var(--chip);color:var(--navy)}
html[data-theme="dark"] .chip.stagebadge{color:#cdd6e4}
```

In `src/bullet_in/serve/static/app.js`, update the DOM contract comment (line 1):

```javascript
// DOM contract: a.card[data-outlet][data-tier][data-stage][data-published][data-confidence][data-text]
```

In `applyFilters()`, add the stage group read (after the `tiers` line, line 29):

```javascript
  const stages = checkedValues('stage');
```

Add `okStage` and include it in `visible` (replace lines 33-35):

```javascript
    const okOutlet = outlets.length === 0 || outlets.includes(card.dataset.outlet);
    const okTier = tiers.length === 0 || tiers.includes(card.dataset.tier);
    const okStage = stages.length === 0 || stages.includes(card.dataset.stage);
    const visible = okText && okOutlet && okTier && okStage;
```

And include `stages.length` in the `conds` sum (line 41):

```javascript
  const conds = outlets.length + tiers.length + stages.length + (q ? 1 : 0);
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_serve_render.py tests/test_serve_layout.py -v`
Expected: PASS (전부)

전체 스위트도 회귀 확인:
Run: `uv run pytest -q`
Expected: PASS (통합은 DB 있으면 실행, 없으면 skip)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/serve/templates/_layout.html.j2 src/bullet_in/serve/templates/index.html.j2 src/bullet_in/serve/templates/detail.html.j2 src/bullet_in/serve/static/style.css src/bullet_in/serve/static/app.js tests/test_serve_render.py
git commit -F - <<'EOF'
feat(serve): 영입 단계 사이드바 필터 · 배지 활성화

비활성 자리였던 영입 단계 그룹을 6개 단계 체크박스로 활성화하고,
app.js에 단계 필터 (그룹 내 OR · 그룹 간 AND) 를 추가함. 카드 · 상세에
색상 점 + 라벨 배지를 달아 필터 없이도 단계를 읽게 함. 타 구단 실데이터
수집 전까지 사이드바 팀 필터의 "예정" 자리는 제거 (Arsenal만 노출).

Refs: docs/superpowers/plans/2026-06-30-tier2b-transfer-stage.md (Task 6)
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

## Task 7: run.py — 분류 패스 연결 · SELECT 반영

**Files:**
- Modify: `src/bullet_in/run.py` (분류 패스 호출 · write_site SELECT에 `transfer_stage`)

**Interfaces:**
- Consumes: `classify_stage_rows` (Task 4), `MartStore.rows_missing_stage` · `set_stage` (Task 3).
- Produces: 파이프라인 1회 실행마다 미태깅 행이 분류 · 저장되고, 서빙 입력 행에 `transfer_stage`가 포함됨.

- [ ] **Step 1: 분류 패스 연결**

In `src/bullet_in/run.py`, update the enrich import (line 15):

```python
from bullet_in.enrich import enrich_rows, classify_stage_rows
```

After the translation save loop (after line 53, the `mart.set_translation(...)` loop), add the classification pass:

```python
    stage_rows = mart.rows_missing_stage()
    for h, stage in classify_stage_rows(stage_rows, client, GEMINI_MODEL).items():
        mart.set_stage(h, stage)
```

- [ ] **Step 2: 서빙 SELECT에 컬럼 추가**

In `src/bullet_in/run.py`, update the `write_site` SELECT (lines 56-60) to include `transfer_stage`:

```python
        rows = [dict(r) for r in c.execute(text(
            "SELECT content_hash,url,source_id,title_original,title_ko,summary_ko,"
            "summary3_ko,body_ko,image_url,outlet,journalist,team,transfer_stage,tier,"
            "confidence_score,published_at "
            "FROM articles")).mappings().all()]
```

- [ ] **Step 3: import 스모크 + 전체 스위트**

Run: `uv run python -c "import bullet_in.run"`
Expected: 출력 없음 (import 성공 — 구문/심볼 오류 없음)

Run: `uv run pytest -q`
Expected: PASS (전체)

- [ ] **Step 4: 라이브 멱등 검증 (DB 필요)**

docker DB · `.env` 자격증명이 있는 환경에서:

```bash
set -a; source .env; set +a
uv run python -m bullet_in.run --concurrency 8
```

검증 쿼리 (분류가 채워지는지 · other 분포):

```bash
set -a; source .env; set +a
uv run python - <<'PY'
from sqlalchemy import create_engine, text
import os
e = create_engine(os.environ["MARIADB_URL"])
with e.connect() as c:
    total = c.execute(text("SELECT COUNT(*) FROM articles")).scalar()
    tagged = c.execute(text("SELECT COUNT(*) FROM articles WHERE transfer_stage IS NOT NULL")).scalar()
    print(f"total={total} tagged={tagged}")
    for r in c.execute(text("SELECT transfer_stage, COUNT(*) FROM articles "
                            "GROUP BY transfer_stage ORDER BY 2 DESC")).all():
        print(" ", r[0], r[1])
PY
```

Expected: `tagged`가 1회 실행마다 증가 (429로 한 번에 다 안 될 수 있음 — 다음 사이클 누적). `site/index.html` 사이드바 단계 카운트 · 카드 배지가 보임. (429만 발생하고 0건 태깅이면 다음 사이클 재실행 — 멱등.)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/run.py
git commit -F - <<'EOF'
feat(pipeline): 단계 분류 패스를 run에 연결

번역 패스 뒤에 미태깅 행 분류 · 저장을 추가하고, 서빙 입력 SELECT에
transfer_stage를 실어 카드 · 상세 배지와 사이드바 카운트가 채워지게 함.
분류는 번역과 독립 트리거라 기존 203건도 다음 실행부터 누적 태깅됨.

Refs: docs/superpowers/plans/2026-06-30-tier2b-transfer-stage.md (Task 7)
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

## 완료 기준 (전체)

- `uv run pytest -q` 전부 통과 (통합은 DB 있을 때).
- 라이브 실행 후 `articles.transfer_stage`가 채워지고 (429 시 누적), `other` 분포가 합리적.
- `site/index.html` 사이드바 단계 6개 체크박스가 활성 · 카운트 표시, 단계 체크 시 카드 필터링, 타 구단 자리 없음.
- 카드 · 상세에 단계 배지 (색상 점 + 라벨) 표시, `other`는 배지 없음.

## 참조
- spec: `docs/superpowers/specs/2026-06-30-tier2b-transfer-stage-design.md`
- 상위 spec: `docs/superpowers/specs/2026-06-29-tier2a-detail-page-design.md` (§2-b)
- 후속 트랙: 메모리 `tier1-cleanup-track` (이적 키워드 필터 · 데이터 정리)
