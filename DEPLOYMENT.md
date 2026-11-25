# Web backend deployment

The backend, compute worker, database, and Redis run on the same Linux Docker host as the frontend. Use Docker Engine 28 or later and the Compose plugin. The first build downloads Python dependencies and NLP models.

Read [CONTRIBUTING.md](CONTRIBUTING.md) for development checks and documentation conventions.

## Fresh production installation

From the backend checkout, create the production environment file once.

```sh
mkdir -p wannadb_web/.env
(umask 077; cp -i deployment/production.env.example wannadb_web/.env/.prod)
chmod 600 wannadb_web/.env/.prod
```

Fill in `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD`, `CACHE_PASSWORD`, `WANNA_DB_JWT_SECRET` and `AUTH_PROXY_SECRET`. Use a separate secret for each password or key. Generate random hexadecimal values with `openssl rand -hex 32`. Compose requires a Redis password of at least 32 hexadecimal characters. The backend signing secret must be at least 32 UTF-8 bytes. On upgrades keep the database name, its owning role and password, and the existing backend signing secret. Copy the same `AUTH_PROXY_SECRET` into the frontend's environment file so it can authenticate client context for sign-in and registration. Set `FLOWER_BASIC_AUTH` to `username:password` only to enable Flower.

In your deployment shell, define this helper and start the stack from the backend checkout. Use the same Compose file, environment file, project name, and volumes throughout operations.

```sh
compose() { docker compose --env-file wannadb_web/.env/.prod -f docker-compose-prod.yaml "$@"; }
compose up -d --build
compose ps -a
compose logs --tail=100 migrate
curl -fsS http://127.0.0.1:8000/health/ready
```

A successful migration container exits with code 0. The web service and both workers wait for that result. `/health/live` checks the web process. `/health/ready` checks PostgreSQL's applied migration versions, Redis connectivity and a live consumer for each of the `celery` and `feedback` queues. Readiness may return `503` during startup until both workers publish their first heartbeat, normally within ten seconds after their consumers start.

Start the [frontend](https://github.com/DataManagementLab/wannadbDemo) on the same host. For SSH use the forwarded frontend at `http://localhost:3000`. For public access terminate TLS at a reverse proxy that targets loopback port 3000 and set the frontend's `NEXTAUTH_URL` to the public HTTPS origin. The production backend listens on host loopback port 8000. PostgreSQL and Redis stay inside the Compose network. Flower is optional through the `monitoring` profile and requires authentication on loopback port 5555. Expose only the HTTPS reverse proxy publicly.

Deploy the backend and frontend as a compatible pair from the same web release. This checkout requires migrations 0001–0009, versioned feedback commands and mapping-bound public review requests. The current frontend uses Next.js 15.5.29, Node 26.13.1 in Docker and bundled Yarn 4.0.1; PostgreSQL uses version 16. Use the dependency pins and images in each checkout when rebuilding. An older frontend without these request fields is not compatible with the current backend. For upgrades, stop writers, migrate and start the API and both workers before deploying the matching frontend.

## Local backend development

The development Compose file uses Flask debug and development database credentials. Run it on a trusted machine because it publishes backend port 8000 on all interfaces. Create `wannadb_web/.env/.dev` locally with mode 600 and the settings below. Replace the signing-secret placeholder with a fresh random value and keep this file out of version control.

```dotenv
DATABASE_HOST=postgres
DATABASE_PORT=5432
DATABASE_NAME=userManagement
DATABASE_USER=postgres
DATABASE_PASSWORD=0
CACHE_HOST=redis
CACHE_PORT=6379
CACHE_DB=0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0
WANNA_DB_JWT_SECRET=replace-with-a-unique-secret
AUTH_PROXY_SECRET=replace-with-the-same-secret-as-the-frontend
```

Run `docker compose up -d --build` from the backend checkout. The development file mounts the checkout. Rebuild if dependencies change. If the mounted checkout needs additional desktop or experimental models, see `scripts/prepare_models.py` and `scripts/prepare_glove.py`. Use the production file for deployments where you rely on the model assets baked into the image.

Upload/corpus, task, session, SQL and propagation budgets are described under [Limits and expiry](ROUTES.md#limits-and-expiry). Upload request size must fit the frontend proxy, reverse proxy and API limits, including multipart overhead. Change environment settings consistently in the API and workers and recreate the affected services; changing a local environment file alone does not update a running container.

## Worker CPU and concurrency settings

Both Compose files default to two compute processes with four Torch intra-op threads each. The dedicated feedback worker runs one process with two intra-op threads. Inter-op threads are fixed at one in each process. The OpenMP, MKL and OpenBLAS thread budgets follow that worker's intra-op count, and tokenizer parallelism is disabled to avoid additional tokenizer pools. Compute prefetch is reduced to one per process; task acknowledgement and admission policies stay unchanged. With early acknowledgements this can still reserve an extra waiting task per process; it is not a limit of two total queued/running tasks.

In the default pool, a lone compute job still uses four threads; it does not automatically borrow the idle child's thread budget. These defaults target the measured eight-vCPU server. On the same four-document subsample, two parallel four-thread jobs finished in a median 70.4 seconds, versus 84.8 seconds for two sequential eight-thread jobs (three warm pairs per setup). The first result arrived after 68.8 seconds in parallel versus 42.7 seconds sequentially. Sampled combined warm PSS was 6.43 GiB versus 4.57 GiB; PSS apportions shared pages. These measurements exclude Celery scheduling and persistence. The feedback two-thread cap is a contention policy, not a separately measured feedback optimum. Simultaneous feedback and compute work still share CPU and memory; threads are budgets rather than reserved cores. Larger bases and all three active processes were not benchmarked together.

| Compose setting | Default | Purpose |
| --- | --- | --- |
| `WANNADB_COMPUTE_CONCURRENCY` | `2` | Number of compute prefork processes. |
| `WANNADB_COMPUTE_THREADS` | `4` | Torch/OpenMP/MKL/OpenBLAS threads per compute process. |
| `WANNADB_FEEDBACK_THREADS` | `2` | Torch/OpenMP/MKL/OpenBLAS threads in the single feedback process. |

Set these positive integers in the shell or Compose interpolation environment (`.env` or the file supplied with `--env-file`). A service's `env_file` alone does not supply Compose interpolation. The Compose files translate them into the worker-local `WANNADB_TORCH_THREADS` setting; `WANNADB_TORCH_INTEROP_THREADS` is one. Workers apply Torch settings once per process, before model-resource imports, and reuse their models across jobs. The first model-using task logs `Worker CPU runtime configured` with the actual thread counts. The API and Celery parent register tasks without importing Torch.

To prioritize one job's latency, set compute concurrency to one and compute threads to eight when recreating the workers. This trades the measured parallel throughput benefit for a faster first result. For development:

```sh
WANNADB_COMPUTE_CONCURRENCY=1 WANNADB_COMPUTE_THREADS=8 docker compose up -d --no-deps --force-recreate worker feedback-worker
```

To apply the default throughput settings, finish running jobs and feedback steps, then run from the backend checkout:

```sh
docker compose up -d --no-deps --force-recreate worker feedback-worker
```

For production use the usual `compose` helper/environment and `compose up -d --build --no-deps --force-recreate worker feedback-worker` so the changed web worker code is baked into the image. Persistent overrides must be present on subsequent recreations too. No migration or frontend update is required. Check the compute banner reports concurrency two and that the first model-using tasks log four threads on compute and two on feedback. Verify readiness and one small creation job and feedback step after rollout; those live checks belong to the operator. The code/configuration checks are local and do not establish production throughput under concurrent feedback load.

## Authentication request limits

The frontend authenticates client addresses for login and registration with a dedicated `AUTH_PROXY_SECRET`. Generate it once with `openssl rand -hex 32`, place the same value in the backend environment file and the frontend `.env`, and recreate the API and frontend services so they load it. Keep it separate from the backend JWT secret and `NEXTAUTH_SECRET`. Retain it on normal deployments. The API and frontend require at least 32 UTF-8 bytes for this shared secret when signing or verifying context.

The backend verifies a short-lived HMAC signature bound to the client address, method and authentication route. Invalid or incomplete signed context returns `503`. Direct API clients that send no signed context use the connection peer. Ordinary forwarded-address headers never determine client identity at the backend.

| Setting                         | Default                                         |
| ------------------------------- | ----------------------------------------------- |
| `AUTH_RATE_WINDOW_SECONDS`      | 60 seconds                                      |
| `AUTH_REGISTRATIONS_PER_CLIENT` | 15 registrations per window                     |
| `AUTH_LOGINS_PER_CLIENT`        | 120 sign-in attempts per window                 |
| `AUTH_LOGINS_PER_USERNAME`      | 10 sign-in attempts per username per window     |
| `AUTH_REGISTRATIONS_GLOBAL`     | 150 registrations per window across clients     |
| `AUTH_LOGINS_GLOBAL`            | 1200 sign-in attempts per window across clients |

Set positive integers in the backend environment file to override these defaults. Redis checks the applicable client, username and service budgets atomically. A request denied by one budget consumes none of the others. Malformed credentials also consume client and service admission. A limit returns `429` with `Retry-After`; a Redis outage returns `503`.

Client identity normally comes from the frontend's socket peer. If a reverse proxy fronts Next.js, configure the frontend's `AUTH_TRUSTED_PROXY_CIDRS` only for exclusive, controlled ingress peers that append or overwrite the actual client address correctly. See the [frontend README](https://github.com/DataManagementLab/wannadbDemo#readme). Users behind the same NAT or SSH tunnel can share a client bucket. The username limit is intentionally shared across client addresses, and the service limit can throttle all clients during overload.

For an upgrade, install these backend files and configure both environment files, then recreate the API with its usual Compose file. With development, run `docker compose up -d --force-recreate --no-deps wannadb` from the backend checkout. For production, use the production environment/file options with `up -d --build --no-deps wannadb`. Update and rebuild the frontend after the API loads the shared secret.

## Service recovery and queue health

Enable Docker Engine to start when the Linux host boots. Both Compose files give long-running services a restart policy. The API keeps its existing `always` policy, and the other services use `unless-stopped`. The separate frontend Compose service also uses `unless-stopped`. Docker restarts exited containers and resumes eligible containers after a Docker or host restart. An intentionally stopped `unless-stopped` service requires `compose up -d` to resume. The migration job remains a one-shot service.

Recreate containers with `compose up -d --build` to load backend code and policy changes. From the frontend checkout, use `docker compose up -d frontend` for a Compose-only policy change. A process that remains running but becomes unhealthy needs operator attention. Docker restart policies respond to container exits. See [Docker restart policies](https://docs.docker.com/engine/containers/start-containers-automatically/).

Workers refresh queue-consumer leases from their parent event loop, including while a prefork child processes a task. The API checks those leases without loading models or inspecting task contents. Configure these settings consistently in the API and both workers.

| Setting                             | Default | Meaning                                                                                 |
| ----------------------------------- | ------- | --------------------------------------------------------------------------------------- |
| `WORKER_HEARTBEAT_INTERVAL_SECONDS` | 10      | Seconds between consumer lease refreshes.                                               |
| `WORKER_HEARTBEAT_TTL_SECONDS`      | 45      | Seconds before an unrefreshed consumer lease expires. Must exceed the refresh interval. |
| `QUEUE_WAIT_WARNING_SECONDS`        | 60      | Broker waiting age that marks a queue `delayed` and emits a warning.                    |

Poll `/health/ready` from the private deployment network and monitor its `queues` fields. A missing consumer returns `503`, subject to the heartbeat lease's expiry window. A healthy consumer with a delayed backlog still returns `200`, with queue status `delayed` and a warning in the API log. Configure monitoring alerts for missing consumers, delayed queues and unknown waiting ages. Queue depth and age cover messages waiting in the broker. Reserved and running tasks have left that count. `oldest_wait_seconds: null` means a waiting message has no usable enqueue timestamp, which also emits a warning.

### Rehearse recovery in staging

Finish active jobs and feedback sessions, confirm a current PostgreSQL backup, and use the staging deployment's usual `compose` helper and environment. First confirm both queues are ready and complete a small creation job and feedback step.

Ask the worker's main process to terminate through Celery's SIGTERM handler to exercise automatic recovery. The exec command can fail when the container exits. Repeat with `feedback-worker` after the first recovery succeeds.

```sh
compose exec -T worker python -c 'import os, signal; os.kill(1, signal.SIGTERM)'
compose ps -a
compose logs --since=5m worker feedback-worker
curl -fsS http://127.0.0.1:8000/health/ready
```

Allow time for Docker restart, broker reconnection and fresh heartbeats. Verify each queue has a consumer, then complete a fresh creation job and feedback step. In the same staging environment, restart Docker with the host's service manager and repeat those checks. Reboot the staging host, reconnect and repeat them again, including access through the frontend. Record the restart results and any queue warnings. These recovery checks are deployment rehearsals performed by the operator.

## Upgrade and back up

Schedule downtime. Finish active jobs and close feedback sessions before stopping writers. The commands below assume the production `compose` helper above. For development define it as `compose() { docker compose "$@"; }`.

```sh
compose stop wannadb worker feedback-worker
database=userManagement  # Set this to the current DATABASE_NAME.
backup="wannadb-$(date -u +%Y%m%dT%H%M%SZ).dump"
(umask 077; compose exec -T postgres sh -ec 'exec pg_dump -Fc -U "${POSTGRES_USER:-postgres}" -d "$1"' sh "$database" > "$backup")
compose exec -T postgres pg_restore -l < "$backup" > /dev/null
```

Continue only when both backup commands succeed. Store the dump securely since it contains account and document data. Update the checkout, then rerun the migration job without replacing the database volume.

```sh
compose rm -f migrate
compose up -d --build
compose logs --tail=100 migrate
compose ps -a
curl -fsS http://127.0.0.1:8000/health/ready
```

If migration fails, review its log with the application stopped. Resolve the reported error before restarting. PostgreSQL applies each migration transactionally and tracks versions and checksums in `public.wannadb_schema_migrations`. Reapplying the same migration set is safe. Add new migration files for future schema changes instead of editing applied migrations.

| Version | Change                                                                                                                      |
| ------- | --------------------------------------------------------------------------------------------------------------------------- |
| 0001    | Creates a fresh web schema or adopts the supported unversioned schema while retaining existing rows and IDs.                |
| 0002    | Preserves shared organization data when a contributor deletes their account.                                                |
| 0003    | Adds stable attribute IDs and a versioned attribute schema.                                                                 |
| 0004    | Stores durable receipts for saved feedback commands.                                                                        |
| 0005    | Stores expiring feedback-session checkpoints.                                                                               |
| 0006    | Keeps one vote per user, document, and attribute. Migration removes opposing duplicates.                                    |
| 0007    | Stores explicit no-match suggestions in public feedback.                                                                    |
| 0008    | Adds owner review state for public correction suggestions.                                                                  |
| 0009    | Binds public votes to mapping identities and gives correction review stable attribute, source, span and version identities. |

Public feedback after migration 0009 uses the identity of the displayed mapping. Historical votes without that identity stay unbound and are excluded from current-value counts. Usable source-anchored correction suggestions remain reviewable. Deploy the API and both workers with the migrated schema before updating the frontend. Old frontend requests must refresh through the updated frontend to obtain the required mapping identities.

## Restore

Keep the app and both workers stopped. Restore into a new database in the existing PostgreSQL service. The example expects `$backup` to point to the dump and uses the configured owning role. Choose an unused database name.

```sh
compose exec -T postgres sh -ec 'exec createdb -U "${POSTGRES_USER:-postgres}" wannadb_restore'
compose exec -T postgres sh -ec 'exec pg_restore --exit-on-error --single-transaction -U "${POSTGRES_USER:-postgres}" -d wannadb_restore' < "$backup"
```

Verify account, membership, base, document and feedback rows in the restored database before switching `DATABASE_NAME` to `wannadb_restore` in the backend environment. Keep the current signing secrets. PostgreSQL contains committed document data and feedback receipts; Redis contains temporary publications and queued work. Starting the restored database against the old Redis contents can replay jobs from the old database.

While the API and both workers remain stopped, stop Redis and create an empty cache volume. Run these commands from the backend checkout using the same Compose project as before. `docker volume create` returns a new volume name; the override records it for future deployments.

```sh
compose stop redis
restore_cache="$(docker volume create)"
cat > restore-cache.yaml <<EOF
services:
  redis:
    volumes:
      - restorecache:/data
volumes:
  restorecache:
    external: true
    name: $restore_cache
EOF
```

For production, redefine the helper to keep the new cache attached:

```sh
compose() { docker compose --env-file wannadb_web/.env/.prod -f docker-compose-prod.yaml -f restore-cache.yaml "$@"; }
```

For development, use this helper instead:

```sh
compose() { docker compose -f docker-compose.yaml -f restore-cache.yaml "$@"; }
```

Retain `restore-cache.yaml` and the same Compose project name on every later deployment. Its `/data` mount replaces the old Redis mount in production and adds an explicit cache mount in development. It does not replace the PostgreSQL volume. Recreate the migration job and resume with the intended code and updated database setting:

```sh
compose rm -f migrate
compose up -d --build
compose logs --tail=100 migrate
compose ps -a
curl -fsS http://127.0.0.1:8000/health/ready
```

Proceed only when the migration exits 0 and both queues become ready. Sign in, inspect restored bases and complete a small creation job and feedback step. Rerun SQL queries and open fresh feedback sessions; old cached publications and uncommitted queued work are unavailable. Check the saved result before retrying a decision whose response was lost. Keep the old database and cache volumes until the restore is verified. This is an operator-run deployment rehearsal; a source check alone does not establish a successful restore on the target host.

## Operate and troubleshoot

See [Web backend structure](WEBSERVER_STRUCTURE.md) for queues, timings, and where to diagnose image warnings. See [Web API](ROUTES.md) for authentication, status polling, and feedback recovery. When rotating a database password on an existing volume, update the actual PostgreSQL role password and the Compose environment together. Updating Compose alone changes client settings and fresh database initialization.
