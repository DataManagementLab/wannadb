# WannaDBWeb backend structure

See [deployment and database recovery](README.md#web-backend-deployment) and the [web API contract](ROUTES.md).

| Layer | Responsibility |
| --- | --- |
| Next.js | Browser UI, NextAuth, and a same-origin proxy. Server-rendered pages also call Flask directly over the private backend connection. |
| Flask web service | `app.py` registers the organization/account, file, and core blueprints. Requests carry a correlation ID. PostgreSQL membership and task scope determine access. |
| Compute worker | Processes document creation and mutations, loads bases, and runs read-only SQL previews. |
| Feedback worker | Opens interactive sessions and advances feedback one step at a time. |
| PostgreSQL | Authoritative source documents, saved BSON snapshots, attribute metadata, votes, checkpoints, and durable receipts for committed feedback. |
| Redis | Celery broker/results, admissions, and temporary task, feedback, and SQL publications. |
| SQLite | In-memory read-only SQL query projection inside the worker. |
| Flower | Optional monitoring. Production enables it with the `monitoring` profile, authentication, and the loopback listener. |

## Image roles

All backend Docker stages use Python 3.11. `backend-requirements.txt` constrains the lightweight roles; it is not installed wholesale in every image.

| Service | Development / production target | Installed role |
| --- | --- | --- |
| API (`wannadb`) | `dev` / `prod`, both based on `api` | Flask/PostgreSQL, auth, Celery/Redis submission and lightweight BSON/NumPy document support. No Torch, model downloads or desktop UI dependencies. |
| Migration (`migrate`) | `migrate` / `migrate` | Flask and psycopg2 plus the migration runner and SQL files. No worker or model imports. |
| Monitor (`flower`) | `flower` / `flower` | Celery, Flower and Redis. Monitors the broker without importing `celery_app` or loading models. |
| Both workers | `worker` / `worker-prod` | Torch 2.4.1, core and backend requirements, extraction/matching libraries and model assets. |

The development worker image also prepares desktop/experimental models, and Compose mounts the host checkout over `/home/wannadb`; ensure that checkout's model paths are populated. Production workers bake in the web spaCy, Stanza, BERT and sentence-transformer assets and set `HF_HUB_OFFLINE=1`. This flag only controls Hugging Face access. The shared extractor still requests NLTK `punkt_tab` at import time; provision its cache or allow that request until the separate shared-core issue is resolved. Avoid describing worker startup as fully network-independent.

API startup registers task classes for submission without loading their model resources. Workers initialize those resources lazily when needed. `BaseTask` remains the common lifecycle/status helper and is not registered as a standalone runnable task. The obsolete demo/setup/reset tasks and backend CSV stub are removed; CSV is built by the frontend from the bounded query result.

## Queue ownership

The `worker` service consumes the `celery` queue for general document-base work. The `feedback-worker` service consumes the `feedback` queue for opening interactive sessions and applying feedback commands. It releases its slot when a session waits for input. Separate users can have open sessions on the same base.

Stopping an attribute advances the current session to its next attribute. The explicit whole-session close command can run while a proposal is in conflict, clears that reviewer's durable checkpoint and releases their session capacity. It preserves committed matches and uses the same durable receipt and publication recovery as other feedback commands. The close task does not restore the matcher or load model resources.

Tasks have independent queue and execution deadlines. `QUEUE_SECONDS` defaults to 900. Both queues share an admission limit of 32 waiting or running tasks and 8 per user by default, controlled by `MAX_COMPUTE_TASKS` and `MAX_COMPUTE_TASKS_PER_USER`. Interactive sessions waiting for user input do not consume a compute slot. Do not change queue routing by restarting a consumer on a different queue while jobs are in flight.

## Worker recovery and health

Both Compose configurations restart exited long-running services. The migration job runs once and exits. Docker must start on host boot, and intentionally stopped services using `unless-stopped` need an explicit start. Docker's restart policy responds to process exits, so external monitoring must also check queue health and alert on stale consumers or waiting work.

Each worker publishes a lease for the queues it actually consumes from its parent event loop. By default it refreshes every ten seconds and the lease expires after 45 seconds. Redis time determines lease expiry. Busy prefork children do not prevent the parent from refreshing availability.

`/health/live` reports the API process. `/health/ready` also checks migrations, Redis and live consumers for both `celery` and `feedback`. It reports broker waiting depth, oldest waiting age and `ready`, `missing_consumer` or `delayed` for each queue. Missing consumers cause `503` after lease expiry. Waiting age of at least 60 seconds produces `delayed` and a log warning while readiness remains `200` with available consumers. Reserved/running tasks are excluded. Missing enqueue timestamps produce a null age and a warning.

The API reads these metrics without importing worker models. See [service recovery and queue health](README.md#service-recovery-and-queue-health) for configuration and the operator's staging restart rehearsal.

## Artifacts

Users upload UTF-8 TXT as source documents. The persisted BSON snapshot is a backend artifact and contains derived nuggets and mappings. The browser receives compact JSON catalogs and page data. A catalog carries IDs and counts. A document view carries text once plus span offsets. Feedback views carry the current ranked candidates and a page of manual-review documents. Table exports are CSV built from the retained, bounded query result.

A Redis or worker failure can interrupt an active publication. The command ID can recover a committed feedback receipt from PostgreSQL. Preserve PostgreSQL independently of cache state, and reopen a session from the base if its live publication is gone.

## Diagnose delays and image warnings

- Use the browser Network panel to separate upload, request submission, status polling, and rendering. The browser uses the frontend origin for all of those requests.
- Check the API error's `X-Request-ID` and the task or command UUID separately. In worker logs, `queue_wait_seconds` is time before claim and `compute_seconds` is time spent running. For a queue wait, check the worker for that task’s queue and the shared admission limits.
- Check `/health/ready` and the migration log before diagnosing task submissions. An expired or cancelled task has a status distinct from waiting on the queue.
- For a SIMD message such as `CPU supports … software requires …`, identify the emitting service and whether it occurred at build, startup, or request time. Capture guest CPU flags, runtime architecture, and Sharp/libvips versions if the frontend optimizer is involved. The navigation logo is served as a static PNG, and the deployed image optimizer is disabled. An image warning alone does not identify a matching or preprocessing slowdown.
