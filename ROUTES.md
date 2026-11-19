# WannaDBWeb API

The browser uses the Next.js `/api/backend/<path>` proxy. The proxy checks the NextAuth session and forwards a backend Bearer token from server-side storage. It requires the configured frontend origin for write requests. Sign in through NextAuth in the browser. Direct Flask API clients on a private connection use `POST /login` to obtain a token and send `Authorization: Bearer <token>`. Use JSON for request bodies unless noted.

Responses are scoped to the current user and organization. Treat `401` as a sign-in or credential failure, `403` as denied access, and `404` as a missing or unavailable resource. `409` means the request conflicts with current state. Reload before repeating an edit with a new version. `429` means the queue or a rate limit is full. Use `Retry-After` when present. `503` indicates a temporary dependency or publication failure. Keep the `X-Request-ID` from errors for log correlation.

## Health and accounts

| Method and path | Request and response |
| --- | --- |
| `GET /health/live` or `GET /` | Process status. Does not require authentication. |
| `GET /health/ready` | PostgreSQL migration, Redis connectivity and consumer leases for both required queues. Returns `200` when ready and `503` otherwise, with top-level `status` and per-queue metrics in `queues`. |
| `POST /register` | `username` and `password`. Returns `201`, `409` with `USERNAME_TAKEN` for a duplicate, or `429` when throttled. |
| `POST /login` | `username` and `password`. Returns `200` with a private `token`, `401` for invalid credentials, or `429` when throttled. |
| `DELETE /deleteUser` | Current `username` and `password`. Returns `204`. |

Readiness reports `queues.celery` and `queues.feedback`, each containing `consumers`, `queued`, `oldest_wait_seconds` and `status`. Queue status is `ready`, `missing_consumer` or `delayed`. A missing consumer makes readiness unavailable after its lease expires, by default 45 seconds. A delayed broker backlog emits a warning while keeping readiness `200` if dependencies and both consumers are available. `queued` excludes reserved and running tasks. An unknown enqueue timestamp produces `oldest_wait_seconds: null` and a warning. Queue metrics contain counts and ages. See [service recovery and queue health](README.md#service-recovery-and-queue-health) for settings and operator checks.

## Organizations

| Method and path | Request and response |
| --- | --- |
| `GET /getOrganisationNames` | `organisations` for the authenticated user. |
| `GET /getOrganisationName/<orgId>` | `organisation_name` for a member. |
| `GET /getOrganisationMembers/<orgId>` | `members`, `isOwner`, `canManageOwnership`, and `canInvite`. |
| `POST /createOrganisation` | `organisationName`, returns `organisation_id`. |
| `GET /get/user/suggestion?organisationId=…&prefix=…` | Suggested `usernames` for authorized management. |
| `POST /addUserToOrganisation` | `organisationId` and `newUser`. |
| `DELETE /removeUserFromOrganisation` | `organisationId` and `userToRemove`. The backend checks management access and role rules. |
| `DELETE /leaveOrganisation` | `organisationId`. An owner must transfer ownership or delete the organization where applicable. |
| `POST /transferOrganisationOwnership` | `organisationId` and `newOwner`. |
| `DELETE /deleteOrganisation` | `organisationId` and `confirmDelete: true`. Deletes the organization and its data. |

## Files and document bases

Convenience names in the URL or body are case-sensitive. Prefer stable numeric IDs for routes. Existing scoped operations also take `baseName`. Where supported, include `baseId` so the server can reject a stale name-to-ID mapping.

| Method and path | Request and response |
| --- | --- |
| `POST /data/upload/file` | Multipart `organisationId` and one or more parts named `file` containing UTF-8 text. For a new base, omit `baseName` and `baseId`. The response is an array of document IDs and per-file errors, with `201` for success, `207` for mixed results, or `400` for all failures. For an existing base include its name and ID, then poll the `taskId` returned with `202`. Check `errors` for any files skipped. |
| `GET /data/organization/get/files/<orgId>` | Files available to an organization member. |
| `GET /data/organization/get/documentbase/<orgId>` | Document bases available to an organization member. |
| `POST /core/document_base` | `organisationId`, `baseName`, `document_ids` as a list of distinct IDs from the upload, and `attributes` as a list of names. Returns `202` with `task_id`. On success, status includes the new `base_id`. |
| `GET /core/document_base/by-id/<orgId>/<baseId>` | Base reference with `id`, `name` and `attributeIds`. |
| `GET /core/document_base/resolve/<orgId>?name=…` | Same reference, resolved by exact name. |
| `DELETE /core/document_base/by-id/<orgId>/<baseId>` | Deletes the scoped base, subject to role checks. |
| `POST /core/document_base/load` | `organisationId`, `baseName` and optional `baseId`. Returns `task_id` to read a catalog or document through status. |
| `PUT /data/update/file/content` | `organisationId`, `baseName`, `baseId`, `documentId`, `newContent` and `expectedContent` to guard against concurrent edits. Returns `202` with `taskId`. |
| `DELETE /data/file/delete` | `organisationId`, `baseName`, `baseId` and `documentId` for a document in a base. Returns `202` with `taskId`. |
| `GET /core/document_base/feedback/overview?organisationId=…&baseName=…` | Attribute progress, IDs and current `attributeVersion`. No task is started. |
| `POST /core/document_base/attributes/update` | `organisationId`, `baseName`, `baseId`, `expectedVersion` and `operations`. Operations are `{"op":"add","name":"City"}`, `{"op":"rename","id":"…","name":"Place"}`, or `{"op":"remove","id":"…"}`. Returns `202` with `task_id`. |

## Tasks and SQL query results

A response of `202` acknowledges a submission. Poll `GET /core/status/<task_id>?summary=1&feedback=0` with backoff. This is a scoped read. Task status includes `state`, `meta`, a publication in `session`, and `command` when applicable. `QUEUED` means work has been admitted, `STARTED` means processing or an active interactive session, and `SUCCESS` means the task completed. Terminal faults can return HTTP `500` with states such as `FAILURE`, `EXPIRED`, or `REVOKED`, plus `meta.error` when available. A browser timeout only ends the wait.

| Status view | Content |
| --- | --- |
| `view=catalog` | Attribute counts and document IDs/names without text. |
| `view=document&documentId=…` | One document. `documentName` is available for legacy references. |
| `view=review&offset=…` | Current ranked candidates and a page of up to eight manual-review documents. |
| `view=table&offset=…` | Up to 50 rows and metadata including `columns`, `totalRows` and `truncated`. |
| `view=table-export` | All retained rows from the same query. |

Post `organisationId`, `baseName`, `baseId`, and `sqlQuery` to `/core/document_base/query`. For example, `select City where City is not null` is a read-only query against the documents table. The backend bounds result size. `truncated` indicates that only the retained rows can be downloaded. Query results expire after an hour, so rerun an expired query.

## Interactive feedback

1. Post `organisationId`, `baseName` and `baseId` to `/core/document_base/interactive`. Use the returned `task_id` as `sessionId`. Read it with `feedbackSession=1`, `organisationId` and `baseName` on the status URL. The parent publication moves from `loading` to `selection`.
2. In `selection`, post `attribute` and `doAttribute` to `/core/document_base/do_current_attribute` along with the command fields below and the base scope. Use `doAttribute: true` to start ranking, or `false` to skip the waiting attribute. `reset: true` with `doAttribute: true` repopulates it. The session moves through `processing`, then publishes a new version in `ranking`, `selection`, or `finished`.
3. In `ranking`, use a match, custom span, batch submission, or no-match decision. Poll the command's returned task ID. A command is confirmed when `command.state` is `published` and the session version reaches `command.published_version`. The Celery state alone is insufficient. A conflict may be published for review without accepting the proposed change. The UI can keep the saved decision or explicitly replace it.
4. Close a session through `/core/document_base/feedback/stop`. `finished` represents a closed publication. A failed or expired session can be reopened from the base with its saved matches.

Every command below is a JSON POST under `/core/document_base` and carries `sessionId` (UUID), `expectedVersion` (the last published version), and a fresh `commandId` (UUID) for each new decision. Single-document and batch match requests include `organisationId` and `baseName` as scope.

| Path suffix | Additional fields |
| --- | --- |
| `/do_current_attribute` | `organisationId`, `baseName`, `attribute`, `doAttribute` and optional `reset`. |
| `/confirm/nugget/match` or `/confirm/nugget/custom` | `documentName`, `documentContent`, `nuggetText`, `startIndex` and `endIndex`. Optional negative span fields are `noMatchText`, `noMatchStartIndex`, and `noMatchEndIndex`. |
| `/confirm/nugget/multiple` | `nuggets` list, one per document, each with `documentName`, `documentContent`, `text`, `startIndex` and `endIndex`. |
| `/confirm/nugget/none` | `documentName`, `documentContent` and the span fields. For a whole-document no match, use empty `nuggetText` and both offsets zero. |
| `/reload` | Optional `conflictResolution`, either `keep` or `replace` when resolving a conflict. |
| `/feedback/stop` | Command fields alone. |

Offsets count Unicode code points and use an exclusive end. Text fields must match the selected span of the current stored document exactly.

If a reply is lost, poll by the original command ID before retrying. For an exact replay, reuse the same command ID, expected version, and payload. Changed data or a new decision requires a new command ID after checking the live version. If a saved receipt is recovered from PostgreSQL, `command.recovered` is true and the result confirms the saved decision. Reopen the base to continue because the live publication is unavailable. If there is no saved outcome and the session is gone, reopen the base and inspect current state before sending another decision.

## Member document feedback

The historical path name `public` refers to votes shared with the organization. Both routes require membership.

- `POST /core/document_base/feedback/public/get` takes `organisationId`, `baseId`, and `documentId`. It returns `feedback` keyed by attribute name. With `suggestionsOffset` (start at 0), it instead returns a page of distinct corrections and `nextOffset`. Omit `documentId` when paging through suggestions for the entire base. Each item includes the document ID and name. A null replacement represents no match. Counts show how often each correction was suggested. `canReview` indicates organization-owner access.
- Owners can POST `organisationId`, `baseId`, `documentId`, `attribute`, `replacement` and boolean `accepted` to `/core/document_base/feedback/public/review`. The response gives a task ID. Accept applies the selected replacement or confirms no match. Reject dismisses the suggestion. Both preserve the votes.
- `POST /core/document_base/feedback/public` also takes `attributeId`, `documentContent`, `isPositive`, and either the selected span or null `startIndex`, `endIndex`, and `nuggetText`. The response includes the updated `feedback` counts and `mine`. Repeating the current thumbs-up or thumbs-down vote clears it. Selecting the opposite vote switches it.
- Send `noMatch: true` with `isPositive: false` and null span fields to suggest no match in the document. The correction replaces the user’s previous feedback, counts as a negative vote, and stays saved if resubmitted.

`POST /core/status/<task_id>` is retired and returns `410` to authenticated callers. The former `POST /core/document_base/order/nugget` endpoint has been removed. The browser proxy rejects it with `404`, and Flask rejects direct POST requests with `405`. Use `view=review` on task status for ranked feedback candidates, or `view=document` to inspect a document’s nuggets. The former development route inventory and debug endpoints are unavailable.
