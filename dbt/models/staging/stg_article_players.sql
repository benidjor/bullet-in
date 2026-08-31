select content_hash, player_id, role, stage, extracted_at
from {{ source('maria', 'article_players') }}
