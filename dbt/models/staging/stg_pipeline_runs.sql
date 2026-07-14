select run_id, started_at, duration_sec, fetch_duration_sec,
       new_count, dup_count, error_count, success_rate
from maria.pipeline_runs
