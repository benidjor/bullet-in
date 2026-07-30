# 링크 선수 명단 DB 설계 (players · article_players)

2026-07-31 브레인스토밍 확정본.
이적 링크 선수 명단을 `config/name_map.yaml` 에서 MariaDB 테이블로 옮기고,
enrich 자동 발굴 + 사람 확정으로 운영하는 구조를 정의한다.
구현은 별도 트랙 — 이 문서는 스펙까지다.

## 1. 배경 · 목표

- 원 지시 (2026-07-25): 이적 링크가 뜬 선수 명단의 DB 화.
수집 트랙으로 분류돼 미착수인 사이 서빙 스펙이 name_map 재사용으로 확정됐고,
2026-07-27 에 PR #144 (선수 페이지) 머지 보류로 이 설계가 선행 과제가 됐다.
- 현 name_map.yaml 의 한계: 스쿼드 · 감독 21명과 이적 관련 실명 19명이 YAML 주석으로만 구분돼 기계 분리가 불가하고,
완료된 딜이 다수 섞여 있어 노후 정리 없이는 워치리스트 원천으로 쓸 수 없다.
- 첫 소비자 = 환각 게이트의 인명 검출 (#166 풀네임 근거 가드 포함).
선행 조건 없음 — 단계 재분류는 서빙 #144 에만 걸린다 (2026-07-31 확인).

## 2. 확정 사항 요약

| 쟁점 | 결정 |
|---|---|
| 원천 | 혼합 — enrich 자동 후보 등재 + Discord 알림 + 사람 확정 |
| name_map 관계 | 전면 DB 화 — name_map.yaml 폐지, 용도 분리는 컬럼 조건으로 |
| 스키마 | 신분 (category) · 이적 축 (transfer_status) 2컬럼 분리, 표기 2컬럼 분리 (순환 차단), archived 는 보존 |
| 소비자 범위 | article_players 매핑 테이블 · 기존 기사 백필 포함, 워치리스트 · 서빙은 소비 계약만 명시 |
| 확정 전 서빙 | 현행대로 배포 (a안) + 확정 시 즉각 소급 수정 |

## 3. 스키마

`storage/schema.sql` 에 추가하고 `MartStore.ensure_schema()` 멱등 적용 관례를 따른다.
enum 성 컬럼은 기존 관례 (articles.transfer_stage) 대로 VARCHAR + 코드 검증으로 둔다.

```sql
CREATE TABLE IF NOT EXISTS players (
  id INT AUTO_INCREMENT PRIMARY KEY,
  full_name VARCHAR(100) NOT NULL UNIQUE,   -- 영문 풀네임 (Ousmane Diomande)
  first_name VARCHAR(50),                   -- 영문 이름
  surname VARCHAR(50) NOT NULL,             -- 영문 성 = 게이트 매칭 키
  ko_name VARCHAR(50),                      -- 검출용 한글 표기 (사람 확정만 기록)
  ko_candidate VARCHAR(50),                 -- 발굴용 표기 (모델 추출 후보, 게이트 미공급)
  club VARCHAR(50),                         -- 현 소속팀
  category VARCHAR(16) NOT NULL,            -- squad | manager | external
  status VARCHAR(16) NOT NULL,              -- candidate | confirmed | archived
  transfer_status VARCHAR(16) NOT NULL,     -- none | in_link | in_done | out_link | out_done | link_dropped | other_club | loan_in | loan_out
  origin VARCHAR(16) NOT NULL,              -- curated | extracted
  first_seen CHAR(64),                      -- 최초 근거 기사 content_hash (자동 등재 시)
  added_at DATETIME NOT NULL,
  confirmed_at DATETIME,                    -- 사람 확정 시각
  archived_at DATETIME);

CREATE TABLE IF NOT EXISTS article_players (
  content_hash CHAR(64) NOT NULL,           -- articles.content_hash 참조
  player_id INT NOT NULL,                   -- players.id 참조
  stage VARCHAR(32),                        -- 그 기사에서 그 선수의 영입 단계 (articles.transfer_stage 값 세트)
  extracted_at DATETIME NOT NULL,
  PRIMARY KEY (content_hash, player_id));
```

### 3.1. 신분 · 이적 축 분리

category 는 현재 신분, transfer_status 는 표시용 이적 축이다.
한 컬럼에 섞으면 "스쿼드이면서 방출설" 같은 상태를 표현할 수 없어 값이 폭발한다.

| 예 | category | transfer_status | 화면 배지 |
|---|---|---|---|
| 사카 | squad | none | 없음 |
| 아르테타 | manager | none | 없음 |
| 마두에케 · 에제 · 요케레스 | squad | in_done | 영입 완료 |
| 영입 링크 선수 | external | in_link | 영입 링크 |
| 타 클럽행 이적 성사 | external | other_club | 타 클럽행 |
| 성사 없는 링크 소멸 | external | link_dropped | 링크 소멸 |
| 임대 영입 성사 | squad | loan_in | 임대 영입 |
| 임대 이탈 성사 | squad | loan_out | 임대 이적 |
| 스쿼드 선수 방출설 | squad | out_link | 방출 링크 |
| 방출 성사 | external | out_done | 방출 완료 |

선수 단위 방출 축은 이 컬럼이 처음 담는다.
기사 단위 방출 단계 분류는 별도 트랙이다 (§10 범위 밖).

### 3.2. 표기 2컬럼 분리 — 순환 차단

게이트가 모델 출력을 모델 자신의 표기로 검증하는 순환을 컬럼 구조로 끊는다.

- ko_candidate: enrich 가 추출한 한글 표기 후보.
알림 표시 · 확정 참고용으로만 쓰고 게이트에 공급하지 않는다.
- ko_name: 사람이 확정할 때 기입하는 검출용 표기 (후보가 맞으면 복사, 틀리면 교정).
- 게이트 검출 사전 = `status = 'confirmed' AND ko_name IS NOT NULL` 행만.
- 근거 실사례: Tzolis 기사 제목의 "조르제" 창작 · Mateta 를 "앙리필리프" 로 옮긴 게시자 오역.
자동 등재를 그대로 사전에 넣으면 게이트가 그 오역을 정상으로 보호하게 된다.

### 3.3. surname 단일 단어 전제

풀네임 근거 가드 (`_has_name_context`) 는 성이 한 단어라는 전제의 패턴이다 (enrich.py 주석 명문화 · 현 40명 전부 충족).
두 단어 성 (Van Dijk 류) 을 등재하면 이 가드 축이 조용히 꺼지므로, 확정 CLI 가 두 단어 surname 에 경고를 낸다.
가드 자체의 두 단어 성 지원은 범위 밖이다.

## 4. 동작 설계

### 4.1. 자동 발굴 (enrich)

- 기존 enrich 프롬프트에 기사별 (선수, 단계) 쌍 출력 필드를 추가한다.
별도 배치 패스를 만들지 않아 Gemini 호출 수 · 429 예산이 늘지 않는다 (출력 토큰 소폭 증가만).
- 추출된 쌍은 article_players 에 저장한다.
- 명단에 없는 선수가 나오면 players 에 후보 행을 넣는다
(status=candidate · origin=extracted · first_seen=content_hash · ko_candidate=모델 표기).

### 4.2. 후보 알림 (신규 인프라 없음)

- 새 candidate 행 생성 시 기존 `notify.send_alert()` (Discord 웹훅) 로 알린다.
내용: 선수명 · 추출 단계 · 근거 기사 제목 · 링크.
- 하루 8회 회차에 물려 있어 수집 후 최대 몇 시간 안에 인지된다.

### 4.3. 확정 CLI — 즉각 소급 수정

확정 명령 1회가 다음을 순서대로 수행한다.

1. status → confirmed 승격 + ko_name 기입 (두 단어 surname 경고 포함).
2. 그 선수가 등장한 기사 (article_players 조회) 만 골라 게이트 재검사.
오역 표기 발견 시 재번역 큐 → 즉시 재번역.
3. 재렌더 → 배포.

- 기존 enrich 단독 재실행 경로 (`docs/runbook/2026-07-19-enrich-only-pass.md`) 를 대상 기사만으로 좁혀 재사용한다.
- 실질 지연 = 알림 인지부터 명령 실행까지의 시간이며, 회차 주기에 묶이지 않는다.

### 4.4. 확정 전 서빙 정책 (a안)

- 후보 상태 선수의 기사는 현행대로 배포한다.
게이트 미보호 노출 창은 지금의 사전 밖 선수와 동일한 수준이고, 알림 → 확정 → 소급 수정으로 좁힌다.
- 채택 근거: 인명 환각은 드문 이벤트 (라이브 412행 실측에서 오탐 확인 2건 수준) 이고,
새 링크 선수 기사일수록 속보성이 중요해 보류 · 원문 폴백의 비용이 더 크다.
- 검토 후 기각한 대안: 후보 기사 제목만 원문 폴백 (본문 오역은 못 지킴) · 확정까지 서빙 보류 (기사 자체가 안 나감).

## 5. 로더 전환 — name_map.yaml 폐지

- 소비처 3곳의 YAML 로드를 DB 조회로 바꾼다:
run.py 의 게이트용 name_map 로드 · `finalize_translation` 표기 통일 · serve `load_player_names` 서빙 사건 사전.
- 사전 형태는 기존과 동일한 `{ko_name: surname}` dict 로 만들어 넘긴다.
게이트 함수들은 이미 dict 를 인자로 받으므로 본체 무수정 · 테스트의 dict 주입도 그대로다.
- YAML 파일이면 선수 추가에 커밋 → 머지 → VM pull 이 필요해 §4.3 의 즉각 반영과 양립하지 않는다.
DB 가 사전의 단일 원천이어야 확정 명령 한 줄로 게이트에 반영된다.
- name_map.yaml 삭제와 참조 제거는 마이그레이션 (§7) 완료 후 같은 트랙에서 한다.
- 기존 "검출용과 워치리스트 분리 유지" 권고의 취지는 컬럼 조건으로 지킨다:
물리 저장은 하나, 소비자별 조회 조건 (§8) 이 용도를 분리한다.

## 6. 생애주기 · 노후 정리

- 영입 성사: category external → squad · transfer_status in_link → in_done.
- 임대 영입 성사: category squad · transfer_status loan_in (링크 단계 = in_link).
- 임대 복귀: transfer_status loan_out → none (스쿼드 복귀) 또는 loan_out → out_link (처분 재검토).
- 방출 성사: category squad → external · transfer_status out_link → out_done.
- 타 클럽행 이적 성사: category external · transfer_status other_club · status → archived.
- 성사 없는 링크 소멸: transfer_status → link_dropped · status → archived.
- 이적 시장 종료: 남은 링크 선수를 사람이 일괄 archived 처리한다 (수동 트리거 · 자동 만료 없음).
- archived 는 보존이다 — 물리 삭제 없음.
게이트 사전에는 잔류해 (표기 대조는 많을수록 보호가 넓고 비용이 없음) 과거 기사 재번역 시에도 보호가 유지되고,
등재 이력 (언제 · 어떤 기사로 발굴됐는지) 이 트랙의 운영 데이터로 남는다.

## 7. 마이그레이션 · 백필

- name_map 39명 → players 이관: 전원 status=confirmed · origin=curated.
category · transfer_status 분류는 사람이 확정하며, 완료 딜 (트로사르 · 촐리스 · 로저스 등) 정리를 겸한다.
- 기존 기사 약 500행 백필: enrich 추출을 재실행해 article_players 를 채운다.
일회성 Gemini 호출 약 500건 (15 RPM 한도로 약 35분 + 소액 과금 — 무료 티어 아님 · Tier 1 선불).
- 백필을 지금 하는 이유: §10 서빙 헬퍼가 나중에 이 테이블을 읽을 때 재추출 (같은 호출 재과금) 을 피한다.

## 8. 소비 계약 (구현은 각자 트랙)

| 소비자 | 조회 조건 |
|---|---|
| 게이트 검출 사전 · 표기 통일 | confirmed 전체 (archived 포함) 의 `{ko_name: surname}` |
| 워치리스트 검색 (수집 트랙) | `confirmed AND transfer_status = 'in_link'` 만 — 429 예산 최소화, out_link 확장은 그 트랙에서 판단 |
| 서빙 사건 사전 (#144 재개 시) | confirmed 전체의 ko_name 목록 |
| 서빙 선수별 단계 (§10 헬퍼) | article_players 를 content_hash 로 조인 |

## 9. 검증 (구현 트랙 계약)

- TDD: 추출 쌍 파싱 · candidate INSERT 멱등성 (같은 선수 재등장 시 중복 없음) ·
로더 동등성 (마이그레이션 결과 dict = 기존 YAML 40명 dict) · 확정 CLI 상태 전이 · 두 단어 surname 경고.
- 라이브: VM 회차 1회에서 후보 알림 발송 · article_players 적재 · 확정 CLI 종단 (승격 → 재검사 → 재렌더) 확인.

## 10. 범위 밖

- #144 (선수 페이지) 재개 자체 — 이 스펙은 그 선행 조건만 푼다.
- 기사 단위 방출 단계 분류 (transfer_stage 의 방출 축).
- 풀네임 근거 가드의 두 단어 성 지원.
- E안 퍼가기 정책 · 워치리스트 수집 구현.
- 구현 전부 — 이 문서는 스펙까지고, 구현 계획은 별도 세션에서 쓴다.
