select source_id,
       count(*) as n_articles,
       avg(confidence_score) as avg_confidence,
       sum(case when title_ko is null then 1 else 0 end) as untranslated
from {{ ref('stg_articles') }}
group by source_id
