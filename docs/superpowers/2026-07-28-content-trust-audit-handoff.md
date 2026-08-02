# 콘텐츠 신뢰성 감사 — 발견 정리 · 인수인계 (2026-07-28)

선수 명단 DB화를 설계하려다 그 전제가 되는 데이터 품질 문제 넷을 발견해 트랙을 나눈 기록이다.
발견은 전부 배포판 (VM) 데이터 실측이며, 재현 절차와 스크립트를 그대로 싣는다.
다음 세션이 같은 측정을 처음부터 다시 하지 않게 하는 것이 이 문서의 목적이다.

## 1. 어쩌다 여기까지 왔나

- PR #144 (선수 색인 · 선수 페이지) 는 선수 명단을 `config/name_map.yaml` 에 의존한다.
사전 밖 선수는 페이지가 생기지 않아 사용자 지시로 **머지 보류 · draft 전환** 했다.
- 대체 설계 (기사에서 선수를 LLM 으로 추출) 를 논의하던 중, 그 설계가 기대는 두 값 — 기사 본문과 영입 단계 — 이 모두 신뢰하기 어렵다는 것이 드러났다.
- 선수 추출은 본문을 읽어 판단하고 단계를 승계하므로, 본문과 단계가 오염돼 있으면 추출도 함께 오염된다.
그래서 선수 명단 트랙을 멈추고 아래 넷을 선행 과제로 분리했다.

## 2. 발견 1 — 원문 없이 생성된 본문 149건 (가장 시급)

### 2.1. 확인된 사례

- 기사: `아스날, 올여름 선수 15명 방출 확정…구단 전설 2인 포함`
- 배포판: https://bullet-in.pages.dev/article/096b26b9772dc5374ce5b83da59c5c575ee9fc7c484db9004a2b955a3580310f
- 원문: https://www.football.london/arsenal-fc/news/arsenal-confirm-15-players-set-34064323

DB 필드 길이는 다음과 같다.

| 필드 | 길이 |
| --- | --- |
| `title_original` | 78자 |
| `body_excerpt` | **0자** |
| `body_source` | **0자** |
| `body_ko` | **1,105자** |
| `summary3_ko` | 408자 |

원문 본문이 한 글자도 없는데 한국어 본문 1,105자가 생성돼 있다.
모델이 가진 재료는 영어 제목 한 줄뿐이었는데, 산출물에는 방출 선수 15명의 이름이 나열돼 있다
(모하메드 엘네니 · 세드릭 소아레스 · 아서 오콩쿼 · 찰리 패티노 · 알렉스 커크 등).
제목에는 "15명" 과 "구단 전설 2인" 만 있었으므로 **명단 전체가 생성된 것**이다.
사용자가 원문과 대조해 없는 사실임을 확인했다.

### 2.2. 범위 — 이 기사 하나가 아니다

```sql
SELECT COUNT(*) FROM articles
WHERE (body_source IS NULL OR body_source='')
  AND body_ko IS NOT NULL AND body_ko<>'';
-- 149건

SELECT COUNT(*) FROM articles
WHERE (body_source IS NULL OR body_source='')
  AND body_ko IS NOT NULL AND body_ko<>''
  AND COALESCE(LENGTH(body_excerpt),0) < 200;
-- 149건 (전부 — 발췌마저 없음)
```

배포판 467건 중 **149건 (32%)** 이 같은 구조다.
전부 같은 방식으로 생성됐으므로 같은 위험을 안고 있다.
실제 오류율은 원문 대조로만 알 수 있으나, 근거 없이 생성됐다는 사실 자체는 확정이다.

### 2.3. 선례

- `docs/troubleshooting/` 계열의 헤드라인-온리 엔티티 오특정 (Vinicius Jr → 카를로스 오역) 과 같은 뿌리다.
그때는 인명 오역으로, 이번에는 명단 생성으로 드러났다.
- 세션 메모리 `collection-audit-findings-2026-07-26` 의 세 번째 항목이 이 문제이며 후속이 미확정 상태였다.

### 2.4. 정해야 할 것

- 149건 처리 — 본문 재수집 후 재번역 · 요약만 남기고 본문 삭제 · 서빙 제외 중 선택.
- 재발 방지 — 원문 본문이 없으면 본문 생성을 아예 막을지 (게이트), 아니면 제목 기반 생성을 허용하되 표시를 다르게 할지.
- 전면 재번역 범위 — 149건만인지, 번역 모델 교체 이전 행 전체인지.

## 3. 발견 2 — 영입 단계 재현 오분류 110건

### 3.1. 구조적 원인

`run.py` 는 `rows_missing_stage()` 로 `WHERE transfer_stage IS NULL` 인 행만 분류한다.
**한 번 값이 박히면 다시 분류되지 않는다.**
프롬프트를 개선해도 (#147 등) 기존 기사는 옛 판정을 유지한다.

### 3.2. 실측 (배포판 461건 · 규칙 경로 제외)

현재 프롬프트로 두 번 재분류해 모델 흔들림과 실제 차이를 갈랐다.

| 구분 | 건수 |
| --- | --- |
| 모델 흔들림 (2회차가 서로 다름) | 43건 (9%) |
| 저장값과 일치 (2회 모두) | 308건 (67%) |
| **재현되는 불일치** (2회 동일 · 저장값과 다름) | **110건 (24%)** |

BBC 가십 26건은 소스 단위 루머 롤업이라 화면이 바뀌지 않으므로, 실제 배지가 바뀌는 것은 **84건**이다.

방향은 루머 이탈이 압도적이다.

| 저장값 | 재분류 | 건수 |
| --- | --- | --- |
| rumour | interest | 29 |
| rumour | other | 18 |
| other | agreed | 7 |
| interest | rumour | 6 |
| other | interest | 6 |

### 3.3. 티어는 무관하다

| 티어 | 대상 | 재현 불일치 |
| --- | --- | --- |
| 1.0 | 64 | 16건 (25%) |
| 1.5 | 28 | 3건 (11%) |
| 2.0 | 44 | 9건 (20%) |
| 3.0 | 22 | 4건 (18%) |
| 4.0 | 303 | 78건 (26%) |

티어 1 과 티어 4 가 사실상 같다.
티어는 소스 신뢰도이지 분류 정확도가 아니다.
소스별로는 BBC 가십 49% 가 압도적이고 (모음글에 단계 하나를 붙이는 구조적 한계), guardian 0% · bbc_sport 8% 가 낮다.

### 3.4. 재분류 절차

`docs/runbook/2026-06-30-transfer-stage-classification-ops.md` 3절에 이미 있다.
`transfer_stage` 를 NULL 로 되돌리면 다음 분류 패스가 현재 프롬프트로 전부 다시 매긴다.
2026-07-19 에 201건으로 실행해 1패스 수렴한 기록이 있고, 지금은 461건이라 24회 호출이다.

실행 전 `content_hash` 와 `transfer_stage` 를 덤프해 둘 것.
되돌릴 수 없다.
공홈 규칙 분기 (`rule_stage`) 를 반드시 포함해야 `official` 이 유실되지 않는다.

### 3.5. 재분류로 풀리지 않는 것 — 방출 축 부재

현재 단계 체계 (rumour · interest · negotiating · personal_terms · medical · agreed · official · other) 는 전부 영입 관점이다.
방출을 담을 값이 없어 같은 성격의 기사가 흩어진다.
제목에 방출 · 이탈 어휘가 있는 기사 16건의 분포는 기타 8 · 루머 4 · 이적 합의 3 · 관심 1 이다.

- https://bullet-in.pages.dev/article/096b26b9772dc5374ce5b83da59c5c575ee9fc7c484db9004a2b955a3580310f
— `아스날, 올여름 선수 15명 방출 확정` → 기타
- https://bullet-in.pages.dev/article/cb0894b71f0692d35aef7c2c21184ba883da0a48ff648264b0bc7bf5bf0fe905
— `레안드로 트로사르, 베식타스 완전 이적…아스날 떠난다` → 이적 합의 (방출인데 영입 뉘앙스 배지)
- https://bullet-in.pages.dev/article/b38deb05d7cd113cecb73997b3d43fbb9c072cd2367355ec73eb2bf3330ac294
— `아스날, 가브리엘 제주스 매각 및 훌리안 알바레스 영입설` → 루머

체계에 방출 축을 추가할지 결정이 필요하다.
프롬프트 개선으로는 풀리지 않는다.

## 4. 발견 3 — football.london 제거 (사용자 확정)

- 사용자 판단: 저품질 기사가 많고, 신뢰할 만한 내용은 상위 티어가 함께 다루므로 불필요.
- 수집 구조: `config/sources.yaml` 의 `football_london` 은 `adapter: html` 로 목록 페이지를 직접 크롤링한다
(`list_url: https://www.football.london/arsenal-fc/` · `item_selector: a.headline`).
`journalist_allowlist: ['Tom Canton']` 이 이미 걸려 있는데도 배포판에 95건이 적재돼 있다.
- **허용 범위**: 애그리게이터 (afcstuff) 가 트윗에서 언론사 원문으로 승격시키는 경로 (`x_backtrack`) 로 들어오는
Tom Canton 기사는 계속 허용한다.
이 경로는 `football_london` 소스와 별개로 동작하므로 소스를 비활성화해도 유지된다.
- 정해야 할 것: `enabled: false` 로 수집만 끊을지, 기존 95건 (배포판의 20%) 을 서빙에서 내릴지 · 삭제할지.

## 5. 발견 4 — '기타' 는 필터가 아니라 토글

`static/app.js` 의 판정부다.

```js
const isOther = !d.stage || d.stage === 'other';
const okStage = isOther ? showOther
  : (stageEnums.size === 0 || stageEnums.has(d.stage));
```

기타만 체크하면 단계 체크박스는 비어 있으므로 `stageEnums.size === 0` 이 참이 되어,
**기타가 아닌 카드가 전부 통과한다.**
즉 기타를 켜도 다른 단계가 걸러지지 않고 기타 카드가 추가로 보일 뿐이다.

사용자가 기타로 거른 뒤 이적 합의 기사를 발견한 것이 이 동작 때문이다
(https://bullet-in.pages.dev/article/032cbf87a2b3492494192b01d766ba9d755243f8f1b407d70d3cc91bd90162b2 — 기사 자체는 정상).

설계 의도 (기본 숨김인 기타를 마저 보여주는 토글) 는 타당하나, 사이드바의 단계 목록 옆에 건수까지 달고 있어
다른 체크박스와 같은 것으로 읽힌다.
기타를 진짜 단계 필터로 바꾸거나, 토글임이 드러나게 UI 를 분리하는 두 갈래가 있다.

## 6. 조사 방법 — 재사용용

### 6.1. VM 덤프 (읽기 전용 · 로컬 기존 DB 무영향)

`docs/runbook/2026-07-22-mockup-rerender-from-vm.md` 절차 그대로다.
로컬 `bulletin` 은 건드리지 않고 `bulletin_mock` 에 적재한다.

**2026-07-28 실측 — 로컬은 배포판을 대신할 수 없다.**

| 항목 | 값 |
| --- | --- |
| 배포판 (VM) | 467건 · 최종 수집 2026-07-27 21:02 |
| 로컬 스냅샷 | 205건 · 최종 수집 2026-07-19 13:36 |
| 양쪽 공통 | 198건 |
| 배포판에만 | 269건 |
| 로컬에만 | 7건 |
| **공통 행 중 제목이 다름** | **196건** (재번역으로 거의 전부) |
| 공통 행 중 단계가 다름 | 3건 (#147 의 라이브 수동 정정분) |

제목이 바뀌므로 **기사를 언급할 때는 `content_hash` 기반 배포판 URL 을 함께 적어야 한다.**
제목만 적으면 사용자가 라이브에서 찾지 못한다 (실제 발생).

### 6.2. 단계 감사 스크립트

앱의 `classify_stage_rows` 를 그대로 import 해 프로덕션과 같은 경로로 돌린다.
직접 옮겨 적으면 하네스가 어긋나 가짜 원인을 만든다
(`docs/troubleshooting/2026-07-26-repro-harness-loader-mismatch.md`).

```python
"""배포판 단계 분류 감사 — 2회 실행으로 흔들림과 실제 불일치를 분리한다. 읽기 전용."""
import collections, json, os, sys
REPO = "<저장소 루트 절대 경로>"
sys.path.insert(0, f"{REPO}/src"); os.chdir(REPO)
from google import genai
from sqlalchemy import create_engine, text
from bullet_in import transfer_stage
from bullet_in.enrich import classify_stage_rows
from bullet_in.run import GEMINI_MODEL

engine = create_engine("mysql+pymysql://root:bulletin@localhost:3306/bulletin_mock")
with engine.connect() as c:
    rows = [dict(r) for r in c.execute(text(
        "SELECT content_hash, source_id, tier, title_original, title_ko, summary_ko, "
        "transfer_stage FROM articles WHERE transfer_stage IS NOT NULL")).mappings().all()]
# 2026-08-02 방향 축 도입으로 rule_stage 가 (stage, direction) 튜플을 반환하게 됐다
# (스펙 §4) — 항상 truthy 이므로 첫 원소로 판정해야 한다.
target = [r for r in rows if transfer_stage.rule_stage(r["source_id"])[0] is None]

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
runA = classify_stage_rows(target, client, GEMINI_MODEL)
runB = classify_stage_rows(target, client, GEMINI_MODEL)

stored = {r["content_hash"]: r["transfer_stage"] for r in target}
common = set(runA) & set(runB)
noise = [h for h in common if runA[h] != runB[h]]
solid = [h for h in common if runA[h] == runB[h] and runA[h] != stored[h]]
print(f"흔들림 {len(noise)} · 재현 불일치 {len(solid)} / 공통 {len(common)}")
```

**대조군 (2회 실행) 은 반드시 포함할 것.**
1회만 돌리면 모델 흔들림과 실제 오분류를 구분할 수 없다.
로컬 200건 1회 감사에서는 38% 가 나왔으나, 대조군을 붙이자 흔들림이 4~9% 로 드러났다.

### 6.3. 선수 추출 스파이크 결과 (선수 명단 트랙 재개 시 입력)

기존 `classify_stage_rows` 와 같은 배치 형태로 초안 프롬프트를 1회 호출해 20건을 관찰했다.

- **사전 밖 선수가 실제로 잡힌다** — 미귀속 6건 중 4건에서 추출 (네이선 브라운 · 크루피 · 맥스 다운먼).
- **감독 제외가 작동한다** — 아르테타 기사 2건에서 선수 0명 반환.
PR #144 에서 지적된 "아르테타가 이적 후보에 뜬다" 문제가 프롬프트 규칙만으로 해소된다.
- **표기 흔들림이 실재한다** — `Guimaraes` 에 한글 표기 3종 (기마랑이스 · 브루노 기마랑이스 · 브루누 기마랑이스),
`Kroupi` 에 2종.
영문명을 동일인 판단 기준으로 삼는 결정이 옳았음이 확인됐다.
- **원문 대조 게이트에 결함이 있다** — 추출 영문명을 원문과 대조하는 방식은 fmkorea 처럼 원문이 한국어인 소스에서
오탈락한다 (실측 2건 · 둘 다 정답).
영문명과 한글 표기를 둘 다 대조해 하나라도 맞으면 통과시켜야 한다.

### 6.4. 사용자 확정 사항 (선수 명단 트랙 재개 시 유효)

- 기사에서 선수를 LLM 으로 자동 추출한다 (큐레이션 명단이 아니라).
- LLM 이 한글 표기와 영문 성을 함께 반환하고, 영문명을 동일인 판단 기준 · slug 원료로 쓴다.
- (선수, 단계) 쌍을 추출한다.
- 원문 대조 자동 게이트를 둔다 (사람 승인 큐가 아니라).
- 적용 범위는 선수 페이지 · 색인 · ops 로 한정하고, 인덱스의 사건 묶음은 `name_map` 기반 현행을 유지한다.
- 유형별 처리 방침은 사용자가 나눈 기사 세 유형을 따른다.
가십 모음글은 루머 통칭 유지 · 선수 1명 기사는 기사 단계를 승계 (LLM 에 묻지 않음) · 선수 2명 이상 기사만 선수별 단계를 묻는다.

## 7. 착수 순서 제안

1. **번역 신뢰성** — 149건 처리 방침 결정 · 재발 방지 게이트.
가장 시급하고 다른 모든 판단의 전제다.
2. **소스 정리** — football.london 제거 + 기존 95건 처리.
1번과 함께 "무엇을 서빙할 것인가" 결정이라 묶어도 된다.
3. **단계 분류** — 전건 재분류 + 방출 축 결정 + 기타 필터 UI.
4. **선수 명단 DB** — 위가 정리된 뒤 재개.
PR #144 (draft) 를 그 위에 얹거나 원천만 교체한다.

## 8. 관련 자료

- 보류 중인 PR: #144 (선수 색인 · 선수 페이지 · ops 미매칭 — draft).
브랜치 `feat/serve-player-pages` · SDD 원장은 워크트리 `.claude/worktrees/serve-filter-fix` 안에 있다.
- 설계 · 계획: `docs/superpowers/specs/2026-07-26-serve-explore-pages-design.md` · `docs/superpowers/plans/2026-07-26-serve-explore-pages.md`.
- 절차: `docs/runbook/2026-07-22-mockup-rerender-from-vm.md` (VM 덤프) ·
`docs/runbook/2026-06-30-transfer-stage-classification-ops.md` (전건 재분류) ·
`docs/runbook/2026-07-26-local-serve-render-verification.md` (로컬 렌더 검증).
- 세션 메모리: `player-roster-db-decision` · `cite-article-urls` · `collection-audit-findings-2026-07-26`.
- 로컬 `bulletin_mock` DB 에 2026-07-28 시점 배포판 사본 467건이 남아 있다.
낡으면 6.1 절차로 다시 받고, 불필요해지면 `DROP DATABASE bulletin_mock` 으로 정리한다.
