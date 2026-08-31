select id, ko_name, ko_full_name, transfer_status
from {{ source('maria', 'players') }}
