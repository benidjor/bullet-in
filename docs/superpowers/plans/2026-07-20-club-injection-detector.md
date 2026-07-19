# 무근거 구단명 검출기 구현 계획 (2026-07-20)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 번역 산출물 4필드에 원문 근거 없는 구단명이 등장하면 검출해 기존 재번역 큐로 보내는 게이트 4축을 추가한다.

**Architecture:** `enrich.py` 에 순수 함수 `detect_club_injection` (이중 대조 — 한글 표기 or 영문 별칭) 을 추가하고,
`config/club_map.yaml` 사전 (glossary · name_map 과 분리) 을 시드한 뒤,
`run.py` enrich 루프에 `detect_roundup_omission` 과 동일한 패턴 (1차 → 재번역 큐 · 재발 → 잔존 WARNING) 으로 배선한다.
spec: `docs/superpowers/specs/2026-07-20-club-injection-detector-design.md`.

**Tech Stack:** Python 3.11 · uv · pytest (모킹 불필요 — 전부 순수 함수) · yaml.

## Global Constraints

- 테스트 실행은 항상 `uv run pytest` (셸 pytest 직접 호출 금지 — uv 가상환경).
- 커밋 제목은 `<type>(<scope>): 한국어 제목`, 본문은 도입 1–2문장 + 명사형 불릿 (컨벤션 §1.1).
- 커밋 트레일러는 실제 작업 모델 기준 (§1.3) — 아래 커밋 블록은 설계 Fable 5 + 구현 subagent 병기 형태이며,
  인라인 실행 (단독 작업) 시 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` 한 줄로 조정한다.
- git 신원은 `benidjor <94089198+benidjor@users.noreply.github.com>` 고정.
- `docs/` 아래 .md 수정 시 서식 규칙 (§2.2 — 한 줄 = 한 문장, `→` · `—` 줄 시작, `·` 양옆 띄우기) 준수 — PostToolUse 훅이 검사.
- 기존 코드의 인접 정리 · 리팩터 금지 (수술적 변경) — 바뀐 줄은 전부 이 계획에 추적돼야 한다.

## 파일 구조

- `src/bullet_in/enrich.py` — 검출 함수 2개 추가 (`_ko_present` · `detect_club_injection`). 기존 검출기 3종 옆.
- `config/club_map.yaml` — 신규 사전 (한글 통용 표기 → 영문 별칭 목록).
- `src/bullet_in/run.py` — import 1곳 · 사전 로드 1곳 · enrich 루프 판정 2곳.
- `tests/test_enrich.py` — 함수 테스트 6종 추가 (기존 검출기 테스트 블록 뒤).
- 문서 3건 — 런북 (4축 반영) · 진단 문서 (§6 후속) · 백로그 (§5 완료 처리).

---

### Task 1: `detect_club_injection` 함수 + 테스트

**Files:**
- Modify: `src/bullet_in/enrich.py` (156행 `detect_title_hallucination` 끝 다음, `_SENT_END_RE` 정의 앞에 삽입)
- Test: `tests/test_enrich.py` (513행 `test_detect_title_mistranslation_passes_partial_name_condensation` 뒤에 추가)

**Interfaces:**
- Consumes: `enrich._fold_latin(text: str) -> str` (기존 · 86행) — casefold + 분음부호 제거.
- Produces: `detect_club_injection(parsed: dict, source_text: str, club_map: dict[str, list[str]]) -> list[str]`
  — parsed 는 enrich 결과 dict (title_ko · summary_ko · summary3_ko · body_ko, str | None),
  반환은 무근거 의심 한글 구단명 목록 (Task 3 이 소비).
- Produces: `_ko_present(text: str, name: str) -> bool` — 내부 헬퍼 (한글 표기 존재 판정, 선행 문자 가드).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_enrich.py` 말미에 추가:

```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_enrich.py -k club_injection -v`
Expected: 6건 전부 FAIL — `ImportError: cannot import name 'detect_club_injection'`

- [ ] **Step 3: 최소 구현**

`src/bullet_in/enrich.py` 의 `detect_title_hallucination` 함수 끝 (156행) 과
`# 문장 종결 …` 주석 (157행) 사이에 삽입:

```python
def _ko_present(text: str, name: str) -> bool:
    """한글 표기 존재 판정 — 직전 문자가 한글 음절이면 불인정 ("리즈" ⊄ "시리즈").
    직후 문자는 조사 결합 ("리즈가") 이 정상이라 판정에 쓰지 않는다."""
    start = text.find(name)
    while start != -1:
        if start == 0 or not ("가" <= text[start - 1] <= "힣"):
            return True
        start = text.find(name, start + 1)
    return False

_CLUB_FIELDS = ("title_ko", "summary_ko", "summary3_ko", "body_ko")

def detect_club_injection(parsed: dict, source_text: str,
                          club_map: dict[str, list[str]]) -> list[str]:
    """번역 산출물 4필드에 등장한 구단명이 원문에 근거 없으면 의심 목록 반환 (게이트 4축).
    이중 대조 — 원문의 한글 표기 (ko 경로 · fmkorea) or 영문 별칭 단어 경계 (en 경로) 중
    하나라도 있으면 근거 인정. 사전 밖 구단은 미검출 (name_map 과 같은 점진 확장).
    실사례: 로저스의 전 소속 (미들즈브러) 학습 지식 주입 — 원문은 Aston Villa 명시."""
    if not club_map:
        return []
    joined = " ".join(filter(None, (parsed.get(k) for k in _CLUB_FIELDS)))
    if not joined:
        return []
    src = source_text or ""
    folded_src = _fold_latin(src)
    suspects = []
    for ko, aliases in club_map.items():
        if not _ko_present(joined, ko):
            continue
        if _ko_present(src, ko):
            continue
        if any(re.search(rf"\b{re.escape(_fold_latin(a))}\b", folded_src)
               for a in aliases):
            continue
        suspects.append(ko)
    return suspects
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_enrich.py -k club_injection -v`
Expected: 6 passed

Run: `uv run pytest tests/test_enrich.py -q`
Expected: 전체 통과 (기존 검출기 회귀 없음)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/enrich.py tests/test_enrich.py
git commit -m "$(cat <<'EOF'
feat(enrich): detect_club_injection — 무근거 구단명 검출 (게이트 4축)

번역이 학습 지식을 주입해 원문에 없는 구단명을 만드는 환각 유형
(실사례 미들즈브러 — 기존 3축 전부 사각) 의 검출 함수 (spec §3).

- 이중 대조: 원문 한글 표기 or 영문 별칭 단어 경계 (ko 경로 오탐 cc2c7b58 해소)
- 대상: 번역 4필드 (title·summary·summary3·body_ko) 결합 검사
- _ko_present 가드: 선행 문자 한글이면 불인정 ("리즈" ⊄ "시리즈",
  조사 결합 "리즈가" 는 유지)
- 사전 밖 구단 미검출 (name_map 동일 점진 확장 정책)

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `config/club_map.yaml` 사전 시드

**Files:**
- Create: `config/club_map.yaml`

**Interfaces:**
- Consumes: 없음 (독립 데이터 파일).
- Produces: yaml 루트 `clubs:` — `한글 통용 표기: [영문 별칭, …]` 매핑. Task 3 의 `run.py` 가
  `yaml.safe_load(...).get("clubs", {})` 로 로드해 `detect_club_injection` 의 `club_map` 인자로 전달.

- [ ] **Step 1: 사전 파일 작성**

`config/club_map.yaml` 생성 (전체 내용):

```yaml
# 무근거 구단명 검출 사전 — 한글 통용 표기 → 영문 별칭 목록 (enrich.detect_club_injection).
# glossary (표기 교정 치환) · name_map (인명 검출) 과 목적이 달라 분리 — 치환하지 않는 검출 전용.
# 등재 규칙:
# ① 별칭 누락 = 오탐 — 원문이 통칭 (Boro · Spurs) 으로만 표기해도 근거로 인정되게 통칭까지 등재.
# ② 짧은 한글 표기 주의 — 선행 결합 오매치 (시리즈 ⊃ 리즈) 는 코드 가드가 막지만,
#    후행 결합 오매치 (인터뷰 ⊃ 인터 · 로마노 ⊃ 로마 · 포르투갈 ⊃ 포르투) 는 못 막으므로
#    구별 가능한 긴 표기 (인터 밀란 · AS 로마) 로 등재하거나 미등재 (포르투 · 릴).
# ③ 아스날 미등재 — 전 기사가 아스날 문맥이라 검출 신호 없음.
# ④ 같은 구단의 복수 한글 표기 (맨시티 · 맨체스터 시티) 는 각각 등재 (name_map 과 동일).
clubs:
  # EPL (2025-26 시즌 기준 · 아스날 제외)
  아스톤 빌라: [Aston Villa, Villa]
  본머스: [Bournemouth]
  브렌트퍼드: [Brentford]
  브라이턴: [Brighton]
  번리: [Burnley]
  첼시: [Chelsea]
  크리스탈 팰리스: [Crystal Palace, Palace]
  에버턴: [Everton, Toffees]
  풀럼: [Fulham]
  리즈: [Leeds]
  리버풀: [Liverpool]
  맨시티: [Manchester City, Man City]
  맨체스터 시티: [Manchester City, Man City]
  맨유: [Manchester United, Man United, Man Utd]
  맨체스터 유나이티드: [Manchester United, Man United, Man Utd]
  뉴캐슬: [Newcastle]
  노팅엄: [Nottingham Forest, Forest]
  선덜랜드: [Sunderland]
  토트넘: [Tottenham, Spurs]
  웨스트햄: [West Ham, Hammers]
  울버햄튼: [Wolverhampton, Wolves]
  울브스: [Wolverhampton, Wolves]
  # 챔피언십 — 실사례 구단
  미들즈브러: [Middlesbrough, Boro]
  # 유럽 빈출 (아스날 이적설 · 코퍼스 등장 구단)
  레알 마드리드: [Real Madrid]
  바르셀로나: [Barcelona, Barca]
  아틀레티코: [Atletico Madrid, Atletico]
  바이에른: [Bayern]
  도르트문트: [Dortmund, Borussia Dortmund]
  레버쿠젠: [Leverkusen, Bayer Leverkusen]
  라이프치히: [Leipzig, RB Leipzig]
  파리 생제르맹: [Paris Saint-Germain, PSG]
  PSG: [Paris Saint-Germain, PSG]
  유벤투스: [Juventus, Juve]
  AC 밀란: [AC Milan, Milan]
  인터 밀란: [Inter Milan, Inter]
  나폴리: [Napoli]
  AS 로마: [Roma]
  아약스: [Ajax]
  스포르팅: [Sporting]
  벤피카: [Benfica]
  클럽 브뤼헤: [Club Brugge, Brugge]
  베식타스: [Besiktas]
  갈라타사라이: [Galatasaray]
  페네르바체: [Fenerbahce]
```

- [ ] **Step 2: 구조 검증 (일회성 — 테스트 파일 없음, name_map · glossary 선례와 동일)**

Run:

```bash
uv run python -c "
import yaml
m = yaml.safe_load(open('config/club_map.yaml'))['clubs']
assert m and all(isinstance(v, list) and v and all(isinstance(a, str) for a in v)
                 for v in m.values()), '구조 오류'
assert '아스날' not in m, '아스날 미등재 규칙 위반'
print('키', len(m), '개 OK')
"
```

Expected: `키 44 개 OK`

- [ ] **Step 3: 커밋**

```bash
git add config/club_map.yaml
git commit -m "$(cat <<'EOF'
feat(enrich): club_map.yaml — 구단명 검출 사전 시드 (EPL + 유럽 빈출)

detect_club_injection 용 한↔영 사전 (spec §4). glossary · name_map 과
목적이 달라 분리하며, 치환 없는 검출 전용.

- 시드: EPL 20 (아스날 제외 19 + 복수 표기) + 미들즈브러 + 유럽 빈출 20개
- 등재 규칙 주석 4건: 별칭 검수 필수 · 짧은 표기 후행 결합 오매치는
  긴 표기 등재 or 미등재 (인터 밀란·AS 로마 / 포르투·릴 제외) ·
  아스날 미등재 · 복수 한글 표기 각각 등재

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: run.py 배선 — 재번역 큐 · 잔존 로그

**Files:**
- Modify: `src/bullet_in/run.py:16-19` (import) · `run.py:73-74` 근처 (사전 로드) · `run.py:88-104` (판정 분기)

**Interfaces:**
- Consumes: `detect_club_injection(parsed, source_text, club_map) -> list[str]` (Task 1)
  · `config/club_map.yaml` 의 `clubs` 매핑 (Task 2).
- Produces: 없음 (종단 배선). 로그 계약 — 1차 검출은 기존 `재번역 큐` WARNING 에 `구단주입=` 필드 추가,
  재발은 신규 `무근거 구단명 잔존 — 수동 확인` WARNING (런북 §3 로그 해석과 1:1 대응, Task 4 가 문서화).

- [ ] **Step 1: import 추가**

`src/bullet_in/run.py` 16–19행의 enrich import 를 수정:

```python
from bullet_in.enrich import (enrich_rows, classify_stage_rows, resummarize_rows,
                              apply_glossary, paragraphize,
                              detect_title_hallucination, detect_roundup_omission,
                              detect_title_mistranslation, detect_club_injection)
```

- [ ] **Step 2: 사전 로드 추가**

`name_map` 로드 (73–74행) 바로 아래에 추가:

```python
    club_map = (yaml.safe_load(Path("config/club_map.yaml").read_text())
                or {}).get("clubs", {})
```

- [ ] **Step 3: 판정 분기 배선**

enrich 루프의 `omissions = …` 행 (89행 근처) 아래에 검출 호출을 추가하고,
재번역 큐 분기 조건 · 로그에 구단 축을 편입, 잔존 분기를 신설.
수정 전 (현재 코드):

```python
        # 라운드업 단신 누락 게이트: 원문 괄호 출처 vs 번역 병기 대조 (환각 큐와 같은 재시도 1회)
        omissions = detect_roundup_omission(r0.get("body_source"), v["body_ko"])
        title_ko = v["title_ko"]
        retry = bool(r0.get("summary_ko"))
        if suspects and retry:
            logging.getLogger(__name__).warning(
                "제목 환각 재발 — 원문 제목 폴백 content_hash=%s 의심=%s", h, suspects)
            title_ko = r0.get("title_original")
        elif (suspects or omissions) and not retry:
            logging.getLogger(__name__).warning(
                "재번역 큐 content_hash=%s 환각의심=%s 단신누락=%s", h, suspects, omissions)
            title_ko = None
        if omissions and retry:
            logging.getLogger(__name__).warning(
                "라운드업 단신 누락 잔존 — 수동 확인 content_hash=%s 누락=%s", h, omissions)
```

수정 후:

```python
        # 라운드업 단신 누락 게이트: 원문 괄호 출처 vs 번역 병기 대조 (환각 큐와 같은 재시도 1회)
        omissions = detect_roundup_omission(r0.get("body_source"), v["body_ko"])
        # 무근거 구단명 게이트 (4축): 번역 4필드 × 원문 이중 대조 — 인명 suspects 와 분리
        # (합치면 body 만 오염된 케이스에 불필요한 원문 제목 폴백이 걸린다)
        club_suspects = detect_club_injection(v, src_text, club_map)
        title_ko = v["title_ko"]
        retry = bool(r0.get("summary_ko"))
        if suspects and retry:
            logging.getLogger(__name__).warning(
                "제목 환각 재발 — 원문 제목 폴백 content_hash=%s 의심=%s", h, suspects)
            title_ko = r0.get("title_original")
        elif (suspects or omissions or club_suspects) and not retry:
            logging.getLogger(__name__).warning(
                "재번역 큐 content_hash=%s 환각의심=%s 단신누락=%s 구단주입=%s",
                h, suspects, omissions, club_suspects)
            title_ko = None
        if omissions and retry:
            logging.getLogger(__name__).warning(
                "라운드업 단신 누락 잔존 — 수동 확인 content_hash=%s 누락=%s", h, omissions)
        if club_suspects and retry:
            logging.getLogger(__name__).warning(
                "무근거 구단명 잔존 — 수동 확인 content_hash=%s 구단=%s", h, club_suspects)
```

- [ ] **Step 4: 전체 테스트 · 임포트 검증**

Run: `uv run pytest -q`
Expected: 전체 통과 (통합 테스트는 DB · Airflow 없으면 skip — 기존과 동일)

Run: `uv run python -c "import bullet_in.run"`
Expected: 임포트 에러 없음 (배선 문법 검증 — run.py 단위 테스트는 기존에도 없음 · 선례 #76 · #78 · #80 동일)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/run.py
git commit -m "$(cat <<'EOF'
feat(enrich): 무근거 구단명 게이트 배선 — 재번역 큐 · 잔존 로그

detect_club_injection 을 enrich 저장 루프에 편입한다 (spec §5, 조치 A안).
라운드업 축과 동일 패턴 — 1차 → 재번역 큐, 재발 → 잔존 WARNING.

- 1차 검출: 기존 재번역 큐 (title NULL) 재사용, 로그에 구단주입= 필드 추가
- 재발: 저장 유지 + "무근거 구단명 잔존 — 수동 확인" WARNING
- 인명 suspects 와 변수 분리 — body 만 오염 시 제목 폴백 오발동 방지
- 라운드업 (bbc_gossip) 제외 없음 — 실사례 자체가 라운드업

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 문서 반영 — 런북 4축 · 진단 후속 · 백로그 완료

**Files:**
- Modify: `docs/runbook/2026-07-19-translation-quality-gates-ops.md` (표 · 사전 · 로그 · 등재 규칙 · 스윕 · 롤백)
- Modify: `docs/troubleshooting/2026-07-20-translation-club-name-injection.md` (§6 후속)
- Modify: `docs/superpowers/2026-07-19-post-v1-followup-tracks.md` (§5 완료 처리)

**Interfaces:**
- Consumes: Task 1–3 의 함수명 · 로그 문구 · 사전 파일명
  — 문서와 코드가 1:1 이어야 함 (런북 스니펫 드리프트 함정 `docs/troubleshooting/2026-07-19-runbook-snippet-logic-drift.md`).
- Produces: 없음 (문서 종단).

- [ ] **Step 1: 런북 갱신** — `docs/runbook/2026-07-19-translation-quality-gates-ops.md`

아래 6곳을 수정한다 (§2.2 서식 준수 — 훅 검사).

① 도입부 (1–5행): "게이트 3축 + 표기 사전 2종" → "게이트 4축 + 사전 3종",
도입 PR 나열 끝에 ` · 구단명 주입 (2026-07-20)` 추가.

② §1 제목 "구성 — 게이트 3축과 사전 2종" → "구성 — 게이트 4축과 사전 3종", 표에 행 추가:

```markdown
| 무근거 구단명 | `detect_club_injection` | 번역 4필드 (제목 · 요약 · 3줄 · 본문) 에 생긴 원문 근거 없는 구단명 (학습 지식 주입) | `9956234a` 미들즈브러 (로저스 전 소속 주입) |
```

"**사전 2종**" 불릿 → "**사전 3종**" 으로 바꾸고 항목 추가:

```markdown
  · `config/club_map.yaml` (한글 통용 표기 → 영문 별칭 목록, 검출 전용 — 치환 안 함).
```

③ §2 재검출 불릿에 구단 축 추가:

```markdown
  · 구단명 축: 잔존 WARNING (수동 확인) — 라운드업 축과 동일 (사이클당 1회 재시도).
```

④ §3 로그 해석: 첫 불릿의 로그 문구를 `환각의심=… 단신누락=… 구단주입=…` 으로 갱신하고 항목 추가:

```markdown
- **`무근거 구단명 잔존 — 수동 확인`** — 재번역까지 같은 구단명 주입. 학습 지식 주입형은
  재롤로 안 고쳐질 수 있음 (원문 대조 수동 정정 → 선례: 미들즈브러 REPLACE 정정).
```

⑤ §4 사전 확장 절차에 하위 절 추가:

```markdown
### 4.3. club_map (구단명 검출 사전 — 치환 아님)

1. `clubs` 에 `한글 통용 표기: [영문 별칭 목록]` 추가. 통칭 (Boro · Spurs) 까지 등재해야 오탐이 없다.
2. 짧은 한글 표기의 후행 결합 오매치 (인터뷰 ⊃ 인터 · 로마노 ⊃ 로마) 는 코드 가드 밖
→ 구별 가능한 긴 표기 (인터 밀란 · AS 로마) 로 등재하거나 미등재 (포르투 · 릴).
3. 선행 결합 (시리즈 ⊃ 리즈) 은 `_ko_present` 가드가 방어 — 별도 고려 불필요.
4. 아스날은 미등재 (전 기사가 아스날 문맥이라 신호 없음) · 복수 한글 표기는 각각 등재.
```

⑥ §5 스윕 스니펫에 구단 축 편입 (스니펫 드리프트 방지) — SELECT 에 `summary_ko, summary3_ko` 추가,
import 에 `detect_club_injection` 추가, yaml 로드 · 호출 추가:

```python
from bullet_in.enrich import (detect_title_mistranslation, detect_roundup_omission,
                              detect_club_injection)
club_map = yaml.safe_load(open("config/club_map.yaml"))["clubs"]
```

SELECT 문:

```python
        "SELECT id, source_id, title_original, title_ko, body_source, body_ko, "
        "summary_ko, summary3_ko FROM articles WHERE title_ko IS NOT NULL"
```

루프 말미에 추가:

```python
    c2 = detect_club_injection(r, r["body_source"] or "", club_map)
    if c2: print("구단:", r["id"], c2)
```

⑦ §7 롤백에 한 줄 추가:

```markdown
- 구단명 축만 무력화: `club_map.yaml` 의 `clubs` 를 비우면 no-op (코드 revert 불필요).
```

- [ ] **Step 2: 진단 문서 후속 기록** — `docs/troubleshooting/2026-07-20-translation-club-name-injection.md`

§6 말미에 추가:

```markdown
- **구현 완료 (2026-07-20)**: `detect_club_injection` (게이트 4축) + `config/club_map.yaml` 시드
→ 설계 `docs/superpowers/specs/2026-07-20-club-injection-detector-design.md` ·
  운영 `docs/runbook/2026-07-19-translation-quality-gates-ops.md` §4.3.
```

- [ ] **Step 3: 백로그 완료 처리** — `docs/superpowers/2026-07-19-post-v1-followup-tracks.md` §5

"**무근거 구단명 검출기 보강 (신규 후보, 2026-07-20)**" 항목의 첫 줄을 취소선 + 완료 표기로
(퍼가기 항목과 동일 패턴 — 하위 불릿은 근거 기록으로 유지):

```markdown
- ~~무근거 구단명 검출기 보강 (신규 후보, 2026-07-20)~~ — **완료 (2026-07-20)**:
  `detect_club_injection` 4축 + `club_map.yaml`, spec · 런북 §4.3 참조.
```

- [ ] **Step 4: 훅 통과 확인 · 커밋**

문서 3건 저장 시 PostToolUse 훅 (`check-doc-format.py`) 이 서식을 검사한다 — 훅 경고가 나오면 해당 줄을 §2.2 규칙으로 수정.

```bash
git add docs/runbook/2026-07-19-translation-quality-gates-ops.md \
        docs/troubleshooting/2026-07-20-translation-club-name-injection.md \
        docs/superpowers/2026-07-19-post-v1-followup-tracks.md
git commit -m "$(cat <<'EOF'
docs: 번역 게이트 4축 문서 반영 — 런북 · 진단 후속 · 백로그 완료

무근거 구단명 검출기 구현에 맞춰 운영 문서를 코드와 1:1 로 동기화한다
(스니펫 드리프트 함정 방지 — 스윕에 구단 축 편입 포함).

- 런북: 4축 표 · 사전 3종 · 잔존 로그 해석 · club_map 등재 규칙 §4.3 ·
  스윕 스니펫 구단 축 · 롤백 (clubs 비우면 no-op)
- 진단 문서 §6: 구현 완료 후속 (spec · 런북 링크)
- 백로그 §5: 검출기 항목 완료 처리 (취소선 + 참조)

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>
EOF
)"
```

---

## 완료 후 (계획 밖 — 세션 컨트롤러 몫)

- push + PR 생성 (7섹션 본문 · `--body-file` · Claude 서명 금지) — **머지는 사용자 직접** (머지 대기 보고).
- 라이브 실효 확인은 머지 후 다음 enrich 회차의 WARNING 로그 관찰 (신규 번역 유입 시)
— 게이트는 결정적 후처리라 회차 비용 없음.
