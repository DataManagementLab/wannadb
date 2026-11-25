# Contribute to the WannaDB web backend

This guide covers `wannadb_web`, the Flask/Celery entry points, web Compose files and
web documentation. Keep shared-core (`wannadb`, `wannadb_parsql`) and desktop
(`wannadb_ui`) changes in the separately agreed upstream issue work. A web change
must preserve the current matching logic and nugget identities.

## Prepare a local checkout

Use Python 3.11 for the web application. Follow [deployment/setup](DEPLOYMENT.md)
for service dependencies and environment configuration. Use a disposable local or
staging PostgreSQL/Redis instance for integration work. The lean API/migration/Flower
images intentionally omit worker models and the full development toolchain; use a
separate development environment with the pinned backend/core requirements when
linting or exercising worker code.

## Python conventions

Use typed function signatures for new or substantively changed helpers. Document
public/non-obvious behavior with reStructuredText docstrings, explicit `:type name:`
and `:rtype:` fields for meaningful return values, and `:raises ExceptionType:` for
caller-visible failures. Omit `:returns:` and `:rtype:` for procedures and constructors
that only return `None`; describe their side effects in prose. Keep `None` documented
when it is a meaningful absent-result sentinel alongside other possible return
values. Describe side effects, scope, expiry and concurrency requirements rather
than repeating the function name. Keep field types consistent with annotations.
For Flask routes, distinguish JSON request fields from actual Python parameters;
state the response type and link [ROUTES.md](ROUTES.md) for the wire contract.

```python
def require_positive_id(value: int) -> int:
    """Validate a positive database ID.

    :param value: The already-parsed database ID.
    :type value: int
    :returns: The validated ID.
    :rtype: int
    :raises ValueError: If the ID is not positive.
    """
    if value <= 0:
        raise ValueError("The ID must be positive.")
    return value
```

See [Sphinx's Python field-list reference](https://www.sphinx-doc.org/en/master/usage/domains/python.html#info-field-lists).
The existing `.pylintrc` specifies tab indentation and a 100-column limit. Preserve an
existing file's indentation when making a small change; do not mix tabs/spaces or
reformat an unrelated file. Use the surrounding quote style. No Python autoformatter
is configured, so formatting review follows that configuration and the focused diff.
Keep type-only documentation changes free of runtime imports or annotation changes
that alter startup behavior.

## Documentation conventions

Use **organization** in prose and user-facing English text. Preserve compatibility-sensitive
API, database and existing code identifiers such as `organisationId`, `organization_id`
and `baseName`. Never rename a wire field as a spelling cleanup.

Use one level-one title in standalone guides and consecutive heading levels. PR bodies start at level two under the PR title. Prefer task headings and
imperative instructions. Use `sh`, `python`, `ts`, `tsx`, `json`, `sql`, `yaml` and
`dotenv` fence labels. Keep request/response examples valid and clearly mark fixture
values; show integers, booleans, UUIDs and Unicode code-point spans with their actual
types. Update comments, examples and the contract in the same change as behavior.

Use this structure for a new procedure; omit a section only when it adds no value:

```md
# Task or feature

State the purpose and intended reader.

## Prerequisites

State the checkout/directory, runtime, configuration, access and initial state.

## Procedure

Give ordered actions and executable commands with fixture values identified.

## Verify

State the expected response, resulting state and checks actually performed.

## Recover

Describe retry/rollback and retained data; link the relevant operations guide.
```

Distinguish verified behavior from source review, local fixtures and operator-run
staging checks. Never label an unperformed check successful. Use synthetic document
text in examples and keep credentials, tokens, model caches and user data out of docs.

## Validate a web change

Run from the backend checkout in the configured local development environment:

```sh
python -m compileall -q wannadb_web app.py celery_app.py
python -m pylint --rcfile=.pylintrc wannadb_web app.py celery_app.py
```

Compilation must succeed. Pylint is already declared in `backend-requirements.txt`.
Run it with the repository configuration and inspect its exit status and diagnostics.
The legacy tree can have existing lint findings; record the original and changed
results and introduce no new diagnostics in changed code. Do not hide a failure with
new disables or claim a clean whole-tree baseline. Scope a follow-up invocation to
the changed web modules when triaging legacy findings.

There is no configured Python formatter command or committed web integration-test
suite. `tests/test_data.py` exercises shared-core data behavior and does not verify
web authorization, queues, migrations or sessions. Add relevant web regression tests
for functional changes and record their exact command, fixtures and results in the PR.
For documentation-only changes, check links, heading levels, fenced examples and that
code/docstring edits leave executable behavior unchanged. Do not run service checks
against a live deployment merely to validate prose.

For functional web changes, the author runs the relevant local/staging checks:

| Changed area      | Required evidence                                                                                               |
| ----------------- | --------------------------------------------------------------------------------------------------------------- |
| HTTP/access       | Member/outsider and owner/non-owner cases; typed failures and request IDs.                                      |
| Jobs/sessions     | Both queue consumers, a creation job, a feedback step, stale/replayed commands and session close.               |
| Public review     | Repeated/overlapping occurrences, No Match, stale votes/review dialogs and owner-only accept/reject.            |
| Schema/deployment | Fresh install and supported upgrade; backup/restore and restart rehearsal using [DEPLOYMENT.md](DEPLOYMENT.md). |
| SQL/export        | Supported reads, rejected writes, budgets/truncation, confirmed/automatic mode and retained CSV scope.          |

## Prepare a pull request and rollout

Explain the problem and resulting behavior, affected contract/docs, exact checks and
any baseline failures or checks still pending. Use the PR template. The author owns
local regression evidence; the reviewer checks contracts, types, permission boundaries
and documentation consistency. The operator owns backups, migration/restart/restore
rehearsals and deployment verification. Existing stable-branch workflows create PRs;
they are not evidence that web regression checks passed.

Add a new migration rather than modifying an applied migration/checksum. For paired
changes, deploy/migrate the API and workers before the matching frontend. Finish
active work and follow the operator's normal backup procedure. Preserve environment
secrets, existing project names and storage. Keep formatter sweeps, dependency upgrades
and functional changes in separately reviewable work.
