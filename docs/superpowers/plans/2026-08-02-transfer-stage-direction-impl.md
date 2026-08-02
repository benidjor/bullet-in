# 영입 단계 재분류 · 이적 방향 축 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 스펙 `docs/superpowers/specs/2026-08-02-transfer-stage-direction-design.md` 구현 — `transfer_direction` 축 신설 · 규칙 경로 2형태 (가십 완전 고정 · 공홈 stage 만 고정) · 소급 재분류 배치 · render 가십 하드코딩 제거.

**Architecture:** 분류 패스 확장이 중심이다.
`rule_stage()` 가 (stage, direction) 쌍을 반환하고, LLM 분류 (`classify_stage_rows`) 가 한 호출로 두 값을 함께 판정한다.
서빙 표시는 무변경이며, render 의 가십 하드코딩 제거는 소급 배치 수렴 뒤 별도 PR 로만 한다.

**Tech Stack:** Python 3.11 · SQLAlchemy (MariaDB) · google-genai (Gemini) · pytest.

## Global Constraints

- **PR 2개 + 운영 게이트 1개**: PR-1 (Task 1~6 · 코드 + 런북) → 운영 게이트 (Task 7 · VM 소급 배치 수렴) → PR-2 (Task 8 · render 정리).
  순서 역전 금지 — render 하드코딩 제거는 배치 수렴 전에 머지되면 가십 화면이 흔들린다 (스펙 §5).
- **서빙 표시 무변경**: 배지 · 사이드바 · 라벨에 방향을 노출하지 않는다 (스펙 §2 · §5).
- **PR 머지는 사용자 직접** — 세션은 push + PR 생성까지.
- **VM 은 쓰기 접근 전 고지** — 병렬 워치리스트 세션이 관찰 (읽기 전용) 중이다 (스펙 §10).
- **Gemini 는 과금 대상 (Tier 1 선불)** — 소급 배치는 약 21회 호출 1회성으로 설계됐고, 이를 늘리는 변경은 금지 (스펙 §6.1).
- **문서는 한국어 · 컨벤션 §2.2 서식** (`docs/` 저장 시 훅이 자동 검사) · 커밋은 `<type>(<scope>): 한국어 제목` + 본문 + `Co-authored-by: Claude Fable 5 <noreply@anthropic.com>` (구현을 subagent 에 위임하면 역할 라벨 2줄 병기 · §1.3).
- 브랜치: PR-1 = `feat/transfer-direction` · PR-2 = `fix/render-gossip-rollup-removal`.

---

### Task 1: transfer_stage.py — 방향 정규화 · rule_stage (stage, direction) 확장

**Files:**
- Modify: `src/bullet_in/transfer_stage.py:45-48`
- Test: `tests/test_transfer_stage.py`

**Interfaces:**
- Produces: `DIRECTIONS: set[str]` = {"in", "out", "none"} · `normalize_direction(value: str | None) -> str` (밖 값 · None → "none") · `rule_stage(source_id: str | None) -> tuple[str | None, str | None]` — arsenal_official → ("official", None) · bbc_gossip → ("rumour", "none") · 그 외 → (None, None).
- Consumes: 없음 (기존 모듈 확장).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_transfer_stage.py` 의 기존 `test_rule_stage_official_only_for_arsenal_official` 를 아래로 교체하고, 방향 정규화 테스트를 추가한다.

```python
def test_rule_stage_returns_stage_direction_pairs():
    # 규칙 경로 2형태 (스펙 2026-08-02 §4.1) — 공홈은 stage 만 고정 (방향은 LLM 몫),
    # 가십은 둘 다 고정 (다주제 라운드업은 대표 단계 · 방향이 성립하지 않음)
    assert ts.rule_stage("arsenal_official") == ("official", None)
    assert ts.rule_stage("bbc_gossip") == ("rumour", "none")
    assert ts.rule_stage("bbc_sport") == (None, None)
    assert ts.rule_stage(None) == (None, None)


def test_normalize_direction_keeps_valid_else_none():
    assert ts.normalize_direction("in") == "in"
    assert ts.normalize_direction("out") == "out"
    assert ts.normalize_direction("none") == "none"
    assert ts.normalize_direction("bogus") == "none"
    assert ts.normalize_direction(None) == "none"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_transfer_stage.py -q`
Expected: FAIL — `rule_stage` 가 문자열을 반환 (튜플 아님) · `normalize_direction` 미정의.

- [ ] **Step 3: 최소 구현**

`src/bullet_in/transfer_stage.py` 의 `rule_stage` 를 교체하고 방향 상수 · 정규화를 추가한다 (`OTHER = "other"` 아래에 배치).

```python
DIRECTIONS = {"in", "out", "none"}


def normalize_direction(value: str | None) -> str:
    """LLM이 돌려준 방향이 허용 값이면 그대로, 아니면 none으로 강등."""
    return value if value in DIRECTIONS else "none"
```

```python
def rule_stage(source_id: str | None) -> tuple[str | None, str | None]:
    """소스 조건 규칙 (stage, direction) — 방향 축 스펙 §4.1.
    공홈은 stage 만 고정 (방향은 LLM 몫) · 가십은 둘 다 고정 (LLM 완전 제외).
    official 은 이 규칙 경로에서만 생성된다 (LLM enum 에서 제외 · 반환 시 강등)."""
    if source_id == "arsenal_official":
        return "official", None
    if source_id == "bbc_gossip":
        return "rumour", "none"
    return None, None
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_transfer_stage.py -q`
Expected: PASS (전건).

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/transfer_stage.py tests/test_transfer_stage.py
git commit -m "feat(enrich): rule_stage 를 (단계, 방향) 쌍 반환으로 확장"
```

---

### Task 2: enrich.py — 분류 프롬프트 · 파서에 방향 축 추가

**Files:**
- Modify: `src/bullet_in/enrich.py:720-793` (`STAGE_PROMPT` · `_extract_stages` · `classify_stage_rows`)
- Test: `tests/test_enrich.py:186-280` (기존 stage 테스트 갱신 + 신규)

**Interfaces:**
- Consumes: Task 1 의 `transfer_stage.normalize_direction(value) -> str`.
- Produces: `classify_stage_rows(rows, client, model, batch_size=20) -> dict[str, tuple[str, str]]` — content_hash → (stage, direction). 기존 호출부 (run.py) 는 Task 4 에서 맞춘다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_enrich.py` 의 기존 stage 테스트 7건을 튜플 반환에 맞게 교체 · 추가한다.
`_StageClient` · `_StageModels` 헬퍼는 그대로 재사용한다.

```python
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


def test_classify_demotes_official_to_agreed():
    """프롬프트에 없어도 모델이 official을 뱉으면 agreed로 강등 (spec §4.3 불변량)."""
    payload = '[{"content_hash":"h1","stage":"official","direction":"in"}]'
    rows = [{"content_hash": "h1", "title_original": "t", "summary_ko": "s"}]
    out = classify_stage_rows(rows, _StageClient(payload), "m")
    assert out == {"h1": ("agreed", "in")}


def test_classify_omits_missing_hashes():
    payload = '[{"content_hash":"a","stage":"rumour","direction":"none"}]'   # b 누락
    rows = [{"content_hash": "a", "title_original": "A", "summary_ko": ""},
            {"content_hash": "b", "title_original": "B", "summary_ko": ""}]
    out = classify_stage_rows(rows, _StageClient(payload), "m")
    assert out == {"a": ("rumour", "none")}   # b는 NULL 유지 (다음 사이클 재시도)


def test_stage_prompt_lists_directions_and_tie_rule():
    """프롬프트가 방향 3값 정의 · 임대 포괄 · 대등 혼합 out 우선을 담는다 (방향 축 스펙 §4.2)."""
    from bullet_in.enrich import STAGE_PROMPT
    for d in ("- in:", "- out:", "- none:"):
        assert d in STAGE_PROMPT, f"STAGE_PROMPT 가 방향 {d} 정의를 누락"
    assert "임대" in STAGE_PROMPT
    assert "대등" in STAGE_PROMPT
```

기존 `test_classify_returns_hash_to_stage` 는 `test_classify_returns_stage_and_direction` 으로 교체한다.
`test_classify_skips_unparseable_batch` · `test_classify_batches_by_size` · `test_classify_stops_on_rate_limit` 은 반환값 단언이 없거나 `{}` 라 무수정으로 통과해야 한다.

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_enrich.py -q -k "classify or stage_prompt"`
Expected: FAIL — 반환이 str 단일 값 · 프롬프트에 방향 정의 없음.

- [ ] **Step 3: 구현**

`STAGE_PROMPT` 의 `- other:` 줄과 "합의 보도는 당사자로 가른다" 줄 사이에 방향 블록을 삽입하고, JSON 예시 줄을 교체한다.

```python
    "- other: 이적과 무관하거나 단계를 판단할 수 없음\n"
    "방향 (direction — 반드시 아래 영문 값 중 하나로 답한다):\n"
    "- in: 아스날로 오는 이적 (임대 영입 포함)\n"
    "- out: 아스날에서 나가는 이적 (방출 · 매각 · 임대 방출 포함)\n"
    "- none: 이적 무관 기사 · 방향을 판단할 수 없음\n"
    "방향은 제목이 내세우는 주된 이적 하나로 정한다 — 요약 말미의 부수 언급"
    " (예: 영입 기사 끝의 '방출 작업도 진행 중' 한 줄) 은 무시한다.\n"
    "제목이 영입과 방출을 병기하는 대등 혼합이면 out 으로 답한다.\n"
    "합의 보도는 당사자로 가른다 — 구단과 구단이면 agreed, 선수와 구단이면 personal_terms.\n"
    "이적 주체가 아스날이 아니어도 (타 구단 간 이적을 다룬 기사) 그 이적의 단계로 분류한다.\n"
    "각 기사의 content_hash는 그대로 두고 stage와 direction만 채운다.\n"
    'ONLY JSON 배열: [{{"content_hash":"...","stage":"rumour","direction":"in"}}]\n\n'
```

`_extract_stages` 는 direction 을 함께 뽑는다 (원시값 그대로 — 정규화는 `classify_stage_rows` 몫).

```python
def _extract_stages(text: str) -> dict[str, tuple[str, str | None]] | None:
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        out: dict[str, tuple[str, str | None]] = {}
        for item in data:
            h, s = item.get("content_hash"), item.get("stage")
            if h and s:
                out[h] = (s, item.get("direction"))
        return out
    except (json.JSONDecodeError, TypeError, AttributeError):
        return None
```

`classify_stage_rows` 의 반환 타입 힌트 · docstring · 마지막 정규화 루프를 교체한다.

```python
def classify_stage_rows(rows: list[dict], client, model: str,
                        batch_size: int = 20) -> dict[str, tuple[str, str]]:
    """미태깅 행을 batch_size 단위로 묶어 이적 단계 · 방향을 분류한다.

    content_hash -> (stage, direction) 을 반환한다. 허용 enum 밖 stage는 other,
    direction은 none으로 강등하고, 응답에 없는 hash는 결과에서 빠져 (NULL 유지)
    다음 사이클에 재시도된다. 429를 만나면 그 회차는 즉시 중단한다."""
    result: dict[str, tuple[str, str]] = {}
```

```python
        for h, (stage, direction) in parsed.items():
            stage = _stage.normalize(stage)
            if stage == "official":
                # 규칙 경로 전용 불변량 (spec §4.3) — 프롬프트 밖 응답 방어
                log.warning("LLM이 official 반환 — agreed로 강등 content_hash=%s", h)
                stage = "agreed"
            result[h] = (stage, _stage.normalize_direction(direction))
    return result
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_enrich.py -q`
Expected: PASS (stage 테스트 전건 + 기존 번역 테스트 무영향).

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/enrich.py tests/test_enrich.py
git commit -m "feat(enrich): 분류 프롬프트 · 파서에 이적 방향 축 추가"
```

---

### Task 3: storage — transfer_direction 컬럼 · set_stage 확장

**Files:**
- Modify: `src/bullet_in/storage/schema.sql:26` 아래 · `src/bullet_in/storage/mariadb.py:111-114`
- Test: `tests/integration/test_mariadb_store.py:78-93` (DB 없으면 자동 skip)

**Interfaces:**
- Produces: `MartStore.set_stage(content_hash: str, stage: str, direction: str | None = None) -> None` — 두 컬럼 동시 기록. `articles.transfer_direction VARCHAR(8)` 컬럼.
- Consumes: 없음.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/integration/test_mariadb_store.py` 의 `test_rows_missing_stage_and_set_stage` 에서 `set_stage` 호출과 단언을 확장한다 (기존 스타일 유지).

```python
    store.set_stage("hs", "negotiating", "in")
    assert "hs" not in {r["content_hash"] for r in store.rows_missing_stage()}
    with engine.connect() as c:
        row = c.execute(text(
            "SELECT transfer_stage, transfer_direction FROM articles "
            "WHERE content_hash='hs'")).one()
    assert tuple(row) == ("negotiating", "in")
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/integration/test_mariadb_store.py -q` (docker compose 의 mariadb 필요 · 없으면 skip 확인만)
Expected: FAIL — `set_stage` 가 인자 2개만 받음.

- [ ] **Step 3: 구현**

`schema.sql` 의 `ALTER TABLE articles ADD COLUMN IF NOT EXISTS transfer_stage VARCHAR(32);` 줄 아래에 추가:

```sql
ALTER TABLE articles ADD COLUMN IF NOT EXISTS transfer_direction VARCHAR(8);
```

`mariadb.py` 의 `set_stage` 교체:

```python
    def set_stage(self, content_hash: str, stage: str,
                  direction: str | None = None) -> None:
        with self.engine.begin() as c:
            c.execute(text("UPDATE articles SET transfer_stage=:s, "
                           "transfer_direction=:d WHERE content_hash=:h"),
                      {"s": stage, "d": direction, "h": content_hash})
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/integration/test_mariadb_store.py -q`
Expected: PASS (DB 있을 때) 또는 skip (없을 때 — 이 경우 Task 4 의 전체 스위트에서 회귀만 확인).

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/storage/schema.sql src/bullet_in/storage/mariadb.py tests/integration/test_mariadb_store.py
git commit -m "feat(storage): articles 에 transfer_direction 컬럼 · set_stage 확장"
```

---

### Task 4: run.py 분류 패스 배선 · backfill_arsenal 호출부 정합

**Files:**
- Modify: `src/bullet_in/run.py:148-157` · `src/bullet_in/backfill_arsenal.py:76-79`
- Test: 전체 스위트 (이 배선의 단위 테스트는 없음 — 구성 요소는 Task 1~3 이 검증)

**Interfaces:**
- Consumes: Task 1 `rule_stage() -> tuple` · Task 2 `classify_stage_rows() -> dict[str, tuple[str, str]]` · Task 3 `set_stage(h, stage, direction)`.
- Produces: 없음 (최종 배선).

- [ ] **Step 1: run.py 분류 패스 교체**

`run.py:148-157` 을 아래로 교체한다.

```python
    # 분류 패스 (방향 축 스펙 §4): 규칙 경로 2형태 — 가십은 stage · direction 둘 다
    # 고정 (LLM 제외), 공홈은 stage 만 고정하고 방향은 LLM 배치에서 받는다 (stage 응답은 버림)
    llm_rows = []
    stage_ruled: dict[str, str] = {}
    for r in mart.rows_missing_stage():
        stage_fixed, direction_fixed = transfer_stage.rule_stage(r["source_id"])
        if stage_fixed and direction_fixed:
            mart.set_stage(r["content_hash"], stage_fixed, direction_fixed)
            continue
        if stage_fixed:
            stage_ruled[r["content_hash"]] = stage_fixed
        llm_rows.append(r)
    for h, (stage, direction) in classify_stage_rows(llm_rows, client, GEMINI_MODEL).items():
        mart.set_stage(h, stage_ruled.get(h, stage), direction)
```

- [ ] **Step 2: backfill_arsenal.py 호출부 언팩**

`backfill_arsenal.py:76` 을 교체한다 (1회성 복구 도구 — 방향은 소급 배치가 어차피 전건 재부여하므로 stage 만 유지).

```python
    ruled, _ = transfer_stage.rule_stage("arsenal_official")
```

- [ ] **Step 3: 전체 스위트 통과 확인**

Run: `uv run pytest -q`
Expected: PASS (통합은 DB · Airflow 없으면 skip).

- [ ] **Step 4: 커밋**

```bash
git add src/bullet_in/run.py src/bullet_in/backfill_arsenal.py
git commit -m "feat(run): 분류 패스에 방향 축 배선 — 규칙 경로 2형태 적용"
```

---

### Task 5: 런북 갱신 — 소급 재분류 절차에 방향 축 반영

**Files:**
- Modify: `docs/runbook/2026-06-30-transfer-stage-classification-ops.md` 3절

**Interfaces:**
- Consumes: 없음 (문서).
- Produces: Task 7 (운영 게이트) 이 그대로 따라 할 실행 절차.

- [ ] **Step 1: 3절에 방향 축 내용 추가**

기존 3절 (NULL 복원 → 2절 재실행) 뒤에 아래 내용을 §2.2 서식으로 추가한다 (한 줄 = 한 문장 · `·` 양옆 띄우기).

추가할 내용 (문구는 서식에 맞게 다듬되 아래 사실을 전부 담는다):

- 2026-08-02 방향 축 스펙 이후 재분류는 `transfer_direction` (in · out · none) 도 함께 부여한다.
- 사전 덤프에 `transfer_direction` 을 포함한다 (첫 소급은 전건 NULL 이라 실질 대상은 `transfer_stage` 뿐).

```bash
uv run python - <<'PY'
import csv, os, sys
from sqlalchemy import create_engine, text
e = create_engine(os.environ["MARIADB_URL"])
with e.connect() as c, open("stage_dump.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["content_hash", "transfer_stage", "transfer_direction"])
    for row in c.execute(text(
            "SELECT content_hash, transfer_stage, transfer_direction FROM articles")):
        w.writerow(row)
print("덤프 완료: stage_dump.csv")
PY
```

- 규칙 경로가 2형태가 됐다: bbc_gossip 은 rumour + none 으로 LLM 없이 고정되고, arsenal_official 은 official 고정 + 방향만 LLM 판정이라 배치에 포함된다.
- 수렴 확인 쿼리 3종:

```sql
SELECT COUNT(*) FROM articles WHERE transfer_stage IS NULL;      -- 0 이어야 수렴
SELECT COUNT(*) FROM articles WHERE transfer_direction IS NULL;  -- 0 이어야 수렴
SELECT transfer_stage, COUNT(*) FROM articles
 WHERE source_id = 'bbc_gossip' GROUP BY transfer_stage;         -- rumour 단일이어야 정상
```

- 스팟 체크: 감사 문서 §3.5 의 방출 어휘 기사 3건 (096b26b9 · cb0894b7 · b38deb05 로 시작하는 content_hash) 의 `transfer_direction` 이 out 인지 확인한다.

- [ ] **Step 2: 서식 훅 통과 확인**

저장 시 `.claude/hooks/check-doc-format.py` 가 자동 검사한다.
위반 출력이 없어야 한다.

- [ ] **Step 3: 커밋**

```bash
git add docs/runbook/2026-06-30-transfer-stage-classification-ops.md
git commit -m "docs(runbook): 단계 재분류 절차에 방향 축 · 수렴 확인 쿼리 추가"
```

---

### Task 6: PR-1 생성

**Files:**
- 없음 (절차).

- [ ] **Step 1: 최종 검증**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 2: push + PR 생성**

PR 본문은 7섹션 템플릿 (`.github/pull_request_template.md` 주석 세칙 포함) 으로 작성하고, humanize-korean fast 문체 점검 1회를 통과시킨 뒤 `--body-file` 로 전달한다.
제목: `feat(enrich): 이적 방향 축 · 단계 규칙 경로 2형태` (scope 는 대표 모듈 기준 · 필요시 조정).
본문에 "머지 후 운영 게이트 (Task 7 소급 배치) 를 거쳐야 PR-2 (render 정리) 가 가능" 을 명시한다.

- [ ] **Step 3: 머지 대기**

머지는 사용자 직접.
머지 확인 전에 Task 7 로 넘어가지 않는다.

---

### Task 7: 운영 게이트 — VM 반영 · 소급 재분류 배치 · 수렴 확인

**Files:**
- 없음 (운영 · 런북 `docs/runbook/2026-06-30-transfer-stage-classification-ops.md` 2~4절 + Task 5 추가분을 따른다).

**전제**: PR-1 머지 완료.
**주의**: VM 쓰기 접근이므로 시작 전 사용자에게 고지한다 (병렬 워치리스트 세션이 읽기 전용 관찰 중).

- [ ] **Step 1: VM 코드 반영**

VM 에서 `git pull` 후 HEAD 가 PR-1 머지 커밋인지 확인한다 ("머지했다고 끝이 아니다" — 반영 없이는 옛 분류 패스가 돈다).

- [ ] **Step 2: 사전 덤프**

Task 5 에서 런북에 추가한 덤프 스니펫을 VM 에서 실행하고 `stage_dump.csv` 행수가 배포판 기사 수와 일치하는지 확인한다.

- [ ] **Step 3: NULL 복원**

런북 3절의 `UPDATE articles SET transfer_stage = NULL` 스니펫을 실행한다.

- [ ] **Step 4: 재분류 수렴 대기 · 확인**

다음 정기 회차 (하루 8회) 가 분류 패스를 돌린다.
급하면 enrich 전용 재실행 (`docs/runbook/2026-07-19-enrich-only-pass.md`) 을 쓴다.
회차 후 Task 5 의 수렴 쿼리 3종이 전부 기대값 (NULL 0 · 0 · 가십 rumour 단일) 인지 확인한다.
1패스 미수렴분 (LLM 응답 누락) 은 다음 회차가 흡수하므로 최대 2~3회차까지 관찰한다.

- [ ] **Step 5: 스팟 체크 · 재측정**

방출 어휘 3건의 direction = out 확인 (런북 스팟 체크 절).
감사 스크립트 (`docs/superpowers/2026-07-28-content-trust-audit-handoff.md` §6.2) 를 재실행해 재현 불일치율이 모델 흔들림 수준 (약 9%) 으로 내려왔는지 잰다.
결과 수치를 세션 메모리에 기록한다.

---

### Task 8: PR-2 — render 가십 하드코딩 제거 (배치 수렴 후에만)

**Files:**
- Modify: `src/bullet_in/serve/render.py:446-451` (`filter_stage`)

**전제**: Task 7 수렴 확인 완료 (가십 전행 rumour 저장 확인).
이 전제가 없으면 화면의 가십 배지가 저장값 (interest · agreed 등 혼재) 으로 흔들린다.

**Interfaces:**
- Consumes: 저장 계층이 가십 = rumour 를 보장 (Task 1 규칙 + Task 7 배치).
- Produces: `filter_stage(row) -> str | None` — 저장값 단순 반환 (호출부 3곳 무변경: `facet_counts` · `_ctx` · 카드 렌더).

- [ ] **Step 1: 하드코딩 제거**

```python
def filter_stage(row: dict) -> str | None:
    """카드 · 사이드바 건수가 공유하는 필터 단계 키.
    가십 루머 롤업은 저장 계층 규칙 (rule_stage) 으로 이동 — 방향 축 스펙 §5."""
    return row.get("transfer_stage")
```

- [ ] **Step 2: 화면 불변 검증**

로컬에서 배포판 덤프 (런북 `2026-07-28-content-trust-audit-handoff.md` §6.1 의 읽기 전용 VM 덤프 절차) 로 제거 전후 사이트를 각각 렌더하고, bbc_gossip 카드의 배지 · 사이드바 루머 건수가 동일한지 대조한다.

```bash
uv run pytest -q   # 회귀 확인
```

- [ ] **Step 3: 커밋 · PR-2 생성**

```bash
git add src/bullet_in/serve/render.py
git commit -m "fix(serve): 가십 루머 롤업 하드코딩 제거 — 저장 규칙으로 일원화"
```

PR 본문 7섹션 + humanize fast.
본문에 화면 불변 대조 결과 (전후 배지 · 건수 동일) 를 증거로 싣는다.
머지는 사용자 직접.
머지 · VM 반영 후 이 트랙이 종결되고 #144 재개 조건 (스펙 §8) 이 충족된다.
