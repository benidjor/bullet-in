# 재번역 큐 종착 상태 복구 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 인명 축 게이트가 끝내 못 푸는 행을 회차마다 무한 재번역하는 것을 멈추고, 관용구 · 프레이밍을 사람 이름으로 오인하던 원인을 없앤다.

**Architecture:** `enrich.py` 한 파일 안에서 두 곳을 고친다.
`detect_title_mistranslation` 은 성 단독 출현을 인명으로 세지 않도록 근거 조건을 붙이고, `finalize_translation` 은 재시도 회차에 의심이 남아도 번역 제목을 채택해 종착시킨다.
스키마 변경과 신규 모듈은 없다.

**Tech Stack:** Python 3.11 · pytest · uv · 표준 라이브러리 `re` 와 `unicodedata` 만 사용.

## Global Constraints

- 스펙은 `docs/superpowers/specs/2026-07-30-retranslation-queue-terminal-state-design.md` 다.
- TDD — 각 태스크는 실패하는 테스트를 먼저 쓰고 통과시킨다.
- 스키마를 바꾸지 않는다 (컬럼 추가 · 마이그레이션 없음).
- Gemini 를 호출하지 않는다 — 이 계획의 모든 검증은 단위 테스트로 끝난다.
- 머지는 사용자가 한다 — 세션은 push 와 PR 생성까지다.
- 커밋 메시지는 `<type>(<scope>): 한국어 제목` + 도입 1~2문장 + 명사형 불릿 + `Refs:` + `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- `docs/` 아래 `.md` 는 서식 규칙 §2.2 를 따른다 — `→` 와 `—` 는 줄 시작에만 두고, 한 줄에 한 문장을 쓰고, `·` 와 `+` 와 여는 괄호 양옆을 띄운다 (코드 · URL · 경로는 예외).
`.claude/hooks/check-doc-format.py` 가 저장 시 자동 검사한다.
- 브랜치는 `fix/retranslation-queue-terminal-state` 이고 이미 만들어져 있다.

## 파일 구조

| 파일 | 역할 | 태스크 |
| --- | --- | --- |
| `src/bullet_in/enrich.py` | 가드 헬퍼 2개 신설 · 검출기 1개 수정 · 종착 분기 수정 · 집계 함수 수정 | 1 · 2 |
| `src/bullet_in/run.py` | 회차 요약 로그 문구 · 5요소 반환 언패킹 | 2 |
| `tests/test_enrich.py` | 신규 테스트 4개 · 기존 테스트 9곳 갱신 | 1 · 2 |
| `docs/runbook/2026-07-19-translation-quality-gates-ops.md` | 종착 동작 · 로그 해석 갱신 | 3 |
| `docs/runbook/2026-07-19-enrich-only-pass.md` | 스니펫의 반환값 언패킹 갱신 | 3 |
| `docs/troubleshooting/2026-07-30-silent-drops-and-blind-alerts.md` | §3 미해결 표시 닫기 | 3 |

---

### Task 1: 풀네임 근거 가드

성이 원문에 단독으로만 나오면 사람 이름으로 세지 않는다.
`white flag` 관용구와 `With Arteta's Backing…` 프레이밍이 이 조건에서 걸러진다.

**Files:**
- Modify: `src/bullet_in/enrich.py:102-137` (`_fold_latin` 아래에 헬퍼 2개 추가 · `detect_title_mistranslation` 수정)
- Modify: `src/bullet_in/enrich.py:295-296` (호출부에 `src_text` 전달)
- Test: `tests/test_enrich.py` (525행 `test_detect_title_mistranslation_passes_partial_name_condensation` 뒤에 추가)

**Interfaces:**
- Produces: `detect_title_mistranslation(title_ko, title_original, name_map, source_text="")` — 네 번째 인자는 기본값이 있어 기존 3인자 호출은 그대로 동작한다.
- Produces: `_strip_marks(text: str) -> str` · `_has_name_context(source: str, surname: str) -> bool` — 모듈 내부용이라 다른 태스크는 쓰지 않는다.

- [ ] **Step 1: 실패하는 테스트 4개를 쓴다**

`tests/test_enrich.py` 의 `test_detect_title_mistranslation_passes_partial_name_condensation` 바로 뒤에 붙인다.

```python
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
```

- [ ] **Step 2: 테스트가 실패하는 것을 확인한다**

```bash
uv run pytest tests/test_enrich.py -k "name_context or without_fullname or stopword_before" -q
```

Expected: 처음 두 개는 FAIL (`AssertionError: ['인명 누락:White'] != []` 와 `['인명 누락:Arteta'] != []`).
뒤 두 개는 이미 PASS 한다 — 현재 코드가 근거를 안 따지므로 우연히 같은 결과가 나온다.
Step 4 에서 넷 다 통과해야 하고, 뒤 두 개는 회귀 방지용이다.

- [ ] **Step 3: 헬퍼 2개를 추가하고 검출기를 고친다**

`src/bullet_in/enrich.py` 의 `_fold_latin` 바로 아래 (`_LOAN_RE` 앞) 에 넣는다.

```python
def _strip_marks(text: str) -> str:
    """결합 분음부호만 제거하고 대소문자는 보존 (Guimarães → Guimaraes).
    _fold_latin 은 casefold 까지 하므로 '성 앞 단어가 대문자인가' 판정에 쓸 수 없다."""
    import unicodedata
    out = unicodedata.normalize("NFD", text)
    out = "".join(ch for ch in out if not unicodedata.combining(ch))
    return (out.replace("ø", "o").replace("Ø", "O")
               .replace("æ", "ae").replace("Æ", "AE").replace("ß", "ss"))

# 성 앞 대문자 단어가 이름이 아니라 문장 첫머리 기능어인 경우를 걸러낸다
# (With Arteta's Backing… 의 With). 영어 기능어는 고정 집합이라 도메인 사전처럼 늘지 않는다.
_NAME_CONTEXT_STOPWORDS = frozenset({
    "a", "after", "an", "and", "as", "at", "before", "breaking", "but", "by",
    "can", "could", "deal", "exclusive", "for", "from", "had", "has", "have",
    "he", "her", "his", "how", "if", "in", "is", "it", "its", "latest", "new",
    "news", "not", "now", "of", "official", "on", "over", "report", "she",
    "that", "the", "their", "they", "this", "to", "under", "was", "we", "were",
    "what", "when", "where", "who", "why", "will", "with", "would", "you",
})

def _has_name_context(source: str, surname: str) -> bool:
    """원문에 '이름 + 성' 형태가 있는지 — 성 단독 출현을 인명 근거로 인정하지 않는다.
    앞 단어가 기능어면 근거로 치지 않는다 (With Arteta's Backing… 오탐 차단).
    실측 (2026-07-30 · 라이브 412행): 제목에 등재 성이 나온 132건 중 128건이 이 근거를 가지고,
    근거가 없는 4건 중 2건이 확인된 오탐이다 (스펙 4.3절)."""
    marked = _strip_marks(source)
    pat = rf"\b([A-Z][a-z]+)[- ]{re.escape(_strip_marks(surname))}\b"
    return any(m.group(1).lower() not in _NAME_CONTEXT_STOPWORDS
               for m in re.finditer(pat, marked))
```

그다음 `detect_title_mistranslation` 을 고친다.
시그니처에 `source_text` 를 더하고, docstring 에 새 조건을 적고, 루프 안에 `continue` 를 넣는다.

```python
def detect_title_mistranslation(title_ko: str | None, title_original: str | None,
                                name_map: dict[str, str],
                                source_text: str = "") -> list[str]:
    """원문 제목 대비 번역 제목의 결정적 불일치 사유 목록 (환각 검출기의 역방향 축).
    ①원문 제목의 등재 인명 (단어 경계) 이 번역 제목에 **전부** 누락
    — '조르제' (Tzolis) 창작 · 무관 제목 전면 환각 실사례를 잡는다.
    일부만 유지된 경우는 다절 제목 (트윗 · 리스트클) 의 정당한 축약이라 통과.
    ②'임대' 가 원문 근거 (loan · 한국어 원문의 임대) 없이 생성 — permanent 반전 실사례.
    성 단독 출현은 인명으로 세지 않는다 — 원문 (제목 + source_text) 에 '이름 + 성' 형태가
    있어야 인정한다 (white flag 관용구 · With Arteta's Backing 프레이밍 오탐 차단).
    라운드업 (제목 재초점이 정상) 은 호출측에서 제외한다."""
    if not title_ko or not title_original:
        return []
    reasons = []
    folded = _fold_latin(title_original)
    context = f"{title_original} {source_text}"
    missing, present = [], 0
    for en in dict.fromkeys(name_map.values()):
        if re.search(rf"\b{re.escape(_fold_latin(en))}\b", folded):
            if not _has_name_context(context, en):
                continue
            if any(ko in title_ko for ko, v in name_map.items() if v == en):
                present += 1
            else:
                missing.append(f"{NAME_MISSING_PREFIX}{en}")
    if missing and present == 0:
        reasons.extend(missing)
    if "임대" in title_ko and "임대" not in title_original \
            and not _LOAN_RE.search(title_original):
        reasons.append("임대 무근거")
    return reasons
```

- [ ] **Step 4: 테스트가 통과하는 것을 확인한다**

```bash
uv run pytest tests/test_enrich.py -k "mistranslation" -q
```

Expected: 신규 4개 + 기존 6개 모두 PASS.

기존 테스트가 왜 깨지지 않는지 확인해 둔다.

- `flags_missing_registered_name` — 원문에 `Christos Tzolis` 가 있어 근거가 선다.
- `passes_partial_name_condensation` — `Mikel Arteta` 와 `Morgan Rogers` 둘 다 근거가 선다.
- `passes_variant_spelling_same_person` — `Rashford to Arsenal?` 에는 근거가 없어 이제 검사에서 빠진다.
결과는 여전히 빈 목록이라 통과하지만 통과 이유가 달라졌다.

- [ ] **Step 5: 호출부에 원문을 넘긴다**

`src/bullet_in/enrich.py:295-296` 을 고친다.
`src_text` 는 같은 함수 287행에서 이미 만들어 두었다.

```python
        reasons = detect_title_mistranslation(
            v["title_ko"], row.get("title_original"), name_map, src_text)
```

- [ ] **Step 6: 배선이 걸렸는지 테스트로 확인한다**

`tests/test_enrich.py` 의 `test_finalize_translation_keeps_name_omission_axis_for_normal_sources` 뒤에 붙인다.

```python
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
    title_ko, _, _, _ = finalize_translation(v, row, {}, {"화이트": "White"}, {})
    assert title_ko is None      # 1차 검출 → 재번역 큐
```

```bash
uv run pytest tests/test_enrich.py -k "guard_uses_body" -q
```

Expected: PASS.

- [ ] **Step 7: 전체 테스트를 돌린다**

```bash
uv run pytest -q
```

Expected: 전부 PASS (DB · Airflow 없는 환경에서 통합 테스트는 skip).

- [ ] **Step 8: 커밋**

```bash
git add src/bullet_in/enrich.py tests/test_enrich.py
git commit -F - <<'MSG'
fix(enrich): 인명 축 게이트에 풀네임 근거 조건 추가

원문 제목에 성이 단독으로 나오면 사람 이름이 아니어도 인명으로 세고 있었다.
'white flag' 관용구가 벤 화이트로 오인돼 좋은 번역 제목이 하루 여덟 번 거부됐다.

- 조건: 원문 (제목 + 본문) 에 '이름 + 성' 형태가 있어야 성을 인명으로 인정
- 기능어 제외: 성 앞 단어가 With · The 류면 근거로 안 침 (With Arteta's Backing 오탐)
- 헬퍼 신설: _strip_marks (대소문자 보존 발음 부호 제거) · _has_name_context
- 배선: finalize_translation 이 이미 만들어 둔 src_text 를 검출기에 전달
- 실측 근거: 제목 성 출현 132건 중 검사 면제 4건 (3%) · 그중 2건이 확인된 오탐

Refs: docs/superpowers/specs/2026-07-30-retranslation-queue-terminal-state-design.md §5.1

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
```

---

### Task 2: 재시도 1회 후 채택 종착

재시도 회차에 의심이 남으면 지금은 제목을 다시 비워 큐로 돌려보낸다.
판정 근거가 회차마다 같으니 결과도 같아 무한히 돈다.
번역 제목을 채택하고 경고만 남겨 끝낸다.

**Files:**
- Modify: `src/bullet_in/enrich.py:306-325` (`finalize_translation` 종착 분기 · 반환값)
- Modify: `src/bullet_in/enrich.py:327-344` (`retranslation_summary` 집계 정의)
- Modify: `src/bullet_in/run.py:104-111` (반환값 언패킹 · 요약 로그 문구)
- Test: `tests/test_enrich.py:686-707` 와 4인자 언패킹 8곳

**Interfaces:**
- Consumes: Task 1 이 고친 `detect_title_mistranslation` — 이 태스크는 그 결과인 `suspects` 만 쓴다.
- Produces: `finalize_translation` 이 5요소 튜플을 돌려준다 — `(title_ko, summary_ko, summary3_ko, body_ko, flagged)`.
`flagged` 는 재시도 회차에 남은 의심 사유 목록이고 그 외에는 빈 목록이다.
- Produces: `retranslation_summary(finals, by_hash) -> (신규, 채택, 해소)` — 가운데 값의 뜻이 잔존에서 채택으로 바뀐다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_enrich.py:686` 의 `test_finalize_translation_requeues_on_retry_instead_of_english_fallback` 를 통째로 아래로 바꾼다.
이 테스트가 지금 동작을 그대로 못박고 있어 두면 변경이 들어가지 않는다.

```python
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
```

그리고 `test_retranslation_summary_counts_new_stuck_resolved` 를 아래로 바꾼다.

```python
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
```

- [ ] **Step 2: 테스트가 실패하는 것을 확인한다**

```bash
uv run pytest tests/test_enrich.py -k "adopts_title_on_retry or leaves_flagged_empty or counts_new_adopted" -q
```

Expected: 세 개 모두 FAIL (`ValueError: not enough values to unpack (expected 5, got 4)`).

- [ ] **Step 3: 종착 분기와 반환값을 고친다**

`src/bullet_in/enrich.py` 의 `finalize_translation` 에서 305행부터 끝까지를 아래로 바꾼다.

```python
    title_ko = v["title_ko"]
    flagged: list[str] = []
    retry = bool(row.get("summary_ko"))
    if suspects and retry:
        # 종착 상태 (설계 5.2): 재시도 1회로 끝내고 번역 제목을 채택 + 경고.
        # NULL 재큐는 게이트가 충족 불가능한 요구를 하면 회차마다 무한 반복됐다
        # (white flag 관용구를 벤 화이트로 오인 · 2026-07-30 실측 하루 8회).
        flagged = suspects
        log.warning("제목 의심 잔존 — 수동 확인 content_hash=%s 의심=%s", h, suspects)
    elif (suspects or omissions or club_suspects) and not retry:
        log.warning(
            "재번역 큐(1차) content_hash=%s 환각의심=%s 단신누락=%s 원문에 없는 구단명=%s",
            h, suspects, omissions, club_suspects)
        title_ko = None
    elif retry and not suspects:
        log.info("제목 해소 content_hash=%s title_ko=%s", h, title_ko)
    if omissions and retry:
        log.warning(
            "라운드업 단신 누락 잔존 — 수동 확인 content_hash=%s 누락=%s", h, omissions)
    if club_suspects and retry:
        log.warning(
            "원문에 없는 구단명 잔존 — 수동 확인 content_hash=%s 구단=%s", h, club_suspects)
    return (title_ko, v["summary_ko"], v["summary3_ko"],
            paragraphize(v["body_ko"]), flagged)
```

이어서 `retranslation_summary` 를 바꾼다.

```python
def retranslation_summary(finals: dict[str, tuple], by_hash: dict[str, dict]
                          ) -> tuple[int, int, int]:
    """finalize_translation 결과로 재번역 큐 추이를 집계 → (신규, 채택, 해소).

    신규 = 신규 행 (summary_ko 없음) 이 NULL 로 큐 진입,
    채택 = 재시도 행이 의심을 남긴 채 제목을 확정 (운영자 수동 확인 대상),
    해소 = 재시도 행이 의심 없이 제목 확보.
    정상 신규 성공 (NULL 아님 · 재시도 아님) 은 집계 밖.
    관측 ② — 호출측 (run.py) 이 사이클 요약 한 줄로 로깅한다."""
    new_q = adopted = resolved = 0
    for h, final in finals.items():
        title_ko, flagged = final[0], final[4]
        retry = bool(by_hash.get(h, {}).get("summary_ko"))
        if title_ko is None and not retry:
            new_q += 1
        elif retry and flagged:
            adopted += 1
        elif retry and title_ko is not None:
            resolved += 1
    return new_q, adopted, resolved
```

- [ ] **Step 4: 4인자 언패킹 8곳을 5인자로 고친다**

`tests/test_enrich.py` 에서 아래 줄을 찾아 마지막에 `, _` 를 더한다.

```
682행   title_ko, _, _, _ = finalize_translation(          → title_ko, _, _, _, _ = finalize_translation(
715행   title_ko, summary_ko, _, body_ko = finalize_translation(
                                                           → title_ko, summary_ko, _, body_ko, _ = finalize_translation(
772행   title_ko, _, _, _ = finalize_translation(v, _tweet_row(), {}, _TWEET_NAMES, {})
                                                           → title_ko, _, _, _, _ = ...
782행   title_ko, _, _, _ = finalize_translation(v, row, {}, _TWEET_NAMES, {})
                                                           → title_ko, _, _, _, _ = ...
790행   title_ko, _, _, _ = finalize_translation(v, _tweet_row(), {}, _TWEET_NAMES, {})
                                                           → title_ko, _, _, _, _ = ...
800행   title_ko, _, _, _ = finalize_translation(v, row, {}, _TWEET_NAMES, {})
                                                           → title_ko, _, _, _, _ = ...
```

Task 1 Step 6 에서 추가한 `test_finalize_translation_guard_uses_body_as_name_context` 도 같이 고친다.

그리고 989행의 튜플 비교를 고친다.

```python
    assert finalize_translation(v, row, {}, {}, {}) == ("아스날 소식", None, None, None, [])
```

- [ ] **Step 5: `run.py` 를 고친다**

`src/bullet_in/run.py:104-111` 을 아래로 바꾼다.

```python
    for h, (title_ko, s_ko, s3_ko, body_ko, _) in finals.items():
        mart.set_translation(h, title_ko, s_ko, s3_ko, body_ko)
    for h, rep in gate_reports.items():
        mart.set_rewrite_retention(h, rep["retention"])
    if finals:  # 관측 ②: 재번역 큐 추이 한 줄 (신규 진입 · 채택 · 해소)
        logging.getLogger(__name__).warning(
            "재번역 큐 요약: 신규 %d · 채택 %d · 해소 %d",
            *retranslation_summary(finals, by_hash))
```

- [ ] **Step 6: 전체 테스트를 돌린다**

```bash
uv run pytest -q
```

Expected: 전부 PASS.
실패하면 대개 언패킹을 빠뜨린 곳이다 — `grep -n "= finalize_translation" tests/test_enrich.py` 로 전수 확인한다.

- [ ] **Step 7: 커밋**

```bash
git add src/bullet_in/enrich.py src/bullet_in/run.py tests/test_enrich.py
git commit -F - <<'MSG'
fix(enrich): 재번역 큐에 종착 상태 복구 — 재시도 1회 후 채택

재시도 회차에 의심이 남으면 제목을 다시 비워 큐로 돌려보내고 있었다.
판정 근거가 회차마다 같아 결과도 같으므로 종착 없이 무한히 돌았다.

- 종착: 재시도 1회로 끝내고 번역 제목 채택 + 수동 확인 경고 (구단명 축 · 라운드업 축과 동일)
- 반환값: finalize_translation 이 남은 의심 사유 목록을 다섯 번째 요소로 함께 돌려줌
- 집계: 큐 추이 가운데 값을 잔존에서 채택으로 재정의 (재시도 행이 NULL 로 남는 상태가 사라짐)
- 로그: '재번역 재시도 잔존 → 재큐' → '제목 의심 잔존 — 수동 확인'
- 스키마 무변경: 재시도 표지는 기존 summary_ko 존재 여부를 그대로 쓴다

Refs: docs/superpowers/specs/2026-07-30-retranslation-queue-terminal-state-design.md §5.2 §5.3

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
```

---

### Task 3: 문서 갱신

게이트 운영 런북이 아직 구 정책 (원문 제목 폴백) 을 적고 있다.
그 어긋남이 이번 회귀를 눈에 안 띄게 만든 원인 중 하나라 이번에 맞춘다.

**Files:**
- Modify: `docs/runbook/2026-07-19-translation-quality-gates-ops.md` (§2 재번역 큐 동작 · §3 로그 해석)
- Modify: `docs/runbook/2026-07-19-enrich-only-pass.md:80` (스니펫 언패킹)
- Modify: `docs/troubleshooting/2026-07-30-silent-drops-and-blind-alerts.md` (§3 미해결 닫기)

**Interfaces:**
- Consumes: Task 2 의 로그 문구와 반환값 형태.

- [ ] **Step 1: 게이트 운영 런북 §2 를 고친다**

`docs/runbook/2026-07-19-translation-quality-gates-ops.md:26-28` 의 세 줄을 찾는다.

```
- **재검출 (재시도 행)** — 제목 축: 원문 제목 폴백 확정 + WARNING (사실 보존 우선)
  · 라운드업 축: 잔존 WARNING (수동 확인) — 사이클당 1회 재시도로 무한루프 차단.
  · 구단명 축: 잔존 WARNING (수동 확인) — 라운드업 축과 동일 (사이클당 1회 재시도).
```

세 축이 같은 규칙이 됐다는 내용으로 바꾼다.

```
- **재검출 (재시도 행)** — 세 축 모두 동일: 번역 결과 채택 + WARNING (수동 확인)
— 사이클당 1회 재시도로 무한루프를 차단한다.
- 제목 축은 2026-07-23 부터 NULL 재큐로 바뀌어 있었고 종착이 없어 무한 루프가 났다.
2026-07-30 에 채택 종착으로 되돌렸다 (`specs/2026-07-30-retranslation-queue-terminal-state-design.md`).
```

- [ ] **Step 2: 게이트 운영 런북 §3 의 로그 해석을 고친다**

`제목 환각 재발 — 원문 제목 폴백` 항목을 지우고 아래로 바꾼다.

```
- **`제목 의심 잔존 — 수동 확인`** — 재시도까지 의심이 남아 번역 제목을 그대로 채택했다.
서빙은 한국어 제목이므로 화면은 정상이고, 사유 목록을 보고 오탐인지 진짜 오역인지 판단한다.
진짜 오역이면 수동 정정 (아래 §5) 후 원인 표기를 사전에 추가한다.
```

35행 하나만 바꾸면 된다.
37행 · 38행의 `잔존 WARNING` 두 줄은 라운드업 축 · 구단명 축이라 동작이 그대로다.

- [ ] **Step 3: 인명 축 가드를 §1 표에 반영한다**

`역방향 오역` 행의 '잡는 것' 칸에 조건을 더한다.

```
| 역방향 오역 | `detect_title_mistranslation` | 원문 제목 인명이 번역에서 전부 소실 · 무근거 '임대' (성 단독 출현은 제외 — 원문에 '이름 + 성' 형태가 있어야 인명으로 본다) | id 385 '조르제' · id 392 임대 반전 · id 420 무관 제목 |
```

- [ ] **Step 4: enrich 전용 패스 스니펫을 고친다**

`docs/runbook/2026-07-19-enrich-only-pass.md:79-81` 의 아래 두 줄을 찾는다.

```python
        mart.set_translation(h, *finalize_translation(
            v, by_hash.get(h, {}), glossary, name_map, club_map))
```

다섯 번째 요소가 생겼으므로 명시적으로 푼다.

```python
        title_ko, s_ko, s3_ko, body_ko, _ = finalize_translation(
            v, by_hash.get(h, {}), glossary, name_map, club_map)
        mart.set_translation(h, title_ko, s_ko, s3_ko, body_ko)
```

- [ ] **Step 5: 트러블슈팅 §3 의 미해결을 닫는다**

`docs/troubleshooting/2026-07-30-silent-drops-and-blind-alerts.md` 의 아래 두 줄을 찾는다.

```
**미해결** — 상한을 두거나 관용구 예외를 넣어야 한다.
다음 세션 착수 항목이다.
```

조치 결과로 바꾼다.

```
**조치 완료 (2026-07-30)** — 둘 다 넣었다.
게이트는 성 단독 출현을 인명으로 세지 않게 됐고 (`White flag` 가 여기서 걸러진다), 재시도 회차에 의심이 남으면 번역 제목을 채택해 끝낸다.
설계는 `docs/superpowers/specs/2026-07-30-retranslation-queue-terminal-state-design.md` 다.
```

- [ ] **Step 6: 서식 훅을 확인한다**

```bash
for f in docs/runbook/2026-07-19-translation-quality-gates-ops.md \
         docs/runbook/2026-07-19-enrich-only-pass.md \
         docs/troubleshooting/2026-07-30-silent-drops-and-blind-alerts.md; do
  echo "{\"tool_input\":{\"file_path\":\"$PWD/$f\"}}" | python3 .claude/hooks/check-doc-format.py
  echo "$f exit=$?"
done
```

Expected: 셋 다 `exit=0`.

- [ ] **Step 7: 커밋**

```bash
git add docs/runbook/ docs/troubleshooting/
git commit -F - <<'MSG'
docs(runbook): 게이트 종착 동작을 채택으로 갱신 · 진단 미해결 닫기

게이트 운영 런북이 2026-07-23 에 바뀐 NULL 재큐를 반영하지 않아 구 정책을 적고 있었다.
그 어긋남 때문에 종착 상태가 사라진 것이 오래 눈에 띄지 않았다.

- 게이트 운영 §1: 역방향 오역 축에 풀네임 근거 조건 명시
- 게이트 운영 §2: 세 축 모두 재시도 1회 후 채택 · 무한 루프가 났던 경위 기록
- 게이트 운영 §3: '제목 환각 재발 — 원문 제목 폴백' → '제목 의심 잔존 — 수동 확인'
- enrich 전용 패스: finalize_translation 다섯 번째 반환값에 맞춰 스니펫 언패킹 수정
- 조용한 드롭 진단 §3: 미해결 → 조치 완료

Refs: docs/superpowers/specs/2026-07-30-retranslation-queue-terminal-state-design.md §9

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
```

---

### Task 4: 통합 검증 · PR

**Files:**
- 새로 만들거나 고치는 파일 없음.

**Interfaces:**
- Consumes: Task 1 · 2 · 3 의 커밋 전부.

- [ ] **Step 1: 전체 테스트**

```bash
uv run pytest -q
```

Expected: 전부 PASS.

- [ ] **Step 2: 두 실사례가 실제로 검사에서 빠지는지 확인한다**

Gemini 를 부르지 않고 검출기만 직접 돌린다.

```bash
uv run python - <<'EOF'
import yaml
from bullet_in.enrich import detect_title_mistranslation
nm = yaml.safe_load(open("config/name_map.yaml"))["names"]
cases = [
    ("White flag: Arsenal give up on Vinicius Junior deal",
     "백기: 아스날, 비니시우스 주니오르 영입 포기"),
    ("With Arteta's Backing: Liverpool Compete Strongly to Snatch "
     "Target of Chelsea, Arsenal and United",
     "아스날 · 첼시 · 맨유 노리는 알렉스 스콧, 리버풀 영입전 가세"),
]
for src, ko in cases:
    print(detect_title_mistranslation(ko, src, nm), "|", src[:60])
EOF
```

Expected: 두 줄 다 `[]` 로 나온다.

- [ ] **Step 3: push**

```bash
git push -u origin fix/retranslation-queue-terminal-state
```

- [ ] **Step 4: PR 본문을 쓰고 문체 점검을 돌린다**

`.github/pull_request_template.md` 의 주석 세칙까지 직접 대조해 7섹션으로 쓴다.
본문은 스크래치패드에 `pr-body.md` 로 저장하고 `--body-file` 로 넘긴다.
Claude 서명은 넣지 않는다.
게시 전에 humanize-korean 스킬 fast 모드로 1회 점검한다 — 호출할 때 서식 규칙 §2.2 · 명사형 불릿 · 수치 · 경로를 변경 금지로 명시한다.

- [ ] **Step 5: PR 생성**

```bash
gh pr create --title "fix(enrich): 재번역 큐 무한 루프 — 풀네임 근거 가드 · 채택 종착" \
             --body-file "$SCRATCHPAD/pr-body.md"
```

머지는 하지 않는다.
사용자가 직접 한다.

- [ ] **Step 6: 사용자에게 남은 일을 알린다**

- VM 반영이 필요하다 — 정기 회차는 자동으로 `git pull` 하지 않으므로 머지 후 직접 반영해야 다음 회차부터 적용된다.
- 반영 뒤 첫 회차에서 확인할 것 : `journalctl -u bullet-in` 에 `재번역 재시도 잔존` 이 더 나오지 않고, 3740329594 가 한국어 제목을 얻는다.
- 7341690b 는 이번 변경으로 자동으로 안 고쳐진다 (`title_ko` 가 차 있어 재선별 대상이 아니다).
같은 부류가 몇 건인지 세는 것은 별도 작업이다.

---

## Self-Review — 스펙 커버리지

| 스펙 절 | 태스크 |
| --- | --- |
| 5.1 조치 A 풀네임 근거 가드 · 기능어 제외 · 발음 부호 헬퍼 · 시그니처 변경 | Task 1 |
| 5.2 조치 B 재시도 1회 후 채택 · 스키마 무변경 · 정방향 축 동시 적용 | Task 2 |
| 5.3 로그 문구 · 큐 추이 집계 재정의 | Task 2 |
| 8 테스트 (가드 4종 · 상한 · 회귀) | Task 1 Step 1 · Task 2 Step 1 |
| 9 문서 갱신 | Task 3 |
| 7 두 행의 수렴 | Task 4 Step 2 · Step 6 |

스펙 2절이 범위 밖으로 둔 것 (링크 선수 DB · `name_map` 확장 · 배지 문구 · 기존 저장 행 정정) 은 어느 태스크에도 없다.
