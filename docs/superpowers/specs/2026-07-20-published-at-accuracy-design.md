# 발행 시각 정확화 설계 — 추출 보강 · 폴백 · 정밀도 정렬 (2026-07-20)

서빙 "최신순" 이 실제로는 수집 · 처리 순으로 동작하는 문제의 해소 설계.
7-19 수동 회차 실측에서 HTML 스크랩 · fmkorea 4건의 `published_at` 이 전부 파이프라인 처리 시각 (13:37:02) 으로 동일했고,
동률의 안정 정렬이 적재 순서를 노출해 최신 소식 (fmkorea 디오망데) 이 구 소식 (skysports Rogers 추진) 뒤로 밀렸다.

## 1. 문제

- `_sorted_latest` 는 `published_at` 내림차순인데, `published_at` 의 의미가 소스별로 다르다.
  - 실발행 시각: RSS · Guardian API · 공홈 API (`published`) · X (`created_at`).
  - 폴백: HTML 스크랩 (skysports · bbc · football_london · goal) · fmkorea 는 어댑터가 발행 시각을 안 넣어
    `pipeline._published()` 가 **처리 시각 `now()`** 로 폴백.
- 폴백 행은 회차 내 전부 동일 값 → 동률 → 적재 순서가 곧 노출 순서.
- revision 재수집 시 `published_at=VALUES()` 로 덮어써 폴백 행은 매번 현재 시각으로 재부상.
- 발행 시각이 날짜까지만 제공되는 기사 (day 정밀도) 는 시분 기사와의 상호 순서를 알 수 없고, UI 도 구분을 표시하지 않는다.

## 2. 목표 · 비목표

- 목표 A (트랙 A): 어댑터가 실발행 시각을 추출하고, 폴백 의미를 "수집 시점" 으로 명확화하며, 정렬 동률을 결정화한다.
- 목표 B (트랙 B): 정밀도 (day/time) 를 저장 · 정렬 · 표시에 반영해 "실제보다 정밀한 척" 을 없앤다.
- 비목표: 기존 행 `published_at` 소급 백필 (별도 판단) · 스케줄 가동 (별개 결정 사안) · bbc_gossip 등 기사 페이지 미fetch 경로의 추출 (폴백 유지).

## 3. 트랙 A — 발행 시각 추출 · 폴백 · 보조 정렬 (PR 1)

트랙 경계: precision 은 트랙 A 에서 추출돼 `raw_payload` 까지만 실리고 (전방 호환), DB 영속화 · 정렬 · 표시 반영은 트랙 B (§4) 가 담당한다.

### 3.1. `meta.extract_published_at(html) -> tuple[datetime, str] | None`

기사 페이지 HTML 에서 발행 시각과 정밀도를 추출하는 순수 함수.
반환은 (UTC datetime, precision) — precision 은 §4.1 의 `'time'` | `'day'`.

우선순위 (첫 성공 채택):
1. JSON-LD `datePublished` — `@graph` · 리스트 · dict 변형은 기존 함정 문서
   (`2026-07-16-json-ld-author-extraction-traps.md`) 의 순회 방식 재사용.
2. `<meta property="article:published_time" content=…>`.
3. `<time datetime=…>` 첫 요소.

- 파싱은 `dateutil` (기존 `_published` 와 동일 계열) · tz 없는 값은 UTC 로 간주 후 UTC 정규화.
- 값 문자열에 시각 성분이 없으면 (`YYYY-MM-DD` 꼴) precision `'day'`, 있으면 `'time'`.
- 미발견 · 파싱 실패는 `None` (폴백은 pipeline 몫).

### 3.2. HtmlAdapter — 기사 페이지에서 추출

- `body_selector` 경로는 이미 기사 페이지 (`rb.text`) 를 fetch 하므로 그 자리에서 `extract_published_at` 호출
→ 성공 시 `raw_payload["published"]` (ISO 문자열) + `raw_payload["published_precision"]`.
- 기사 페이지를 fetch 하지 않는 소스 (bbc_gossip 라운드업) 는 무변경 — 폴백 (수집 시각) 유지.

### 3.3. fmkorea — 경로별 발행 시각

- 무료 경로: 원문 페이지 (`ro.text`, 이미 fetch 중) 에서 `extract_published_at`.
- 페이월 · 퍼가기 경로 (원문 미fetch · 실패 포함): fmkorea 게시 시각 셀렉터 **`.rd_hd .date`** (실DOM 확정, 예: `2026.06.11 10:04`) 파싱.
  - 표기는 KST → `Asia/Seoul` 로 해석 후 UTC 변환, precision `'time'`.
  - 셀렉터 미발견 · 파싱 실패는 미설정 (폴백).
- 게시 시각은 소식 시점의 근사로 충분하다 (번역러가 원문 직후 게시하는 관행).

### 3.4. pipeline 폴백 · 정렬 동률 결정화

- `_published()` 폴백을 `now()` → **`item.fetched_at`** 으로 변경
— 의미가 "수집 시점" 으로 고정되고, 회차 내 소스별 fetch 순서 (초 단위 차이) 도 보존된다.
- `_sorted_latest` 정렬 키를 `(published_at, fetched_at)` 내림차순으로 — 동률 순서를 결정화.
- revision 덮어쓰기 (`published_at=VALUES()`) 는 유지
— 추출값은 재수집에도 안정적이라 무해하고, 폴백 행의 재부상은 "갱신된 기사" 라 피드 관점에서 자연.

## 4. 트랙 B — 정밀도 저장 · 보간 정렬 · 표시 (PR 2)

### 4.1. `published_precision` 컬럼

- `articles.published_precision VARCHAR(4)` (`'time'` | `'day'`) · 멱등 ALTER · nullable.
- 채움: 어댑터 추출값 (§3.1~3.3) → pipeline → upsert (revision 시 `VALUES()` 갱신).
- 폴백 (fetched_at) 행과 기존 행 (NULL) 은 `'time'` 취급 — 표시 · 정렬 동작이 현행과 동일.

### 4.2. 수집순 보간 정렬 (채택 결정)

- day 기사의 정렬용 유효 시각 = `clamp(fetched_at, 발행일 00:00:00, 발행일 23:59:59)`
→ 그날 카드들 사이에서 수집 시점 자리에 배치 (목록 노출 순서 ≈ 발행 순서 근사).
- 시분 기사 · NULL precision 은 `published_at` 그대로.
- 구현: render 에 `_sort_ts(row) -> (datetime, datetime)` 순수 헬퍼, `_sorted_latest` 가 사용.
- 클램프가 있어 fetch 가 발행일보다 늦어도 (수일 뒤 수집) 다른 날짜로 새지 않는다.

### 4.3. 표시 — 정밀한 척 금지

- `humanize_when` 계열에서 precision `'day'` 는 상대 시각 ("N시간 전") 대신 날짜만 표시 — "7월 19일" (당해 연도 생략 · 그 외 "2025년 7월 19일").
- 카드 · 상세 페이지 동일 규칙.

## 5. 데이터 흐름 변경 요약

```
adapter (published + precision 추출)
  → RawItem.raw_payload
  → pipeline._published (폴백 = fetched_at) · Article.published_precision
  → mart upsert (published_at · published_precision, revision 시 VALUES 갱신)
  → serve _sort_ts (day = fetched_at 클램프 보간) · humanize_when (day = 날짜만)
```

## 6. 엣지 · 함정

- **JSON-LD 변형**: `@graph` 내장 · 배열 루트 · `datePublished` 부재 — 기존 함정 문서의 순회를 재사용하고 테스트로 고정.
- **tz 처리**: 사이트별 오프셋 표기 (`+01:00` 등) 는 dateutil 이 흡수, naive 값은 UTC 간주 (오차 최대 수 시간 — 폴백보다 정확).
  fmkorea `.rd_hd .date` 만 KST 명시 해석.
- **미래 시각 방어**: 추출값이 `fetched_at + 1h` 를 넘으면 오파싱으로 보고 버린다 (폴백 경로로).
- **fmkorea `.date` 다중 매칭**: 목록 위젯에도 `.date` 가 있어 (실측 7개) 반드시 `.rd_hd` 스코프로 첫 요소만.
- **bbc_gossip**: 기사 페이지 미fetch 라 추출 불가 — 폴백 유지가 의도된 동작 (비목표 명시).

## 7. 테스트 · 검증

- TDD 단위: `extract_published_at` (JSON-LD · meta · time 태그 · day 정밀도 · 미래 시각 방어 · 미발견), fmkorea 게시 시각 (KST 변환 · 스코프), `_published` 폴백 = fetched_at, `_sort_ts` (보간 · 클램프 · 동률), `humanize_when` day 표시.
- 회귀: 기존 어댑터 · render 스위트 그린 유지.
- 라이브 스팟: skysports · bbc 실기사 1건씩 `extract_published_at` 값 확인, fmkorea 는 세션 저장 실DOM 3건 재사용 (추가 접촉 없음).
- 종단: 수동 회차 1회 후 인덱스 카드 순서가 발행 시각 순인지 확인.

## 8. 파일 변경 목록

| 파일 | 트랙 | 변경 |
|---|---|---|
| `src/bullet_in/adapters/meta.py` | A | `extract_published_at` 신설 |
| `src/bullet_in/adapters/html.py` | A | 기사 페이지에서 추출 → payload |
| `src/bullet_in/adapters/fmkorea.py` | A | 원문/게시 시각 경로별 추출 |
| `src/bullet_in/pipeline.py` | A · B | 폴백 fetched_at · precision 전달 |
| `src/bullet_in/serve/render.py` | A · B | `(published_at, fetched_at)` → `_sort_ts` 보간 · day 표시 |
| `src/bullet_in/storage/schema.sql` · `mariadb.py` | B | `published_precision` 컬럼 · upsert |
| `src/bullet_in/models.py` | B | `Article.published_precision` |
| `tests/` | A · B | 상기 단위 테스트 |

## 9. 롤백

- 트랙 단위 git revert 가능 (A 는 스키마 무변경, B 의 컬럼은 nullable 이라 revert 후에도 무해).
- 추출이 오동작해도 폴백 (수집 시각) 으로 강등될 뿐 수집 · 번역 경로는 무영향.

## 10. 참고

- 진단 근거: 이 문서 §1 실측 (7-19 회차) · `serve/render.py:452` · `pipeline.py:20`.
- JSON-LD 함정: `docs/troubleshooting/2026-07-16-json-ld-author-extraction-traps.md`.
- 백필 선례 (소급 교정 시): `docs/runbook/2026-07-15-tone-backfill-ops.md` 계열.
