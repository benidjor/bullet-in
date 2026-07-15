# 기자 중심 트랙 — 저자 추출 · 기자 tier · 기자 facet · 상세 필터 이동 설계 (2026-07-16)

본문 컨벤션 묶음 (#50–#53) 종결 후의 다음 트랙.
기사 페이지에서 저자를 추출해 저장하고, 등재 기자 기준으로 신뢰도를 보정하며, 사이드바에 기자 facet을 신설하고, 상세 페이지의 무동작 필터를 필터된 인덱스 이동으로 바꾼다.
완료 기준은 세 가지 — 신규 · 기존 기사에 기자가 표시되고, 등재 기자 기사의 tier가 규칙대로 보정되며, 상세 페이지에서 필터 적용 시 필터가 걸린 인덱스로 이동하는 것.

## 배경 · 문제

- `journalist` 채움 현황 (2026-07-15 라이브 DB): x_afcstuff 13/13 · fmkorea 6/21만 채워져 있고, html 소스 274건 (football_london 205 · bbc_gossip 41 · goal 12 · skysports 10 · bbc_sport 6) 은 전부 NULL이다.
- 고정 소스의 tier는 `sources.yaml`의 소스 단위 값으로만 산출된다 (`credibility.py:resolve_tier`).
  등재 기자가 쓴 기사도 소스 tier에 머문다 — 기자 레지스트리 조회는 동적 소스 (x · fmkorea) 전용이다.
- 사이드바에 기자 facet이 없고, 상세 페이지 사이드바의 "필터 적용"은 no-op이다 (`app.js` 상세 분기).
  필터 상태가 URL에 남지 않아 상세 → 인덱스로 상태를 전달할 방법 자체가 없다.
- guardian 적재 0건의 원인은 실측으로 확정 — `GUARDIAN_API_KEY`가 `.env`에 추가된 시각 (7/15 19:47) 이 마지막 파이프라인 실행 (7/15 10:26) 이후라, 키가 있는 상태로 실행된 적이 없다.
  키 · 어댑터 모두 단독 fetch로 정상 확인 (필터 통과 3건).
  이 프로젝트는 dotenv 미사용 — 실행 전 `set -a; source .env; set +a` 필수.

## 라이브 실측 (2026-07-16, 소스별 기사 페이지 저자 마크업)

| 소스 | JSON-LD author | 비고 |
|---|---|---|
| bbc_sport | Person × 2 (Alastair Telfer, Sami Mokbel) | 복수 저자 실증, meta는 Facebook URL이라 무용 |
| goal | Person (Moataz Elgammal) | JSON-LD만 |
| football_london | Person (Raff Tindale) | `meta[name=author]` 병존 |
| skysports | Person (Dharmesh Sheth) | 등재 기자 실증 |
| arsenal_official | Person (Arsenal Media) | 조직명 바이라인 → 통칭 대체 |
| guardian | — | API `show-fields=byline`으로 해결, HTML 추출 불필요 |

→ 5/5 html 소스가 JSON-LD로 저자를 노출한다.
소스별 CSS 셀렉터 없이 범용 체인으로 충분하며, 셀렉터 드리프트 감시 대상을 늘리지 않는다.

## 확정 결정 (brainstorming 합의)

- **기자 ↔ 언론사 1:1 소속 전제**: 기자는 단일 언론사 소속으로 매핑한다 (사용자 전제).
  Watts · Romano처럼 특정 매체에 매핑되지 않는 프리랜서는 `outlet` 미지정으로 등재한다.
- **tier 보정 = min 가드 + 소속 일치 조건**: 고정 소스에서 등재 기자가 식별되고 **그 기자의 `outlet`이 기사 소스와 일치**할 때만 `tier = min(기자 tier, 소스 tier)`.
  프리랜서 (`outlet` 미지정) · 미등재 기자는 표시 (바이라인 · facet) 만 하고 tier는 소스 값 유지 (사용자 결정 — "tier를 조정하지 마라").
  동적 소스 (x · fmkorea) 의 기존 기자 조회 경로는 무변경.
- **미등재 기자**: 추출된 이름 그대로 저장 · 바이라인 표시 · facet 집계 포함.
  등재는 지금처럼 `credibility.yaml` 수동 관리.
- **facet 구성**: 등재 기자 (기사 1건 이상) 는 바로 노출, 미등재 기자는 "더보기" 토글 뒤 (사용자 결정).
  표기는 `기자 (언론사)` 형식 — 등재 기자는 레지스트리 `outlet`, 미등재는 수집 소스의 언론사, 통칭은 괄호 생략.
- **통칭 바이라인**: arsenal_official → `Arsenal Official`, bbc_gossip → `BBC Gossip` (사용자 결정).
  통칭은 미등재 취급이라 더보기 그룹에 노출된다.
- **복수 저자 = 대표 1명**: `journalist` 컬럼은 단일 문자열 유지.
  복수면 레지스트리 등재자 우선, 없으면 첫 번째 (실증: BBC의 Telfer + Mokbel → Mokbel).
- **백필 전건**: html 4소스 `journalist IS NULL` 약 233건 재fetch + 통칭 2소스 일괄 UPDATE.
  raw 저장소에 원본 HTML이 없어 재fetch가 유일한 경로.
- **프랑스 매체 등재**: L'Équipe tier 2 · RMC Sport tier 1 · Foot Mercato tier 4 (사용자 결정).
- **③ 상태 전달 = URL 쿼리 파라미터**: 필터 상태를 쿼리로 직렬화 — 북마크 · 공유 가능, 뒤로가기 시 상태 유지.

## 설계

### 1. 추출 — 범용 체인 + 대표 선정 (`meta.py` · `html.py` · `guardian_api.py` · `pipeline.py`)

`meta.py`에 공통 함수 `extract_authors(html) -> list[str]`를 신설한다 (기존 `extract_og_image` · `extract_body_images` 옆).

- `<script type="application/ld+json">` 전부 순회 → 트리 재귀 탐색으로 `author` 필드 수집 (dict의 `name`, 문자열형 허용).
  등장 순서 보존 · 중복 제거.
- 비었으면 `meta[name=author]` 폴백.
- URL 형태 값 (`article:author`의 Facebook URL 등) · 빈 문자열 배제.
- JSON 파싱 실패는 조용히 건너뛴다 — 저자 추출 실패가 기사 적재를 막지 않는다.

연결 지점 — 전부 이미 받아온 응답 재사용, 추가 네트워크 요청 0회:

| 경로 | 연결 지점 |
|---|---|
| html 4곳 (bbc_sport · goal · football_london · skysports) | `html.py` 기사 페이지 fetch 자리에서 `payload["authors"]` 추가 |
| guardian | `show-fields`에 `byline` 추가 → `payload["authors"] = [byline]` |
| arsenal_official · bbc_gossip | 통칭 규칙 (`journalist_label`) 이 대표 선정에서 우선 — 추출 결과는 쓰지 않음 |
| fmkorea · x 어댑터 | 무변경 (`payload["journalist"]` 기존 경로) |

대표 선정은 `pipeline.py:to_articles`에서 수행한다 — 어댑터는 레지스트리를 모르게 유지.

- `payload["journalist"]`가 이미 있으면 그대로 (동적 소스 경로).
- 없고 소스에 `journalist_label`이 설정돼 있으면 그 통칭 (`sources.yaml` 신규 옵션 — arsenal_official: `Arsenal Official`, bbc_gossip: `BBC Gossip`).
- 없으면 `payload["authors"]`에서 레지스트리 등재자 우선 · 없으면 첫 번째.

### 2. 레지스트리 · tier 보정 (`credibility.yaml` · `credibility.py` · `sources.yaml`)

`config/credibility.yaml`:

- 기자 항목에 `outlet:` 필드 추가 (옵션).
  소속 확인 가능한 기자만 기입 — Ornstein · McNicholas · Lawrence · de Roché (The Athletic), Mokbel (BBC), Sheth (Sky Sports), Olley (ESPN), Jacob (The Times), Collings (Evening Standard), Di Marzio (Sky Italia), Dean · Law (The Telegraph), Delaney (The Independent).
  프리랜서 (Watts · Romano) · X 계정 (handofarsnal · Teamnewsandtix · LatteFirm) 은 미지정.
- outlets에 3곳 등재: `{name: L'Équipe, tier: 2}` (aliases: 레키프 · L'Equipe · lequipe), `{name: RMC Sport, tier: 1}` (aliases: RMC · RMC 스포르), `{name: Foot Mercato, tier: 4}` (aliases: 풋 메르카토 · footmercato).

`config/sources.yaml`:

- 고정 소스에 `outlet:` 필드 추가 — 레지스트리 outlet 정식 명칭 참조 (bbc_sport · bbc_gossip → BBC, skysports → Sky Sports, goal → Goal.com, football_london → football.london, guardian → The Guardian, arsenal_official → Arsenal.com).
  기자 소속 일치 판정과 미등재 기자의 facet 언론사 표기에 쓴다.
- `journalist_label` 옵션 신설 (§1).

`credibility.py`:

- `load_registry`: 기자 조회 키에 정식 `name`도 포함 (현재 aliases만 — html 추출 결과는 "Sami Mokbel" 같은 풀네임이라 매치 불가).
  소문자 정규화 · 완전 일치, 중복 검사 유지.
  기자별 `outlet` 조회를 함께 제공한다.
- `resolve_tier` 고정 소스 경로: 항목의 journalist가 등재 기자이고 그 기자의 `outlet`이 소스의 `outlet`과 일치하면 `min(기자 tier, 소스 tier)`, 아니면 기존대로 소스 tier.

실증 예시 — Sheth (outlet: Sky Sports) @ skysports → `min(1.5, 1.5)` = 1.5, Watts (프리랜서) @ goal → 4 유지 · 표시만, 미등재 Tindale @ football_london → 4 유지.

### 3. 서빙 — 기자 facet · URL 필터 상태 · 상세 이동 (`render.py` · 템플릿 · `app.js`)

`render.py`:

- `facet_counts`에 `journalists` 추가 — `journalist` 값 집계 후 두 그룹으로 분리 (NULL 제외, 각 건수순).
  등재 그룹: 레지스트리 등재 기자, `기자 (언론사)` 표기.
  더보기 그룹: 미등재 기자 + 통칭.
- **집계 전 정규화 필수**: fmkorea (한글 말머리 "온스테인") · x (핸들) 의 저장값을 레지스트리 alias → 정식명 맵 (기존 `journalist_display_names`) 으로 정규화한 뒤 집계한다.
  정규화 없이는 같은 기자가 facet에서 갈라지고 필터 매칭이 깨진다.
- `_decorate`의 `_byline`도 동일한 `기자 (언론사)` 표기를 적용해 카드 · 상세 · facet이 일관되게 보이도록 한다.

템플릿:

- `_layout.html.j2`: "소스 (언론사)" 아래 "기자" 섹션 신설 — 등재 그룹 바로 노출, 더보기 그룹은 "더보기 N명" 토글 뒤.
  체크박스 `data-group="journalist"`, 값은 정규화된 기자 정식명 (괄호 언론사 제외).
- `index.html.j2`: 카드에 `data-journalist` 속성 추가 (체크박스와 같은 정규화 정식명 — 값이 다르면 필터 매칭 실패), DOM contract 주석 갱신.

`app.js`:

- `applyFilters`에 journalist 그룹 추가 (outlet과 동일한 OR 매칭).
- URL 동기화: 인덱스에서 필터 적용 시 체크 상태 · 검색어를 `history.replaceState`로 쿼리 파라미터에 기록, 로드 시 `URLSearchParams`로 체크박스 복원 후 자동 적용.
  직렬화 대상은 기존 · 신규 그룹 전부 — outlet · tier · stage · other · journalist · 정렬 · 검색어 `q`.
  초기화 버튼은 쿼리도 지운다.
- 상세 페이지: no-op 분기 제거 — "필터 적용" 클릭 시 체크 상태를 쿼리로 직렬화해 `{root}index.html?…`로 이동.
- 더보기 토글: 클래스 토글 몇 줄로 처리 (라이브러리 없음).

### 4. 백필 — 1회성 스크립트 (`scripts/backfill_journalist.py` 신설)

`scripts/` 디렉터리를 신설한다 (1회성 운영 스크립트의 첫 사례 — 기존 백필은 run 사이클 통합형 tone뿐).

- 대상 1 (재fetch 불필요): arsenal_official · bbc_gossip 전건 → 통칭 일괄 UPDATE.
- 대상 2 (재fetch): bbc_sport · goal · football_london · skysports의 `journalist IS NULL` 약 233건.
  기사 URL 재fetch → `extract_authors` → 대표 선정 → `journalist` UPDATE.
  §2 조건 충족 시 `tier` · `confidence_score` 재산출.
- 소스별 순차 실행 · 요청 간격 1–2초.
- `--limit N` 드라이런 옵션으로 소량 검증 후 전건 실행.
- 멱등 — 재실행 시 NULL 건만 재시도.
- 실패 (404 · 타임아웃 등) 는 NULL 유지 · 건너뛰고, 종료 시 소스별 성공 / 실패 집계를 출력한다.
- 실행 전 `set -a; source .env; set +a` 필수 (guardian 스킵 사례 — "배경 · 문제" 참조).
- guardian은 적재 0건이라 백필 대상 없음 — 신규 수집분부터 byline이 붙는다.

## 에러 처리

- `extract_authors`: JSON-LD 파싱 실패 · author 부재 시 빈 목록 → `journalist` NULL (기존 기사와 동일 동작).
- guardian `byline` 필드 부재 → `authors` 빈 목록 → NULL.
- 백필 재fetch 실패는 해당 건 스킵 — 파이프라인 · 사이트 생성에 영향 없음.

## 테스트 · 검증

단위 테스트:

- `extract_authors` — 실측 5소스 HTML 축약 픽스처: JSON-LD 복수 저자 · 문자열형 author · `meta[name=author]` 폴백 · URL 값 배제 · 파싱 실패.
- 대표 선정 (`to_articles`) — 등재자 우선 · 첫 번째 폴백 · `journalist_label` 통칭 · 기존 `journalist` 우선.
- `load_registry` — `name` 키 포함 · `outlet` 조회.
- `resolve_tier` — min 가드 (소속 일치) · 프리랜서 비조정 · 미등재 비조정 · 동적 소스 무변경.
- `facet_counts` — 등재 / 더보기 분리 · NULL 제외 · 표기 형식 · alias → 정식명 정규화 (fmkorea 한글 말머리 · x 핸들).

라이브 검증 (머지 전, 컨벤션 준수):

- html 어댑터 단독 `fetch()`로 4소스 `authors` 채움 확인 + guardian byline 확인 (guardian 어댑터 자체는 2026-07-16 단독 fetch 검증 완료).
- 백필 `--limit 5` 드라이런 → 전건 실행 → 채움률 쿼리 검증.
- 사이트 재생성 후 기자 facet · 더보기 · 상세 필터 이동 · URL 복원 육안 확인.

## 범위 외 (이번 트랙에서 하지 않음)

- 미등재 기자 등재 유도 파이프라인 (ops 빈도 집계 등).
- 복수 저자 전체 보존 (`journalist`는 대표 1명 유지).
- 기자별 상세 · 프로필 페이지.
- 트랙 ③ (문서 · 캡처) — 이 트랙 종료 후, 기자 바이라인이 반영된 화면으로 1회 캡처.
