select run_id, checked_at, source_id, age_hours, stale
from {{ source('maria', 'source_freshness') }}
