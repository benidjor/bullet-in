# Bullet-in

[![CI](https://github.com/benidjor/bullet-in/actions/workflows/ci.yml/badge.svg)](https://github.com/benidjor/bullet-in/actions/workflows/ci.yml)

> 영국 현지 언론과 ITK (X) 에 흩어진 Arsenal FC 소식을 하루 8회 병렬 수집하고 공신력 스코어링과 중복 제거를 거쳐 LLM 으로 번역 · 요약한 뒤 신뢰도순으로 제공하는 뉴스 데이터 파이프라인입니다.
>
> **공개 서비스**: https://bullet-in.pages.dev · 2026-08-29 공개 · Airflow 가 3시간마다 파이프라인을 실행해 수집하고 검증하고 배포합니다.
> 현재 가동 상태는 [수집 현황 대시보드](https://bullet-in.pages.dev/ops.html) 의 페이지 생성 시각과 SLO 표에서 확인하실 수 있습니다.

*Bullet-in = bulletin (단신) + bullet (병기고 Arsenal) 의 언어유희입니다.*

![Bullet-in 전체 기사 (실데이터)](docs/assets/serving-page-live.png)

> 전체 기사 화면 (`all.html`) 입니다.
> 날짜별 시간순 정렬, 영입 단계 · 공신력 · 소스 · 기자 facet 필터, 한국어 번역과 요약을 표시합니다.
> 홈 화면은 대표 기사와 주요 소식을 신문 레이아웃으로 배치합니다.

![Bullet-in 기사 상세 (실데이터)](docs/assets/article-detail-live.png)

> 기사 상세 화면입니다.
> 3줄 요약, 소스 성격에 따른 차등 서빙 (언론사는 발췌 + 원문 링크, X 와 공식 발표는 전문), 기자 바이라인을 표시합니다.

## 한눈에 보기

| 항목 | 내용 |
|---|---|
| **서비스** | 2026-08-29 공개 · 공개일 688명 · 첫 주 827명 |
| **규모** | 활성 소스 9종 · 기사 1,161건 · 3시간 간격 실행 |
| **신뢰성** | 완주율 99.2% (2026-07-20 이후 508회 중 504회) · 중복 적재율 0% · 필수 필드 완전성 100% |
| **품질 게이트** | 실행 마지막 단계의 dbt 데이터 계약 테스트 21종 · 하나라도 실패하면 배포 중단과 Discord 알림 |
| **배포** | 머지된 코드를 다음 실행이 자동으로 내려받아 배포 · 운영 환경에서 반영 검증 · 불일치 시 이전 커밋으로 롤백 |
| **복구** | 매일 GCS 백업 · 별도 DB 에 복원해 테이블 6개와 `raw_items` 의 행 수를 백업 매니페스트와 대조 (2026-09-01 복구 테스트 전부 일치) |
| **비용** | Iceberg 테이블은 GCS · 카탈로그만 Google Lakehouse runtime catalog · 매니지드 Iceberg 테이블의 시간당 요금 없이 GCS 저장 · 작업 요금만 발생 (금액은 GCP 결제 보고서에서 조회) |

위 수치는 [수집 현황 대시보드](https://bullet-in.pages.dev/ops.html) 가 실행할 때마다 새로 계산합니다.
설계 판단만 빠르게 확인하시려면 [8. 설계 결정과 트레이드오프](#8-설계-결정과-트레이드오프) 로 바로 이동하셔도 됩니다.

**이 문서 읽는 법**

- **무엇인가**: [1. 배경 및 문제](#1-배경-및-문제) · [2. 아키텍처](#2-아키텍처) · [3. 핵심 기능](#3-핵심-기능)
- **어떻게 운영하는가**: [4. 정량 지표 (SLO)](#4-정량-지표-slo) · [5. 운영](#5-운영) · [6. 데이터 품질](#6-데이터-품질)
- **왜 그렇게 만들었는가**: [7. 기술 스택](#7-기술-스택) · [8. 설계 결정과 트레이드오프](#8-설계-결정과-트레이드오프) · [9. 데이터 모델](#9-데이터-모델)
- **코드를 직접 보려면**: [10. 저장소 구조](#10-저장소-구조) · [11. 실행 방법](#11-실행-방법) · [12. 문서 구성](#12-문서-구성)
- **그 밖**: [13. AI 도구 활용](#13-ai-도구-활용) · [14. 한계 및 향후 개선 방향](#14-한계-및-향후-개선-방향) · [15. 윤리 및 법적 고지](#15-윤리-및-법적-고지)

---

## 1. 배경 및 문제

아스날 관련 소식을 확인하려면 영국 언론 5~6곳과 ITK (In The Know) 트위터 계정을 각각 방문해야 합니다.
매체와 계정마다 공신력 편차가 커서, 같은 이적설이라도 어디서 나왔는지에 따라 신뢰도가 크게 달라집니다.
이 불편을 해결하기 위해 **신뢰할 수 있는 소스만 선별해 한곳에 모으고, 한국어로 번역 · 요약해 신뢰도순으로 제공하는** 서비스를 만들었습니다.

단순 수집 스크립트가 아니라 신뢰성 · 멱등성 · 데이터 품질 · 관측성을 갖춘 **데이터 프로덕트**로 설계했습니다.
공개일에 688명, 공개 첫 주 (08-29 ~ 09-04) 에 827명이 방문했습니다 (순 사용자 기준이며, 광고 차단 환경의 방문은 집계되지 않습니다).

## 2. 아키텍처

메달리온 아키텍처 (Bronze → Silver → Gold) 위에 LLM 번역 · 요약, 데이터 품질 게이트, 배포 자동화를 올린 구조입니다.
파이프라인 1회 실행은 Airflow DAG 의 태스크 8개로 나뉩니다.

[![아키텍처 (실행 한 번의 전체 지형)](docs/assets/architecture.svg)](https://raw.githubusercontent.com/benidjor/bullet-in/main/docs/assets/architecture.svg)

> 왼쪽이 입력 (수집 소스 · 코드 저장소 · GA4 사이트 태그), 가운데가 Oracle Cloud VM 에서 도는 수집 · 저장과 Airflow DAG, 아래가 Google Cloud 의 레이크하우스, 오른쪽이 서빙과 알림입니다.
> 글자가 작으면 그림을 눌러 3배 크기로 여십시오.
> 그림의 「소스 10종」 은 설정에 등재된 수를 말하며 이 가운데 9종이 활성입니다 (§3).

DAG 안에서 태스크는 이 순서로 돕니다.

```
advance -> collect -> enrich -> publish -> gate -> deploy_site -> judge
                                |
                                +-> warehouse_load (publish 이후 병렬)
```

| 태스크 | 하는 일 |
|---|---|
| `advance` | `origin/main` 내려받기 (사람이 운영 서버에서 pull 하지 않는 구조) |
| `collect` | 어댑터 9종 `asyncio` 병렬 수집 → 정규화 → URL · `content_hash` 기준 중복 제거 → 공신력 tier 산출 → Bronze · Silver 적재 |
| `enrich` | Gemini API 로 번역 · 요약 · 영입 단계 분류 (신규 행만 처리하는 멱등 설계) |
| `publish` | 정적 HTML 렌더 (기사 · 선수 · 대시보드 2종) · 실행 기록 · 신선도 판정 |
| `gate` | `dbt build` 와 테스트 21종 (DuckDB 가 MariaDB 를 attach) · 실패 시 배포 중단 |
| `deploy_site` | Cloudflare Pages 업로드 (산출물이 비정상이면 중단) |
| `judge` | 라이브 `build.json` 으로 반영 확인 · 불일치 시 이전 커밋으로 롤백 · Discord 알림 |
| `warehouse_load` | MariaDB 변경분 · 스냅샷과 GA4 행동 로그를 Iceberg (GCS) 에 적재 · Gold 재작성 |

실행 주기는 3시간이고 실행기는 `LocalExecutor` 입니다 (§5).

systemd 는 파이프라인 외부의 부가 작업만 담당합니다: 선수 워치리스트 (귀속된 선수를 fmkorea 에서 재검색) · 일일 백업 (GCS) · 레이크하우스 유지보수 (스냅샷 만료 · 컴팩션) · Airflow 감시 (하트비트 · 실행 지연).

## 3. 핵심 기능

### 3.1. 수집과 적재

- **이종 소스 통합**: RSS · REST API · 정적 HTML · JS 렌더링 · X (트위터) · 한국 커뮤니티를 단일 어댑터 인터페이스로 추상화했습니다.
  소스 특성에 맞는 도구를 각각 선택합니다 (정적 = `httpx`, API = Guardian Open Platform, X = 쿠키 주입 Playwright).
- **병렬 수집과 실패 격리**: `asyncio` 팬아웃으로 소스를 동시에 호출하며, 한 소스가 실패해도 나머지 수집은 정상 진행됩니다.
- **중복 제거와 변경 감지**: `content_hash` 와 URL 정규화에 DB `UNIQUE` 제약을 더해 애플리케이션과 DB 양쪽에서 중복을 막습니다.

### 3.2. 변환과 품질 판정

- **공신력 스코어링**: Tier 0 (Arsenal.com 공식) 부터 4 (타블로이드) 까지를 YAML 로 외부화하고 `confidence` 값으로 정렬합니다.
  기자 단위 tier 가 매체 tier 보다 우선 적용됩니다 (전담 기자의 기사만 등급 상향).
- **LLM 번역 · 요약**: Gemini 3.1 Flash-Lite 로 제목 · 본문 번역, 1줄 · 3줄 요약, 영입 단계 분류를 만듭니다.
  신규 행만 처리하므로 같은 실행을 다시 돌려도 결과가 달라지지 않고, 429 (rate limit) 를 만나면 그 실행의 번역을 멈추고 다음 실행이 이어서 처리합니다.
- **번역 품질 게이트**: LLM 산출물을 규칙 코드로 검사해 위반이 있으면 다시 생성합니다 (§6.3).
- **선수 추출과 이적 상태 관리**: 기사 본문에서 선수를 추출해 주체와 단순 언급으로 구분해 매핑하고, 선수별 페이지와 이적 상태 (영입 진행 · 확정 · 무산 · 타 클럽행 · 방출) 를 명단에서 관리합니다.

### 3.3. 서빙과 관측

- **데이터 품질 게이트**: 실행 마지막 단계의 dbt 테스트 21종이 배포를 차단합니다 (§6.1).
- **배포 자동화**: 머지된 코드를 다음 실행이 자동으로 내려받아 배포하고, 운영 환경에서 반영을 검증한 뒤 불일치 시 롤백합니다 (§5).
- **관측성**: 대시보드 2종 (행동 지표 · 수집 현황) 과 Discord 알림 (수집량 이상 · 신선도 · 게이트 · 태스크 실패 · 배포 판정) 을 운영합니다.
- **행동 로그와 레이크하우스**: GA4 이벤트를 Iceberg 에 Bronze · Silver · Gold 로 적재하고, 서빙 DB 의 변경 이력과 일별 스냅샷도 같은 레이크하우스에 보존합니다 (§9).

### 3.4. 수집 소스

활성 소스는 9종이며 고정 tier 7종과 항목별 동적 tier 2종으로 구성했습니다 (X 와 커뮤니티는 게시물에 언급된 기자 · 매체의 공신력으로 tier 를 산출합니다).
아래 표에는 2026-07 에 비활성으로 돌린 1종을 포함해 10종을 싣습니다.
언론 5종은 공통 이적 키워드 필터를 공유합니다 (`config/sources.yaml`).

| 소스 | tier | 어댑터 | 비고 |
|---|---|---|---|
| Arsenal.com | 0 | arsenal_api | 공식: 공홈 GraphQL API, taxonomy 필터 (이적 · 1군 재계약) |
| BBC Sport | 1.5 | html | 비전담 기준선: 전담 기자 (Mokbel) 는 tier 1 로 상향 |
| Sky Sports | 2 | html | 비전담 기준선: 전담 기자 (Sheth) 는 tier 1.5 로 상향 |
| The Guardian | 3 | guardian_api | Open Platform API (`GUARDIAN_API_KEY` 필요) |
| Goal.com | 4 | html | 정적 서빙 확인 후 playwright → html 전환 (2026-07) |
| BBC Football Gossip | 4 | html | 타 매체 루머 라운드업 |
| football.london | 4 | html | 2026-07 이후 비활성 (`enabled: false`) · 과거 실행 기록에는 남아 있음 |
| afcstuff (X) | 동적 | x_playwright | 트윗에 언급된 기자 · 매체 tier 로 라우팅 (fallback 4) |
| David Ornstein (X) | 1 | x_playwright | 기자 본인 계정: 트윗에 @핸들이 없어 고정 tier |
| fmkorea 축구 소식통 | 동적 | fmkorea | 한국 커뮤니티: 언급된 기자 · 매체 tier 로 라우팅 (기본 4) |

**기자 · ITK 공신력**: 동적 소스는 항목마다 tier 를 개별 산출합니다.
기자를 먼저 조회하고, 없으면 매체를 조회하고, 둘 다 없으면 기본값을 적용합니다.

```
항목 1건의 tier 산출

  1. 게시물에 언급된 기자가 레지스트리에 있는가?
       있으면  -> 기자 tier (전담 기자는 매체보다 높다)
  2. 없으면, 해당 매체가 레지스트리에 있는가?
       있으면  -> 매체 tier
  3. 기자도 매체도 레지스트리에 없으면
       기본값  -> tier 4 (출처를 특정하지 못한 루머)
```

레지스트리 전체 (기자 · ITK 105명 · 매체 55곳 · 별칭) 는 [`config/credibility.yaml`](config/credibility.yaml) 에 있으며 화면의 기자 필터도 같은 파일을 참조합니다.

## 4. 정량 지표 (SLO)

> 목표치와 측정 방법입니다.
> 번호는 [수집 현황 대시보드](https://bullet-in.pages.dev/ops.html) 의 SLO 표와 동일하며 SLO-2 부터 6 까지는 실행마다 해당 대시보드에 갱신됩니다.
> 병렬화 측정 절차는 [SLO-1 벤치마크 런북](docs/runbook/2026-07-14-slo1-benchmark.md), 지표 정의는 [SLO 측정 런북](docs/runbook/2026-07-19-slo-measurement.md) 에 정리했습니다.

| 번호 | 지표 | 목표 | 측정 방법 | 실측 (2026-09-22) |
|---|---|---|---|---|
| SLO-1 | 병렬화 수집 시간 단축 | 순차 대비 55% 이상 단축 (실측 기반 재조정¹) | `metrics.benchmark()` (concurrency=1 vs N 벤치마크) | 56.5% 단축 (2026-07-15 · 3회 중앙값 · 실행마다 측정하지 않음) |
| SLO-2 | 실행 성공률 | 99% 이상 | `pipeline_runs.success_rate` 최근 30회 평균 (재시도 · 소스 격리 포함) | 100.0% |
| SLO-3 | 중복 적재율 | 0% | `content_hash` · URL `UNIQUE` 제약 + dbt `unique` 테스트 5종 | 0% (기사 1,161건) |
| SLO-4 | 필수 필드 완전성 | 99% 이상 | dbt `not_null` 테스트 10종 | 100% |
| SLO-5 | 소스 신선도 | 중단된 소스 0 | `source_freshness` 워터마크 · 소스별 임계 (24h ~ 192h) 초과 여부 | 2 (이적 시장 마감 후 기사량 감소로 임계 초과 · 임계 재조정 검토 중) |
| SLO-6 | 수집량 이상 감지 | 이상 소스 0 · ±2σ 알림 | `quality.volume_anomalies` (직전 실행 대비) | 0 · 가동 중 (실발송 검증 2026-07-13) |

¹ 초기 목표 70% 를 도달 불가로 판정하고 55% 로 하향한 경위는 [8. 설계 결정과 트레이드오프](#8-설계-결정과-트레이드오프) 에 있습니다.

## 5. 운영

실행 · 배포 · 감시를 모두 자동화했습니다.
2026-09-04 에 systemd 타이머에서 Airflow DAG 로 마이그레이션했습니다.
첫 24시간 동안 정규 실행 8회가 모두 성공했습니다 (소요 3.5~6.0분 · 재시도 0 · 오탐 0 · [런북 §6.5](docs/runbook/2026-09-04-running-the-cycle-under-airflow.md)).

### 5.1. 실행

- **구성**: Airflow 3.3.1 · `LocalExecutor` · Postgres 메타 DB · DAG 1개 · 태스크 8개 (§2)
- **옛 타이머의 성질을 그대로 옮긴 설정**
  - `catchup=False`: 밀린 실행은 1회만 수행
  - `max_active_runs=1`: 동시 실행 금지
  - `dagrun_timeout` 30분
- **완주율**: 508회 중 504회로 **99.2%** (2026-07-20 이후 · 마지막 태스크까지 끝낸 실행의 비율)
  - 산출 방식은 [성공률 3종과 아무도 측정하지 않았던 1종](docs/troubleshooting/2026-09-11-three-success-rates-and-the-one-nobody-measured.md) 에 정리했습니다.
  - 수집 현황 대시보드의 「완주율 · 07-20 이후」 타일이 같은 기준으로 실행마다 값을 새로 산출합니다.

### 5.2. 배포 자동화

`advance` 가 `origin/main` 을 내려받고, 파이프라인 실행 후 `judge` 가 라이브의 `build.json` 으로 반영 여부를 확인합니다.
설계는 [배포 자동화 스펙](docs/superpowers/specs/2026-09-03-deploy-automation-design.md) 에 있습니다.

```
gate (dbt 테스트 21종)
  |
  +-- 통과
  |     +-- deploy_site -> judge 가 라이브 build.json 의 커밋 해시를 대조
  |           |
  |           +-- 일치 -> 반영 완료 + 리뷰 채널 알림
  |           +-- 불일치 -> 이전 커밋으로 롤백 + 사고 채널 알림
  |
  +-- 차단
        +-- deploy_site 를 건너뛴다 (배포 없음) + 사고 채널 알림
```

게이트 결과 파일이 없으면 통과로 간주하지 않고 차단으로 판정합니다 ([8. 설계 결정과 트레이드오프](#8-설계-결정과-트레이드오프)).

### 5.3. 알림

Discord 채널 2개 (사고 · 리뷰) 를 운영합니다.
모든 알림에 「무엇이 · 어디서 · 다음에 확인할 로그」 를 함께 담습니다.

- **데이터 축**: 수집량 이상 · 소스 신선도 · dbt 게이트 차단
- **실행 축**: 태스크 실패 · DAG 타임아웃 · 배포 판정
- **운영 축**: 워치리스트 · 명단 정합

### 5.4. 백업과 복구

- **매일**: MariaDB 논리 덤프와 MongoDB 아카이브 (합계 약 4 MB) 를 GCS 에 업로드
- **복구할 때**: 별도 DB 에 복원해 테이블 6개와 `raw_items` 의 행 수를 백업 매니페스트와 대조
  - 하나라도 불일치하면 0 이 아닌 종료 코드로 끝납니다.
  - 2026-09-01 복구 테스트에서 7개가 전부 일치했습니다 ([백업 · 복구 런북](docs/runbook/2026-09-01-backup-and-restore.md)).

### 5.5. 재처리와 스키마 변경

원본을 Bronze 에 불변으로 보존하므로 판정 규칙이 바뀌면 전체 재처리가 가능합니다.

- **누적된 일회성 스크립트**: `src/bullet_in/` 의 `backfill_*.py` 15개와 `migrate_*.py` 2개
  - 바이라인 회수 · 본문 재수집 · 선수 귀속 재추출 · URL 신원 이관 등
- **스키마 변경**: `schema.sql` 의 `ALTER TABLE … IF NOT EXISTS` 25건으로 멱등하게 처리
  - 실행 시작 시 `ensure_schema()` 가 다시 적용합니다.

### 5.6. 대시보드 2종

정적 HTML 로 실행할 때마다 새로 생성하며 검색 엔진에는 노출하지 않습니다.

![행동 지표 대시보드](docs/assets/dashboard-behavior-live.png)

> [행동 지표](https://bullet-in.pages.dev/behavior.html): DAU · 퍼널 (진입 → 카드 클릭 → 반복 → 재방문) · 요일 × 시각 히트맵 · 관심 지수 · 리텐션 · 화면별 클릭 · 페이지 · 상위 기사 · 선수 페이지를 보여 줍니다.
> GA4 이벤트를 Iceberg Gold 테이블로 집계해 렌더링합니다.

**행동 로그의 출처 (GA4 → BigQuery → Iceberg)**

행동 지표 대시보드의 수치는 GA4 가 BigQuery 로 매일 내보낸 이벤트 원본을 `warehouse_load` 태스크가 Iceberg Bronze 로 적재해 집계한 결과입니다.

- **직접 정의한 이벤트 4종**: `bi_entry` (유입) · `bi_card_click` (카드 클릭) · `bi_filter_apply` (필터) · `bi_origin_exit` (원문 이탈)
  - 계측 코드는 `src/bullet_in/serve/static/app.js` 에 있습니다.
- **기사와의 연결**: `bi_card_click` 의 매개변수 `card_hash` 가 기사의 `content_hash` 와 같습니다.
  - 클릭 로그를 Silver 의 기사 행과 그대로 조인할 수 있습니다.
- **교차 검증**: 같은 이벤트를 GA4 콘솔에서도 조회할 수 있습니다.
  - 콘솔 화면으로 확인한 기록은 [계측 배선과 도착 증명 런북](docs/runbook/2026-08-24-wiring-analytics-and-proving-it-arrives.md) 에 있습니다.
  - 방문자 수 산출은 [방문자 · 퍼널 런북](docs/runbook/2026-09-04-measuring-visitors-funnel-and-retention-from-bronze.md) 에 있습니다.

![수집 현황 대시보드](docs/assets/dashboard-ops-live.png)

> [수집 현황](https://bullet-in.pages.dev/ops.html): SLO 6개 행 · 완주율 타일 · 일별 신규 · 실행 수 캘린더 · 소스 × 주차 · 처리량 · 소요 시간 분포 · 발행에서 수집까지의 지연 · 선수 축 · 공신력 · 단계 구성 · 소스 신선도를 한 화면에 모았습니다.

**수집 현황의 출처 (MariaDB Silver → 화면)**

행동 지표와 달리 별도의 집계 저장소를 두지 않고 서빙 DB 를 직접 읽습니다.

- **`pipeline_runs`**: 실행마다 한 행 · 신규 · 중복 · 에러 · 소요 시간 · 소스별 건수
- **`articles`**: 등급 · 이적 단계 · 발행 시각
- **`source_freshness`**: 실행 × 소스의 마지막 수집 시각과 임계
- **dbt 게이트 결과 파일**: 직전 실행의 `unique` · `not_null` 테스트 결과 (SLO-3 과 SLO-4 의 값)

화면 맨 위의 「데이터 원천」 절이 같은 내용을 밝히고 있어 열어서 대조할 수 있습니다.

## 6. 데이터 품질

데이터 계약을 코드로 선언해 두고, 통과하지 못하면 배포를 중단합니다.

### 6.1. dbt 게이트

- **검사 구성**: 실행의 `gate` 태스크가 `dbt build` 로 스테이징 5개와 Gold 3개를 생성하고 테스트 21종을 돌립니다.
  - `unique` 5 · `not_null` 10 · `accepted_values` 4 · `relationships` 2
  - 차단되면 `deploy_site` 가 실행되지 않고 알림이 발송됩니다.
  - 임계 미만의 결측은 경고로 분류해 로그에만 남깁니다.
  설계는 [dbt 품질 게이트 스펙](docs/superpowers/specs/2026-08-31-dbt-quality-gate-design.md) 에 있습니다.
- **게이트 자체의 장애**: dbt 프로세스가 시그널로 종료되면 (세그멘테이션 폴트) 1회 재시도하고 그래도 결과 파일이 생기지 않으면 통과로 간주하지 않습니다.
  2026-08-31 에 실제로 차단이 발생했고, 이후 진단 정보를 stdout 과 stderr 양쪽에 기록하도록 수정했습니다 ([트러블슈팅](docs/troubleshooting/2026-09-01-the-gate-blocked-and-the-journal-could-not-say-why.md)).
### 6.2. 신선도와 수집량

- **신선도**: 소스별 마지막 수집 시각을 원본 수집 워터마크로 판정합니다.
  임계는 소스마다 다르며 (24h ~ 192h) 실측 공백 분포를 근거로 설정했습니다.
  임계를 초과하면 알리고, 재알림 간격은 48시간입니다.
- **수집량 이상**: 직전 실행들의 소스별 수집 건수를 기준으로 ±2σ 를 벗어나는 급감과 급증을 실행마다 탐지합니다.
### 6.3. 번역 품질 게이트

LLM 이 만든 본문을 LLM 없이 규칙 코드로 검사합니다.
검사 여섯 가지 가운데 하나라도 걸리면 사유를 프롬프트에 붙여 최대 두 번까지 다시 생성하고, 세 시도 중 위반이 가장 적은 것을 채택합니다.

| 검사 | 무엇을 보는가 |
|---|---|
| 숫자 누락 | 원문의 숫자가 번역본에 남아 있는가 |
| 수치 주입 | 원문에 없던 숫자가 생겼는가 |
| 인용 보존 | 원문의 인용이 훼손됐는가 |
| 구단명 주입 | 근거 없는 구단명이 들어갔는가 |
| 인명 주입 | 근거 없는 인명이 들어갔는가 |
| 원문 복제 | 글자 8-gram 잔존율이 0.75 를 넘는가 |

게이트는 재생성 트리거이지 폐기 조건이 아니라서 본문을 버리지 않습니다.
잔존율이 임계를 넘은 채로 남은 기사는 수집 현황 대시보드에 올려 사람이 검토합니다.

- **설계**: [번역 신뢰성 설계](docs/superpowers/specs/2026-07-29-translation-trust-design.md)
- **측정 함정**: [LLM 산출물을 코드로 채점할 때 잣대가 만드는 가짜 발견](docs/troubleshooting/2026-07-29-llm-metric-artifacts.md)
  - 숫자를 세는 잣대가 형식을 내용으로 세던 사례입니다.

### 6.4. 테스트

- **구성**: 테스트 1,792개를 유지합니다 (단위 · 통합 · DAG 임포트 · 브라우저 1건).
  통합 테스트는 CI 의 MariaDB 컨테이너에 실제로 연결해 돌리는 방식입니다.

## 7. 기술 스택

| 영역 | 선택 | 이유 |
|---|---|---|
| 서빙 mart | **MariaDB** | 일 수십 건 규모의 서빙 (포인트 조회 · 필터 · `UNIQUE` dedup) 에는 OLTP 가 적합 |
| 원본 랜딩 | **MongoDB** | 구조가 제각각인 원문을 손실 없이 schema-on-read 로 보존해 언제든 재처리 가능 |
| 품질 · 분석 | **dbt + DuckDB** | `dbt test` 가 데이터 계약 검증과 그대로 대응 · DuckDB 가 MariaDB 를 attach 해 별도 인프라 없이 집계와 테스트 수행 |
| 레이크하우스 | **Apache Iceberg on GCS + Google Lakehouse runtime catalog** | 변경 이력 · 스냅샷 · 행동 로그처럼 append 위주 데이터를 서빙 DB 외부에 적재 · PyIceberg 로 직접 쓰고 카탈로그만 매니지드 서비스를 사용해 운영할 서버가 없음 (§8) |
| 스크래핑 | **Playwright / httpx** | 소스 난이도 (정적 · 쿠키 인증 · 안티봇) 에 맞춰 도구를 선택 · X 는 쿠키 주입 Playwright |
| 스케줄 · 배포 | **Airflow 3 (LocalExecutor) + wrangler** | 실행을 태스크 8개로 분리해 3시간마다 수행 · 실패한 태스크만 식별되고 판정 태스크가 배포를 롤백 (§8) · 실행 종료 시 Pages 직접 업로드 |
| LLM 번역 · 요약 | **Gemini 3.1 Flash-Lite** | 일 수백 건 규모 · 단순 번역에 맞는 단가 · `response_mime_type` 으로 JSON 출력 강제. **유료 (Tier 1 선불)** 이며 월 요금은 GCP 결제 보고서에서 조회 (문서에 금액을 고정하면 값이 낡음) |

## 8. 설계 결정과 트레이드오프

선택한 것보다 **선택하지 않은 것과 그에 따라 감수한 것**을 기록합니다.

- **CDC 를 사용하지 않았습니다**
  - 배경: CDC (Debezium · binlog) 는 상류 트랜잭션 DB 의 변경을 캡처하는 기술인데, 이 파이프라인의 소스는 웹 · API · X 라 읽을 binlog 가 없습니다.
  - 선택: 일 수백 건 규모의 배치에 Kafka + Debezium 은 과설계라, 애플리케이션 레벨 변경 감지 (`content_hash` 비교 + `revision` 증가) 를 사용했습니다.
  - 감수한 것: 소스가 조용히 수정한 기사는 다음 수집 시점까지 감지하지 못합니다.
    변경 이력은 실행마다 Iceberg `articles_changes` 에 적재합니다.

- **SLO-1 목표를 70% 에서 55% 로 하향했습니다**
  - 배경: 병렬화로 수집 시간을 단축하는 목표를 초기에 70% 로 설정했으나, 벤치마크 결과 최장 소스 (x_afcstuff · Playwright 약 42초) 가 병렬 수행 시간의 하한을 결정하는 구조였습니다.
  - 선택: 구조적으로 도달 불가능한 목표를 유지하면 지표가 실제 상태를 왜곡하므로 실측을 근거로 재조정했습니다 ([SLO-1 벤치마크 런북](docs/runbook/2026-07-14-slo1-benchmark.md)).
  - 감수한 것: 목표를 하향한 이력이 남습니다.
    다만 그 이력 자체가 목표치를 임의로 정하지 않았다는 근거가 됩니다.

- **매니지드 Iceberg 테이블을 사용하지 않았습니다**
  - 배경: BigQuery 의 `BigLake Table Management` 는 **시간당 165.99 KRW** 라 상시 가동하면 월 12만원 수준입니다 ([레이크하우스 설계 §2](docs/superpowers/specs/2026-09-02-history-lakehouse-design.md)).
  - 선택: 카탈로그만 Google Lakehouse runtime catalog 를 사용하고 테이블은 직접 관리합니다.
  - 감수한 것: PyIceberg 가 제공하지 않는 **Compaction · 스냅샷 만료 · 고아 파일 정리**를 직접 구현하고 매일 수행해야 합니다.
    그 대신 시간당 요금 없이 GCS 저장 · 작업 요금만 부담합니다.

- **품질 게이트와 웨어하우스 적재를 분리했습니다**
  - 배경: 두 작업은 실패했을 때 영향 범위가 다릅니다.
  - 선택: 게이트는 DuckDB 가 MariaDB 를 attach 해 수행하는 **필수 단계**로 두어 실패 시 배포를 중단하고, 웨어하우스 적재는 파이프라인 뒤에 붙는 **부가 단계**로 두어 실패해도 배포에 영향을 주지 않게 했습니다.
  - 감수한 것: Gold 가 두 곳에 생겨 문서와 화면에서 「어느 Gold 인지」 를 매번 명시해야 합니다 (§9).

- **게이트 실패 시 배포를 차단하는 쪽으로 설계했습니다 (fail-closed)**
  - 배경: dbt 프로세스가 시그널로 종료되면 (세그멘테이션 폴트) 결과 파일이 생기지 않아 판정 근거가 사라집니다.
  - 선택: 1회 재시도하고 그래도 결과 파일이 없으면 **차단**으로 판정합니다.
    2026-08-31 에 실제로 발생했으며, 당시 로그만으로는 원인을 특정할 수 없어 진단 정보를 stdout 과 stderr 양쪽에 기록하도록 수정했습니다 ([트러블슈팅](docs/troubleshooting/2026-09-01-the-gate-blocked-and-the-journal-could-not-say-why.md)).
  - 감수한 것: 게이트 자체의 장애도 배포를 막습니다.
    검증되지 않은 데이터가 배포되는 것보다 낫다고 판단했습니다.

- **LLM 429 응답에 행 단위 백오프를 두지 않았습니다**
  - 배경: 분당 요청 수 제한이라 건별로 대기하면 실행 시간이 길어집니다.
  - 선택: 429 를 받으면 해당 실행의 번역을 중단하고 다음 실행이 남은 건을 처리합니다.
  - 감수한 것: 제한에 걸린 실행의 기사는 번역이 한 주기 지연됩니다.
    스케줄이 3시간마다 재시도하므로 누적되지는 않습니다.

- **systemd 타이머에서 Airflow 로 마이그레이션했습니다 (2026-09-04)**
  - 배경: 단일 유닛이 실패하면 어느 단계에서 중단됐는지 로그를 직접 추적해야 했습니다.
  - 선택: 태스크 8개로 분리해 실패한 태스크만 식별되게 하고, 판정 태스크가 배포를 롤백하도록 구성했습니다 ([마이그레이션 설계](docs/superpowers/specs/2026-09-04-airflow-migration-design.md)).
  - 감수한 것: Postgres 메타 DB 와 스케줄러가 같은 VM 에 추가로 올라갔습니다.
    되돌릴 경로 (기존 타이머 재활성화) 는 남겨 두었습니다.

## 9. 데이터 모델

메달리온을 2개 운영합니다.
기사와 행동 로그는 원천 시스템도 저장소도 달라 층을 따로 구성했으며, 둘 다 같은 DAG 가 채웁니다.

```
메달리온 1 · 기사

Bronze · MongoDB
 - raw_items · 소스 원문을 변형 없이 보존
 - 신선도 판정의 워터마크가 이 층에서 나옵니다
      |
      v   정규화 · content_hash 계산 · 공신력 tier 산출 · UNIQUE 중복 제거
Silver · MariaDB
 - 테이블 6개 · 서비스 화면과 수집 현황 대시보드가 직접 조회합니다
 - articles · sources · players · article_players
 - pipeline_runs · source_freshness
      |
      v   dbt build (실행의 마지막 단계)
Gold · dbt + DuckDB
 - 집계 모델 3개 · 테스트 21종이 배포를 막는 품질 게이트

Silver 는 mart_history (Iceberg) 로도 흘러갑니다 · 아래 레이크하우스 절


메달리온 2 · 행동 로그        Iceberg on GCS 의 behavior 네임스페이스

Bronze · ga4_events
 - BigQuery 일별 내보내기 · 중첩 · 반복 필드를 그대로 적재
      |
      v   Flatten (ARRAY · STRUCT 해제) · 중복 이벤트 제거
Silver · ga4_events_flat
 - 1행 1이벤트 · 1열 1값
      |
      v   전량 재구축 (신규 · 재방문은 전체 이력이 필요한 비가산 지표)
Gold
 - 팩트 3개 · fact_card_click · fact_session · fact_user_daily
 - 디멘션 2개 · dim_date · dim_user
```

층 이름은 실제 데이터가 존재하는 자리에만 붙였습니다.

- **Bronze (MongoDB `raw_items`)**: 원문을 변형 없이 보존합니다.
  신선도 판정의 워터마크가 이 층에서 산출됩니다.
- **Silver (MariaDB 테이블 6개)**
  - `articles`: 정규화 메타 + `tier` + `confidence` + 번역 · 요약 · `content_hash` 와 `url` 에 `UNIQUE` 로 dedup
  - `sources` · `players`: 소스와 선수 명단
  - `article_players`: 기사 × 선수 매핑 (주체 · 언급)
  - `pipeline_runs`: 실행별 SLO 근거
  - `source_freshness`: 실행 × 소스 신선도 이력
- **Gold (dbt `models/gold/` 모델 3개)**: `gold_daily_source_quality` · `gold_slo_rollup` · `gold_tier_distribution`.
  실행 종료 시 `dbt build` 가 갱신하며 같은 실행의 테스트 21종이 품질 게이트로 동작합니다.

`models/staging/` 의 모델 5개는 MariaDB 테이블을 그대로 읽어 오는 경유 뷰라 층 이름을 붙이지 않았습니다.

**레이크하우스 (Iceberg on GCS)**: 서빙 DB 외부에 적재하는 네임스페이스 2개입니다.

- **`mart_history`**: 서빙 DB 가 덮어쓰면 사라질 값을 남깁니다.
  - `articles_changes`: 실행별 변경분
  - `articles_snapshot` · `players_snapshot` · `article_players_snapshot`: 90일까지 매일 · 이후 주 1회
  - `ops_daily`: 일별 운영 지표
- **`behavior`**: GA4 이벤트 (BigQuery 일별 내보내기 · §5) 를 층으로 나눠 적재합니다.
  - Bronze `ga4_events` · Silver `ga4_events_flat`
  - Gold 팩트: `fact_card_click` · `fact_session` · `fact_user_daily`
  - Gold 디멘션: `dim_date` · `dim_user`
  - Gold 는 실행마다 Silver 에서 전량 재구축하며 사용자 식별에는 `user_pseudo_id` 만 씁니다 ([사용자 키를 혼용하면 방문자가 두 배로 집계된다](docs/troubleshooting/2026-09-04-two-keys-double-the-visitor-count.md)).

## 10. 저장소 구조

| 경로 | 내용 |
|---|---|
| `src/bullet_in/run.py` · `pipeline.py` | 실행 1회의 진입점과 항목 판정 (여성 축구 제외 · 본문 등급 · 기자 선택) |
| `src/bullet_in/adapters/` | 소스별 수집기 (`rss` · `html` · `playwright_news` · `x_playwright` · `arsenal_api` · `guardian_api` · `fmkorea`) |
| `src/bullet_in/ingest.py` · `canonical.py` · `dedup.py` | 병렬 수집 · URL 정본화와 `content_hash` · 신규 · 변경 · 중복 분류 |
| `src/bullet_in/credibility.py` · `score.py` | 기자 · 매체 레지스트리 조회와 `tier` · `confidence` 산출 |
| `src/bullet_in/enrich.py` · `fidelity.py` | LLM 번역 · 요약과 번역 품질 게이트 (§6) |
| `src/bullet_in/roster.py` · `transfer_stage.py` | 선수 명단과 이적 단계 |
| `src/bullet_in/storage/` | MongoDB (Bronze) · MariaDB (Silver) 접근과 `schema.sql` |
| `src/bullet_in/serve/` | 정적 HTML 렌더 · 대시보드 2종의 뷰 · 차트 |
| `src/bullet_in/dbt_gate.py` · `deploy.py` · `warehouse.py` | 품질 게이트 · 배포 판정과 롤백 · Iceberg 적재 |
| `src/bullet_in/quality.py` · `metrics.py` · `notify.py` | 수집량 이상 감지 · SLO 측정 · Discord 알림 |
| `airflow/dags/` | DAG 정의와 태스크 스크립트 |
| `dbt/models/` | staging 5개 · gold 3개와 테스트 21종 |
| `config/` | 수집 소스 · 공신력 레지스트리 · 표기 사전 등 YAML 5개 |
| `tests/` | 단위 테스트와 `integration/` (MariaDB 컨테이너가 필요합니다) |
| `infra/` | systemd 유닛 · 백업 · 배포 스크립트 |
| `docs/` | 설계 · 계획 · 런북 · 트러블슈팅 (§12) |

## 11. 실행 방법

```bash
# 0. 환경
cp .env.example .env          # 값 채우기 (Mongo · MariaDB · Gemini · Guardian · X)
uv sync --extra dev
uv run playwright install chromium

# 1. 데이터 스토어
docker compose up -d          # mongo, mariadb

# 2. 파이프라인 1회 실행 (dotenv 미사용 → 셸 export 필요)
set -a; source .env; set +a
uv run python -m bullet_in.run --concurrency 8          # collect → enrich → publish → gate 를 한 프로세스로

# 3. 결과 확인
open site/index.html          # 기사 · 선수 · 대시보드 2종 (site/behavior.html · site/ops.html)
```

테스트는 `uv run pytest -q` 로 실행합니다 (통합 테스트는 MariaDB 컨테이너가 없으면 skip 됩니다).
Airflow DAG 임포트는 별도 venv 에서 검증합니다 ([docs/MIGRATION.md](docs/MIGRATION.md)).
운영 VM 의 실행 · 수동 트리거 · 롤백 절차는 [Airflow 런북](docs/runbook/2026-09-04-running-the-cycle-under-airflow.md) 에 있습니다.

## 12. 문서 구성

설계 (`docs/superpowers/specs/` 71편) · 계획 (`docs/superpowers/plans/` 61편) · 런북 (`docs/runbook/` 88편) · 트러블슈팅 (`docs/troubleshooting/` 181편) 이 있습니다.
아래 5편을 먼저 읽는 것을 권장합니다.

1. [파이프라인 실행을 Airflow 로 이관한 설계](docs/superpowers/specs/2026-09-04-airflow-migration-design.md): 이관 시점의 판단 근거 · 태스크 8개 구성 · 실패 유형 3종 (프로세스 종료 · 건너뜀 · 차단) · 롤백 경로.
2. [배포 자동화 설계](docs/superpowers/specs/2026-09-03-deploy-automation-design.md): 머지된 코드가 자동으로 배포되고 검증되고 롤백되는 경로.
3. [dbt 품질 게이트 설계](docs/superpowers/specs/2026-08-31-dbt-quality-gate-design.md) 와 [게이트가 차단됐는데 로그가 원인을 말하지 못한 사례](docs/troubleshooting/2026-09-01-the-gate-blocked-and-the-journal-could-not-say-why.md).
4. [백업 · 복구 런북](docs/runbook/2026-09-01-backup-and-restore.md): 복원 검증까지 포함한 절차.
5. [사용자 키를 혼용하면 방문자가 두 배로 집계된다](docs/troubleshooting/2026-09-04-two-keys-double-the-visitor-count.md) 와 [층을 잘못 참조한 차트 3건](docs/troubleshooting/2026-09-04-three-charts-that-pointed-at-the-wrong-layer.md): 행동 로그를 화면에 올리기 전에 겪은 측정 오류.

트러블슈팅 문서는 「무엇이 틀렸는가」 보다 「해당 결함을 어떤 검증 수단이 놓쳤는가」 에 무게를 둡니다.
같은 검증 공백이 다른 곳에서 반복되기 때문입니다.

## 13. AI 도구 활용

이 저장소는 한 사람이 Claude Code 와 함께 개발하고 운영합니다.
어디까지 AI 에 맡기고 어디부터 사람이 결정하는지, AI 가 만든 오류를 어떻게 걸러냈는지를 적었습니다.

| 순서 | 단계 | 주체 |
|---|---|---|
| 1 | brainstorming | 사람이 승인 |
| 2 | 스펙 | AI 초안 · 사람이 승인 |
| 3 | 계획서 (dry run) | AI 초안 · 사람이 승인 |
| 4 | Task 단위 구현 (subagent · TDD) | AI |
| 5 | spec 리뷰 · code 리뷰 | 리뷰 모델 |
| 6 | 실측 검증 | 사람 · 리뷰 모델 |
| 7 | PR 작성 | AI |
| 8 | Merge | 사람 |
| 9 | 배포 | 다음 파이프라인 실행이 수행 |

### 13.1. 방법론

- 개발 흐름은 `superpowers` 스킬 묶음으로 고정합니다.
  - `brainstorming`: 아직 정해지지 않은 사항을 먼저 확인합니다.
  - `writing-plans`: 스펙과 계획서를 문서로 만듭니다.
  - `subagent-driven-development`: 계획서를 Task 단위로 구현합니다.
  - `verification-before-completion`: 실행 결과를 근거로만 완료를 선언하도록 강제합니다.
- 코드 작성 규칙은 Karpathy 4원칙입니다 (코딩 전 사고 · 단순함 우선 · 수술적 변경 · 검증 가능한 목표).
  2026-06-12 에 `CLAUDE.md` 에 병합했고 모든 코드 태스크에 동일하게 적용합니다.
- 계획서에 코드 전문이 포함되면 구현 전에 1회 실행해 봅니다 ([dry run 런북](docs/runbook/2026-09-06-dry-running-a-plan-before-executing-it.md)).
  2026-09-05 에는 단위 테스트를 모두 통과한 계획서 코드에서 실제 동작과 어긋난 곳을 11군데 찾았습니다.
- 설계 · 구현 · 최종 리뷰를 서로 다른 모델이 담당하고 실제로 작업한 모델을 커밋의 co-author 로 기록합니다.
  2026-09-22 기준 co-author 가 기록된 커밋은 607건, 등장한 모델은 7종입니다.

### 13.2. 역할 분담

| 주체 | 맡은 일 |
|---|---|
| **사람** | 요구사항과 지표를 정의하고, 스펙 · 계획서 · 화면 목업을 승인하거나 반려합니다. 실측값을 화면 · DB · 로그로 대조하고, LLM 호출과 운영 데이터 정정을 승인합니다. 리뷰 피드백의 채택과 기각, 최종 전체 리뷰를 담당합니다. **PR Merge 491건은 전부 사람이 수행했습니다.** |
| **AI** | 스펙과 계획서 초안, 코드와 테스트 (버그는 재현 테스트부터 작성), 실측 스크립트, 실데이터 기반 대시보드 목업, 문서 초안, 리뷰를 담당합니다. |
| **AI 에 부여하지 않은 권한** | Merge 권한, 운영 서버에서의 `git pull`, 승인 없는 운영 데이터 정정입니다. 배포는 파이프라인의 첫 태스크가 `origin/main` 을 내려받는 방식이므로 사람도 서버에서 직접 pull 하지 않습니다. |

반려 예시: 잘린 트윗의 뒷부분을 프롬프트로 보완하자는 제안은 기각하고 수집기를 수정해 전문을 받도록 했습니다.

### 13.3. 검사 장치

사람이 매번 확인하지 않아도 자동으로 걸러지도록 만든 장치입니다.

- 문서 서식은 저장 시점에 검사합니다.
  `.claude/hooks/check-doc-format.py` 가 컨벤션 §2.2 를 검사하고, CI 의 `docs-format` 잡이 변경된 `docs/*.md` 에 같은 검사를 한 번 더 돌립니다.
- PR 본문은 게시 전에 `.claude/tools/check-pr-format.py` 를 통과시킵니다.
  동일한 위반이 5회 재발한 뒤에 만든 도구라 파일 상단에 그 이력을 기록해 두었습니다.
- 산문 비중이 큰 산출물 (PR 본문 · 런북 · 트러블슈팅) 은 게시 전에 문체 점검을 1회 거칩니다.
- 완료 판정은 실측값으로만 합니다.
  테스트 통과만으로 값이 정확하다고 결론짓지 않습니다 ([테스트 통과가 값의 정확성을 보증하지 않은 사례](docs/troubleshooting/2026-09-06-passing-tests-said-nothing-about-the-values.md)).

### 13.4. AI 협업에서 발생한 문제

동일한 실패가 반복되면 트러블슈팅으로 기록하고, 재발 방지 규칙을 `CLAUDE.md` 나 런북으로 옮기고, 검사 장치가 그 규칙을 받아 강화됩니다.
이 순환이 실제로 동작한 사례 4건입니다.

- [계획서 결함이 구현으로 전파된 사례](docs/troubleshooting/2026-07-14-plan-artifact-defect-propagation.md): 구현 subagent 가 계획서 코드를 사실상 그대로 옮기므로 계획서의 결함이 코드가 됩니다.
  여기서 계획서 dry run 절차가 도입됐습니다.
- [subagent 가 다른 체크아웃에 커밋한 사례](docs/troubleshooting/2026-07-15-subagent-cross-checkout-contamination.md): 디스패치 문구를 게이트 형태로 바꾼 뒤 같은 트랙의 나머지 태스크 7개에서 재발하지 않았습니다.
- [번역 모델 교체 후 게이트가 정상 번역을 오탐한 사례](docs/troubleshooting/2026-07-22-model-swap-gate-false-positives.md): 에러가 아니라 정상 동작처럼 보이는 장애라, 무엇이 실패했는지가 아니라 무엇이 이전보다 늘었는지를 세어야 발견됩니다.
- [계획서 코드를 실행해야 드러난 결함 3건](docs/troubleshooting/2026-09-05-what-only-showed-up-when-the-plan-was-run.md): 템플릿 엔진이 CSS 를 주석으로 해석하는 사례처럼, 부분 테스트로는 드러나지 않고 실제로 실행해야 발견되는 유형입니다.

나머지는 `docs/troubleshooting/` 에서 `subagent` · `session` · `plan` · `prompt` 로 검색하시면 됩니다.

## 14. 한계 및 향후 개선 방향

- **재방문 유도 장치가 없습니다**: 공개 첫 주 순 사용자 827명 중 카드를 클릭한 사용자는 207명, 이틀 이상 방문한 사용자는 113명입니다 (행동 로그 Gold `fact_user_daily` · 08-29 ~ 09-04).
  구독이나 알림 기능은 아직 없습니다.
- **방문자 수는 실제보다 적게 집계됩니다**: GA4 는 광고 차단 환경의 방문을 잡지 못합니다.
  화면과 이 문서에 적힌 사용자 수도 같은 이유로 작게 나옵니다.
- **정적 서빙**: 페이지는 실행마다 다시 생성한 HTML 이며 개인화와 검색 기능은 없습니다.
- **소스 확장**: The Athletic 같은 하드 페이월과 추가 ITK 는 어댑터 추가로 대응합니다.
  교차 검증 스코어링 (복수 소스가 같은 내용을 보도하면 신뢰도 가산) 과 번역 정확도 표본 검수는 후순위 과제입니다.
- **단일 VM**: 파이프라인 · Airflow · DB 컨테이너가 한 VM 에서 동작합니다.
  백업은 매일 수행하지만 장애 발생 시 복구는 사람이 런북에 따라 수동으로 진행합니다.

## 15. 윤리 및 법적 고지

- 공개된 콘텐츠만 대상으로 하며, robots.txt 준수 · 보수적 rate limit · 출처와 링크 표기를 원칙으로 합니다.
- X (ITK) 는 ToS 그레이존이라 버너 계정을 사용하고 자격증명은 `.env` 로 분리해 커밋하지 않습니다.
  개인 학습 용도입니다.
- 원문 전체를 재배포하지 않고 메타데이터 · 요약 · 원문 링크 중심으로 서빙합니다.
- 소스 성격에 비례한 차등 서빙: 언론사 기사는 요약과 짧은 발췌에 원문 링크를 붙이고, 수십 단어 분량의 트윗과 구단 공식 발표문만 전문을 싣고, 퍼가기를 금지한 커뮤니티는 헤드라인만 표시합니다.
- 방문 분석은 GA4 익명 id 만 사용하며 개인을 식별하지 않습니다 ([이벤트 스키마](docs/superpowers/specs/2026-08-31-analytics-event-schema.md)).
