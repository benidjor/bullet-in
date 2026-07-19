# 영입 단계 분류 개편 spec — '이적 합의' 신설 · 오피셜 공홈 한정 · 전건 재분류

- 날짜: 2026-07-19
- 트랙: 후속 트랙 ⑤ (백로그 SoT `docs/superpowers/2026-07-19-post-v1-followup-tracks.md` §3)
- 선행: 트랙 ⑥ (#65) — 가십 45건 요약이 전문 기반으로 개선돼 분류 입력 품질 상승 시점

## 1. 배경 · 문제

라이브 점검 (2026-07-19) 에서 단계 분류의 결함 두 가지가 확정됐다.

- **협상과 합의가 안 갈라진다**
— 이적 확정 보도 (`cb0894b7…` 트루사르) 가 official 로, 영입 합의 보도 (`b8055b5b…` 요케레스) 가 negotiating 으로 갈라져 "합의됐다" 는 중간 상태를 표현할 단계가 없다.
- **오피셜이 LLM 판정만으로 부여된다**
— 실측 official 21건 중 arsenal_official (공홈) 소스는 0건.
  전부 타 소스 기사를 LLM 이 official 로 판정한 것으로, 공식 발표와 발표 보도가 구분되지 않는다.

## 2. 확정 결정 (사용자, 2026-07-19)

- **'이적 합의' 는 넓은 의미** — 구단 간 이적료 합의부터 딜 확정 · 임박 보도 (here we go 류) 까지 한 버킷.
  사다리 위치는 오피셜 바로 아래.
- **오피셜 규칙은 규칙 분리** — arsenal_official 소스는 LLM 없이 규칙으로 자동 official,
  LLM 분류 enum 에서는 official 제거 (타 소스는 구조적으로 official 불가).
- SoT §3 기존 확정: 전체 개편 + 매핑 전건 검증, 재분류는 기존 런북 멱등 경로
  (`docs/runbook/2026-06-30-transfer-stage-classification-ops.md`).

## 3. 단계 체계

`transfer_stage.SIDEBAR_STAGES` 에 `("agreed", "이적 합의", "s-agree")` 를 official 다음에 삽입한다.

| 순서 | enum | 라벨 | 비고 |
|---|---|---|---|
| 1 | official | 오피셜 | 공홈 한정 (규칙 경로 전용) |
| 2 | agreed | 이적 합의 | 신설 — 합의 ~ 확정 · 임박 보도 |
| 3 | medical | 메디컬 | 유지 |
| 4 | personal_terms | 개인 합의 | 유지 |
| 5 | negotiating | 협상 중 | 유지 |
| 6 | interest | 관심 | 유지 |
| 7 | rumour | 루머 | 유지 |
| — | other | 기타 | 유지 — 서빙 기본 숨김 토글 불변 |

- enum · 라벨 · css · 순서는 이 모듈 단일 출처에서 전파된다 (템플릿 · facet · 배지 자동).
- 예시 기대 매핑: 트루사르 이적 확정 → agreed · 요케레스 영입 합의 → agreed.

## 4. 분류 규칙

### 4.1 규칙 경로 (official)

- `transfer_stage.rule_stage(source_id) -> str | None` 순수 함수 신설 — arsenal_official → "official" · 그 외 → None.
- run.py 분류 패스에서 미태깅 행을 규칙 대상 / LLM 대상으로 분리한다.
  규칙 대상은 LLM 호출 없이 직접 `set_stage` 한다.
- `rows_missing_stage` SELECT 에 source_id 를 추가한다 (분리 판정 입력).

### 4.2 LLM 경로 (agreed 포함 · official 제외)

- STAGE_PROMPT 에서 official 항목을 제거하고 agreed 정의를 추가한다:
  "구단 간 이적 합의 · 딜 확정 · 임박 보도, 타 매체의 공식 발표 보도 포함".
- 공홈 한정 원칙상 발표 *보도* 는 오피셜이 아니라 이적 합의로 분류된다 (제품 의도).
- 배치 20건 · 429 즉시 중단 · 파싱 실패 배치 스킵 · 미허용값 other 강등은 기존 규칙 그대로.

### 4.3 방어 불변량

- 프롬프트에 없어도 모델이 official 을 반환하면 agreed 로 강등하고 WARNING 을 남긴다.
- 구조적 보장: **official 은 규칙 경로에서만 생성될 수 있다.**

### 4.4 알려진 한계 (관찰 항목)

- 공홈 sign 필터는 재계약 기사도 잡으므로 재계약도 official 배지를 받는다.
  현재 공홈 적재 0건이라 실측 무 — 발생 시 재검토.

## 5. 전건 재분류 (소급)

- 기존 런북 멱등 경로 그대로: 전체 `transfer_stage` NULL 복원 → 분류 패스 재실행.
- fetch 없음 — fmkorea 2h 규칙과 무관, DB 와 Gemini 만 접촉.
- 기존 official 21건도 NULL 복원 → 대부분 agreed 등으로 재분류될 전망.
  공홈 적재 0건이므로 재분류 후 official 0건이 정상이다 (빈 facet 그룹은 자동 생략).
- 파싱 실패 잔존은 최대 3패스 반복으로 수렴시킨다 (enrich 전용 패스 런북과 동일).

## 6. 매핑 검증 (전건 점검)

- **구조 불변량** — official 행의 source_id 가 arsenal_official 뿐인지 SQL 검증 (현재 기대값 = 0건).
- **예시 기대 매핑** — `cb0894b7…` · `b8055b5b…` → 둘 다 agreed.
- **눈검수 리포트** — agreed 전건 제목 목록 + 단계별 전후 분포 비교표를 사용자에게 제시해 최종 점검.
- **수렴 확인** — 미분류 잔존 0 · 재분류 후 사이트 재렌더.

## 7. 서빙 · 스타일

- SIDEBAR_STAGES 삽입으로 사이드바 필터 · 카드 / 상세 배지 자동 반영.
- `style.css` 에 `.s-agree` 배지 색 1줄 추가 (기존 6색과 구분되는 색 — 구현에서 확정).
- dbt 무변경 — transfer_stage 에는 accepted_values 게이트가 없음 (실측).

## 8. 테스트

- `rule_stage` 단위 테스트 (arsenal_official → official · 그 외 None).
- LLM official 반환 시 agreed 강등 방어 테스트.
- 프롬프트 동기화 가드 개정 — LLM enum 집합 = VALID_STAGES − {official} + agreed 포함 검증.
- SIDEBAR_STAGES 파생 (라벨 · css · 순서 · facet) 기존 테스트 갱신.
- 429 · 파싱 실패 · other 강등 기존 테스트 유지.

## 9. 범위 밖

- 제목 환각 검출 · X outlet 칩 (트랙 ③).
- gossip 의 루머 / 기타 갈림 — 기사별 판정으로 버그 아님 (SoT §3 배경 확인).
- 단계 변경 이력 추적 · corroboration.
