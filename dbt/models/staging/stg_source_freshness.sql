select run_id, checked_at, source_id, age_hours, stale, state
from {{ source('maria', 'source_freshness') }}
