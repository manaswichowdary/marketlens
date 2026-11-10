-- If the latest successful run of a source fetched less than half of the run before it, something is wrong
-- (the source changed, our request was blocked, a company board went missing). A row returned is a failure.
with ranked as (
    select
        source,
        fetched,
        row_number() over (partition by source order by started_at desc) as recency
    from {{ source('raw', 'runs') }}
    where status = 'ok'
)
select latest.source, latest.fetched as latest_fetched, previous.fetched as previous_fetched
from ranked latest
join ranked previous on previous.source = latest.source and previous.recency = 2
where latest.recency = 1
  and previous.fetched > 0
  and latest.fetched < 0.5 * previous.fetched
