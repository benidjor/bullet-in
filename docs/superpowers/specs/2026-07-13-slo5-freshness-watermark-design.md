# SLO-5 신선도 워터마크 감시 설계 (2026-07-13)

로드맵 SoT ( `docs/superpowers/2026-06-28-v1-completion-roadmap.md` ) Tier 3 잔여 중 SLO-5 슬라이스.
초기 설계 §10 "신선도 ( freshness ) — 윈도우 내 신규 누락 0" 을 앱 레벨 소스별 감시 + 알림으로 구현.

## 1. 배경 · 문제

- **조용한 소스 사망** — 소스가 셀렉터 드리프트 · 피드 URL 변경 · X 쿠키 만료로 수집이 끊겨도 파이프라인은 예외 없이 "0건" 을 반환하고 넘어감.
- **뒤늦은 발견** — 며칠 뒤에야 "이 소스 소식이 안 들어온다" 를 사람이 알아챔.
  이 프로젝트가 자주 밟는 "소스 셀렉터 드리프트" 함정 ( `docs/troubleshooting/2026-06-12-live-source-selector-drift.md` ) 과 직결.
- **SLO-6 의 사각** — 수집량 이상 알림 ( SLO-6 ) 은 baseline ≥ 3 소스의 *건수* 급변만 봄.
  저빈도 · 조용한 소스는 min_baseline 필터로 제외되어 못 잡음.

## 2. 목표 · 비목표

- **목표** — 소스별 "마지막 신규 수집 후 경과 시간" 을 매 실행 재서 임계 초과 시 Discord 알림.
- **목표** — 회차별 소스 신선도를 이력 테이블에 기록해 SLO-7 모니터링 뷰 기반 확보.
- **비목표 ( YAGNI )** — 증분 수집 fetch 전환 없음 ( 전량 수집 + dedup 유지 ).
- **비목표** — 어댑터 수정 없음 · dbt freshness 블록 없음 · `published_at` 미사용.

### 2.1. 감시만 하는 이유 · 증분 전환과의 직교성

- **알림은 "무엇" 만, "왜" 는 진단 몫** — 신선도 위반의 원인이 처방을 정하며 처방 목록에 "수집 방식 변경" 은 없음.
- **원인 → 처방** — 진단표는 아래.

| 원인 | 처방 |
|---|---|
| 셀렉터 드리프트 ( 사이트 개편 ) | `sources.yaml` 셀렉터 수정 |
| 피드 URL 변경 | `feed_url` 갱신 |
| X 쿠키 만료 | 쿠키 재주입 |
| 기자 계정 이전 | 팔로우 대상 갱신 |
| 소스가 진짜 조용 ( 오프시즌 ) | 조치 없음 — 정상 |

- **증분 전환은 별개 축** — 증분 수집은 "새 것만 골라 덜 fetch" 하는 효율 작업이지 죽은 소스를 살리지 못함.
  신선도 문제의 해결책이 아니므로 이번 트랙에서 제외하고 필요 시 독립 트랙으로 정당화.

## 3. 동작 흐름

run.py 가 서빙 후 · SLO-6 이상탐지 블록 옆에서 수행.

```
[수집 · 적재 · enrich · 서빙 완료]
▼
watermarks = SELECT source_id, MAX(fetched_at) GROUP BY source_id   (enabled 소스 전부)
now        = SELECT NOW()                                            (DB 시계)
▼
records = evaluate_freshness(watermarks, now, default_hours, overrides)
▼
source_freshness 테이블에 records 전량 append (run_id 공유)
▼
breaches = [r for r in records if r.stale]
▼
breaches 있으면 → notify.send_alert(build_freshness_alert(...))   없으면 조용
```

## 4. 컴포넌트 설계

### 4.1. 판정 함수 ( quality.py )

- **순수 함수 · 테스트 대상** — I/O 없이 입력만으로 판정해 단위 테스트로 경계 · override · NULL 을 고정.

```python
@dataclass
class SourceFreshness:
    source_id: str
    last_fetched_at: datetime | None
    threshold_hours: float
    age_hours: float | None   # 워터마크 없으면 None
    stale: bool               # 워터마크 없으면 False (알림 제외)

def evaluate_freshness(watermarks, now, default_hours, overrides) -> list[SourceFreshness]:
    # thr = overrides.get(sid, default_hours)
    # age = (now - wm)/3600, stale = age > thr  (wm None → age None, stale False)
```

- **입력** — `watermarks` 는 `{source_id: MAX(fetched_at) | None}` ( enabled 소스 전부 ).
- **`now`** — DB `SELECT NOW()` 로 받아 DB 측 `MAX(fetched_at)` 과 TZ · 시계 불일치 제거.
- **반환** — 소스별 한 레코드 · run.py 가 전량 기록하고 `stale` 만 골라 알림.

### 4.2. 이력 테이블 ( schema.sql )

- **멱등 추가** — 기존 `articles` · `pipeline_runs` 처럼 `CREATE TABLE IF NOT EXISTS` 로 `ensure_schema()` 가 적용.

```sql
CREATE TABLE IF NOT EXISTS source_freshness (
  run_id VARCHAR(64), checked_at DATETIME, source_id VARCHAR(64),
  last_fetched_at DATETIME, age_hours FLOAT, threshold_hours FLOAT,
  stale BOOLEAN,
  PRIMARY KEY (run_id, source_id));
```

| 컬럼 | 의미 |
|---|---|
| `run_id` | 실행 식별자 ( pipeline_runs 와 공유 ) |
| `checked_at` | 신선도를 잰 시각 ( = DB `NOW()` ) |
| `source_id` | 소스 식별자 |
| `last_fetched_at` | 워터마크 = 소스 `MAX(fetched_at)` · 기사 0건이면 NULL |
| `age_hours` | 경과 시간 = checked_at − last_fetched_at · 워터마크 없으면 NULL |
| `threshold_hours` | 적용된 임계 ( 전역 기본 또는 개별 override ) |
| `stale` | 임계 초과 여부 |

- **적재량** — 회차 × 소스 한 행 ( 4회/일 × ~15소스 = ~60행/일 ) 로 부담 없음.

### 4.3. 임계값 ( config/sources.yaml )

- **전역 기본 48h + 개별 override** — 오탐을 줄이는 안전망을 전역에 두고 빠른 소스만 좁힘.
- **X 계정 소스 24h** — adapter 가 x_playwright / x_backtrack 인 소스에 `freshness_hours: 24` ( 현재 x_afcstuff ).

```yaml
freshness_default_hours: 48        # 신규 최상위 키
sources:
  - source_id: x_afcstuff
    adapter: x_playwright
    freshness_hours: 24            # 개별 override
```

- **읽기** — run.py 가 `cfg.get("freshness_default_hours", 48)` + 소스별 `freshness_hours` 를 함수에 전달.

### 4.4. 알림 ( notify.py )

- **`send_alert` 재사용** — SLO-6 과 동일 채널 · embed 규격 · `COLOR_ANOMALY` ( 소프트 경고 톤 ).

```python
def build_freshness_alert(breaches, default_hours) -> dict:
    # "⏳ x_afcstuff: 61.4h 경과 (임계 24h)" 줄 나열
    # title = "🕰️ 신선도 경고 — 오래된 소스", color = COLOR_ANOMALY
```

- **조건 발송** — stale 소스가 하나라도 있을 때만 발송 · 없으면 무음.

### 4.5. run.py 연결

- **run_id 공유 리팩터** — 현재 pipeline_runs INSERT 에 인라인 생성되는 `run_id` 를 `main()` 상단에서 한 번 생성.
  freshness 기록 · pipeline_runs 가 같은 값을 씀.
- **위치** — 서빙 ( `write_site` ) 후 · SLO-6 anomaly 블록 인접.

## 5. 엣지 케이스

- **워터마크 없음** ( 기사 0건 ) — 행은 기록 ( last_fetched_at NULL · stale False ) 하되 알림 제외.
  "신규 추가" 와 "처음부터 죽음" 을 구분 불가하므로 SLO-6 · 에러 처리가 담당.
- **첫 실행 · 신규 소스** — 워터마크가 방금 찍혀 신선 → 알림 없음.
- **비활성 · config 제거 소스** — 순회 대상 ( enabled config ) 에서 제외 → 유령 알림 없음.
- **경계** — `age > threshold` ( 초과 ) 만 stale · 정확히 같으면 아님.

## 6. 테스트 계획

- **`evaluate_freshness` 단위 테스트** — 위반 · 비위반 · override 적용 · NULL 워터마크 · 경계 ( 임계 정확히 · 초과 ) · 빈 입력.
- **`build_freshness_alert` 테스트** — 문자열 형식 · title · color · 여러 소스 나열.
- **DB 게이트 통합** — 테이블 적재 · run_id 공유는 DB 있을 때만 ( 기존 통합 테스트 skip 규약 준수 ).

## 7. 산출물

- **코드** — `quality.evaluate_freshness` · `notify.build_freshness_alert` · `schema.sql` 테이블 · `config/sources.yaml` 키 · run.py 연결.
- **테스트** — 위 단위 테스트.
- **런북** — 신선도 알림 대응 절차 ( §2.1 원인 → 처방 진단표 확장 · 임계 조정 가이드 ).

## 8. 향후 확장 ( 범위 밖 )

- **증분 수집** — 소스별 워터마크로 신규만 fetch 하는 효율 최적화는 별도 트랙 · 별도 정당화.
- **dbt freshness 블록** — 테이블 전역 단위라 소스별 사각이 있어 미채택 · 필요 시 재검토.
- **SLO-7 모니터링 뷰** — 본 트랙의 `source_freshness` 이력을 소스별 신선도 추세 조회에 사용.
