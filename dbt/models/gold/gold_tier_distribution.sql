{{ config(materialized='table') }}
with counted as (
    select tier, count(*) as n_articles
    from {{ ref('stg_articles') }}
    group by tier
)
select tier, n_articles,
       round(100.0 * n_articles / sum(n_articles) over (), 1) as pct
from counted
