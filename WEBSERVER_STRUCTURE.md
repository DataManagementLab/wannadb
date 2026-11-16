# WannaDBWeb backend structure

See [deployment and database recovery](README.md#web-backend-deployment) and the [web API contract](ROUTES.md).

| Layer | Responsibility |
| --- | --- |
| Next.js | Browser UI, NextAuth, and a same-origin proxy. Server-rendered pages also call Flask directly over the private backend connection. |
| Flask web service | `app.py` registers the organization/account, file, and core blueprints. Requests carry a correlation ID. PostgreSQL membership and task scope determine access. |
| Compute worker | Processes document creation and mutations, loads bases, runs read-only SQL previews, and advances interactive feedback a step at a time. |
| PostgreSQL | Authoritative source documents, saved BSON snapshots, attribute metadata, votes, checkpoints, and durable receipts for committed feedback. |
| Redis | Celery broker/results, admissions, and temporary task, feedback, and SQL publications. |
| SQLite | In-memory read-only SQL query projection inside the worker. |
| Flower | Optional monitoring. Production enables it with the `monitoring` profile, authentication, and the loopback listener. |

## Queue ownership

The `worker` service consumes the `celery` queue, including interactive feedback commands. It releases its slot when a session waits for input. Separate users can have open sessions on the same base. The `feedback-worker` service listens on the legacy `feedback` queue. Its presence in Flower does not mean current review commands run there.

Tasks have independent queue and execution deadlines. `QUEUE_SECONDS` defaults to 900. The compute queue defaults to 32 waiting or running tasks and 8 per user, controlled by `MAX_COMPUTE_TASKS` and `MAX_COMPUTE_TASKS_PER_USER`. Interactive sessions waiting for user input do not consume a compute slot. Do not change queue routing by restarting a consumer on a different queue while jobs are in flight.

## Artifacts

Users upload UTF-8 TXT as source documents. The persisted BSON snapshot is a backend artifact and contains derived nuggets and mappings. The browser receives compact JSON catalogs and page data. A catalog carries IDs and counts. A document view carries text once plus span offsets. Feedback views carry the current ranked candidates and a page of manual-review documents. Table exports are CSV built from the retained, bounded query result.

A Redis or worker failure can interrupt an active publication. The command ID can recover a committed feedback receipt from PostgreSQL. Preserve PostgreSQL independently of cache state, and reopen a session from the base if its live publication is gone.

## Diagnose delays and image warnings

- Use the browser Network panel to separate upload, request submission, status polling, and rendering. The browser uses the frontend origin for all of those requests.
- Check the API error's `X-Request-ID` and the task or command UUID separately. In worker logs, `queue_wait_seconds` is time before claim and `compute_seconds` is time spent running. A queue wait calls for checking the `celery` consumer and admission limits.
- Check `/health/ready` and the migration log before diagnosing task submissions. An expired or cancelled task has a status distinct from waiting on the queue.
- For a SIMD message such as `CPU supports … software requires …`, identify the emitting service and whether it occurred at build, startup, or request time. Capture guest CPU flags, runtime architecture, and Sharp/libvips versions if the frontend optimizer is involved. The navigation logo is served as a static PNG, and the deployed image optimizer is disabled. An image warning alone does not identify a matching or preprocessing slowdown.
