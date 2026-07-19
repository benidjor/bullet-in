# 영입 단계 분류 개편 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** '이적 합의 (agreed)' 단계 신설 · 오피셜 공홈 규칙 한정 · 전건 재분류를 라이브 반영까지 완료한다.

**Architecture:** `transfer_stage.py` 단일 출처에 enum 을 추가하면 서빙이 자동 전파된다.
오피셜은 LLM enum 에서 제거하고 소스 규칙 (`rule_stage`) 경로에서만 생성한다 (방어 강등 포함).
소급은 기존 런북 멱등 경로 (NULL 복원 → 분류 패스) 를 그대로 쓴다.

**Tech Stack:** Python 3.11 · uv · pytest · google-genai (Gemini) · SQLAlchemy · MariaDB.

## Global Constraints

- spec: `docs/superpowers/specs/2026-07-19-transfer-stage-overhaul-design.md` (결정 근거 SoT).
- 브랜치 `feat/track5-transfer-stage-overhaul` 에서 작업한다 (spec 커밋 dc592c2 존재).
- 실행 전 `set -a; source .env; set +a` 필수 (dotenv 미사용) — 라이브 태스크 (Task 5) 만 해당.
- 커밋 컨벤션: `<type>(<scope>): 한국어 제목` + 도입 1–2문장 + 명사형 불릿 + `Refs:` + co-author 트레일러 (실제 작업 모델).
- 재분류는 fetch 를 하지 않는다 — fmkorea 2h 규칙과 무관해야 한다 (DB · Gemini 만 접촉).
- dbt 무변경 (transfer_stage 에 accepted_values 게이트 없음 — 실측).

---

### Task 1: transfer_stage 모듈 — agreed 신설 + rule_stage

**Files:**
- Modify: `src/bullet_in/transfer_stage.py`
- Test: `tests/test_transfer_stage.py`

**Interfaces:**
- Produces: `SIDEBAR_STAGES` 에 `("agreed", "이적 합의", "s-agree")` 가 official 다음 (index 1) 에 존재.
- Produces: `rule_stage(source_id: str | None) -> str | None` — `"arsenal_official"` → `"official"` · 그 외 → `None`.
- 이후 태스크가 `transfer_stage.rule_stage` (Task 3 run.py · Task 5 소급) 와 `"agreed"` enum (Task 2 강등) 을 사용한다.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_transfer_stage.py` 의 기존 순서 테스트를 개정하고 신규 2건을 추가한다.

기존 `test_sidebar_stages_order_and_count` 를 다음으로 교체:

```python
def test_sidebar_stages_order_and_count():
    enums = [e for e, _, _ in ts.SIDEBAR_STAGES]
    assert enums == ["official", "agreed", "medical", "personal_terms",
                     "negotiating", "interest", "rumour"]
```

기존 `test_label_and_css_lookup` 에 agreed 줄 2개 추가 (기존 assert 는 유지):

```python
    assert ts.label_for("agreed") == "이적 합의"
    assert ts.css_for("agreed") == "s-agree"
```

파일 끝에 신규 테스트 추가:

```python
def test_rule_stage_official_only_for_arsenal_official():
    # 오피셜은 공홈 소스 규칙 전용 (spec §4.1) — 그 외 소스·None 은 LLM 몫
    assert ts.rule_stage("arsenal_official") == "official"
    assert ts.rule_stage("bbc_sport") is None
    assert ts.rule_stage(None) is None
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_transfer_stage.py -q`
Expected: FAIL — 순서 불일치 (agreed 부재) · `rule_stage` AttributeError.

- [ ] **Step 3: 최소 구현** — `src/bullet_in/transfer_stage.py` 수정.

`SIDEBAR_STAGES` 를 다음으로 교체:

```python
SIDEBAR_STAGES: list[tuple[str, str, str]] = [
    ("official", "오피셜", "s-off"),
    ("agreed", "이적 합의", "s-agree"),
    ("medical", "메디컬", "s-med"),
    ("personal_terms", "개인 합의", "s-personal"),
    ("negotiating", "협상 중", "s-talk"),
    ("interest", "관심", "s-interest"),
    ("rumour", "루머", "s-rum"),
]
```

파일 끝 (`is_displayable` 아래) 에 추가:

```python
def rule_stage(source_id: str | None) -> str | None:
    """소스 조건 규칙 단계 (spec §4.1) — 공홈만 official, 그 외는 None(LLM 분류 몫).
    official 은 이 규칙 경로에서만 생성된다 (LLM enum 에서 제외 · 반환 시 강등)."""
    return "official" if source_id == "arsenal_official" else None
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_transfer_stage.py -q`
Expected: PASS (전건).

- [ ] **Step 5: 전체 테스트로 파급 확인**

Run: `uv run pytest -q`
Expected: `tests/test_enrich.py::test_stage_prompt_lists_every_valid_stage` 1건 FAIL (STAGE_PROMPT 에 agreed 부재 — Task 2 에서 해소).
그 외 전건 PASS 여야 한다.
다른 실패가 나오면 원인을 파악해 이 태스크에서 고친다.

- [ ] **Step 6: Commit**

```bash
git add src/bullet_in/transfer_stage.py tests/test_transfer_stage.py
git commit -m "feat(stage): agreed 단계 신설 · rule_stage 소스 규칙 추가

'이적 합의' 를 official 바로 아래 신설하고 오피셜을 소스 규칙 경로로
분리하기 위한 단일 출처 모듈 개정 (spec §3 · §4.1).

- SIDEBAR_STAGES: (agreed, 이적 합의, s-agree) 삽입 — 서빙 자동 전파
- rule_stage: arsenal_official → official · 그 외 None (규칙 경로 전용)
- 알려진 실패: STAGE_PROMPT 동기화 가드 1건 (Task 2 에서 해소)

Refs: docs/superpowers/specs/2026-07-19-transfer-stage-overhaul-design.md

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: <구현 모델> <noreply@anthropic.com>"
```

트레일러의 `<구현 모델>` 은 실제 구현 모델명으로 치환한다 (예: Claude Haiku 4.5 (구현)).

---

### Task 2: enrich — STAGE_PROMPT 개정 + official 강등 방어

**Files:**
- Modify: `src/bullet_in/enrich.py:219-231` (STAGE_PROMPT) · `src/bullet_in/enrich.py:281-282` (classify 결과 처리)
- Test: `tests/test_enrich.py`

**Interfaces:**
- Consumes: Task 1 의 `"agreed"` enum · `transfer_stage.normalize`.
- Produces: STAGE_PROMPT 에 agreed 정의 포함 · official 항목 부재.
- Produces: `classify_stage_rows` 가 official 응답을 `"agreed"` 로 강등.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_enrich.py` 의 프롬프트 가드를 교체하고 강등 테스트를 추가한다.

기존 `test_stage_prompt_lists_every_valid_stage` (248행 부근) 를 다음으로 교체:

```python
def test_stage_prompt_lists_llm_stages_and_excludes_official():
    """STAGE_PROMPT는 LLM 분류 대상 enum 전부를 포함하되 official은 제외한다.
    official은 공홈 소스 규칙 전용 (spec §4.1) — 프롬프트에 등장하면 규칙 분리가 깨진 것."""
    from bullet_in import transfer_stage as ts
    from bullet_in.enrich import STAGE_PROMPT
    for enum in sorted(ts.VALID_STAGES - {"official"}):
        assert enum in STAGE_PROMPT, f"STAGE_PROMPT가 {enum} 단계를 누락 — transfer_stage와 동기화 필요"
    assert "official" not in STAGE_PROMPT
```

`test_classify_demotes_invalid_stage_to_other` (209행 부근) 아래에 신규 테스트 추가.
같은 파일의 기존 classify 테스트들이 쓰는 가짜 클라이언트 패턴을 그대로 따른다 (해당 테스트의 client 헬퍼를 확인해 동일하게 작성).
헬퍼가 재사용 불가한 인라인 형태면 아래 자립형을 쓴다:

```python
def test_classify_demotes_official_to_agreed():
    """프롬프트에 없어도 모델이 official을 뱉으면 agreed로 강등 (spec §4.3 불변량)."""
    class M:
        class models:
            @staticmethod
            def generate_content(**kw):
                class R:
                    text = '[{"content_hash":"h1","stage":"official"}]'
                return R()
    from bullet_in.enrich import classify_stage_rows
    out = classify_stage_rows(
        [{"content_hash": "h1", "title_original": "t", "summary_ko": "s"}], M(), "m")
    assert out == {"h1": "agreed"}
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_enrich.py -q`
Expected: FAIL 2건 — 프롬프트에 agreed 부재 · official 존재, 강등 미구현 (`{"h1": "official"}` 반환).

- [ ] **Step 3: 구현** — `src/bullet_in/enrich.py` 수정.

STAGE_PROMPT 의 단계 목록에서 official 줄을 제거하고 agreed 를 추가해 다음으로 교체 (앞뒤 안내문은 유지):

```python
STAGE_PROMPT = (
    "다음은 아스날 FC 관련 기사 목록이다. 각 기사를 이적 진행 단계로 분류한다.\n"
    "단계 (반드시 아래 영문 값 중 하나로 답한다):\n"
    "- rumour: 근거 약한 소문 · 연결설\n"
    "- interest: 구단이 실제 관심 표명 · 스카우팅\n"
    "- negotiating: 구단 간 · 에이전트와 이적료/조건 협상 중\n"
    "- personal_terms: 선수와 개인 조건 (연봉 등) 합의\n"
    "- medical: 메디컬 테스트 진행 · 통과\n"
    "- agreed: 구단 간 이적 합의 · 딜 확정/임박 보도 (타 매체의 공식 발표 보도 포함)\n"
    "- other: 이적과 무관하거나 단계를 판단할 수 없음\n"
    "각 기사의 content_hash는 그대로 두고 stage만 채운다.\n"
    'ONLY JSON 배열: [{{"content_hash":"...","stage":"rumour"}}]\n\n'
    "기사 목록:\n{items}")
```

프롬프트 위 주석 (217–218행 "업데이트해야 하며…") 의 테스트명 언급도 새 테스트명으로 갱신한다.

`classify_stage_rows` 의 결과 반영부 (281–282행) 를 다음으로 교체:

```python
        for h, stage in parsed.items():
            stage = _stage.normalize(stage)
            if stage == "official":
                # 규칙 경로 전용 불변량 (spec §4.3) — 프롬프트 밖 응답 방어
                log.warning("LLM이 official 반환 — agreed로 강등 content_hash=%s", h)
                stage = "agreed"
            result[h] = stage
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_enrich.py tests/test_transfer_stage.py -q`
Expected: PASS (전건).

- [ ] **Step 5: 전체 테스트**

Run: `uv run pytest -q`
Expected: 전건 PASS (Task 1 의 알려진 실패가 해소됨).

- [ ] **Step 6: Commit**

```bash
git add src/bullet_in/enrich.py tests/test_enrich.py
git commit -m "feat(enrich): STAGE_PROMPT agreed 반영 · official 강등 방어

LLM 분류 enum 에서 official 을 제거하고 agreed 정의를 추가해
오피셜 규칙 분리를 프롬프트 층에서 강제한다 (spec §4.2 · §4.3).

- STAGE_PROMPT: agreed (합의 ~ 확정 · 발표 보도 포함) 추가 · official 제거
- classify_stage_rows: official 응답 → agreed 강등 + WARNING (불변량 방어)
- 동기화 가드 개정: LLM enum = VALID − {official} + official 부재 검증

Refs: docs/superpowers/specs/2026-07-19-transfer-stage-overhaul-design.md

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: <구현 모델> <noreply@anthropic.com>"
```

---

### Task 3: 규칙 · LLM 분리 배선 — rows_missing_stage + run.py

**Files:**
- Modify: `src/bullet_in/storage/mariadb.py:86-91` (rows_missing_stage)
- Modify: `src/bullet_in/run.py:75-78` (분류 패스) · `src/bullet_in/run.py:16-21` (import)
- Test: `tests/integration/test_mariadb_store.py:78-92`

**Interfaces:**
- Consumes: Task 1 의 `transfer_stage.rule_stage`.
- Produces: `rows_missing_stage()` 행에 `source_id` 키 포함.
- Produces: run.py 분류 패스가 공홈 행을 LLM 없이 태깅 — Task 5 소급 스크립트가 같은 분리 로직을 미러한다.

- [ ] **Step 1: 통합 테스트 개정** — `tests/integration/test_mariadb_store.py` 의 `test_rows_missing_stage_and_set_stage` 에서 missing 검증부에 한 줄 추가:

```python
    assert missing["hs"]["source_id"] == "bbc_sport"   # 규칙·LLM 분리 판정 입력 (spec §4.1)
```

- [ ] **Step 2: 실패 확인 (통합 — DB 필요)**

Run: `docker compose up -d && uv run pytest tests/integration/test_mariadb_store.py -q`
Expected: FAIL — KeyError `source_id`.
DB 를 못 띄우는 환경이면 skip 되므로, 그 경우 Step 4 의 전체 테스트에서 확인한다는 주석을 보고에 남긴다.

- [ ] **Step 3: 구현**

`src/bullet_in/storage/mariadb.py` 의 `rows_missing_stage` SELECT 를 교체:

```python
    def rows_missing_stage(self) -> list[dict]:
        with self.engine.connect() as c:
            rows = c.execute(text(
                "SELECT content_hash,source_id,title_original,summary_ko "
                "FROM articles WHERE transfer_stage IS NULL")).mappings().all()
        return [dict(r) for r in rows]
```

`src/bullet_in/run.py` import 블록 (13행 부근) 에 추가:

```python
from bullet_in import transfer_stage
```

분류 패스 (75–78행) 를 교체:

```python
    # 분류 패스: 공홈은 소스 규칙으로 직접 태깅 (official 은 규칙 경로 전용), 나머지만 LLM 분류
    llm_rows = []
    for r in mart.rows_missing_stage():
        ruled = transfer_stage.rule_stage(r["source_id"])
        if ruled:
            mart.set_stage(r["content_hash"], ruled)
        else:
            llm_rows.append(r)
    for h, stage in classify_stage_rows(llm_rows, client, GEMINI_MODEL).items():
        mart.set_stage(h, stage)
```

참고: classify 배치 조립 (enrich.py:260-264) 은 명시 키만 추리므로 source_id 추가가 프롬프트에 누수되지 않는다.

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/integration/test_mariadb_store.py -q && uv run pytest -q && uv run python -m py_compile src/bullet_in/run.py`
Expected: 전건 PASS · 컴파일 무오류.

- [ ] **Step 5: Commit**

```bash
git add src/bullet_in/storage/mariadb.py src/bullet_in/run.py tests/integration/test_mariadb_store.py
git commit -m "feat(pipeline): 분류 패스 규칙 · LLM 분리 배선

공홈 행을 LLM 호출 없이 rule_stage 로 직접 태깅해 오피셜을
소스 규칙 경로에 한정한다 (spec §4.1).

- rows_missing_stage: source_id 포함 (분리 판정 입력, 프롬프트 누수 없음)
- run.py 분류 패스: 규칙 대상 직접 set_stage · 잔여만 classify_stage_rows

Refs: docs/superpowers/specs/2026-07-19-transfer-stage-overhaul-design.md

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: <구현 모델> <noreply@anthropic.com>"
```

---

### Task 4: 서빙 — s-agree 배지 색 + 렌더 스모크

**Files:**
- Modify: `src/bullet_in/serve/static/style.css:56-57`
- Test: `tests/test_serve_render.py`

**Interfaces:**
- Consumes: Task 1 의 SIDEBAR_STAGES (템플릿 · facet 은 단일 출처라 코드 변경 불필요).
- Produces: `.s-agree` css 클래스 (배지 배경색).

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_serve_render.py` 의 `test_decorate_sets_stage_fields` 아래에 추가:

```python
def test_decorate_agreed_stage_badge():
    from bullet_in.serve.render import _decorate
    d = _decorate(_row(transfer_stage="agreed"), SOURCES, NOW)
    assert d["_stage_badge"] is True
    assert d["_stage_label"] == "이적 합의"
    assert d["_stage_class"] == "s-agree"


def test_sidebar_and_card_render_agreed():
    html = render_index([_row(transfer_stage="agreed")], SOURCES, NOW)
    assert 'data-value="agreed"' in html      # 사이드바 필터 체크박스
    assert "이적 합의" in html                  # 라벨 노출
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_serve_render.py -q`
Expected: Task 1 이 이미 머지된 브랜치 상태라 두 테스트 모두 PASS 할 수 있다.
PASS 라면 단일 출처 전파가 실증된 것 — 그대로 Step 3 으로 진행한다 (css 는 테스트가 못 잡는 시각 자산).

- [ ] **Step 3: css 구현** — `src/bullet_in/serve/static/style.css` 57행 (`.s-personal…` 줄) 끝에 추가:

```css
.s-agree{background:#2563eb}
```

기존 6색 (`#16a34a` 녹 · `#0ea5e9` 하늘 · `#f59e0b` 호박 · `#9ca3af` 회 · `#8b5cf6` 보라 · `#14b8a6` 청록) 과 구분되는 파랑.

- [ ] **Step 4: 전체 테스트**

Run: `uv run pytest -q`
Expected: 전건 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bullet_in/serve/static/style.css tests/test_serve_render.py
git commit -m "feat(serve): 이적 합의 배지 · 사이드바 노출

SIDEBAR_STAGES 단일 출처 전파를 렌더 테스트로 고정하고
agreed 배지 색을 추가한다 (spec §7).

- .s-agree 배지 색 #2563eb (기존 6색과 구분되는 파랑)
- 렌더 스모크: 카드 배지 라벨 · 사이드바 data-value=agreed 고정

Refs: docs/superpowers/specs/2026-07-19-transfer-stage-overhaul-design.md

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: <구현 모델> <noreply@anthropic.com>"
```

---

### Task 5: 전건 재분류 라이브 + 매핑 검증 리포트 (사용자 눈검수 게이트)

**Files:**
- 없음 (라이브 실행 — 코드 변경 없음, 스크립트는 세션 스크래치)

**Interfaces:**
- Consumes: Task 1–3 의 rule_stage · 개정 프롬프트 · source_id 포함 rows_missing_stage.
- Produces: 재분류된 DB · 재렌더된 site/ · 사용자 눈검수용 리포트 (agreed 목록 · 전후 분포).

**전제:** `set -a; source .env; set +a` · docker compose (mongo · mariadb) 기동 · GEMINI_API_KEY 유효.
fetch 는 절대 하지 않는다 (fmkorea 2h 규칙 무관 경로 유지).

- [ ] **Step 1: 재분류 전 분포 스냅샷 (리포트용)**

```bash
uv run python - <<'EOF'
import os
from sqlalchemy import create_engine, text
eng = create_engine(os.environ["MARIADB_URL"])
with eng.connect() as c:
    for r in c.execute(text(
        "SELECT COALESCE(transfer_stage,'NULL') s, COUNT(*) n FROM articles "
        "GROUP BY transfer_stage ORDER BY n DESC")):
        print(f"{r.s:16} {r.n}")
EOF
```

출력을 보고에 기록한다 (기대: rumour 65 · other 43 · interest 34 · negotiating 29 · official 21 · medical 5 · personal_terms 4 부근 — 신규 수집분로 소폭 달라질 수 있음).

- [ ] **Step 2: NULL 복원 (재분류 트리거 — 런북 멱등 경로)**

```bash
uv run python - <<'EOF'
import os
from sqlalchemy import create_engine, text
eng = create_engine(os.environ["MARIADB_URL"])
with eng.begin() as c:
    n = c.execute(text("UPDATE articles SET transfer_stage=NULL")).rowcount
print("NULL 복원:", n, "건")
EOF
```

- [ ] **Step 3: 분류 패스 재실행 (run.py 분리 로직 미러 · 최대 3패스)**

```bash
uv run python - <<'EOF'
import os
from google import genai
from sqlalchemy import create_engine
from bullet_in import transfer_stage
from bullet_in.enrich import classify_stage_rows
from bullet_in.run import GEMINI_MODEL
from bullet_in.storage.mariadb import MartStore

mart = MartStore(create_engine(os.environ["MARIADB_URL"]))
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
for attempt in range(3):
    rows = mart.rows_missing_stage()
    if not rows:
        break
    llm_rows = []
    for r in rows:
        ruled = transfer_stage.rule_stage(r["source_id"])
        if ruled:
            mart.set_stage(r["content_hash"], ruled)
        else:
            llm_rows.append(r)
    done = classify_stage_rows(llm_rows, client, GEMINI_MODEL)
    for h, stage in done.items():
        mart.set_stage(h, stage)
    print(f"패스 {attempt + 1}: 규칙 {len(rows) - len(llm_rows)} · LLM {len(done)}/{len(llm_rows)}")
print("미분류 잔존:", len(mart.rows_missing_stage()))
EOF
```

Expected: 미분류 잔존 0 (파싱 실패는 다음 패스에서 수렴 · 429 시 수 분 대기 후 재실행).

- [ ] **Step 4: 매핑 검증 (spec §6 전건)**

```bash
uv run python - <<'EOF'
import os
from sqlalchemy import create_engine, text
eng = create_engine(os.environ["MARIADB_URL"])
with eng.connect() as c:
    bad = c.execute(text(
        "SELECT COUNT(*) FROM articles "
        "WHERE transfer_stage='official' AND source_id != 'arsenal_official'")).scalar()
    print("불변량 위반 (비공홈 official):", bad, "— 0 이어야 함")
    print("== 예시 기대 매핑 (둘 다 agreed 여야 함) ==")
    for r in c.execute(text(
        "SELECT content_hash, transfer_stage, title_ko FROM articles "
        "WHERE content_hash LIKE 'cb0894b7%' OR content_hash LIKE 'b8055b5b%'")):
        print(f"{r.content_hash[:8]} stage={r.transfer_stage} | {r.title_ko}")
    print("== agreed 전건 (눈검수용) ==")
    for r in c.execute(text(
        "SELECT content_hash, source_id, title_ko FROM articles "
        "WHERE transfer_stage='agreed' ORDER BY published_at DESC")):
        print(f"{r.content_hash[:8]} [{r.source_id}] {r.title_ko}")
    print("== 재분류 후 분포 ==")
    for r in c.execute(text(
        "SELECT COALESCE(transfer_stage,'NULL') s, COUNT(*) n FROM articles "
        "GROUP BY transfer_stage ORDER BY n DESC")):
        print(f"{r.s:16} {r.n}")
EOF
```

Expected: 불변량 위반 0 · 예시 2건 agreed · official 0건 (공홈 적재 0 인 현재 데이터 기준).
예시 2건이 agreed 가 아니면: 해당 행을 개별 프로브 (동일 입력 재분류 1회) 하고, 그래도 다르면 프롬프트 정의를 검토해 컨트롤러에 보고한다 (임의 수정 금지).

- [ ] **Step 5: 사이트 재렌더 + 화면 확인**

```bash
uv run python - <<'EOF'
import os
from sqlalchemy import create_engine, text
from bullet_in.score import load_sources
from bullet_in.credibility import load_registry, journalist_directory
from bullet_in.serve.render import write_site

engine = create_engine(os.environ["MARIADB_URL"])
with engine.connect() as c:
    rows = [dict(r) for r in c.execute(text(
        "SELECT content_hash,url,source_id,title_original,title_ko,summary_ko,"
        "summary3_ko,body_ko,image_url,images_json,outlet,journalist,team,transfer_stage,tier,"
        "confidence_score,published_at FROM articles")).mappings().all()]
write_site(rows, load_sources("config/sources.yaml"), "site",
           directory=journalist_directory("config/credibility.yaml"),
           registry=load_registry("config/credibility.yaml"))
print("site 재생성:", len(rows), "행")
EOF
grep -c 'data-value="agreed"' site/index.html
grep -o '이적 합의' site/index.html | head -1
```

Expected: index.html 에 agreed 체크박스 · '이적 합의' 라벨 존재.

- [ ] **Step 6: 리포트 제출 (커밋 없음)**

Step 1 · 3 · 4 출력 (전후 분포 · agreed 전건 목록 · 불변량 · 예시 매핑) 을 정리해 컨트롤러에 보고한다.
컨트롤러는 이를 사용자 눈검수 게이트로 올린다 — **사용자 승인 전에 Task 6 을 시작하지 않는다.**

---

### Task 6: 분류 런북 개정 (+ 최종 검증)

**Files:**
- Modify: `docs/runbook/2026-06-30-transfer-stage-classification-ops.md`

**Interfaces:**
- Consumes: Task 1–5 의 확정 동작 (규칙 분리 · agreed · 재분류 실측).

**전제:** Task 5 의 사용자 눈검수 승인 후 시작한다.

- [ ] **Step 1: 런북 개정** — 기존 런북을 읽고 다음을 반영한다 (기존 절 구조 유지 · 문서 서식 §2.2 준수, `docs/` 저장 시 훅이 자동 검사).

- 단계 목록 · 예시에 agreed ('이적 합의') 반영.
- 신규 절 "오피셜 규칙 분리 (2026-07-19)": arsenal_official = rule_stage 자동 official (LLM 제외) · LLM enum 에서 official 제거 · official 응답은 agreed 강등 WARNING · 불변량 SQL (Task 5 Step 4 의 비공홈 official 카운트) 을 진단 명령으로 수록.
- 전건 재분류 절에 이번 실측 기록 1–2줄 (재분류 건수 · 수렴 패스 수 · official 0건 = 공홈 적재 0 인 동안 정상).
- 재계약 관찰 항목 (spec §4.4) 1줄.

- [ ] **Step 2: 전체 테스트 최종 확인**

Run: `uv run pytest -q`
Expected: 전건 PASS.

- [ ] **Step 3: Commit**

```bash
git add docs/runbook/2026-06-30-transfer-stage-classification-ops.md
git commit -m "docs(runbook): 단계 분류 런북 — agreed · 오피셜 규칙 분리 반영

트랙 ⑤ 개편 (agreed 신설 · 오피셜 공홈 규칙 한정) 을 운영 절차와
진단 명령에 반영한다.

- 단계 목록 · 재분류 절차에 agreed 반영 + 이번 전건 재분류 실측 기록
- 오피셜 규칙 분리 절 신설: rule_stage · 강등 방어 · 불변량 SQL 진단
- 재계약 official 관찰 항목 (공홈 sign 필터 특성) 기록

Refs: docs/superpowers/specs/2026-07-19-transfer-stage-overhaul-design.md

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: <구현 모델> <noreply@anthropic.com>"
```

---

## 완료 후 (컨트롤러 몫 — 태스크 아님)

- superpowers:requesting-code-review 로 whole-branch 최종 리뷰 (리뷰 모델은 co-author 제외).
- PR 생성: 7섹션 한국어 본문 · `--body-file` · Claude 서명 금지 · squash merge.
- 메모리 스냅샷 갱신.
