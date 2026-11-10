-- One clean row per job. Dates become real dates, every row gets a single key, and blank text becomes null
-- so the not_null tests catch it.
select
    source || ':' || source_id                          as job_key,
    source,
    source_id,
    nullif(trim(title), '')                             as title,
    nullif(trim(company), '')                           as company,
    trim(location)                                      as location,
    description,
    try_cast(posted_at as timestamptz)                  as posted_at,
    nullif(trim(url), '')                               as url,
    category,
    salary_min,
    salary_max,
    try_cast(fetched_at as timestamptz)                 as fetched_at
from {{ source('raw', 'jobs') }}
