# Bullet-in — 설계 스펙

- **작성일**: 2026-05-27
- **상태**: 설계 합의 완료 (구현 전)
- **프로젝트명**: Bullet-in (가칭) — *bulletin (단신/게시판) + bullet (병기고, Arsenal)* 의 언어유희
- **한 줄 정의**: 영국 현지 언론사 뉴스와 ITK (X) 소식을 매일 수집 · 정규화 · 공신력 스코어링 · 중복제거 · LLM 번역/요약하여, 신뢰도순으로 보여주는 Arsenal FC 뉴스 수집 파이프라인.

---

## 1. 배경 & 동기

- 아스날 FC 소식은 영국 현지 언론과 ITK (In The Know) 트위터에 흩어져 있고, 매체 · 계정마다 공신력 편차가 크다. 신뢰할 만한 소스만 골라 한곳에서 한국어로 정리해 보고 싶다는 필요에서 출발한다.
- 단순 "긁어 저장" 스크립트가 아니라, 신뢰성 · 멱등성 · 데이터 품질 · 관측성을 갖춘 **수집 파이프라인**으로 만든다.
- 수집 대상에 동적 (JS 렌더링) 사이트와 인증 · 안티봇이 걸린 X가 포함되므로, 소스별 최적 도구 (정적=httpx, API, 동적=Playwright, X=twikit)를 단일 인터페이스 뒤로 통합한다.

## 2. 목표 & 비목표

**목표**
- 동적 (JS 렌더링) 사이트를 포함한 이종 (異種) 소스를 단일 어댑터 인터페이스로 통합 수집한다.
- 중복제거 · 증분 · 공신력 스코어링으로 신뢰할 수 있는 데이터로 정제한다.
- 정량 SLO (병렬화 시간 단축 · 중복률 · 성공률 등)로 완성을 증명한다.
- 데이터 품질/이상 점검 · LLM 인리치먼트 · 오케스트레이션을 갖춘 파이프라인으로 만든다.

**비목표 (YAGNI)**
- 본격 사용자 서비스 (회원/구독/푸시) — 나중에.
- 무거운 대시보드 — 나중에 (얇은 정적 뷰로 시작).
- 실시간 스트리밍/CDC — 의도적으로 제외 (§9 근거 참조).

## 3. 배치 & 무게중심

- **수집 파이프라인이 본체, 웹 표시는 얇은 뷰.** 백엔드 (수집 · 병렬 · dedup · 스코어링 · 품질 · 적재 · enrich)에 무게를 싣는다.
- 작업 기간: 1~2일은 이상적 목표, **실제 3~5일** 기준.

## 4. 핵심 기능 ↔ 구현

| 기능 | 구현 |
|---|---|
| 다중 소스 매일 수집 (병렬처리) | asyncio 다중 소스 동시 수집 + daily DAG |
| 수집 데이터 이상 점검 | dbt test 품질 게이트 + 수집량 이상탐지 + 알림 |
| 텍스트 인리치먼트 | LLM 번역 · 요약 + 정확도 스팟체크 |
| 수집 현황 모니터링 | SLO 메트릭 + 수집현황 뷰 |
| 다양한 소스 수집 | 단일 어댑터 뒤 이종 소스 (RSS/API/HTML/JS/X) |
| 웹 스크래핑 | JS뉴스=Playwright, 정적=httpx, API=Guardian, X=twikit |
| 저장 | raw=MongoDB → mart=MariaDB (메달리온) |
| 오케스트레이션 | Airflow 3.x DAG (+ 2→3 마이그레이션) |

## 5. 아키텍처 & 파이프라인

```
[Ingest]    소스별 어댑터 (RSS · Guardian API · httpx+파서 · Playwright · twikit)
   │        ↑ 단일 SourceAdapter 인터페이스 / asyncio fan-out 병렬
   ▼
[Normalize] pydantic 스키마 정규화 (title, url, source, author, published_at, body…)
   ▼
[Dedup]     URL 정규화 + content_hash, 증분(워터마크), 앱 레벨 변경/삭제 감지
   ▼
[Score]     공신력 Tier(0~4) 매핑 (YAML 설정 → sources 테이블, confidence score)
   ▼
[Load raw]  MongoDB (불변 원문 보존, schema-on-read)
   ▼
[Load mart] MariaDB (정형 mart: 메타 + tier + dedup UNIQUE + 서빙)
   ▼
[Enrich]    LLM 번역(한국어) + 요약 (신규 항목만, 캐싱/멱등)
   ▼
[Quality]   dbt(DuckDB가 MariaDB attach) build + test = 품질 게이트
   ▼ (통과 시)
[Serve]     정적 HTML (Tier·소스별 카드, 원문+번역+요약)

가로지르는 관심사: 재시도/백오프 · rate limit · robots.txt · 구조적 로깅 · 메트릭 · 이상탐지/알림
오케스트레이션: Airflow (2.x 구축 → 3.x 마이그레이션) 가 전 단계를 태스크로 조율
```

DuckDB는 MySQL 스캐너 확장으로 MariaDB를 직접 attach → 데이터 이중 적재 없이 분석/품질 마트를 구성.

## 6. 소스 전략 & 어댑터

- **소스별 최적 도구 선택**:
  - 정적 HTML → `httpx` + 파서 (BeautifulSoup/selectolax)
  - 공개 API → Guardian Open Platform API (무료)
  - JS 렌더링/지연 로딩 → **Playwright** (동적 스크래핑 시연 지점, 최소 1개 이상 필수)
  - X (ITK) → **twikit/twscrape** (버너 부계정 로그인 세션, 내부 API)
- **단일 `SourceAdapter` 인터페이스**: `fetch() -> list[RawItem]`. 소스 추가가 어댑터 1개 추가로 끝나는 플러그형 구조.
- v1 소스셋 (공신력 Tier 매핑 예시):
  - Tier 0: Arsenal.com (공식)
  - Tier 1: Daily Mail (Sami Mokbel)
  - Tier 1.5: Guardian (Fabrizio Romano, 무료 API)
  - Tier 2: Goal (Charles Watts), ESPN (James Olley)
  - Tier 3: Evening Standard (Simon Collings)
  - Tier 4: football.london 등 (소문/타블로이드, 낮은 가중치)
  - ITK (X): handofarsnal 등 1~2개
- **향후 커넥터** (README 명시): The Athletic · The Times (하드 페이월), 추가 ITK. 어댑터 인터페이스로 확장 가능.

## 7. 데이터 모델

**MongoDB `raw_items` (Bronze, 불변 원본, schema-on-read)**
```
{ _id, source_id, source_type(rss|api|html|playwright|x),
  url, content_hash, fetched_at, raw_payload {원문 그대로} }
```
원문을 손실 없이 보존 → 파서 로직이 바뀌어도 재처리 가능.

**MariaDB (Silver/Gold, 정형 mart, 서빙용)**

`articles` — 정규화 항목 (서빙 핵심)
```
id PK · content_hash UNIQUE · url UNIQUE        ← dedup 보증
source_id · author · tier(0~4) · confidence_score
title_original · title_ko · summary_ko · body_excerpt   ← LLM enrich 결과
published_at · fetched_at · created_at · updated_at · revision(변경감지)
```

`sources` — 소스/기자 ↔ Tier 매핑 참조 (sources.yaml이 source-of-truth, 적재 시 로드)
```
source_id PK · display_name · tier · medium(신문/X/공식) · enabled
```

`pipeline_runs` — 관측성/SLO 근거 데이터
```
run_id · dag_run_id · started_at · finished_at · duration_sec
source_counts(JSON) · new_count · dup_count · error_count · success_rate
```

**dbt (DuckDB) 분석/품질 마트**: `daily_source_quality`, `tier_distribution`, `slo_rollup` 등.

## 8. 핵심 메커니즘

- **Dedup**: `content_hash = sha256(정규화 title + 정규화 url)`. URL 정규화 (utm · fragment 제거). MariaDB UNIQUE 제약으로 DB 레벨 차단 → 앱+DB 이중 방어.
- **증분 수집**: 소스별 워터마크 (RSS=published_at, X=since_id) 저장 → 매 실행 신규만.
- **변경/삭제 감지 (경량 CDC 대체)**: 같은 url의 content_hash 변동 시 `revision` 증가 + 수정 기록. ITK 트윗 수정 · 삭제, 이적설 업데이트에 대응.
- **공신력 스코어링**: tier는 sources.yaml로 외부화 (코드 수정 없이 소스/tier 조정). confidence score로 정렬 · 필터.
- **LLM enrich (번역+요약)**: Claude Haiku 등 저비용 모델. **신규 항목만** 처리 + 결과 캐싱 → 재실행 시 재호출 없음 (비용 · 일관성 · 멱등). 출력 스키마 검증.

## 9. 기술 스택 & 선택 근거

- **서빙 mart = MariaDB**: 데이터 규모 (일 수십~수백 건) · 서빙 패턴 (포인트 조회 · 필터 · 정렬 · UNIQUE dedup · 상시 웹 서버)에 최적.
- **분석/품질 = dbt + DuckDB**: dbt test (`unique` · `not_null` · `accepted_values` · `freshness`)가 "이상 점검"과 정면 일치. DuckDB는 서빙이 아니라 dbt 엔진/분석 마트 역할 (임베디드 · zero-infra). MariaDB를 attach해 읽음.
- **CDC 제외 (의도적)**: 상류에 binlog를 읽을 트랜잭션 DB가 없음 (소스가 웹/API/X). Debezium+Kafka는 이 규모에 과설계다. 대신 앱 레벨 변경감지로 대체한다.
- **언어/라이브러리**: Python 3.11+, asyncio, httpx, Playwright, twikit/twscrape, pymongo, SQLAlchemy/mariadb-connector, pydantic, tenacity (재시도), Jinja2, structlog, pytest.
- **오케스트레이션**: Airflow — **2.x로 먼저 구축 후 3.x로 마이그레이션** (둘 다 필수). breaking changes 대응 기록 (`execution_date`→`logical_date`, provider 패키지 분리, constraints 파일, Task Execution API/워커 DB 접근 제거, UI 변경 등).
- **인프라**: docker-compose (MongoDB · MariaDB · Airflow). AWS 배포는 stretch.

## 10. 정량 지표 (SLO)

| 지표 | 목표 | 측정 방법 |
|---|---|---|
| 병렬화 수집 시간 단축 (headline) | 순차 대비 ~70%↓ | `--concurrency=1` baseline vs asyncio fan-out 벤치마크 |
| 중복 적재율 (headline) | 0% | content_hash UNIQUE + dbt `unique` test |
| 일일 수집 성공률 | ≥ 99% | `pipeline_runs.success_rate` (재시도 · 소스 isolation 포함) |
| 필수 필드 완전성 | ≥ 99% | dbt `not_null` test 통과율 |
| 신선도 (freshness) | 윈도우 내 신규 누락 0 | dbt `freshness` + 워터마크 |
| 수집량 이상 감지 | 전일 대비 ±Xσ 알림 | `pipeline_runs` 추세 anomaly check |
| (stretch) 번역/요약 정확도 | 스팟체크 일치율 | 역번역 일관성 샘플 검증 |

## 11. 디렉토리 구조

```
bullet-in/
├── README.md
├── pyproject.toml
├── docker-compose.yml             # Mongo · MariaDB · Airflow
├── .env.example                   # X 자격증명 · LLM 키 (절대 커밋 금지)
├── config/
│   └── sources.yaml               # 소스 ↔ Tier 매핑 (공신력 설정)
├── src/bullet_in/
│   ├── adapters/                  # base · rss · guardian_api · html · playwright_news · x_twikit
│   ├── ingest.py                  # asyncio fan-out
│   ├── normalize.py · dedup.py · score.py · enrich.py
│   ├── storage/                   # mongo.py(raw) · mariadb.py(mart)
│   ├── quality/                   # 런타임 품질/이상탐지
│   ├── serve/                     # render.py(Jinja2→HTML) · templates/
│   └── metrics.py                 # SLO 집계
├── dbt/                           # DuckDB 프로젝트
│   ├── dbt_project.yml
│   ├── models/                    # staging/ · marts/
│   └── tests/
├── airflow/dags/
│   └── bullet_in_daily.py         # 2.x → 3.x 마이그레이션 대상
├── docs/
│   ├── superpowers/specs/         # 설계 스펙
│   ├── MIGRATION.md               # Airflow 2→3 마이그레이션 기록
│   ├── troubleshooting/           # 이슈별 .md (X 안티봇 · Playwright 안정화 · dedup 충돌 …)
│   └── runbook/                   # 운영 절차별 .md (실행 · 재처리 · 장애 대응 · 이상 알림 대응)
└── tests/                         # pytest
```

## 12. README 골격

1. 한 줄 소개 + 데모 스크린샷
2. 문제정의 · 동기 (아스날 뉴스 파편화 · 공신력 편차)
3. 아키텍처 다이어그램 (파이프라인 스테이지)
4. 핵심 기능 (이종 소스 통합 · 병렬 수집 · 공신력 스코어링 · dedup/증분 · LLM 번역 · 요약 · 품질 게이트)
5. **정량 성과 (SLO 표)**
6. **기술 스택 & 선택 이유** (왜 MariaDB+Mongo, 왜 dbt+DuckDB, 왜 CDC를 안 썼나)
7. 데이터 모델 (medallion)
8. **Airflow 2→3 마이그레이션 기록** (요약 + docs/MIGRATION.md 링크)
9. 트러블슈팅 (docs/troubleshooting/ 링크)
10. 실행 방법 (docker-compose up …)
11. 한계 & 향후 (ITK 확장 · 대시보드 · AWS 배포)
12. **윤리 · 법적 고지** (robots.txt · rate limit · ToS · 개인 학습용)

## 13. 스코프 (v1 / stretch / 나중에)

**v1 필수 (3~5일)**
- 소스 4~6개 (Arsenal.com · Guardian API · 뉴스 2~3개[httpx 정적 + Playwright JS 최소 1] · ITK X 1~2개[twikit])
- asyncio 병렬 · dedup/증분/변경감지 · 공신력 스코어링
- LLM 번역+요약 (멱등/캐싱) · MongoDB→MariaDB 적재
- dbt test 품질 게이트 (DuckDB) · 정적 HTML 뷰
- **Airflow 2.x 구축 → 3.x 마이그레이션** · 정량 SLO 측정
- docs/ 트러블슈팅 · 런북 기록

**Stretch (가능하면)**
- 교차 corroboration 스코어링 (다수 소스 보도 시 신뢰도↑)
- 번역/요약 정확도 스팟체크 (역번역 일관성)
- 모니터링 대시보드 · 소스 추가 · AWS 배포

**나중에**
- 알림 푸시 · 사용자 구독/필터 · 본격 대시보드

## 14. 윤리 & 법적 고지

- 공개 콘텐츠 대상, robots.txt 준수, 보수적 rate limit, 소스 출처/링크 표기.
- X (ITK)는 ToS 그레이존 → 버너 부계정 사용, 자격증명은 env/secret로 분리 (절대 커밋 금지), 개인 학습 용도 명시.
- 원문 전체 재배포가 아니라 메타데이터 · 요약 · 원문 링크 중심으로 서빙.

## 15. 위험 & 미해결 사항

- X 안티봇/세션 만료 → twikit 세션 관리 · 재로그인 · 백오프로 대응, 실패 시 해당 소스만 격리.
- Playwright 셀렉터 취약성 → 대상 사이트 신중 선택 + 셀렉터 변경 대비 테스트.
- dbt-duckdb의 MariaDB attach (MySQL 스캐너) 동작 검증 필요 (구현 초기 PoC).
- Airflow 3.x 마이그레이션 시 provider 호환성 — constraints 파일 기반으로 단계적 진행.
- LLM 번역 품질 변동 → 스팟체크 + 프롬프트 고정 + 모델 버전 핀.
