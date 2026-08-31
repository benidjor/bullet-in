select content_hash, url, source_id, tier, confidence_score,
       title_original, title_ko, summary_ko, transfer_stage, transfer_direction,
       published_at, fetched_at
from {{ source('maria', 'articles') }}
