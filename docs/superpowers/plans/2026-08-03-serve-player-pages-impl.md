# 선수 페이지 재개 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 보류돼 있던 선수 색인 · 선수 페이지 · 상세 칩 · ops 표를 `article_players` 원천으로 재구현하고, 그 화면이 읽을 분류 값 두 가지 (오피셜 도달 · 이적 방향 기준) 를 먼저 정돈한다.

**Architecture:** 원천을 사전 문자열 대조에서 `players` · `article_players` 조인으로 바꾼다.
색인 그룹과 배지는 `players.transfer_status`, 타임라인 단계는 `article_players.stage` 가 공급하며 기사 단위 `transfer_direction` 은 이 화면에서 쓰지 않는다.
PR 을 둘로 나눠 데이터를 먼저 정돈한 뒤 화면을 얹는다.

**Tech Stack:** Python 3.11 · SQLAlchemy Core (raw SQL) · Jinja2 · pytest · MariaDB 11.

## Global Constraints

- 스펙 = `docs/superpowers/specs/2026-08-03-serve-player-pages-resume-design.md` (이하 스펙).
결정을 다시 열지 않는다.
- 선수 페이지 대상 조건 = `category IN ('squad','external') AND transfer_status <> 'none'` + 귀속 기사 1건 이상 (스펙 §3.1).
여기에 `status <> 'candidate'` 를 더한다 (아래 "승인된 스펙 이탈" 참조).
- 색인 그룹 안 정렬은 최근 보도일 내림차순 단일 키다 (스펙 §4.3).
합성 점수를 만들지 않는다.
- 단계 역행은 있는 그대로 표시한다 (스펙 §5.2).
최고 도달 단계로 고정하지 않는다.
- 고아 페이지 정리는 조회 0건이면 삭제를 건너뛴다 (스펙 §5.4).
- `write_site()` 의 인자는 현행 `run.py` 서빙 경로와 1:1 로 유지한다.
런북 재생성 스니펫이 같은 인자로 호출하므로 시그니처를 넓히지 않는다.
- 산출물 본문은 한국어이며 컨벤션 §2.2 서식을 따른다.
- 커밋은 `benidjor <94089198+benidjor@users.noreply.github.com>` 신원으로 한다.
- `git reset` · `git rebase` 를 쓰지 않는다.

## 승인된 스펙 이탈 3건 (2026-08-03 사용자 확정)

착수 직후 운영 DB 실측 (스펙 §11.4) 에서 전제가 어긋난 것이 확인돼 사용자가 아래 셋을 확정했다.

1. **보관 75행의 `transfer_status` 를 `none` 으로 갱신한다** (Task 5).
보관 행 78건 중 75건이 `in_link` 인데, 이는 `insert_candidate()` 가 넣는 기본값이 사람 보관 시 교정되지 않고 남은 것이다.
그중 귀속 기사가 있어 색인에 실제로 나타났을 행은 64건이다.
운영이 실제로 사유를 남길 때는 `other_club` 을 썼다 (은두카 · 마테우스 페르난데스 · 밤바 3건).
갱신하면 스펙 §3.1 조건을 고치지 않고 §3.2 가 서술한 동작 (스태프 · 은퇴 · 오등재 제외) 이 실현된다.
2. **색인 대상에서 `candidate` 를 제외한다.**
스펙 §3.1 은 `status` 를 조건에 넣지 않기로 했으나 후보 행을 논의하지 않았다.
후보 7명은 전원 사람 승인 전이고 각각 기사 1건이라, 확정 전 페이지를 만들지 않는다.
3. **오피셜 승격 방식을 유지가 아니라 덮어쓰기로 바꾼다.**
스펙 §8.1 은 공홈 기사에서 모델이 낸 `official` 을 유지하는 방식으로 적혀 있으나, 추출 프롬프트가 `official` 을 선택지에서 배제하고 있어 그 방식으로는 승격이 일어나지 않는다.
2026-08-03 사용자 확정으로 덮어쓰기로 전환했다
— 공홈 소스면 모델 답과 무관하게 `official` 을 저장하며, 이는 기사 단위 경로 (`run.py` 의 `stage_ruled`) 및 소급 `UPDATE` 와 같은 규칙이다.

## 착수 시점 실측값 (2026-08-03 · VM 운영 DB)

이후 태스크의 대조 기준선이다.

| 항목 | 값 |
| --- | --- |
| `articles` 총 행 | 476 |
| `transfer_stage` NULL | 0 |
| `transfer_direction` NULL | 0 |
| 방향 분포 | `in` 297 · `none` 137 · `out` 42 |
| 아스날 무관 방향 부여 건 (재분류 대상) | 38 (in 31 · out 7) |
| 그 38건의 단계 분포 | `negotiating` 11 · `agreed` 9 · `interest` 8 · `rumour` 8 · `medical` 1 · `personal_terms` 1 |
| `arsenal_official` 기사에 걸린 `article_players` | 6 (`agreed` 5 · `medical` 1) |
| 보관 행 `transfer_status` | `in_link` 75 · `other_club` 3 |
| 갱신 후 색인 예상 | 진행 중 40 · 성사 10 · 무산과 종료 6 |
| 동성 충돌 | 9쌍 (Vieira · Fernandes · Williams · Diaz · Araujo · Diomande · Kroupi · Meslier · Nduka) |

## 파일 구조

### PR ① 분류 계열 — 브랜치 `feat/player-pages-data`

| 파일 | 책임 | 변경 |
| --- | --- | --- |
| `src/bullet_in/roster.py` | 추출 쌍 검증 · 저장 | `normalize_pairs` 에 `source_id` 인자 · 조건부 `official` 승격 |
| `src/bullet_in/run.py` | 정기 회차 | `normalize_pairs` 호출에 `source_id` 전달 |
| `src/bullet_in/backfill_article_players.py` | 1회성 백필 | 대상 SQL 에 `source_id` 추가 · 호출에 전달 |
| `src/bullet_in/enrich.py` | 분류 프롬프트 | `STAGE_PROMPT` 에 방향 기준 문장 1줄 |
| `tests/test_roster.py` | 단위 테스트 | 승격 · 강등 케이스 |
| `tests/test_transfer_stage_prompt.py` | 단위 테스트 | 프롬프트 문구 회귀 가드 (신규) |

### PR ② 서빙 계열 — 브랜치 `feat/player-pages-serve`

| 파일 | 책임 | 변경 |
| --- | --- | --- |
| `src/bullet_in/storage/players.py` | 선수 저장소 | 선수 페이지 조회 3종 추가 |
| `src/bullet_in/serve/render.py` | 렌더 | 배지 · 그룹 · slug · 전이 타임라인 · 색인 · 선수 페이지 · 칩 · ops 표 · `write_site` 통합 |
| `src/bullet_in/serve/templates/players.html.j2` | 색인 화면 | 신규 |
| `src/bullet_in/serve/templates/player.html.j2` | 선수 화면 | 신규 |
| `src/bullet_in/serve/templates/_layout.html.j2` | 레이아웃 | 네비 항목 · `solo` 변수 |
| `src/bullet_in/serve/templates/detail.html.j2` | 상세 | 선수 칩 |
| `src/bullet_in/serve/templates/ops.html.j2` | 운영 뷰 | 추출 누락 표 |
| `src/bullet_in/serve/static/style.css` | 스타일 | 색인 카드 · 타임라인 · 칩 |
| `src/bullet_in/serve/static/app.js` | 동작 | 무산 그룹 접기 |
| `tests/test_serve_players.py` | 단위 테스트 | 신규 |
| `tests/integration/test_player_store.py` | 통합 테스트 | 조회 3종 |

---

# PR ① 분류 계열

## Task 1: `normalize_pairs` 조건부 `official` 승격

**Files:**
- Modify: `src/bullet_in/roster.py:16-41`
- Modify: `src/bullet_in/run.py:127`
- Modify: `src/bullet_in/backfill_article_players.py:26-29`, `:71`
- Test: `tests/test_roster.py`

**Interfaces:**
- Consumes: `bullet_in.transfer_stage.rule_stage(source_id) -> tuple[str | None, str | None]` (기존).
- Produces: `roster.normalize_pairs(raw, source_id: str | None = None) -> list[dict]`.
Task 2 이후 태스크는 이 시그니처에 의존하지 않는다.

**배경:** 지금은 `official` 을 무조건 `agreed` 로 강등해서 공홈 발표 기사가 전이형 타임라인에서 노드를 못 만든다 (스펙 §8.1).
판정을 새로 짜지 않고 `rule_stage()` 를 재사용해 `arsenal_official` 문자열이 두 곳에 생기지 않게 한다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_roster.py` 끝에 추가한다.

```python
def test_normalize_pairs_keeps_official_for_arsenal_official():
    raw = [{"full_name": "Martin Zubimendi", "ko": "수비멘디", "stage": "official"}]
    out = normalize_pairs(raw, "arsenal_official")
    assert out[0]["stage"] == "official"


def test_normalize_pairs_demotes_official_for_other_sources():
    raw = [{"full_name": "Martin Zubimendi", "ko": "수비멘디", "stage": "official"}]
    assert normalize_pairs(raw, "bbc_sport")[0]["stage"] == "agreed"
    assert normalize_pairs(raw, None)[0]["stage"] == "agreed"
    assert normalize_pairs(raw)[0]["stage"] == "agreed"        # 인자 생략 = 강등


def test_normalize_pairs_arsenal_official_does_not_promote_other_stages():
    raw = [{"full_name": "Someone", "ko": "누군가", "stage": "rumour"},
           {"full_name": "Another One", "ko": "다른이", "stage": "발표"}]
    out = normalize_pairs(raw, "arsenal_official")
    assert [p["stage"] for p in out] == ["rumour", "other"]
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_roster.py -q`
Expected: FAIL — `normalize_pairs() takes 1 positional argument but 2 were given`

- [ ] **Step 3: 구현한다**

`src/bullet_in/roster.py` 의 `normalize_pairs` 를 아래로 바꾼다.
docstring 도 함께 고친다 (강등 조건이 바뀌었으므로).

```python
def normalize_pairs(raw, source_id: str | None = None) -> list[dict]:
    """모델 출력 players 필드 검증 — 이름 없는 항목 · 비 dict · 중복은 버리고
    stage 는 enum 정규화.

    official 은 규칙 경로 전용이라 원칙적으로 agreed 로 강등하되, 공홈 기사에서는
    그대로 저장한다 (스펙 §8.1) — 그러지 않으면 공홈 발표가 선수 타임라인에서
    직전 기사와 같은 값이 되어 노드조차 생기지 않는다. 판정은 rule_stage() 를
    재사용한다 (arsenal_official 문자열의 단일 출처 유지).
    스키마 폭 (VARCHAR 100/50) 을 넘는 출력과 배열 폭주는 여기서 걸러 DB 예외를 막는다."""
    if not isinstance(raw, list):
        return []
    ruled_official = _stage.rule_stage(source_id)[0] == "official"
    out, seen = [], set()
    for item in raw[:_MAX_PAIRS]:
        if not isinstance(item, dict):
            continue
        fn = (item.get("full_name") or "").strip()
        if not fn or len(fn) > _MAX_FULL_NAME or _HANGUL_RE.search(fn):
            continue
        folded = _fold_latin(fn)
        if folded in seen:
            continue
        seen.add(folded)
        stage = _stage.normalize(item.get("stage"))
        if stage == "official" and not ruled_official:
            stage = "agreed"
        ko = (item.get("ko") or "").strip() or None
        if ko and len(ko) > _MAX_KO:
            ko = None
        out.append({"full_name": fn, "ko": ko, "stage": stage})
    return out
```

- [ ] **Step 4: 테스트 통과를 확인한다**

Run: `uv run pytest tests/test_roster.py -q`
Expected: PASS (기존 테스트 포함 전부)

- [ ] **Step 5: 호출부 두 곳에 `source_id` 를 전달한다**

`src/bullet_in/run.py:127` 을 바꾼다.
`by_hash` 는 바로 위에서 `missing` 으로 만들어지고 `rows_missing_translation()` 이 이미 `source_id` 를 뽑으므로 추가 조회가 없다.

```python
            pairs = roster.normalize_pairs(v.get("players"),
                                           by_hash.get(h, {}).get("source_id"))
```

`src/bullet_in/backfill_article_players.py` 의 `_TARGET_SQL` 에 `source_id` 를 넣는다.

```python
_TARGET_SQL = text(
    "SELECT content_hash, source_id, title_original, body_source, body_excerpt, url "
    "FROM articles WHERE NOT EXISTS (SELECT 1 FROM article_players ap "
    "WHERE ap.content_hash = articles.content_hash) ORDER BY published_at, id")
```

같은 파일 `:71` 을 바꾼다.

```python
            pairs = roster.normalize_pairs(raw, by_hash[h].get("source_id"))
```

- [ ] **Step 6: 전체 테스트를 돌린다**

Run: `uv run pytest -q`
Expected: PASS (통합 테스트는 DB 없으면 skip)

- [ ] **Step 7: 커밋한다**

```bash
git add src/bullet_in/roster.py src/bullet_in/run.py \
        src/bullet_in/backfill_article_players.py tests/test_roster.py
git commit -m "$(cat <<'EOF'
feat(enrich): 공홈 기사의 선수 단계에 오피셜 저장 허용

선수 타임라인은 단계가 바뀐 기사만 노드로 만드는데, 지금은 공홈 발표도
article_players 에 agreed 로 저장돼 직전 기사와 값이 같아 노드가 생기지 않는다.
같은 기사가 홈 화면에서는 오피셜 배지를 다는 것과 어긋난다.

- 조건부 승격: normalize_pairs 가 source_id 를 받아 공홈이면 official 유지
- 판정 재사용: 공홈 규칙은 rule_stage() 한 곳에만 두고 문자열을 새로 박지 않음
- 호출부 전달: 정기 회차 · 백필 두 경로에 source_id 배선
- 백필 대상 SQL: source_id 컬럼 추가

Refs: docs/superpowers/specs/2026-08-03-serve-player-pages-resume-design.md §8.1
EOF
)"
```

---

## Task 2: `STAGE_PROMPT` 에 방향 기준 명시

**Files:**
- Modify: `src/bullet_in/enrich.py:732-741`
- Test: `tests/test_transfer_stage_prompt.py` (신규)

**Interfaces:**
- Consumes: 없음.
- Produces: `enrich.STAGE_PROMPT` 문자열 (기존 이름 유지).

**배경:** 방향 축을 아스날 기준으로 고정한다 (스펙 §7.1).
바로 아래에 "이적 주체가 아스날이 아니어도 그 이적의 단계로 분류한다" 가 있어 모델이 헷갈려 단계까지 `other` 로 떨어뜨릴 위험이 있으므로 (스펙 §8.2), 두 축이 독립임을 문장에서 못박는다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_transfer_stage_prompt.py` 를 새로 만든다.

```python
"""STAGE_PROMPT 문구 회귀 가드 — 두 축의 독립성이 프롬프트에서 사라지지 않게 고정한다."""
from bullet_in.enrich import STAGE_PROMPT


def test_prompt_fixes_direction_baseline_to_arsenal():
    assert "방향은 아스날 기준이다" in STAGE_PROMPT
    assert "주체가 아니면 (타 구단 간 이적) none 으로 답한다" in STAGE_PROMPT


def test_prompt_keeps_other_club_stage_rule():
    # #200 · #201 에서 의도적으로 넣은 문장 — 방향 문구가 이것을 밀어내면 안 된다
    assert "이적 주체가 아스날이 아니어도" in STAGE_PROMPT


def test_prompt_states_the_two_axes_are_independent():
    assert "방향만 none 이고 단계는 그대로" in STAGE_PROMPT
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_transfer_stage_prompt.py -q`
Expected: FAIL — 첫 · 셋째 단언에서 AssertionError

- [ ] **Step 3: 구현한다**

`src/bullet_in/enrich.py` 의 `STAGE_PROMPT` 에서 방향 값 설명 바로 아래 (현행 `"- none: 이적 무관 기사 · 방향을 판단할 수 없음\n"` 다음 줄) 에 두 줄을 넣는다.
기존 줄은 하나도 지우지 않는다.

```python
    "- none: 이적 무관 기사 · 방향을 판단할 수 없음\n"
    "방향은 아스날 기준이다 — 아스날이 이적의 주체가 아니면 (타 구단 간 이적) none 으로 답한다.\n"
    "이때 단계는 아래 규칙대로 그대로 매긴다 — 방향만 none 이고 단계는 그대로다.\n"
    "방향은 제목이 내세우는 주된 이적 하나로 정한다 — 요약 말미의 부수 언급"
```

- [ ] **Step 4: 테스트 통과를 확인한다**

Run: `uv run pytest tests/test_transfer_stage_prompt.py -q`
Expected: PASS

- [ ] **Step 5: 전체 테스트를 돌린다**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 6: 커밋한다**

```bash
git add src/bullet_in/enrich.py tests/test_transfer_stage_prompt.py
git commit -m "$(cat <<'EOF'
feat(enrich): 이적 방향의 기준 구단을 아스날로 명시

방향 값은 아스날 기준으로 정의돼 있으나 프롬프트가 그것을 적지 않아, 모델이
타 구단 간 이적 기사에서 그 이적 자체의 영입 · 방출로 답해 왔다. 실측 38건이
아스날과 무관한 이적에 방향을 달고 있다.

- 기준 명시: 아스날이 주체가 아니면 방향은 none
- 독립성 명시: 방향만 none 이고 단계는 기존 규칙대로 유지
- 회귀 가드: 두 축 문장이 서로를 밀어내지 않는지 테스트로 고정

Refs: docs/superpowers/specs/2026-08-03-serve-player-pages-resume-design.md §7 · §8.2
EOF
)"
```

---

## Task 3: 계획서 · 런북 기록

**Files:**
- Create: `docs/superpowers/plans/2026-08-03-serve-player-pages-impl.md` (이 문서)
- Modify: `docs/runbook/2026-06-30-transfer-stage-classification-ops.md` "알려진 한계" §

- [ ] **Step 1: 런북의 미결 항목을 결정 반영으로 바꾼다**

`docs/runbook/2026-06-30-transfer-stage-classification-ops.md` 의 "타 구단 이적에 붙은 방향 값은 기준 구단이 없다 — 결정 보류" 항목을 아래로 교체한다.
선택지 3종을 나열한 문단은 지우고 결정과 근거만 남긴다.

```markdown
- **타 구단 이적에 붙은 방향 값은 아스날 기준이다 (2026-08-03 확정).**
`in` 은 아스날로 오는 이적 · `out` 은 아스날에서 나가는 이적이며, 아스날이 이적의 주체가 아니면 `none` 이다.
프롬프트가 기준을 적지 않던 동안 모델이 타 구단 기사에서 그 이적 자체의 영입 · 방출로 답해, 실측 38건이 아스날과 무관한 이적에 방향을 달고 있었다 (2026-08-03 소급 재분류로 정정).
단계는 이 결정의 영향을 받지 않는다
— 타 구단 이적도 그 이적의 단계로 분류한다는 규칙은 `other` 버킷 완화 (#200 · #201) 때 의도적으로 넣은 것이라 그대로 둔다.
기준 구단을 담을 칸은 `articles.team` 이며, 멀티 클럽으로 넓힐 때 방향 정의의 아스날 자리에 이 컬럼을 넣는 일반화 한 번이면 열린다.
배경: `docs/superpowers/specs/2026-08-03-serve-player-pages-resume-design.md` §7.
```

- [ ] **Step 2: 문서 서식 훅을 통과하는지 확인한다**

Run: `uv run python .claude/hooks/check-doc-format.py docs/runbook/2026-06-30-transfer-stage-classification-ops.md`
Expected: 위반 없음 (훅이 인자를 받지 않는 형태면 저장 시 자동 검사에 의존한다)

- [ ] **Step 3: 커밋한다**

```bash
git add docs/superpowers/plans/2026-08-03-serve-player-pages-impl.md \
        docs/runbook/2026-06-30-transfer-stage-classification-ops.md
git commit -m "$(cat <<'EOF'
docs(plan): 선수 페이지 재개 구현 계획 · 방향 기준 결정 반영

스펙 확정 뒤 구현 세션이 쓸 태스크 단위 계획을 남기고, 런북이 미결로 적어 둔
방향 기준 항목을 결정 내용으로 바꾼다.

- 계획서: PR 2개 · 태스크 11개 · 착수 시점 실측 기준선
- 승인된 이탈 2건: 보관 75행 사유 갱신 · 후보 색인 제외
- 런북: 알려진 한계의 선택지 나열을 아스날 기준 확정으로 교체

Refs: docs/superpowers/specs/2026-08-03-serve-player-pages-resume-design.md
EOF
)"
```

---

## Task 4: PR ① 생성

- [ ] **Step 1: 푸시한다**

```bash
git push -u origin feat/player-pages-data
```

- [ ] **Step 2: PR 본문을 파일로 쓴다**

7섹션 한국어 구조 · `pull_request_template.md` 주석 세칙을 따른다.
게시 전 humanize-korean 스킬 (fast) 문체 점검을 1회 통과시킨다.
변경 금지 목록으로 서식 규칙 (§2.2) · 명사형 불릿 · 수치 · 경로를 명시한다.

- [ ] **Step 3: PR 을 만든다**

```bash
gh pr create --base main --head feat/player-pages-data \
  --title "feat(enrich): 공홈 오피셜 저장 · 이적 방향 기준 아스날 고정" \
  --body-file /tmp/pr-body-data.md
```

머지는 사용자가 직접 한다.
세션은 여기서 멈춘다.

---

## Task 5: 소급 3건 (PR ① 머지 · VM 반영 후)

**성격:** 코드가 아니라 운영 작업이다.
전부 VM 운영 DB 에서 실행하며, 각 단계 앞에 덤프를 남긴다 (스펙 §12).

**선행 조건:** PR ① 머지 → VM `git pull --ff-only` → `git log --oneline -1` 로 반영 확인.

- [ ] **Step 1: 덤프를 뜬다**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17
cd ~/bullet-in
docker compose exec -T mariadb mariadb-dump -uroot -pbulletin bulletin \
  players article_players articles > ~/dump-before-player-pages-$(date +%Y%m%d).sql
wc -l ~/dump-before-player-pages-*.sql
```

- [ ] **Step 2: 오피셜 승격 소급 (6행)**

스펙 §8.1 의 `UPDATE` 를 그대로 쓴다.
`medical` 1행도 함께 `official` 이 되는데, 공홈이 발표했다는 뜻으로 값을 일관되게 유지하는 것이 스펙 의도다.

```bash
docker compose exec -T mariadb mariadb -uroot -pbulletin bulletin -e "
SELECT ap.stage, COUNT(*) FROM article_players ap
  JOIN articles a ON a.content_hash = ap.content_hash
 WHERE a.source_id = 'arsenal_official' GROUP BY 1;
UPDATE article_players ap JOIN articles a ON a.content_hash = ap.content_hash
   SET ap.stage = 'official'
 WHERE a.source_id = 'arsenal_official';
SELECT ap.stage, COUNT(*) FROM article_players ap
  JOIN articles a ON a.content_hash = ap.content_hash
 WHERE a.source_id = 'arsenal_official' GROUP BY 1;"
```

검증: 실행 후 `official` 6 · 다른 값 0.

- [ ] **Step 3: 보관 75행의 이적 축 갱신**

대상을 조건이 아니라 id 목록으로 고정한다 (런북 §3.2 의 교훈)
— 덤프와 갱신 사이에 새로 보관되는 행이 생겨도 함께 잡히지 않도록, 갱신은 파일에 고정된 id 로만 실행한다.

```bash
# VM 에서 — 대상 id 를 먼저 파일로 고정
uv run python - <<'PY'
import csv, os
from sqlalchemy import create_engine, text
e = create_engine(os.environ["MARIADB_URL"])
with e.connect() as c, open("archived_inlink_ids.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["id", "full_name", "transfer_status"])
    rows = c.execute(text("SELECT id, full_name, transfer_status FROM players "
                          "WHERE status='archived' AND transfer_status='in_link'")).all()
    for r in rows:
        w.writerow(r)
print("대상 덤프:", len(rows), "행")
PY
cat archived_inlink_ids.csv

# 그 파일의 id 로만 갱신한다
uv run python - <<'PY'
import csv, os
from sqlalchemy import bindparam, create_engine, text
e = create_engine(os.environ["MARIADB_URL"])
ids = [int(r["id"]) for r in csv.DictReader(open("archived_inlink_ids.csv"))]
with e.begin() as c:
    n = c.execute(text("UPDATE players SET transfer_status='none' WHERE id IN :ids")
                  .bindparams(bindparam("ids", expanding=True)), {"ids": ids}).rowcount
print("갱신:", n, "행")
PY

docker compose exec -T mariadb mariadb -uroot -pbulletin bulletin -e "
SELECT status, transfer_status, COUNT(*) FROM players GROUP BY 1,2 ORDER BY 1,2;"
```

검증: `archived` 행이 `none` 75 · `other_club` 3 만 남는다.
`confirmed` 행 분포는 변하지 않는다.

- [ ] **Step 4: 방향 dry-run (대조군 필수)**

런북 `2026-06-30-transfer-stage-classification-ops.md` §3.2 의 dry-run 절차를 쓴다.
DB 를 건드리지 않고 Gemini 를 1~3회 호출한다.

대상 38건에 **대조군 12건을 섞는다** — 아스날이 주체인 기사 중 단계가 서로 다른 것을 고른다 (`agreed` · `interest` · `negotiating` · `rumour` 각 3건).
새 문구가 정상 판정을 되돌리는 과교정을 여기서 잡는다 (#200 → #201 선례).

```bash
docker compose exec -T mariadb mariadb -uroot -pbulletin bulletin -N -e "
SELECT JSON_ARRAYAGG(JSON_OBJECT('content_hash', content_hash,
    'title_original', title_original, 'title_ko', title_ko,
    'summary_ko', summary_ko, 'transfer_stage', transfer_stage,
    'transfer_direction', transfer_direction, 'source_id', source_id))
FROM (
  SELECT * FROM articles
   WHERE transfer_direction IN ('in','out')
     AND title_original NOT LIKE '%rsenal%'
     AND COALESCE(title_ko,'') NOT LIKE '%아스날%'
     AND COALESCE(title_ko,'') NOT LIKE '%rsenal%'
     AND COALESCE(summary_ko,'') NOT LIKE '%아스날%'
     AND COALESCE(summary_ko,'') NOT LIKE '%rsenal%'
  UNION ALL
  (SELECT * FROM articles WHERE transfer_direction='in'
     AND COALESCE(title_ko,'') LIKE '%아스날%' AND transfer_stage='agreed' LIMIT 3)
  UNION ALL
  (SELECT * FROM articles WHERE transfer_direction='in'
     AND COALESCE(title_ko,'') LIKE '%아스날%' AND transfer_stage='interest' LIMIT 3)
  UNION ALL
  (SELECT * FROM articles WHERE transfer_direction='in'
     AND COALESCE(title_ko,'') LIKE '%아스날%' AND transfer_stage='negotiating' LIMIT 3)
  UNION ALL
  (SELECT * FROM articles WHERE transfer_direction='in'
     AND COALESCE(title_ko,'') LIKE '%아스날%' AND transfer_stage='rumour' LIMIT 3)
) t;" > ~/target_rows.json
```

로컬로 내려받아 분류만 돌린다.

```bash
scp -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17:~/target_rows.json .
set -a; source .env; set +a
uv run python - <<'PY'
import json, os
from google import genai
from bullet_in.enrich import classify_stage_rows
from bullet_in.run import GEMINI_MODEL
rows = json.load(open("target_rows.json"))
out = classify_stage_rows(rows, genai.Client(api_key=os.environ["GEMINI_API_KEY"]),
                          GEMINI_MODEL)
moved_stage = moved_dir = 0
for r in rows:
    new, direction = out.get(r["content_hash"], ("(누락)", "-"))
    s_mark = "S" if r["transfer_stage"] != new else " "
    d_mark = "D" if r["transfer_direction"] != direction else " "
    moved_stage += s_mark == "S"
    moved_dir += d_mark == "D"
    print(f'{s_mark}{d_mark} {r["content_hash"][:8]} '
          f'{r["transfer_stage"]:13s}→{new:13s} '
          f'{r["transfer_direction"]:4s}→{str(direction):4s} '
          f'{(r["title_ko"] or "")[:34]}')
print(f"단계 이동 {moved_stage} · 방향 이동 {moved_dir} / {len(rows)}")
PY
```

**판정 기준:**
- 대조군 12건의 **단계 이동 0 · 방향 이동 0** 이어야 한다.
하나라도 움직이면 과교정이므로 프롬프트를 고치고 다시 돌린다.
- 대상 38건은 **방향이 `none` 으로 이동**하고 **단계 분포는 기준선과 크게 다르지 않아야** 한다.
기준선 = `negotiating` 11 · `agreed` 9 · `interest` 8 · `rumour` 8 · `medical` 1 · `personal_terms` 1.
- 이동 내역을 유형별로 훑는다.
잔존 0 은 성공 신호가 아니다 (런북 §3.2).

- [ ] **Step 5: 표적 재분류 실행**

dry-run 이 판정 기준을 통과한 뒤에만 실행한다.
대상 해시를 CSV 로 떠 두고 그 파일을 기준으로 되돌린다 (런북 §3.2).

```bash
# VM 에서 — 대상 38건 해시 · 현재 값 덤프
uv run python - <<'PY'
import csv, os
from sqlalchemy import create_engine, text
e = create_engine(os.environ["MARIADB_URL"])
sql = ("SELECT content_hash, transfer_stage, transfer_direction FROM articles "
       "WHERE transfer_direction IN ('in','out') "
       "AND title_original NOT LIKE '%rsenal%' "
       "AND COALESCE(title_ko,'') NOT LIKE '%아스날%' "
       "AND COALESCE(title_ko,'') NOT LIKE '%rsenal%' "
       "AND COALESCE(summary_ko,'') NOT LIKE '%아스날%' "
       "AND COALESCE(summary_ko,'') NOT LIKE '%rsenal%'")
with e.connect() as c, open("stage_dump_direction.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["content_hash", "transfer_stage", "transfer_direction"])
    rows = c.execute(text(sql)).all()
    for r in rows:
        w.writerow(r)
print("대상 덤프:", len(rows), "행")
PY
```

되돌린 뒤 런북 `2026-07-19-enrich-only-pass.md` §3 의 분류 블록만 떼어 실행한다.

```bash
uv run python - <<'PY'
import csv, os
from sqlalchemy import bindparam, create_engine, text
e = create_engine(os.environ["MARIADB_URL"])
hashes = [r["content_hash"] for r in csv.DictReader(open("stage_dump_direction.csv"))]
with e.begin() as c:
    n = c.execute(text("UPDATE articles SET transfer_stage = NULL "
                       "WHERE content_hash IN :hs")
                  .bindparams(bindparam("hs", expanding=True)),
                  {"hs": hashes}).rowcount
print("NULL 복원:", n)
PY
```

- [ ] **Step 6: 수렴과 분포를 확인한다**

```bash
docker compose exec -T mariadb mariadb -uroot -pbulletin bulletin -e "
SELECT COUNT(*) stage_null FROM articles WHERE transfer_stage IS NULL;
SELECT transfer_direction, COUNT(*) FROM articles GROUP BY 1;
SELECT transfer_stage, COUNT(*) FROM articles GROUP BY 1 ORDER BY 2 DESC;"
```

**검증:**
- `stage_null` = 0.
0 이 아니면 분류 블록을 다시 돌린다 (최대 3회).
- 재분류 대상 38건 (`in` 31 · `out` 7) 의 방향이 `none` 으로 옮겨져 전체 분포가 `in` 266 · `none` 175 · `out` 35 근처가 된다.
- 단계 전체 분포가 재분류 전과 크게 다르지 않다.

- [ ] **Step 7: 결과를 기록한다**

이동 건수 · 대조군 판정 · 최종 분포를 세션 노트에 적는다.
PR ② 의 검증 절에서 이 수치를 참조한다.

---

# PR ② 서빙 계열

**선행 조건:** PR ① 머지 · Task 5 소급 완료.
브랜치는 갱신된 `origin/main` 에서 새로 딴다.

## Task 6: `PlayerStore` 선수 페이지 조회 3종

**Files:**
- Modify: `src/bullet_in/storage/players.py`
- Test: `tests/integration/test_player_store.py`

**Interfaces:**
- Produces:
```python
PlayerStore.page_players() -> list[dict]
    # [{"id": int, "full_name": str, "surname": str, "ko_name": str | None,
    #   "transfer_status": str}, ...]  — id 오름차순
PlayerStore.page_player_links() -> list[dict]
    # [{"player_id": int, "content_hash": str, "stage": str | None}, ...]
PlayerStore.linked_hashes() -> set[str]
    # article_players 에 한 행이라도 있는 content_hash 전체 (ops 표 · 대상 필터 무관)
```
- Task 7 이후가 이 셋에 의존한다.

**주의:** `page_players()` 와 `page_player_links()` 는 같은 술어를 공유해야 한다.
술어가 갈라지면 색인에 있는 선수의 기사가 비거나 그 반대가 된다.
모듈 상수 하나로 둔다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/integration/test_player_store.py` 끝에 추가한다.

```python
def _add_player(engine, *, full_name, surname, ko_name, category, status,
                transfer_status):
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO players (full_name,surname,ko_name,category,status,"
            "transfer_status,origin,added_at) VALUES "
            "(:fn,:sn,:ko,:cat,:st,:ts,'curated',NOW())"),
            {"fn": full_name, "sn": surname, "ko": ko_name, "cat": category,
             "st": status, "ts": transfer_status})
        return c.execute(text("SELECT id FROM players WHERE full_name=:fn"),
                         {"fn": full_name}).scalar_one()


def test_page_players_applies_target_condition(engine):
    store = PlayerStore(engine)
    keep = _add_player(engine, full_name="Target One", surname="One",
                       ko_name="타깃", category="external", status="confirmed",
                       transfer_status="in_link")
    staff = _add_player(engine, full_name="Boss Man", surname="Man",
                        ko_name="보스", category="manager", status="confirmed",
                        transfer_status="in_link")
    no_axis = _add_player(engine, full_name="Squad Guy", surname="Guy",
                          ko_name="스쿼드", category="squad", status="confirmed",
                          transfer_status="none")
    cand = _add_player(engine, full_name="Cand Idate", surname="Idate",
                       ko_name="후보", category="external", status="candidate",
                       transfer_status="in_link")
    archived_kept = _add_player(engine, full_name="Gone Elsewhere", surname="Elsewhere",
                                ko_name="타클럽", category="external",
                                status="archived", transfer_status="other_club")
    orphan = _add_player(engine, full_name="No Articles", surname="Articles",
                         ko_name="무기사", category="external", status="confirmed",
                         transfer_status="in_link")
    for pid in (keep, staff, no_axis, cand, archived_kept):
        store.link_article("a" * 64, pid, "interest")
    ids = {p["id"] for p in store.page_players()}
    assert keep in ids
    assert archived_kept in ids       # 사유가 값에 남은 보관 선수는 노출 (스펙 §3.1)
    assert staff not in ids           # 스태프 제외
    assert no_axis not in ids         # 이적 축 없음 제외
    assert cand not in ids            # 후보 제외 (승인된 이탈)
    assert orphan not in ids          # 귀속 기사 0건 제외


def test_page_player_links_shares_the_same_predicate(engine):
    store = PlayerStore(engine)
    keep = _add_player(engine, full_name="Link Target", surname="Target",
                       ko_name="대상", category="external", status="confirmed",
                       transfer_status="in_link")
    staff = _add_player(engine, full_name="Link Boss", surname="Boss",
                        ko_name="감독", category="manager", status="confirmed",
                        transfer_status="in_link")
    store.link_article("b" * 64, keep, "agreed")
    store.link_article("b" * 64, staff, "agreed")
    links = store.page_player_links()
    assert {l["player_id"] for l in links} == {keep}
    assert links[0]["stage"] == "agreed"
    assert links[0]["content_hash"] == "b" * 64


def test_linked_hashes_ignores_the_target_condition(engine):
    store = PlayerStore(engine)
    staff = _add_player(engine, full_name="Only Staff", surname="Staff",
                        ko_name="스태프", category="manager", status="confirmed",
                        transfer_status="none")
    store.link_article("c" * 64, staff, "rumour")
    # 추출은 됐으나 페이지 대상이 아닌 선수만 걸린 기사도 "추출 누락" 이 아니다
    assert "c" * 64 in store.linked_hashes()
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/integration/test_player_store.py -q`
Expected: FAIL — `AttributeError: 'PlayerStore' object has no attribute 'page_players'`
DB 가 없어 skip 되면 `docker compose up -d` 후 다시 돌린다.

- [ ] **Step 3: 구현한다**

`src/bullet_in/storage/players.py` 의 `_DICT_WHERE` 아래에 상수를 추가한다.

```python
# 선수 페이지 대상 술어 (스펙 §3.1 + 후보 제외 · 2026-08-03 사용자 확정)
# — 스태프 · 이적 얘기 없는 스쿼드 · 사유 없는 보관 · 미확정 후보가 여기서 빠진다.
_PAGE_WHERE = ("category IN ('squad','external') AND transfer_status <> 'none' "
               "AND status <> 'candidate'")
```

`confirm()` 위에 메서드 셋을 추가한다.

```python
    def page_players(self) -> list[dict]:
        """선수 페이지 대상 (스펙 §3.1) — 귀속 기사가 없는 선수는 뺀다.
        빈 페이지를 만들지 않기 위한 조건이며 page_player_links 와 술어를 공유한다."""
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(text(
                "SELECT id, full_name, surname, ko_name, transfer_status "
                f"FROM players WHERE {_PAGE_WHERE} AND EXISTS ("
                "SELECT 1 FROM article_players ap WHERE ap.player_id = players.id) "
                "ORDER BY id")).mappings().all()]

    def page_player_links(self) -> list[dict]:
        """대상 선수의 기사 귀속 전량 — (선수, 기사, 그 기사에서 그 선수의 단계)."""
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(text(
                "SELECT ap.player_id, ap.content_hash, ap.stage "
                "FROM article_players ap JOIN players p ON p.id = ap.player_id "
                f"WHERE {_PAGE_WHERE}")).mappings().all()]

    def linked_hashes(self) -> set[str]:
        """추출이 한 명이라도 붙인 기사 (ops 추출 누락 표의 여집합 · 스펙 §9).
        대상 술어를 걸지 않는다 — 스태프만 걸린 기사도 추출은 성공한 것이다."""
        with self.engine.connect() as c:
            return {r[0] for r in c.execute(text(
                "SELECT DISTINCT content_hash FROM article_players")).all()}
```

- [ ] **Step 4: 테스트 통과를 확인한다**

Run: `uv run pytest tests/integration/test_player_store.py -q`
Expected: PASS

- [ ] **Step 5: 커밋한다**

```bash
git add src/bullet_in/storage/players.py tests/integration/test_player_store.py
git commit -m "$(cat <<'EOF'
feat(serve): 선수 페이지 대상 조회를 저장소에 추가

선수 페이지가 사전 문자열 대조가 아니라 article_players 조인을 원천으로 쓰므로,
대상 선정과 귀속을 저장소에서 한 술어로 공급한다.

- page_players: 대상 조건 + 귀속 기사 1건 이상
- page_player_links: 같은 술어의 기사 귀속 · 선수별 단계 동반
- linked_hashes: 추출 성공 기사 집합 (ops 누락 표의 여집합)
- 술어 단일화: 색인과 기사 목록이 어긋나지 않게 모듈 상수 공유

Refs: docs/superpowers/specs/2026-08-03-serve-player-pages-resume-design.md §3.1 · §9
EOF
)"
```

---

## Task 7: 배지 · 그룹 · slug · 전이 타임라인 (순수 함수)

**Files:**
- Modify: `src/bullet_in/serve/render.py`
- Test: `tests/test_serve_players.py` (신규)

**Interfaces:**
- Consumes: `render.display_stage(enum) -> dict | None` · `render._sort_ts(row) -> tuple[datetime, datetime]` (기존).
- Produces:
```python
render.transfer_badge(status: str) -> dict | None      # {"label": str, "cls": str}
render.transfer_group(status: str) -> str | None       # "진행 중" | "성사" | "무산과 종료"
render.TRANSFER_GROUPS: list[tuple[str, bool]]         # [(그룹명, 기본 접힘), ...]
render.player_slug(surname: str, player_id: int, dupes: set[str]) -> str
render.stage_timeline(entries: list[dict]) -> list[dict]
```
- Task 8 · 9 가 이 다섯에 의존한다.

**`stage_timeline` 계약:** 입력은 오래된 것부터 정렬된 `[{"row": dict, "stage": str | None}, ...]`.
출력은 **최신 노드가 앞**인 `[{"row": dict, "stage": str, "follow": int}, ...]`.
`other` 와 빈 값은 노드를 만들지 않고 `follow` 도 올리지 않는다.
직전 노드와 단계가 같으면 새 노드 대신 그 노드의 `follow` 를 1 올린다.
역행은 그대로 새 노드가 된다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_serve_players.py` 를 새로 만든다.

```python
"""선수 색인 · 선수 페이지 순수 함수 단위 테스트 (스펙 §4 · §5)."""
from datetime import datetime
from bullet_in.serve.render import (TRANSFER_GROUPS, player_slug, stage_timeline,
                                    transfer_badge, transfer_group)

NOW = datetime(2026, 7, 10, 12, 0)
SOURCES = {"bbc_sport": {"display_name": "BBC Sport", "serving": "full"}}


def _row(day: int, h: str = "h1"):
    """전이 판정용 최소 행 — stage_timeline 은 순서만 쓰고 정렬 키를 읽지 않는다."""
    return {"content_hash": h, "published_at": datetime(2026, 7, day, 12, 0)}


def test_transfer_badge_covers_all_eight_values():
    values = ["in_link", "out_link", "in_done", "out_done",
              "loan_in", "loan_out", "link_dropped", "other_club"]
    labels = [transfer_badge(v)["label"] for v in values]
    assert labels == ["영입 링크", "방출 링크", "영입 완료", "방출 완료",
                      "임대 영입", "임대 이적", "링크 소멸", "타 클럽행"]


def test_transfer_badge_is_none_for_no_axis():
    assert transfer_badge("none") is None
    assert transfer_badge("") is None


def test_transfer_group_splits_eight_values_without_gap():
    assert transfer_group("in_link") == "진행 중"
    assert transfer_group("out_link") == "진행 중"
    for v in ("in_done", "out_done", "loan_in", "loan_out"):
        assert transfer_group(v) == "성사"
    for v in ("link_dropped", "other_club"):
        assert transfer_group(v) == "무산과 종료"
    assert transfer_group("none") is None


def test_transfer_groups_order_and_collapse_flag():
    assert [g for g, _ in TRANSFER_GROUPS] == ["진행 중", "성사", "무산과 종료"]
    assert [c for _, c in TRANSFER_GROUPS] == [False, False, True]


def test_player_slug_is_lowercased_surname():
    assert player_slug("Tzolis", 12, set()) == "tzolis"
    assert player_slug("Gibbs-White", 7, set()) == "gibbswhite"


def test_player_slug_falls_back_to_surname_id_on_collision():
    dupes = {"vieira"}
    assert player_slug("Vieira", 41, dupes) == "vieira-41"
    assert player_slug("Vieira", 88, dupes) == "vieira-88"


def test_stage_timeline_makes_node_only_when_stage_changes():
    entries = [{"row": _row(1), "stage": "rumour"},
               {"row": _row(2), "stage": "rumour"},
               {"row": _row(3), "stage": "interest"}]
    nodes = stage_timeline(entries)
    assert [n["stage"] for n in nodes] == ["interest", "rumour"]   # 최신 우선
    assert nodes[1]["follow"] == 1                                  # 같은 단계 1건 접힘
    assert nodes[0]["follow"] == 0


def test_stage_timeline_skips_other_and_blank():
    entries = [{"row": _row(1), "stage": "other"},
               {"row": _row(2), "stage": None},
               {"row": _row(3), "stage": "agreed"}]
    nodes = stage_timeline(entries)
    assert [n["stage"] for n in nodes] == ["agreed"]
    assert nodes[0]["follow"] == 0            # other · 빈 값은 follow 도 올리지 않는다


def test_stage_timeline_keeps_regression_as_its_own_node():
    entries = [{"row": _row(1), "stage": "agreed"},
               {"row": _row(2), "stage": "rumour"}]
    nodes = stage_timeline(entries)
    assert [n["stage"] for n in nodes] == ["rumour", "agreed"]


def test_stage_timeline_is_empty_when_no_article_has_a_stage():
    assert stage_timeline([{"row": _row(1), "stage": "other"}]) == []
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_serve_players.py -q`
Expected: FAIL — ImportError

- [ ] **Step 3: 구현한다**

`src/bullet_in/serve/render.py` 의 `load_clubs` 위 (선수 관련 함수가 모이는 자리) 에 추가한다.

```python
# ── 선수 페이지 (스펙 §4 · §5) ─────────────────────────────────────────
# 선수 단위 이적 축 배지 — players 스펙 §3.1 의 화면 배지 열을 그대로 옮긴다.
# 기사 단위 transfer_direction 은 이 화면에서 쓰지 않는다 (스펙 §4.2).
_TRANSFER_BADGE: dict[str, tuple[str, str]] = {
    "in_link": ("영입 링크", "t-inlink"),
    "out_link": ("방출 링크", "t-outlink"),
    "in_done": ("영입 완료", "t-indone"),
    "out_done": ("방출 완료", "t-outdone"),
    "loan_in": ("임대 영입", "t-loanin"),
    "loan_out": ("임대 이적", "t-loanout"),
    "link_dropped": ("링크 소멸", "t-dropped"),
    "other_club": ("타 클럽행", "t-otherclub"),
}

# 색인 3그룹 (스펙 §4.1) — (그룹명, 기본 접힘). 무산 그룹은 되짚기용이라 접어 둔다.
TRANSFER_GROUPS: list[tuple[str, bool]] = [
    ("진행 중", False), ("성사", False), ("무산과 종료", True),
]

_TRANSFER_GROUP_OF: dict[str, str] = {
    "in_link": "진행 중", "out_link": "진행 중",
    "in_done": "성사", "out_done": "성사", "loan_in": "성사", "loan_out": "성사",
    "link_dropped": "무산과 종료", "other_club": "무산과 종료",
}


def transfer_badge(status: str | None) -> dict | None:
    """선수 이적 축 배지 {label, cls}. 축이 없으면 (none) 배지를 달지 않는다."""
    d = _TRANSFER_BADGE.get(status or "")
    return {"label": d[0], "cls": d[1]} if d else None


def transfer_group(status: str | None) -> str | None:
    """색인 그룹명. 여덟 값이 3그룹으로 빠짐없이 갈린다."""
    return _TRANSFER_GROUP_OF.get(status or "")


def player_slug(surname: str, player_id: int, dupes: set[str]) -> str:
    """선수 페이지 slug — 소문자 영문 성. 동성 복수면 surname-id 로 떨어뜨린다."""
    base = re.sub(r"[^a-z0-9]", "", (surname or "").lower()) or "player"
    return f"{base}-{player_id}" if base in dupes else base


def stage_timeline(entries: list[dict]) -> list[dict]:
    """단계 전이 노드 (스펙 §5.2) — 직전과 값이 달라진 기사만 노드로 만든다.

    입력은 오래된 것부터 정렬된 [{"row", "stage"}], 출력은 최신 노드가 앞이다.
    같은 단계로 이어진 기사는 노드의 follow 로 접고, other · 빈 값은 배지 대상이
    아니므로 노드도 follow 도 만들지 않는다.
    역행은 그대로 새 노드가 된다 — 딜이 틀어진 것인지 오분류인지 화면에서 가릴 수
    없으므로 지어내지 않는다 (최고 도달 단계로 고정하면 링크가 소멸한 선수의 배지가
    이적 합의로 남는 모순이 생긴다)."""
    nodes: list[dict] = []
    for e in entries:
        stage = e.get("stage")
        if not _stage.is_displayable(stage):
            continue
        if nodes and nodes[-1]["stage"] == stage:
            nodes[-1]["follow"] += 1
            continue
        nodes.append({"row": e["row"], "stage": stage, "follow": 0})
    return list(reversed(nodes))
```

`render.py` 상단 import 에 `transfer_stage` 가 `_stage` 로 들어와 있는지 확인한다.
없으면 `from bullet_in import transfer_stage as _stage` 를 추가한다.

- [ ] **Step 4: 테스트 통과를 확인한다**

Run: `uv run pytest tests/test_serve_players.py -q`
Expected: PASS

- [ ] **Step 5: 커밋한다**

```bash
git add src/bullet_in/serve/render.py tests/test_serve_players.py
git commit -m "$(cat <<'EOF'
feat(serve): 선수 색인 배지 · 그룹 · slug · 전이 타임라인 함수

선수 색인과 선수 페이지가 공유할 순수 함수를 먼저 세운다. 화면 조립은 다음
커밋이 맡고 여기서는 판정 규칙만 고정한다.

- 배지: 이적 축 여덟 값을 화면 문구로 (players 스펙 §3.1 열 그대로)
- 그룹: 여덟 값을 3그룹으로 빠짐없이 배정 · 무산 그룹은 기본 접힘
- slug: 소문자 성 · 동성 복수면 surname-id
- 전이 타임라인: 값이 바뀐 기사만 노드 · 같은 단계는 접기 · 역행 보존

Refs: docs/superpowers/specs/2026-08-03-serve-player-pages-resume-design.md §4 · §5.2
EOF
)"
```

---

## Task 8: 선수 색인 · 선수 페이지 조립

**Files:**
- Modify: `src/bullet_in/serve/render.py`
- Create: `src/bullet_in/serve/templates/players.html.j2`
- Create: `src/bullet_in/serve/templates/player.html.j2`
- Modify: `src/bullet_in/serve/templates/_layout.html.j2`
- Test: `tests/test_serve_players.py`

**Interfaces:**
- Consumes: Task 6 의 `page_players()` · `page_player_links()` · Task 7 의 다섯 함수.
- Produces:
```python
render.load_page_players(engine=None) -> list[dict]
    # [{"id","full_name","surname","ko_name","transfer_status",
    #   "name","slug","links":[{"content_hash","stage"}]}, ...]
render.build_player_entries(articles: list[dict], players: list[dict]) -> list[dict]
    # 각 entry 에 "articles" (최신순) · "timeline" · "stage" · "count" · "last_ts" 추가
    # 귀속 기사가 서빙 목록에 하나도 없는 선수는 결과에서 빠진다
render.render_players(entries, now) -> str
render.render_player(entry, sources, now, directory=None, outlet_dir=None) -> str
```

**표시 이름:** `ko_name` 이 있으면 그것, 없으면 `full_name` 을 쓴다.
밤바처럼 확정 표기가 아직 없는 보관 선수가 실제로 있다.

**`load_page_players` 의 engine 기본값:** `load_player_names()` 와 같은 방식으로 `MARIADB_URL` 에서 만든다.
`write_site()` 시그니처를 넓히지 않기 위한 기존 선례다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_serve_players.py` 에 추가한다.

```python
from bullet_in.serve.render import build_player_entries


def _art(h, day, stage=None, title="제목"):
    """서빙 행 — tests/test_serve_render.py 의 _row 와 같은 컬럼 구성을 따른다.
    _decorate 가 url · image_url · tier 를 읽으므로 빠뜨리면 렌더 테스트가 깨진다."""
    return {"content_hash": h, "url": f"https://x/{h}", "source_id": "bbc_sport",
            "title_original": title, "title_ko": title, "summary_ko": "한 줄 요약",
            "tier": 2, "confidence_score": 0.5, "image_url": None, "outlet": None,
            "team": "arsenal", "transfer_stage": stage,
            "published_at": datetime(2026, 7, day, 12, 0)}


def _player(pid, surname, ko, status, links):
    """links = [{"content_hash", "stage"}] — page_player_links 반환 형태."""
    return {"id": pid, "full_name": f"{ko} {surname}", "surname": surname,
            "ko_name": ko, "transfer_status": status, "links": links}


def test_build_player_entries_orders_articles_newest_first():
    arts = [_art("h1", 1, "rumour"), _art("h2", 5, "interest")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"},
                        {"content_hash": "h2", "stage": "interest"}])]
    [e] = build_player_entries(arts, players)
    assert [a["content_hash"][:1] for a in e["articles"]] == ["b", "a"]
    assert e["count"] == 2


def test_build_player_entries_header_count_matches_article_list():
    # draft 리뷰에서 실제로 잡혔던 결함 — 단계 없는 기사도 목록에 든다 (스펙 §5.3)
    arts = [_art("h1", 1, "rumour"), _art("h2", 2, None), _art("h3", 3, "other")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"},
                        {"content_hash": "h2", "stage": None},
                        {"content_hash": "h3", "stage": "other"}])]
    [e] = build_player_entries(arts, players)
    assert e["count"] == len(e["articles"]) == 3
    assert [n["stage"] for n in e["timeline"]] == ["rumour"]


def test_build_player_entries_current_stage_is_latest_node():
    arts = [_art("h1", 1, "agreed"), _art("h2", 5, "rumour")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "agreed"},
                        {"content_hash": "h2", "stage": "rumour"}])]
    [e] = build_player_entries(arts, players)
    assert e["stage"] == "rumour"          # 역행이어도 최신 노드 값


def test_build_player_entries_has_no_stage_when_all_other():
    arts = [_art("h1", 1, "other")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "other"}])]
    [e] = build_player_entries(arts, players)
    assert e["stage"] is None


def test_build_player_entries_drops_player_with_no_serving_article():
    # DB 에는 귀속이 있으나 서빙 목록에 그 기사가 없는 경우 (빈 페이지 방지)
    players = [_player(1, "Ghost", "고스트", "in_link",
                       [{"content_hash": "h9", "stage": "rumour"}])]
    assert build_player_entries([_art("h1", 1, "rumour")], players) == []


def test_build_player_entries_disambiguates_same_surname():
    arts = [_art("h1", 1, "rumour")]
    players = [_player(1, "Vieira", "비에이라", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"}]),
               _player(2, "Vieira", "파트리크 비에이라", "other_club",
                       [{"content_hash": "h1", "stage": "rumour"}])]
    slugs = [e["slug"] for e in build_player_entries(arts, players)]
    assert sorted(slugs) == ["vieira-1", "vieira-2"]


def test_build_player_entries_falls_back_to_full_name():
    arts = [_art("h1", 1, "rumour")]
    players = [{"id": 1, "full_name": "Aladji Bamba", "surname": "Bamba",
                "ko_name": None, "transfer_status": "other_club",
                "links": [{"content_hash": "h1", "stage": "rumour"}]}]
    [e] = build_player_entries(arts, players)
    assert e["name"] == "Aladji Bamba"
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_serve_players.py -q`
Expected: FAIL — ImportError: cannot import name 'build_player_entries'

- [ ] **Step 3: 로더와 조립 함수를 구현한다**

`render.py` 의 Task 7 블록 아래에 추가한다.

```python
def load_page_players(engine=None) -> list[dict]:
    """선수 페이지 대상 + 귀속 (스펙 §3.1) — DB 단일 원천.
    engine 미지정 시 MARIADB_URL 로 생성한다 — write_site 호출부 (run.py · 런북) 는
    이미 그 env 로 돌므로 시그니처 연쇄 변경 없이 전환된다 (load_player_names 선례)."""
    from sqlalchemy import create_engine
    from bullet_in.storage.players import PlayerStore
    store = PlayerStore(engine or create_engine(os.environ["MARIADB_URL"]))
    players = store.page_players()
    links: dict[int, list[dict]] = {}
    for l in store.page_player_links():
        links.setdefault(l["player_id"], []).append(
            {"content_hash": l["content_hash"], "stage": l["stage"]})
    for p in players:
        p["links"] = links.get(p["id"], [])
    return players


def build_player_entries(articles: list[dict], players: list[dict]) -> list[dict]:
    """선수별 기사 목록 · 전이 타임라인 · 현재 단계 (스펙 §5).

    기사 목록은 귀속 전량이다 — 단계 없는 기사도 포함한다.
    머리의 건수와 목록 수가 어긋나지 않게 하기 위한 것이며 draft 리뷰에서 실제로
    잡혔던 결함이다 (스펙 §5.3). 서빙 목록에 없는 기사는 링크에서 빠지고, 그 결과
    남는 기사가 0건인 선수는 빈 페이지가 되지 않도록 결과에서 제외한다."""
    by_hash = {a["content_hash"]: a for a in articles}
    folded = {p["id"]: re.sub(r"[^a-z0-9]", "", (p.get("surname") or "").lower())
              for p in players}
    counts = Counter(folded.values())
    dupes = {s for s, n in counts.items() if n > 1}
    out = []
    for p in players:
        paired = [(by_hash[l["content_hash"]], l["stage"]) for l in p["links"]
                  if l["content_hash"] in by_hash]
        if not paired:
            continue
        paired.sort(key=lambda t: _sort_ts(t[0]))          # 오래된 것부터 (전이 판정)
        timeline = stage_timeline([{"row": r, "stage": s} for r, s in paired])
        slug = player_slug(p.get("surname") or "", p["id"], dupes)
        if folded[p["id"]] in dupes:
            log.warning("동성 복수 — slug 를 id 로 떨어뜨림: %s → %s",
                        p["full_name"], slug)
        out.append({**p,
                    "name": p.get("ko_name") or p["full_name"],
                    "slug": slug,
                    "articles": [r for r, _ in reversed(paired)],
                    "timeline": timeline,
                    "stage": timeline[0]["stage"] if timeline else None,
                    "count": len(paired),
                    "last_ts": _sort_ts(paired[-1][0])[0]})
    return out
```

`render.py` 상단에 `from collections import Counter` 가 이미 있는지 확인한다 (`facet_counts` 가 쓰므로 있을 것이다).

- [ ] **Step 4: 테스트 통과를 확인한다**

Run: `uv run pytest tests/test_serve_players.py -q`
Expected: PASS

- [ ] **Step 5: 렌더 함수와 템플릿을 만든다**

`render.py` 에 추가한다.

```python
def render_players(entries: list[dict], now: datetime) -> str:
    """선수 색인 (스펙 §4) — 3그룹 · 그룹 안 최근 보도일 내림차순."""
    groups = []
    for name, collapsed in TRANSFER_GROUPS:
        members = [e for e in entries if transfer_group(e["transfer_status"]) == name]
        members.sort(key=lambda e: e["last_ts"], reverse=True)
        for e in members:
            e["_badge"] = transfer_badge(e["transfer_status"])
            e["_stage"] = display_stage(e["stage"])
            e["_last"] = fmt_date(to_kst(e["last_ts"]))
        groups.append({"name": name, "collapsed": collapsed, "members": members})
    return _env().get_template("players.html.j2").render(
        groups=groups, active="players", root="", solo=True)


def render_player(entry: dict, sources: dict, now: datetime,
                  directory: dict | None = None,
                  outlet_dir: dict | None = None) -> str:
    """선수 페이지 (스펙 §5) — 머리 · 전이 타임라인 · 귀속 기사 전량."""
    decorated = {}
    for a in entry["articles"]:
        d = _decorate(a, sources, now, directory=directory, outlet_dir=outlet_dir)
        # _decorate 의 _date 는 UTC 라 타임라인 · 카드가 머리와 다른 날짜로 보일 수
        # 있다 — 선수 페이지 지역 범위로만 KST 로 보정한다.
        d["_kdate"] = fmt_date(to_kst(_sort_ts(a)[0]))
        decorated[a["content_hash"]] = d
    nodes = [{"a": decorated[n["row"]["content_hash"]],
              "badge": display_stage(n["stage"]), "follow": n["follow"]}
             for n in entry["timeline"]]
    return _env().get_template("player.html.j2").render(
        e=entry, badge=transfer_badge(entry["transfer_status"]),
        stage=display_stage(entry["stage"]), nodes=nodes,
        articles=[decorated[a["content_hash"]] for a in entry["articles"]],
        last=fmt_date(to_kst(entry["last_ts"])),
        active="players", root="../", solo=True)
```

`src/bullet_in/serve/templates/players.html.j2` 를 만든다.

```jinja
{% extends "_layout.html.j2" %}
{% block title %}선수 · Bullet-in{% endblock %}
{% block content %}
<div class="sechead"><h2>선수</h2><span class="kst">이적 축별 · 최근 보도순</span></div>
{% for g in groups %}{% if g.members %}
<div class="plgrp{{ ' folded' if g.collapsed }}" data-group="{{ g.name }}">
  <h3 class="plgroup">{{ g.name }} <span class="ct">{{ g.members|length }}</span>
    {% if g.collapsed %}<button class="plfold" type="button">펼치기</button>{% endif %}
  </h3>
  <div class="playerlist">
  {% for e in g.members %}
    <a class="pcard" href="player/{{ e.slug }}.html">
      <span class="pname">{{ e.name }}</span>
      {% if e._badge %}<span class="tbadge {{ e._badge.cls }}">{{ e._badge.label }}</span>{% endif %}
      {% if e._stage %}<span class="stage {{ e._stage.tone }}{{ ' filled' if e._stage.filled }}">{{ e._stage.label }}</span>{% endif %}
      <span class="pmeta">기사 {{ e.count }}건 · 최근 {{ e._last }}</span>
    </a>
  {% endfor %}
  </div>
</div>
{% endif %}{% endfor %}
{% endblock %}
```

`src/bullet_in/serve/templates/player.html.j2` 를 만든다.

```jinja
{% extends "_layout.html.j2" %}
{% from "_cards.html.j2" import card with context %}
{% block title %}{{ e.name }} · Bullet-in{% endblock %}
{% block content %}
<div class="phead">
  <h2>{{ e.name }}</h2>
  {% if badge %}<span class="tbadge {{ badge.cls }}">{{ badge.label }}</span>{% endif %}
  {% if stage %}<span class="stage {{ stage.tone }}{{ ' filled' if stage.filled }}">{{ stage.label }}</span>{% endif %}
  <span class="pmeta">기사 {{ e.count }}건 · 최근 보도 {{ last }}</span>
</div>
{% if nodes %}
<div class="sechead"><h2>단계 흐름</h2></div>
<div class="timeline">
  {% for n in nodes %}
  <div class="tlnode">
    <span class="tldate">{{ n.a._kdate }}</span>
    {% if n.badge %}<span class="stage {{ n.badge.tone }}{{ ' filled' if n.badge.filled }}">{{ n.badge.label }}</span>{% endif %}
    <a class="tltitle" href="{{ root }}article/{{ n.a.content_hash }}.html">{{ n.a._title }}</a>
    <span class="tlsrc">{{ n.a._outlet }}</span>
    {% if n.follow %}<span class="tlmore">이후 {{ n.follow }}건</span>{% endif %}
  </div>
  {% endfor %}
</div>
{% endif %}
<div class="sechead"><h2>기사</h2><span class="kst">{{ e.count }}건</span></div>
<div class="daylist plist">
  {% for a in articles %}<div class="block">{{ card(a, thumb=True, when=a._kdate, show_all=True) }}</div>{% endfor %}
</div>
{% endblock %}
```

`_layout.html.j2` 에 네비 항목과 `solo` 처리를 넣는다 (draft 그대로).

```jinja
    <a class="{{ 'active' if active == 'all' else '' }}" href="{{ root }}all.html">전체 기사</a>
    <a class="{{ 'active' if active == 'players' else '' }}" href="{{ root }}players.html">선수</a>
```

같은 파일의 `shell` 줄과 사이드바 조건을 바꾼다.

```jinja
<div class="shell{{ ' solo' if about_page or solo }}">
  {% if not about_page and not solo %}
```

- [ ] **Step 6: 렌더 스모크 테스트를 추가한다**

`tests/test_serve_players.py` 에 추가한다.

```python
from bullet_in.serve.render import render_player, render_players


def test_render_players_groups_and_collapses():
    arts = [_art("h1", 1, "rumour"), _art("h2", 2, "agreed")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"}]),
               _player(2, "Nduka", "은두카", "other_club",
                       [{"content_hash": "h2", "stage": "agreed"}])]
    html = render_players(build_player_entries(arts, players), datetime(2026, 7, 6))
    assert "진행 중" in html and "무산과 종료" in html
    assert "성사" not in html                     # 빈 그룹은 그리지 않는다
    assert 'href="player/tzolis.html"' in html
    assert "folded" in html                       # 무산 그룹 기본 접힘
    assert 'class="side"' not in html             # 사이드바 제외 (스펙 §5.3)


def test_render_player_shows_timeline_and_full_list():
    arts = [_art("h1", 1, "rumour", "촐리스 관심"), _art("h2", 2, "rumour", "촐리스 재보도"),
            _art("h3", 3, None, "촐리스 단계 없음")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"},
                        {"content_hash": "h2", "stage": "rumour"},
                        {"content_hash": "h3", "stage": None}])]
    [e] = build_player_entries(arts, players)
    html = render_player(e, {}, datetime(2026, 7, 6))
    assert "기사 3건" in html
    assert "이후 1건" in html                     # 같은 단계 연속 접힘
    assert "촐리스 단계 없음" in html              # 단계 없는 기사도 목록에
```

- [ ] **Step 7: 테스트 통과를 확인한다**

Run: `uv run pytest tests/test_serve_players.py tests/test_serve_layout.py -q`
Expected: PASS

- [ ] **Step 8: 커밋한다**

```bash
git add src/bullet_in/serve/render.py src/bullet_in/serve/templates/ \
        tests/test_serve_players.py
git commit -m "$(cat <<'EOF'
feat(serve): 선수 색인 · 선수 페이지 화면

이적 축이 있는 선수를 3그룹으로 모아 보여 주고, 선수마다 단계가 바뀐 지점과
귀속 기사 전량을 한 페이지에 담는다.

- 색인: 진행 중 · 성사 · 무산과 종료 · 무산은 기본 접힘 · 그룹 안 최근 보도순
- 선수 페이지: 머리 · 전이 타임라인 · 기사 전량 평면 목록
- 건수 일치: 단계 없는 기사도 목록에 포함해 머리 건수와 어긋나지 않게
- 사이드바 제외: 전역 집계가 선수 부분집합과 어긋나 혼동을 부르므로
- 네비: 헤더에 선수 항목 추가

Refs: docs/superpowers/specs/2026-08-03-serve-player-pages-resume-design.md §4 · §5
EOF
)"
```

---

## Task 9: `write_site` 통합 · 고아 정리

**Files:**
- Modify: `src/bullet_in/serve/render.py` (`write_site`)
- Test: `tests/test_serve_players.py`

**Interfaces:**
- Consumes: Task 8 의 `load_page_players` · `build_player_entries` · `render_players` · `render_player`.
- Produces: `site/players.html` · `site/player/<slug>.html`.

**고아 정리 가드:** 조회가 0건으로 돌아오면 삭제를 건너뛴다 (스펙 §5.4).
조회 실패로 기존 선수 페이지를 전부 지우던 결함이 draft 리뷰에서 잡혔다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_write_player_pages_removes_orphans(tmp_path):
    from bullet_in.serve.render import write_player_pages
    (tmp_path / "player").mkdir()
    (tmp_path / "player" / "gone.html").write_text("낡음", encoding="utf-8")
    arts = [_art("h1", 1, "rumour")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"}])]
    entries = build_player_entries(arts, players)
    write_player_pages(entries, {}, tmp_path, datetime(2026, 7, 6))
    assert (tmp_path / "player" / "tzolis.html").exists()
    assert not (tmp_path / "player" / "gone.html").exists()
    assert (tmp_path / "players.html").exists()


def test_write_player_pages_skips_delete_when_no_entries(tmp_path):
    from bullet_in.serve.render import write_player_pages
    (tmp_path / "player").mkdir()
    (tmp_path / "player" / "keep.html").write_text("기존", encoding="utf-8")
    write_player_pages([], {}, tmp_path, datetime(2026, 7, 6))
    assert (tmp_path / "player" / "keep.html").exists()   # 조회 0건은 오삭제 방어
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_serve_players.py -q`
Expected: FAIL — ImportError: cannot import name 'write_player_pages'

- [ ] **Step 3: 구현한다**

`render.py` 에 추가한다.

```python
def write_player_pages(entries: list[dict], sources: dict, out_dir: str | Path,
                       now: datetime, directory: dict | None = None,
                       outlet_dir: dict | None = None) -> None:
    """선수 색인 · 선수 페이지 생성과 고아 정리.

    대상 0건이면 삭제를 건너뛴다 — DB 조회 실패와 구분할 수 없어, 조회가 비면
    기존 선수 페이지를 전부 지우게 된다 (draft 리뷰에서 잡힌 결함 · 스펙 §5.4)."""
    out = Path(out_dir)
    (out / "player").mkdir(parents=True, exist_ok=True)
    (out / "players.html").write_text(render_players(entries, now), encoding="utf-8")
    keep = set()
    for e in entries:
        keep.add(f"{e['slug']}.html")
        (out / "player" / f"{e['slug']}.html").write_text(
            render_player(e, sources, now, directory=directory, outlet_dir=outlet_dir),
            encoding="utf-8")
    if not entries:
        log.warning("선수 페이지 정리 건너뜀 — 대상 0건 (DB 조회 실패 가능성)")
        return
    removed = [p for p in (out / "player").glob("*.html") if p.name not in keep]
    for p in removed:
        p.unlink()
    if removed:
        log.info("선수 페이지 %d건 삭제 (대상에서 빠진 선수)", len(removed))
```

`write_site` 의 `about.html` 생성 직후에 배선한다.

```python
    (out / "about.html").write_text(render_about(), encoding="utf-8")

    entries = build_player_entries(articles, load_page_players())
    write_player_pages(entries, sources, out, now, directory=directory,
                       outlet_dir=outlet_dir)
```

- [ ] **Step 4: 테스트 통과를 확인한다**

Run: `uv run pytest tests/test_serve_players.py -q`
Expected: PASS

- [ ] **Step 5: 전체 테스트를 돌린다**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 6: 커밋한다**

```bash
git add src/bullet_in/serve/render.py tests/test_serve_players.py
git commit -m "$(cat <<'EOF'
feat(serve): 선수 페이지를 사이트 생성에 배선

렌더 함수를 write_site 에 연결해 정기 회차마다 색인과 선수 페이지가 함께
만들어지게 한다.

- 배선: about 생성 직후 색인 · 선수 페이지 일괄 생성
- 고아 정리: 대상에서 빠진 선수 페이지 삭제
- 오삭제 방어: 대상 0건이면 삭제를 건너뛰고 경고만 남김

Refs: docs/superpowers/specs/2026-08-03-serve-player-pages-resume-design.md §5.4
EOF
)"
```

---

## Task 10: 기사 상세 선수 칩

**Files:**
- Modify: `src/bullet_in/serve/render.py` (`render_article` · `write_site`)
- Modify: `src/bullet_in/serve/templates/detail.html.j2`
- Test: `tests/test_serve_players.py`

**Interfaces:**
- Consumes: Task 8 의 entries.
- Produces: `render.player_chips(entries) -> dict[str, list[dict]]` — `content_hash` → `[{"name","slug"}]`.

**규칙 (스펙 §6):** 칩은 §3.1 조건을 통과해 페이지가 실제로 만들어진 선수만 노출한다.
사카처럼 페이지가 없는 선수에게 칩을 달면 죽은 링크가 된다.
목록 카드에는 칩을 넣지 않는다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_player_chips_only_include_players_with_pages():
    from bullet_in.serve.render import player_chips
    arts = [_art("h1", 1, "rumour")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"}])]
    chips = player_chips(build_player_entries(arts, players))
    assert chips["h1"] == [{"name": "촐리스", "slug": "tzolis"}]


def test_player_chips_are_empty_for_unlinked_article():
    from bullet_in.serve.render import player_chips
    arts = [_art("h1", 1, "rumour"), _art("h2", 2, "rumour")]
    players = [_player(1, "Tzolis", "촐리스", "in_link",
                       [{"content_hash": "h1", "stage": "rumour"}])]
    assert player_chips(build_player_entries(arts, players)).get("h2") is None
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_serve_players.py -q`
Expected: FAIL — ImportError

- [ ] **Step 3: 구현한다**

`render.py` 에 추가한다.

```python
def player_chips(entries: list[dict]) -> dict[str, list[dict]]:
    """기사 → 그 기사에 걸린 선수 칩 (스펙 §6). 페이지가 만들어진 선수만 담는다
    — 페이지 없는 선수에게 칩을 달면 죽은 링크가 된다."""
    out: dict[str, list[dict]] = {}
    for e in entries:
        for a in e["articles"]:
            out.setdefault(a["content_hash"], []).append(
                {"name": e["name"], "slug": e["slug"]})
    return out
```

`render_article` 에 인자를 더한다 (기본값 `None` 으로 하위 호환 유지).

```python
def render_article(article: dict, neighbors: list[dict], current_hash: str,
                   sources: dict, now: datetime, facets: dict | None = None,
                   chips: list[dict] | None = None) -> str:
```

같은 함수의 `render(...)` 호출에 `chips=chips or []` 를 넘긴다.

`write_site` 의 상세 루프에 배선한다.

```python
    chips_map = player_chips(entries)
    for idx, row in enumerate(ordered):
        ...
        html = render_article(a, neighbors, row["content_hash"], sources, now,
                              facets=facets, chips=chips_map.get(row["content_hash"]))
```

`detail.html.j2` 의 본문 블록 앞 (제목 · 메타 아래) 에 칩을 넣는다.

```jinja
{% if chips %}
<div class="pchips">
  {% for c in chips %}<a class="pchip" href="{{ root }}player/{{ c.slug }}.html">{{ c.name }}</a>{% endfor %}
</div>
{% endif %}
```

- [ ] **Step 4: 테스트 통과를 확인한다**

Run: `uv run pytest tests/test_serve_players.py tests/test_serve_render.py -q`
Expected: PASS

- [ ] **Step 5: 커밋한다**

```bash
git add src/bullet_in/serve/render.py src/bullet_in/serve/templates/detail.html.j2 \
        tests/test_serve_players.py
git commit -m "$(cat <<'EOF'
feat(serve): 기사 상세에 연결 선수 칩

기사에서 선수 페이지로 가는 경로를 만든다. article_players 를 그대로 읽으므로
추가 계산이 없다.

- 칩 노출: 페이지가 실제로 만들어진 선수만 (죽은 링크 방지)
- 위치: 상세 페이지만 · 목록 카드에는 넣지 않음 (링크 선수 배지와 중복)

Refs: docs/superpowers/specs/2026-08-03-serve-player-pages-resume-design.md §6
EOF
)"
```

---

## Task 11: ops 추출 누락 표

**Files:**
- Modify: `src/bullet_in/serve/render.py` (`unmatched_articles` 신규 · `render_ops` · `write_ops`)
- Modify: `src/bullet_in/run.py` (`write_ops` 호출)
- Modify: `src/bullet_in/serve/templates/ops.html.j2`
- Test: `tests/test_serve_players.py`

**용도 변경 (스펙 §9):** 같은 조건이 이제는 발굴 대상이 아니라 추출 실패를 뜻한다.
선수 페이지가 `article_players` 를 유일한 원천으로 쓰게 되므로, 추출이 실패한 기사는 어느 선수 페이지에도 나타나지 않고 조용히 사라진다.
표 제목과 설명 문구를 추출 누락 감시로 바꾸고 조건 자체는 draft 것을 유지한다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_unmatched_articles_lists_staged_rows_without_extraction():
    from bullet_in.serve.render import unmatched_articles
    arts = [_art("h1", 1, "rumour", "추출됨"), _art("h2", 2, "agreed", "추출 실패"),
            _art("h3", 3, "other", "단계 없음")]
    rows = unmatched_articles(arts, linked={"h1"})
    assert [r["title"] for r in rows] == ["추출 실패"]
    assert rows[0]["source"] == "bbc_sport"


def test_unmatched_articles_ignores_stageless_rows():
    from bullet_in.serve.render import unmatched_articles
    arts = [_art("h1", 1, None), _art("h2", 2, "other")]
    assert unmatched_articles(arts, linked=set()) == []
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_serve_players.py -q`
Expected: FAIL — ImportError

- [ ] **Step 3: 구현한다**

`render.py` 에 추가한다.

```python
def unmatched_articles(articles: list[dict], linked: set[str]) -> list[dict]:
    """단계가 있는데 귀속 선수가 0명인 기사 (스펙 §9) — 추출 누락 감시.

    선수 페이지가 article_players 를 유일한 원천으로 쓰므로 추출이 실패한 기사는
    어느 선수 페이지에도 나타나지 않고 조용히 사라진다. 그것을 볼 수 있는 자리다."""
    out = []
    for a in _sorted_latest(articles):
        if not _stage.is_displayable(filter_stage(a)):
            continue
        if a["content_hash"] in linked:
            continue
        out.append({"title": a.get("title_ko") or a.get("title_original") or "",
                    "source": a.get("source_id") or "",
                    "date": fmt_date(to_kst(_sort_ts(a)[0]))})
    return out
```

`render_ops` · `write_ops` 에 `unmatched` 를 배선한다 (draft 와 같은 형태).

```python
def render_ops(view: dict, unmatched: list[dict] | None = None) -> str:
    return _env().get_template("ops.html.j2").render(view=view, unmatched=unmatched)


def write_ops(snapshot: dict, sources: dict, out_dir: str | Path,
              anomaly_count: int, now: datetime,
              unmatched: list[dict] | None = None) -> None:
    """운영 뷰 site/ops.html 생성. 실패 격리는 호출부 (run.py) 책임."""
    view = build_ops_view(snapshot, sources, anomaly_count, now)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "ops.html").write_text(render_ops(view, unmatched=unmatched),
                                  encoding="utf-8")
```

`run.py` 의 `write_ops` 호출을 바꾼다.
`rows` 는 서빙 SELECT 결과이고 `linked_hashes()` 는 저장소 조회다.

```python
    try:
        from bullet_in.serve.render import unmatched_articles
        write_ops(mart.ops_snapshot(), sources, "site",
                  anomaly_count=len(anomalies), now=mart.db_now(),
                  unmatched=unmatched_articles(rows, pstore.linked_hashes()))
```

`run.py` 상단 import 에 `unmatched_articles` 를 넣어도 되고 위처럼 지역 import 로 둬도 된다.
기존 import 줄에 합치는 쪽을 택한다.

`ops.html.j2` 의 마지막 표 뒤에 넣는다.

```jinja
<h3>선수 추출 누락 (영입 단계 있음 · 귀속 선수 0명)</h3>
<p class="mut">추출이 실패한 기사는 어느 선수 페이지에도 실리지 않는다 — 재추출 대상.</p>
{% if unmatched %}
<table><thead><tr><th>날짜</th><th>소스</th><th>제목</th></tr></thead><tbody>
{% for r in unmatched %}<tr><td>{{ r.date }}</td><td>{{ r.source }}</td><td>{{ r.title }}</td></tr>{% endfor %}
</tbody></table>
{% else %}<p class="mut">없음</p>{% endif %}
```

- [ ] **Step 4: 테스트 통과를 확인한다**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 5: 스타일과 접기 동작을 넣는다**

`style.css` 에 `.tbadge` (8종 색) · `.pchips` · `.pchip` · `.plgrp.folded .playerlist { display:none }` · `.tlmore` 를 추가한다.
draft 의 `.pcard` · `.pname` · `.pmeta` · `.timeline` · `.tlnode` 정의를 그대로 가져온다.

`app.js` 에 접기 버튼 동작을 추가한다 (기존 `latestMore` 패턴과 같은 형태).

```javascript
// ── 선수 색인 — 무산 그룹 접기 (스펙 §4.1) ─────────────────────────
document.querySelectorAll('.plgrp .plfold').forEach(btn => {
  btn.addEventListener('click', () => {
    const grp = btn.closest('.plgrp');
    const folded = grp.classList.toggle('folded');
    btn.textContent = folded ? '펼치기' : '접기';
  });
});
```

- [ ] **Step 6: 커밋한다**

```bash
git add src/bullet_in/serve/ src/bullet_in/run.py tests/test_serve_players.py
git commit -m "$(cat <<'EOF'
feat(serve): ops 미매칭 표를 추출 누락 감시로 전환

선수 페이지가 article_players 를 유일한 원천으로 쓰면서 이 표의 뜻이 바뀐다.
같은 조건이 이제는 사전에 추가할 선수를 찾는 창구가 아니라, 추출이 실패해 어느
선수 페이지에도 실리지 않는 기사를 보는 자리다.

- 원천 교체: 사전 문자열 대조 → article_players 귀속 여부
- 문구 교체: 표 제목 · 설명을 추출 누락 감시로
- 색인 스타일 · 무산 그룹 접기 동작

Refs: docs/superpowers/specs/2026-08-03-serve-player-pages-resume-design.md §9
EOF
)"
```

---

## Task 12: 로컬 렌더 실측

**Files:** 없음 (검증 전용).

런북 `2026-07-26-local-serve-render-verification.md` 절차를 재사용한다.

- [ ] **Step 1: 배포판 DB 를 로컬로 내려 사이트를 만든다**

런북 절차대로 VM 덤프를 로컬 MariaDB 에 넣고 `write_site` 를 돌린다.

- [ ] **Step 2: 건수 3중 대조**

선수마다 아래 셋이 일치하는지 전원 확인한다 (draft 가 했던 대조 · 스펙 §11.2).

- 선수 페이지 머리의 "기사 N건"
- 그 페이지 기사 목록의 카드 수
- DB 직접 집계

```bash
uv run python - <<'PY'
import os, re
from pathlib import Path
from sqlalchemy import create_engine, text
e = create_engine(os.environ["MARIADB_URL"])
with e.connect() as c:
    db = {r[0]: r[1] for r in c.execute(text(
        "SELECT LOWER(p.surname), COUNT(*) FROM players p "
        "JOIN article_players ap ON ap.player_id = p.id "
        "WHERE p.category IN ('squad','external') AND p.transfer_status <> 'none' "
        "AND p.status <> 'candidate' GROUP BY 1")).all()}
bad = []
for f in sorted(Path("site/player").glob("*.html")):
    html = f.read_text(encoding="utf-8")
    head = int(re.search(r"기사 (\d+)건", html).group(1))
    cards = html.count('class="block"')
    if head != cards or db.get(f.stem, head) != head:
        bad.append((f.stem, head, cards, db.get(f.stem)))
print("불일치:", bad or "없음", f"· 페이지 {len(list(Path('site/player').glob('*.html')))}개")
PY
```

**검증:** 불일치 0건.
동성으로 slug 가 `surname-id` 인 선수는 위 대조에서 성 키가 어긋나므로 따로 확인한다.

- [ ] **Step 3: 화면을 눈으로 확인한다**

- 색인 3그룹이 예상 인원 (진행 중 40 · 성사 10 · 무산과 종료 6) 과 맞는지.
- 무산 그룹이 접혀 있고 버튼으로 펼쳐지는지.
- 사이드바가 선수 페이지에 없는지.
- 상세 페이지 칩이 눌리고 대상 선수 페이지로 가는지.
- 공홈 발표가 걸린 선수의 타임라인에 오피셜 노드가 생겼는지 (Task 5 Step 2 의 효과).

---

## Task 13: PR ② 생성 · 배포

- [ ] **Step 1: 전체 테스트**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 2: 푸시하고 PR 을 만든다**

7섹션 한국어 구조 · humanize-korean (fast) 점검 1회.

```bash
git push -u origin feat/player-pages-serve
gh pr create --base main --head feat/player-pages-serve \
  --title "feat(serve): 선수 색인 · 선수 페이지 · 상세 칩" \
  --body-file /tmp/pr-body-serve.md
```

머지는 사용자가 직접 한다.

- [ ] **Step 3: 머지 후 VM 반영**

런북 `2026-07-20-vm-cohost-bootstrap.md` §6.1 절차다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17
cd ~/bullet-in && git log --oneline -1
git pull --ff-only && git log --oneline -1
ps aux | grep -E '[b]ullet_in|[b]ackfill'      # 돌고 있는 배치가 없는지
```

- [ ] **Step 4: 배포 전 게이트 (스펙 §11.5)**

재렌더 직전에 확인한다.
소급 재분류가 값을 비우는 창을 만들기 때문이다.

```bash
docker compose exec -T mariadb mariadb -uroot -pbulletin bulletin -e "
SELECT COUNT(*) stage_null FROM articles WHERE transfer_stage IS NULL;"
```

**0 이 아니면 재렌더하지 않는다.**
분류 수렴을 먼저 돌린다 (런북 `2026-07-19-enrich-only-pass.md` §3).

- [ ] **Step 5: 재렌더하고 배포한다**

서빙 · 템플릿만 바뀌었으므로 회차를 기다리지 않는다.
런북 `2026-07-19-enrich-only-pass.md` §4 의 재생성 스니펫을 쓴 뒤 배포한다.

```bash
./infra/deploy-site.sh
```

- [ ] **Step 6: 라이브 확인**

```bash
curl -sL https://bullet-in.pages.dev/players.html | grep -c 'href="player/'
curl -sL https://bullet-in.pages.dev/player/tzolis.html | grep -o '기사 [0-9]*건'
curl -sL https://bullet-in.pages.dev/ | grep -o 'article/[0-9a-f]\{64\}\.html' | sort -u | wc -l
```

**검증:** 색인 링크 수 56 근처 · 선수 페이지가 열림 · 홈 카드 수가 배포 전과 같음.

- [ ] **Step 7: 첫 정기 회차를 확인한다**

머지가 끝이 아니다.
다음 회차 (3시간 간격 하루 8회 · KST `00 03 06 09 12 15 18 21`) 가 돈 뒤 선수 페이지가 그대로 재생성되는지 본다.

```bash
docker compose exec -T mariadb mariadb -uroot -pbulletin bulletin -e "
SELECT run_id, started_at, new_count, error_count FROM pipeline_runs
 ORDER BY started_at DESC LIMIT 3;"
ls ~/bullet-in/site/player/*.html | wc -l
```

---

## 위험 · 롤백

- **재분류가 단계를 흔든다** — dry-run 대조군 12건에서 단계 이동 0 을 확인하고 넘어간다.
움직이면 프롬프트를 고쳐 다시 돌린다 (#200 → #201 선례).
- **보관 갱신이 잘못됐다** — Task 5 Step 1 덤프에서 `players` 만 복원한다.
갱신 대상 id 목록은 `archived_inlink_ids.csv` 에 남아 있다.
- **렌더 결함** — 정적 렌더 안에서 끝난다.
`git revert` 후 다음 렌더에서 `players.html` 과 `player/` 가 생성되지 않으며, 배포 디렉터리에 남은 파일은 `player/` 삭제로 정리한다.
- **재렌더 시점 충돌** — 다른 트랙 배치가 도는 중에 렌더하면 중간 상태가 배포된다.
Task 13 Step 3 의 `ps aux` 확인을 건너뛰지 않는다.

## 범위 밖 (스펙 §13)

멀티 클럽 일반화 · 방향 값의 화면 노출 · 방출 모아보기 · 표시 날짜 하루 오차 · 선수 명단 정리 (은퇴 · 오등재 행 정돈) · 타 구단 이적 기사의 단계 정책 · 기타 필터 UI · 공저자 다중 귀속 · 보관 사유 전용 컬럼 신설.
