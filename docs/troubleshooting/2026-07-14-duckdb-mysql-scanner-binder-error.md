# duckdb + mysql_scanner 의 binder 내부 오류 — 오진에서 재현까지 (2026-07-14)

## 배경

Task 5 (dbt staging · 마트 2종 추가) 는 `tier_distribution` · `slo_rollup` 마트를 `stg_articles` 위에 `GROUP BY` 로 구현했다.
`dbt build` 가 신규 모델에서 ERROR 3건을 냈고, 최초 조사는 이를 "dbt-duckdb 프레임워크 버그" 로 결론지었다 (오진).

## 증상

`dbt build` 가 `stg_articles` 를 `GROUP BY tier` 로 집계하는 신규 모델에서만 ERROR 를 냈다.
`stg_articles` 자체를 그대로 select 하는 기존 모델은 통과했다 — 집계가 추가된 지점에서만 실패했다.

## 원인 (오진 경위 포함)

**최초 오진** — "직접 SQL 로 검증했더니 duckdb 자체에서도 재현된다" 며 dbt-duckdb 프레임워크 버그로 보고했다.
그러나 그 "직접 검증" 은 attach 가 없는 세션 + 시스템 `python3` 의 duckdb 1.1.3 (dbt 가 실제로 쓰는 uv venv 는 1.5.3) 으로 실행한 것이었다 — 검증 환경이 실행 환경과 다른 전제 위에서 나온 결론이라 무효였다.

**재현 · 정정된 진단** (uv venv, duckdb 1.5.3, attach 세션에서 재확인):
- `select * from stg_articles` → OK.
- `select tier, count(*) from stg_articles group by tier` → `InternalException: Failed to bind column reference "tier"` (`ColumnBindingResolver` 내부).
- 동일 집계 쿼리를 attach 없이 `maria.articles` 테이블에 직접 실행 → OK — attach 위 뷰를 거칠 때만 발현.
- 옵티마이저를 하나씩 꺼보는 스윕에서 `disabled_optimizers='extension'` 을 줬을 때만 ERROR 가 사라짐을 확인.

**결론** — duckdb 1.5.3 + `mysql_scanner` 의 extension 옵티마이저 (컬럼 pushdown) 가, attach 된 MySQL 테이블을 참조하는 뷰 위에서 집계 쿼리를 돌릴 때 컬럼 바인딩을 잘못 해석해 binder 내부 오류를 낸다.
마트를 `materialized='table'` 로 구체화하는 것만으로는 회피되지 않는다 — CTAS (`CREATE TABLE AS SELECT`) 자체가 내부적으로 같은 집계 경로를 타 동일하게 실패하는 것을 확인했다.

## 해결

`dbt/profiles.yml` 의 duckdb 타깃에 `settings.disabled_optimizers: "extension"` 을 추가해 pushdown 최적화만 끈다.

```yaml
settings:
  disabled_optimizers: "extension"
```

- 마트 2종을 `{{ config(materialized='table') }}` 로 구체화한 것과 별개의, 근본적인 우회다 (구체화는 "마트는 table" 이라는 정석 + attach 없는 직접 조회 지원을 위한 결정이고, ERROR 해소는 옵티마이저 설정이 담당).
- 현재 데이터 규모 (기사 189행 · 실행 이력 12행) 에서는 pushdown 미적용으로 인한 성능 저하가 없다.
- 적용 후 `dbt build` 는 신규 모델 포함 PASS=16 WARN=0 ERROR=0 으로 통과했다 (`.superpowers/sdd/task-5-report.md`).

## 예방

- **검증 환경이 실행 환경과 같은 전제 (attach · 버전) 를 갖는지 먼저 확인한다.**
  이번 최초 오진은 attach 없는 세션 + 다른 duckdb 버전으로 "직접 검증" 했다는 것 자체가 무효 검증이었다.
  "직접 SQL 로 재현했다" 는 진술은 그 SQL 이 실제 실행 경로 (attach 여부 · 버전 · 옵티마이저 설정) 와 같은 조건에서 돌았는지부터 확인해야 신빙성을 갖는다.
- **프레임워크 버그 결론은 최후의 가설로 남겨둔다.**
  "duckdb 가 잘못됐다" 는 결론은 재현 조건을 실행 환경과 일치시키고, 옵티마이저 · 확장 설정을 하나씩 좁혀본 뒤에도 남는 잔여 가설이어야 한다 — 이번처럼 설정 하나 (`disabled_optimizers`) 로 해소되는 경우가 실제로는 훨씬 흔하다.
- 이번 케이스처럼 "뷰 위 집계 + attach 확장" 조합에서 재현 안 되는 것처럼 보이면, 먼저 attach 세션 · venv duckdb 버전으로 재확인부터 한다.

## 참고

- Task 5 report: `.superpowers/sdd/task-5-report.md` ("Fix 1: dbt build ERROR 3 → 0 (원인 진단 정정)").
- 운영: `docs/runbook/2026-07-14-ops-monitoring-view.md` ("dbt 마트 조회" 절 — 이 함정을 만났을 때의 조회 절차).
- 설정: `dbt/profiles.yml` (`disabled_optimizers` 주석에 동일 경위 요약).
