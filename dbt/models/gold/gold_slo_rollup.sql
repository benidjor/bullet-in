{{ config(materialized='table') }}
with recent as (
    select * from {{ ref('stg_pipeline_runs') }}
    order by started_at desc limit 30
),
latest_fresh as (
    select * from {{ ref('stg_source_freshness') }}
    where checked_at = (select max(checked_at)
                        from {{ ref('stg_source_freshness') }})
)
select 'SLO-2' as slo_id,
       '최근 30회 평균 success_rate' as metric,
       avg(success_rate) as value
from recent
union all
select 'SLO-5',
       '수집 끊긴 소스 수 (최신 run)',
       coalesce(sum(case when stale then 1 else 0 end), 0)
from latest_fresh
union all
select 'duration',
       '최근 30회 평균 duration_sec',
       avg(duration_sec)
from recent
union all
select 'fetch_duration',
       '최근 30회 평균 fetch_duration_sec',
       avg(fetch_duration_sec)
from recent
