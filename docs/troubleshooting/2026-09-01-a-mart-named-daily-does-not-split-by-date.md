# 이름에 daily 가 붙은 마트가 날짜로 자르지 않는다 (2026-09-01)

`gold_daily_source_quality` 를 읽다 보니 이름과 내용이 어긋나 있었다.
이름은 「일자별」 을 말하는데 SQL 에 날짜가 한 번도 안 나온다.

## 1. 실물

모델 전문이다.

```sql
select source_id,
       count(*) as n_articles,
       avg(confidence_score) as avg_confidence,
       sum(case when title_ko is null then 1 else 0 end) as untranslated
from {{ ref('stg_articles') }}
group by source_id
```

`group by source_id` 뿐이다.
날짜 컬럼도 `where` 절도 없다.

이 모델이 내는 것은 **「지금 이 순간의 소스별 누적 집계」** 이고 「일자별 추이」 가 아니다.
소스 하나가 한 행이므로 어제 값과 오늘 값을 나란히 놓을 수단이 없다.

## 2. 이름은 어디서 왔나

**2026-05-27 설계에서 왔고 그때부터 날짜가 없었다.**

- `docs/superpowers/specs/2026-05-27-bullet-in-design.md` 가 마트 셋을 `daily_source_quality` · `tier_distribution` · `slo_rollup` 로 적었다
- 2026-09-01 개명 (PR #406) 에서 `gold_` 접두사를 붙이면서 뒷부분은 그대로 뒀다

즉 **어긋남을 만든 것은 개명이 아니라 최초 명명이고 개명이 그것을 한 번 더 지나쳤다.**

## 3. 왜 두 번 다 안 보였나

개명 회차는 「층 + 내용을 병기한다」 를 원칙으로 세우고 이름을 고쳤다.
그 작업의 잣대가 **「이 모델이 어느 층인가」** 였고 **「이 이름이 참인가」** 는 잣대에 없었다.

그 회차의 판단은 `dbt/dbt_project.yml` 주석에 이렇게 남아 있다.

> 메달리온 층 이름은 실물이 있는 자리에만 붙인다.

층 이름은 실물과 대조했지만 **나머지 절반 (`daily_source_quality`) 은 대조하지 않았다.**
이름을 손대는 작업은 이름 전체를 실물과 대조해야 한다.

## 4. 지금 무엇이 잘못되나

**당장 틀린 값이 나오지는 않는다.**
집계 자체는 맞고 이 마트를 읽는 제품 코드도 없다 (`src/` 전체에서 `gold_daily_source_quality` 매치 0건).
런북이 `duckdb` CLI 로 손수 열어 보라고 안내할 뿐이다.

문제는 **다음 사람이 이름을 믿는다는 것**이다.
「일자별 소스 품질을 보고 싶다」 는 요구가 오면 이 마트를 먼저 열게 되고 열고 나서야 없다는 것을 안다.

## 5. 고치는 길 둘

| 길 | 내용 | 조건 |
| --- | --- | --- |
| 이름을 내용에 맞춘다 | `gold_source_quality` 로 줄인다 | 지금 바로 가능 · 런북 한 곳을 함께 고친다 |
| 내용을 이름에 맞춘다 | 날짜 축을 넣어 진짜 일자별로 만든다 | **이력 층이 있어야 성립한다** — 지금은 어제 값이 저장돼 있지 않다 |

두 번째가 본래 의도로 보이지만 `articles` 가 upsert 로 덮어써서 과거 시점 값이 남지 않는다.
그래서 **이력 층을 세우는 안건과 묶어서 처리한다.**

## 6. 남긴 규율

- **이름을 고칠 때는 이름 전체를 실물과 대조한다.** 고치려는 부분만 대조하면 나머지 절반이 그대로 남는다
- **집계 모델의 이름에 「무엇으로 묶는가」 를 적기 전에 `group by` 를 읽는다**

## 관련

- 개명 근거 = `dbt/dbt_project.yml` 주석
- 최초 명명 = `docs/superpowers/specs/2026-05-27-bullet-in-design.md`
- 마트 조회 절차 = `docs/runbook/2026-07-14-ops-monitoring-view.md`
