-- Freshness: the newest posting we fetched must be less than 2 days old. A row returned is a failure.
select max(fetched_at) as newest_fetch
from {{ ref('stg_jobs') }}
having max(fetched_at) < now() - interval 2 day
