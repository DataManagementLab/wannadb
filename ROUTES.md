# WannaDBWeb API

The browser uses the Next.js `/api/backend/<path>` proxy. The proxy checks the NextAuth session and forwards a backend Bearer token from server-side storage. It requires the configured frontend origin for write requests. Sign in through NextAuth in the browser. Direct Flask API clients on a private connection use `POST /login` to obtain a token and send `Authorization: Bearer <token>`. Use JSON for request bodies unless noted.

Responses are scoped to the current user and organization. Treat `401` as a sign-in or credential failure, `403` as denied access, and `404` as a missing or unavailable resource. `409` means the request conflicts with current state. Reload before repeating an edit with a new version. `429` means the queue or a rate limit is full. Use `Retry-After` when present. `503` indicates a temporary dependency or publication failure. Keep the `X-Request-ID` from errors for log correlation.

## Field and error conventions

Use the returned positive numeric IDs for organizations, bases, documents and `suggestionId`. Attribute IDs, task/session IDs and command IDs are UUID strings. `expectedVersion` for a feedback command is a positive JSON integer from `session.version`; the same field name on an attribute-schema edit is the UUID `attributeVersion` from the overview. Public-review revision strings are opaque 64-character lowercase hexadecimal values returned with the displayed item. Send them back unchanged.

JSON booleans and span offsets must be booleans and integers, rather than strings. Span offsets count Unicode code points, not UTF-16 code units, and use an exclusive end. A request body uses `organisationId`, while some returned base payloads use `organization_id`. Task submissions use `task_id`, except the file mutation routes which return `taskId`.

Errors normally contain `error`; some also provide a stable `code`, for example `USERNAME_TAKEN` or `CONFLICT`. Do not assume every failure has a code. Status failures can instead carry the message in `meta.error` or `command.error`. The frontend preserves HTTP status, codes and messages, and stops before polling if submission fails. A timeout leaves the server outcome unknown; inspect the existing task/command or base before issuing a new mutation.

## Health and accounts

| Method and path               | Request and response                                                                                                                                                                            |
| ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /health/live` or `GET /` | Process status. Does not require authentication.                                                                                                                                                |
| `GET /health/ready`           | PostgreSQL migration, Redis connectivity and consumer leases for both required queues. Returns `200` when ready and `503` otherwise, with top-level `status` and per-queue metrics in `queues`. |
| `POST /register`              | `username` and `password`. Returns `201`, `409` with `USERNAME_TAKEN` for a duplicate, or `429` when throttled.                                                                                 |
| `POST /login`                 | `username` and `password`. Returns `200` with a private `token`, `401` for invalid credentials, or `429` when throttled.                                                                        |
| `DELETE /deleteUser`          | Current `username` and `password`. Returns `204`.                                                                                                                                               |

Readiness reports `queues.celery` and `queues.feedback`, each containing `consumers`, `queued`, `oldest_wait_seconds` and `status`. Queue status is `ready`, `missing_consumer` or `delayed`. A missing consumer makes readiness unavailable after its lease expires, by default 45 seconds. A delayed broker backlog emits a warning while keeping readiness `200` if dependencies and both consumers are available. `queued` excludes reserved and running tasks. An unknown enqueue timestamp produces `oldest_wait_seconds: null` and a warning. Queue metrics contain counts and ages. See [service recovery and queue health](DEPLOYMENT.md#service-recovery-and-queue-health) for settings and operator checks.

Backend credentials expire one hour after sign-in, and frontend cookie renewal does not extend that deadline. Sign in again after expiry. Registration accepts a username of at most 128 characters and a password of 1–72 UTF-8 bytes with no null character. Authentication bodies are limited to 16 KiB at Flask; the frontend registration proxy enforces this before forwarding.

Sign-in and registration admission uses a client budget, a separate service-wide budget and, for sign-in, the existing username budget. The API returns `429` with `Retry-After` when an applicable budget is exhausted and `503` if admission is unavailable. See [authentication request limits](DEPLOYMENT.md#authentication-request-limits) for configuration.

The frontend supplies `X-WannaDB-Auth-Client`, `X-WannaDB-Auth-Timestamp` and `X-WannaDB-Auth-Signature` on its private authentication requests. The signature uses the shared `AUTH_PROXY_SECRET`, covers the method and route, and expires after 60 seconds with at most five seconds of future clock tolerance. Clients should use the frontend's normal authentication flow. Direct API clients can omit this context and receive peer-based admission. Supplied context that fails verification returns `503`. Unsigned forwarded headers do not affect the backend's admission identity.

## Organizations

| Method and path                                      | Request and response                                                                                                          |
| ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `GET /getOrganisationNames`                          | `organisations` for the authenticated user.                                                                                   |
| `GET /getOrganisationName/<orgId>`                   | `organisation_name` for a member.                                                                                             |
| `GET /getOrganisationMembers/<orgId>`                | `members`, `isOwner`, `canManageOwnership`, and `canInvite`.                                                                  |
| `POST /createOrganisation`                           | `organisationName`, returns `organisation_id`.                                                                                |
| `GET /get/user/suggestion?organisationId=…&prefix=…` | Suggested `usernames` for authorized management.                                                                              |
| `POST /addUserToOrganisation`                        | `organisationId` and `newUser`.                                                                                               |
| `DELETE /removeUserFromOrganisation`                 | `organisationId` and `userToRemove`. Owner only; removes another non-owner member.                                            |
| `DELETE /leaveOrganisation`                          | `organisationId`. Leaving is blocked for the last owner/administrator; transfer ownership first to preserve owner operations. |
| `POST /transferOrganisationOwnership`                | `organisationId` and `newOwner`.                                                                                              |
| `DELETE /deleteOrganisation`                         | Owner only. `organisationId` and `confirmDelete: true`. Deletes the organization and its data.                                |

Roles are owner (`0`), administrator (`1`) and member (`10`). Members can read and contribute to bases, participate in interactive feedback, and vote or suggest corrections. Owners and administrators can invite members and delete bases. Only owners can remove other users, delete the organization or accept/reject public corrections. Ownership transfer selects another existing member and leaves the previous owner as an administrator. An administrator can recover ownership through transfer only when the organization has no owner; this does not grant owner-only deletion or review access.

Leaving an organization or deleting an account is blocked if it would remove that organization's last owner/administrator. Transfer ownership before leaving to preserve owner operations. Removing an account retains shared documents and bases, with nullable historical attribution. These rules are enforced by the backend, including after a page was opened.

## Files and document bases

Convenience names in the URL or body are case-sensitive. Prefer stable numeric IDs for routes. Existing scoped operations also take `baseName`. Where supported, include `baseId` so the server can reject a stale name-to-ID mapping.

| Method and path                                                         | Request and response                                                                                                                                                                                                                                                                                                                                                                                         |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `POST /data/upload/file`                                                | Multipart `organisationId` and one or more parts named `file` containing UTF-8 text. For a new base, omit `baseName` and `baseId`. The response is an array of document IDs and per-file errors, with `201` for success, `207` for mixed results, or `400` for all failures. For an existing base include its name and ID, then poll the `taskId` returned with `202`. Check `errors` for any files skipped. |
| `GET /data/organization/get/files/<orgId>`                              | Files available to an organization member.                                                                                                                                                                                                                                                                                                                                                                   |
| `GET /data/organization/get/documentbase/<orgId>`                       | Document bases available to an organization member.                                                                                                                                                                                                                                                                                                                                                          |
| `POST /core/document_base`                                              | `organisationId`, `baseName`, `document_ids` as a list of distinct IDs from the upload, and `attributes` as a list of names. Returns `202` with `task_id`. On success, status includes the new `base_id`.                                                                                                                                                                                                    |
| `GET /core/document_base/by-id/<orgId>/<baseId>`                        | Base reference with `id`, `name` and `attributeIds`.                                                                                                                                                                                                                                                                                                                                                         |
| `GET /core/document_base/resolve/<orgId>?name=…`                        | Same reference, resolved by exact name.                                                                                                                                                                                                                                                                                                                                                                      |
| `DELETE /core/document_base/by-id/<orgId>/<baseId>`                     | Deletes the scoped base, subject to role checks.                                                                                                                                                                                                                                                                                                                                                             |
| `POST /core/document_base/load`                                         | `organisationId`, `baseName` and optional `baseId`. Returns `task_id` to read a catalog or document through status.                                                                                                                                                                                                                                                                                          |
| `PUT /data/update/file/content`                                         | `organisationId`, `baseName`, `baseId`, `documentId`, `newContent` and `expectedContent` to guard against concurrent edits. Returns `202` with `taskId`.                                                                                                                                                                                                                                                     |
| `DELETE /data/file/delete`                                              | `organisationId`, `baseName`, `baseId` and `documentId` for a document in a base. Returns `202` with `taskId`.                                                                                                                                                                                                                                                                                               |
| `GET /core/document_base/feedback/overview?organisationId=…&baseName=…` | Attribute progress, IDs and current `attributeVersion`. No task is started.                                                                                                                                                                                                                                                                                                                                  |
| `POST /core/document_base/attributes/update`                            | `organisationId`, `baseName`, `baseId`, `expectedVersion` and `operations`. Operations are `{"op":"add","name":"City"}`, `{"op":"rename","id":"…","name":"Place"}`, or `{"op":"remove","id":"…"}`. Returns `202` with `task_id`.                                                                                                                                                                             |

New-base uploads return one array item per submitted file: successful numeric IDs and error strings for failed files, for example `[101, "bad.bin: wrong type application/octet-stream"]` with `207`. Keep the successful IDs and show the errors. Creation checks the selected documents and total corpus budget before committing the new base. For an existing base, valid files are queued together and skipped-file errors are returned alongside `taskId`; a `202` is not a completed mutation.

## Tasks and SQL query results

A response of `202` acknowledges a submission. Poll `GET /core/status/<task_id>?summary=1&feedback=0` with backoff. This is a scoped read. Task status includes `state`, `meta`, a publication in `session`, and `command` when applicable. `QUEUED` means work has been admitted, `STARTED` means processing or an active interactive session, and `SUCCESS` means the task completed. Terminal faults can return HTTP `500` with states such as `FAILURE`, `EXPIRED`, or `REVOKED`, plus `meta.error` when available. A browser timeout only ends the wait.

| Status view                  | Content                                                                      |
| ---------------------------- | ---------------------------------------------------------------------------- |
| `view=catalog`               | Attribute counts and document IDs/names without text.                        |
| `view=document&documentId=…` | One document. `documentName` is available for legacy references.             |
| `view=review&offset=…`       | Current ranked candidates and a page of up to eight manual-review documents. |
| `view=table&offset=…`        | Up to 50 rows and metadata including `columns`, `totalRows` and `truncated`. |
| `view=table-export`          | All retained rows from the same query.                                       |

Post `organisationId`, `baseName`, `baseId`, and `sqlQuery` to `/core/document_base/query`. For example, `select City where City is not null` is a read-only query against the documents table. The backend bounds result size. `truncated` indicates that only the retained rows can be downloaded. Query results expire after an hour, so rerun an expired query.

## Interactive feedback

1. Post `organisationId`, `baseName` and `baseId` to `/core/document_base/interactive`. Use the returned `task_id` as `sessionId`. Read it with `feedbackSession=1`, `organisationId` and `baseName` on the status URL. The parent publication moves from `loading` to `selection`.
2. In `selection`, post `attribute` and `doAttribute` to `/core/document_base/do_current_attribute` along with the command fields below and the base scope. Use `doAttribute: true` to start ranking, or `false` to skip the waiting attribute. `reset: true` with `doAttribute: true` repopulates it. The session moves through `processing`, then publishes a new version in `ranking`, `selection`, or `finished`.
3. In `ranking`, use a match, custom span, batch submission, or no-match decision. Poll the command's returned task ID. A command is confirmed when `command.state` is `published`, `command.command_id` matches the submitted ID, and the session version reaches `command.published_version`. The Celery state alone is insufficient. A conflict may be published for review without accepting the proposed change. The UI can keep the saved decision or explicitly replace it.
4. Use `/core/document_base/feedback/stop` to stop the current attribute and advance to the next. Use `/core/document_base/feedback/close` to close the whole session from selection, ranking or an unresolved conflict. A successful close preserves the current saved matches and releases that session's active capacity. `finished` represents a closed publication. A failed or expired session can be reopened from the base with its saved matches.

Every command below is a JSON POST under `/core/document_base` and carries `sessionId` (UUID), `expectedVersion` (the last published version), and a fresh `commandId` (UUID) for each new decision. Single-document and batch match requests include `organisationId` and `baseName` as scope.

| Path suffix                                         | Additional fields                                                                                                                                                          |
| --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/do_current_attribute`                             | `organisationId`, `baseName`, `attribute`, `doAttribute` and optional `reset`.                                                                                             |
| `/confirm/nugget/match` or `/confirm/nugget/custom` | `documentName`, `documentContent`, `nuggetText`, `startIndex` and `endIndex`. Optional negative span fields are `noMatchText`, `noMatchStartIndex`, and `noMatchEndIndex`. |
| `/confirm/nugget/multiple`                          | `nuggets` list, one per document, each with `documentName`, `documentContent`, `text`, `startIndex` and `endIndex`.                                                        |
| `/confirm/nugget/none`                              | `documentName`, `documentContent` and the span fields. For a whole-document no match, use empty `nuggetText` and both offsets zero.                                        |
| `/reload`                                           | Optional `conflictResolution`, either `keep` or `replace` when resolving a conflict.                                                                                       |
| `/feedback/stop`                                    | Command fields alone. Stops the current attribute and advances. Resolve any pending decision conflict first.                                                               |
| `/feedback/close`                                   | Command fields alone. Closes the whole session, including an unresolved conflict, and discards its uncommitted proposal.                                                   |

Offsets count Unicode code points and use an exclusive end. Text fields must match the selected span of the current stored document exactly.

Whole-session close is a lightweight command on the dedicated feedback queue. It validates the submitting user's membership and the displayed session version, then atomically clears the checkpoint, records the durable command receipt and marks that session finished. It can close a checkpoint whose source or attribute schema changed. It preserves the current canonical document base and other reviewers' sessions. A failed Redis publication after the commit can recover the receipt through normal status polling. Closing requires an available task queue to submit the command.

If a reply is lost, poll by the original command ID before retrying. For an exact replay, reuse the same command ID, expected version, and payload. Changed data or a new decision requires a new command ID after checking the live version. If a saved receipt is recovered from PostgreSQL, `command.recovered` is true and the result confirms the saved decision. Reopen the base to continue because the live publication is unavailable. If there is no saved outcome and the session is gone, reopen the base and inspect current state before sending another decision.

## Member document feedback

The historical path name `public` refers to votes shared with the organization. These routes require membership, and accepting or rejecting corrections requires the organization owner.

- For counts, POST `organisationId`, `baseId`, `documentId`, the displayed `documentContent`, `attributeIds` (name to stable UUID), and `expectedMappings` (name to code-point span pairs, `[]` for explicit No Match, or `null` for a missing mapping) to `/core/document_base/feedback/public/get`. The server validates that the displayed value matches the canonical document before returning counts. Every attribute summary includes `positive`, `negative`, `mine`, `mappingRevision` and `sourceRevision`. A changed source, attribute or mapping returns `409`.
- To list suggestions, POST the scope and `suggestionsOffset` (start at 0) to the same get route. Omit `documentId` for the whole base. The response contains `suggestions`, `nextOffset` and owner-only action flag `canReview`. Each item includes document ID/name, attribute name/ID, immutable `suggestionId`, `suggestionVersion`, `mappingRevision`, `sourceRevision`, exact `startIndex`/`endIndex`, `replacement`, `context` (`before`, `selected`, `after`) and `count`. Repeated text at different spans is listed separately. A null replacement and null span represent No Match.
- Owners POST `organisationId`, `baseId`, `documentId`, `attributeId`, `suggestionId`, `suggestionVersion`, `mappingRevision`, `sourceRevision`, `startIndex`, `endIndex` and boolean `accepted` to `/core/document_base/feedback/public/review`. The response gives a task ID. The worker validates the displayed identity again before committing. Accept applies that exact occurrence or No Match and clears negative corrections agreeing with that accepted span. Reject dismisses the displayed suggestion group. Different correction proposals remain available, while votes for a previous canonical value are excluded from the new value's counts.
- POST votes to `/core/document_base/feedback/public` with scope, `attributeId`, displayed `documentContent`, `mappingRevision`, `isPositive`, and either the selected correction span or null `startIndex`, `endIndex` and `nuggetText`. Repeating a current plain vote clears it. Selecting the opposite vote switches it. A stale mapping returns `409` and requires the user to reload the displayed document before making a new decision.
- Send `noMatch: true` with `isPositive: false` and null span fields to propose No Match. Corrections replace the user's previous feedback for that document and attribute and remain saved when resubmitted.

Acceptance deletes the agreeing correction feedback rows; it does not convert them into positive votes. Their negative counts therefore disappear. Rejection marks the pending suggestion rows reviewed, retaining their votes while the canonical mapping remains unchanged. Other negative proposals remain stored; votes bound to an older mapping do not count against a changed value.

The owner-review item version covers the displayed group members and their revisions. Replacing, adding or removing an agreeing suggestion can invalidate an open dialog. A conflict found after queueing is returned by task polling as HTTP `409` with `code: CONFLICT`. Refresh suggestions to make a new decision.

`POST /core/status/<task_id>` is retired and returns `410` to authenticated callers. The former `POST /core/document_base/order/nugget` endpoint has been removed. The browser proxy rejects it with `404`, and Flask rejects direct POST requests with `405`. Use `view=review` on task status for ranked feedback candidates, or `view=document` to inspect a document’s nuggets. The former development route inventory and debug endpoints are unavailable.

## SQL review modes

SQL queries accept boolean `includeAutomaticMatches` (default true). Automatic preview retains predicted values. Confirmed-only mode excludes provisional mappings before SQL filtering, grouping and aggregation. Both modes use the same source documents and retain confirmed explicit No Match as an empty value.

Each stored result, page and export includes `includesAutomaticMatches`. Older cached results may omit it or return null; their mode is unknown. The frontend labels the saved result's mode independently of the next query's checkbox, and CSV filenames identify automatic-preview or confirmed-only mode. CSV columns and rows follow the SQL result, including arbitrary projections and aggregates.

Catalog and feedback overview share confirmed/provisional/missing document counts. Explicit confirmed No Match counts as reviewed, while provisional mappings do not count toward completion.

## Limits and expiry

These are source defaults, not a statement of a running deployment's overrides. The settings in the first table are positive integer environment variables from `wannadb_web/limits.py`. Configure them consistently in the API and both workers.

| Setting                      | Default      | Consequence                                                                                                                   |
| ---------------------------- | ------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| `MAX_REQUEST_BYTES`          | 16 MiB       | Whole HTTP body, including multipart overhead. Align the frontend variable of the same name and any reverse-proxy body limit. |
| `MAX_FILE_BYTES`             | 512 KiB      | UTF-8 bytes per source document, also checked on content edits.                                                               |
| `MAX_UPLOAD_FILES`           | 32           | Files per upload.                                                                                                             |
| `MAX_BASE_DOCUMENTS`         | 256          | Documents per base, including additions. Also bounds a batch feedback submission.                                             |
| `MAX_BASE_BYTES`             | 16 MiB       | Combined source text per base.                                                                                                |
| `MAX_DOCUMENT_TOKENS`        | 50,000       | Admission estimate per document.                                                                                              |
| `MAX_BASE_TOKENS`            | 250,000      | Admission estimate across the base.                                                                                           |
| `MAX_ATTRIBUTES`             | 64           | Attributes per base.                                                                                                          |
| `MAX_COMPUTE_TASKS`          | 32           | Shared waiting/running task capacity across both queues.                                                                      |
| `MAX_COMPUTE_TASKS_PER_USER` | 8            | Each user's share of that capacity. Waiting for feedback input uses no compute slot.                                          |
| `QUEUE_SECONDS`              | 900 seconds  | Maximum admitted queue wait. Expired work is not started.                                                                     |
| `COMPUTE_SECONDS`            | 1800 seconds | Worker soft processing deadline per task/feedback step; hard deadline is 30 seconds later.                                    |

Token counts are inexpensive admission estimates, not the model tokenizer's exact counts. A budget violation returns `413` before queueing where possible, or a terminal worker failure if detected during processing. Queue admission exhaustion returns `429`; wait for capacity before retrying. A timed-out browser does not cancel queued or running work.

The following limits are fixed in the current implementation, not environment overrides:

| Area                      | Budget and behavior                                                                                                                                                                                                                                                                                                    |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Durable feedback sessions | Eight active sessions per user and 64 overall. A checkpoint expires one hour after its last saved step; an in-flight command extends its lease. Reading status does not extend idle lifetime. Finish/close sessions to release capacity, or wait for expiry. A finished checkpoint is retained briefly (five minutes). |
| Redis publications        | Session data expires after 24 hours without a refresh; individual command records and stored SQL results expire after one hour. A Redis key outliving a checkpoint does not make that checkpoint usable.                                                                                                               |
| SQL                       | 8 KiB UTF-8 query, one statement without parameters, two-second or 500,000-VM-step execution budget. Up to 1,000 rows within a 2 MiB serialized-result budget are retained. Pages contain at most 50 rows.                                                                                                             |
| Custom propagation        | At most four added propagated candidates per document for the attribute, 128 per attribute across the base, and 32 new candidates per job. Hitting a cap preserves the explicit selection and sets `command.propagation_limited`; some additional occurrences may remain unpropagated.                                 |
| Suggestion list           | 20 suggestion groups per page; use `nextOffset` until null.                                                                                                                                                                                                                                                            |

A missing or expired publication requires reopening the base from saved matches. Concurrent reviewers can keep separate sessions: saved non-conflicting decisions are merged; conflicting canonical decisions require keep/replace review. Source-document or attribute-schema changes can require a fresh session. Closing one session preserves committed matches and other reviewers' sessions.

### SQL surface and CSV scope

The SQL engine exposes only the in-memory `documents` table, with a `Document` name column and text-valued attribute columns. Multiple matches join as comma-separated text. Missing mappings and No Match appear as SQL `NULL`. Case-insensitive column-name collisions receive numbered suffixes; use the returned headers. Quote identifiers containing spaces with double quotes, doubling an embedded quote. Use `CAST` when numeric aggregation needs numeric interpretation.

Simple `SELECT` queries may omit `FROM documents`. Include it explicitly for compound queries or more complex source expressions. Filtering, grouping, aggregates and supported window functions operate on the selected review mode. Writes, schema access, extension loading and unsupported functions are rejected. Supported examples include `COUNT`, `SUM`, `AVG`, `MIN`, `MAX`, `COALESCE`, `LOWER`, `UPPER`, `LENGTH`, `SUBSTR`, `ROUND`, `DATE` and `ROW_NUMBER`; the complete allowlist is `_FUNCTIONS` in [the SQL runner](wannadb_web/SQLite/table_query.py).

```sql
select City where City is not null;
select City, count(*) as "Documents" from documents group by City;
select avg(cast("Flight Hours" as real)) as "Average hours" from documents;
```

Columns/rows follow the SQL projection or aggregate, with result cells represented as text or null. CSV exports all retained rows from the saved query, across table pages, in that saved query's review mode. Changing the checkbox without running a new query does not change the export. `truncated: true` means the result budget was reached; an export cannot recover omitted rows. Narrow or aggregate the query to fit, and rerun it after cache expiry.

## Feedback request examples

These examples show wire shapes for a private API client using a valid `Authorization: Bearer <token>` and `Content-Type: application/json`. The browser sends the same bodies through `/api/backend`. Replace all fixture IDs, text and versions with the values just displayed. Generate a new command UUID for each new decision; never reuse one with changed parameters.

Start with `POST /core/document_base/interactive`:

```json
{ "organisationId": 21, "baseId": 67, "baseName": "Example" }
```

A `202` reply supplies the parent session ID:

```json
{ "task_id": "10000000-0000-4000-8000-000000000001" }
```

Poll `GET /core/status/10000000-0000-4000-8000-000000000001?feedbackSession=1&organisationId=21&baseName=Example&summary=1&feedback=0`. After `selection` publishes version 1 with attribute `City`, start it with `POST /core/document_base/do_current_attribute`:

```json
{
  "organisationId": 21,
  "baseName": "Example",
  "sessionId": "10000000-0000-4000-8000-000000000001",
  "expectedVersion": 1,
  "commandId": "20000000-0000-4000-8000-000000000001",
  "attribute": "City",
  "doAttribute": true,
  "reset": false
}
```

The reply's `task_id` is this command ID. Poll that command and use its latest published version. If it publishes version 2 in `ranking`, a custom decision for document text `Paris and Paris` selecting the second occurrence uses `POST /core/document_base/confirm/nugget/custom`:

```json
{
  "organisationId": 21,
  "baseName": "Example",
  "sessionId": "10000000-0000-4000-8000-000000000001",
  "expectedVersion": 2,
  "commandId": "20000000-0000-4000-8000-000000000002",
  "documentName": "Example.txt",
  "documentContent": "Paris and Paris",
  "nuggetText": "Paris",
  "startIndex": 10,
  "endIndex": 15
}
```

After checking the latest publication, `POST /core/document_base/feedback/stop` or `/core/document_base/feedback/close` requires this body (version 3 here is illustrative):

```json
{
  "sessionId": "10000000-0000-4000-8000-000000000001",
  "expectedVersion": 3,
  "commandId": "20000000-0000-4000-8000-000000000003"
}
```

A successful close command status includes the following fields; other `meta`/command fields may also be present:

```json
{
  "state": "SUCCESS",
  "session": {
    "session_id": "10000000-0000-4000-8000-000000000001",
    "version": 4,
    "phase": "finished",
    "attribute": null,
    "closed": true
  },
  "command": {
    "command_id": "20000000-0000-4000-8000-000000000003",
    "state": "published",
    "expected_version": 3,
    "published_version": 4
  }
}
```

For owner review, list current suggestions with `POST /core/document_base/feedback/public/get` and `{"organisationId":21,"baseId":67,"suggestionsOffset":0}`. Copy `documentId`, `attributeId`, `suggestionId`, `suggestionVersion`, `mappingRevision`, `sourceRevision`, `startIndex` and `endIndex` from the selected item into a JSON body with the same `organisationId`/`baseId` and `accepted: true` (or `false` to reject). POST it to `/core/document_base/feedback/public/review`, then poll its returned `task_id`. For a No Match item both offsets are null. Do not invent revisions or reduce the identity to replacement text. A `409` before submission or during polling requires refreshing suggestions and reviewing the new item before sending a new request.
