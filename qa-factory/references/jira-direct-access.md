# Direct Jira read access

The source collector needs direct, read-only Jira API access to preserve every comment page
and the original bytes of every attachment. A Jira Assistant connection does not replace
this connection because an assistant response may contain only summaries or rendered
observations.

Configure `adapters.ticket` with an explicit authentication scheme and environment-variable
references. Do not put an email address, token, cookie, or authorization header in
`qa-factory/config.json`.

```json
{
  "adapters": {
    "ticket": {
      "kind": "jira",
      "direct_api": {
        "base_url": "https://example.atlassian.net",
        "api_version": "3",
        "auth_type": "basic_token",
        "username_ref": "QA_JIRA_EMAIL",
        "secret_ref": "QA_JIRA_API_TOKEN",
        "acceptance_criteria_fields": ["customfield_12345"]
      }
    }
  }
}
```

Set those variables in the local process environment or an approved host secret launcher.
The package currently resolves environment references; it does not implement a host
keychain reader. For a Jira deployment that accepts OAuth bearer tokens, use
`"auth_type": "bearer"` and `secret_ref`; omit `username_ref`. Authentication is never inferred.
`api_version` defaults to `2`, which supports Jira Server and Data Center; use `3` for Jira
Cloud. Discover the instance's acceptance-criteria field IDs during onboarding and list them
in `acceptance_criteria_fields`. The collector asks for every field and keeps the whole answer
(the raw folder below), but it never guesses that a project-specific field is AC: the light
snapshot a role reads holds only the custom fields the project NAMED.

Three optional keys shape the light form; absent means the default:
`direct_api.custom_fields` (ids of custom fields a role should see, default `[]`),
`direct_api.acceptance_headings` (headings to look for in the description besides those of
`references/jira-fields.json`, default `[]`) and `adapters.ticket.attachments` (`{}` = the
policy of `jira-fields.json`: images up to 5 MB, documents up to 10 MB, never video or archives -
a proposal, unmeasured; `{"policy": "off"}` downloads everything; `rules` / `never_suffixes`
replace the table's). A skipped attachment is listed with `skipped_by_policy:size|never|type`.

Grant only Jira permissions needed to browse issues and download attachments. Verify with
an issue in project scope. The reusable read-only readiness probe writes a sanitized receipt:

```text
run-py.cmd ticket_adapter.py probe APP-123 --output qa-factory/state/integrations/jira-direct-probe.json --json
```

The sample ticket is required. The probe verifies authenticated `/myself`, the selected
issue, every comment page, and one original attachment when the issue has attachments.
HTML login responses are rejected. A sample without attachments records that check as
`not_applicable`; omitting the sample leaves the probe unavailable.

The receipt schema is `schema_version`, `capability`, `status`, `checked_at`, `base_url`,
`api_version`, `auth_type`, `secret_ref`, `username_ref`, `server_title`, `ticket`, `error`,
`retryable`, `retry_at`, and `checks`. It contains secret reference names, never secret values.

Read the story's ticket (S0) with:

```text
run-py.cmd ticket_adapter.py get APP-123 --json --raw-dir qa-factory/artifacts/APP-123/work/ticket-raw
```

This is REST and nothing else: a tracker agent is a write channel, never a data source. The
issue is read with `fields=*all` and every response is kept as it came in the raw folder
(`issue.json` byte for byte, `issue.pretty.json` to slice, `field.json`, `remotelink.json`,
`comments-<n>.json` for pages the issue did not embed). stdout is the light snapshot, with
provenance `{source: fetched, fetched_at, fields_requested, bytes, sha256}` (the hash is over
`issue.json`). Beside the folder, in `work/`: `ticket-view.md` (what a role reads),
`ticket-references.json` (every ticket, merge request, link and local path the text carries,
with origins and status; S1 `collect` adds the text attachments) and, seeded in
`source-inventory.json`, the Epic Link field ids and the known project prefixes, so S1 asks
`/field` and those projects nothing again. Without `--raw-dir` it prints and writes nothing.

Collect the story source with:

```text
run-py.cmd ticket_adapter.py collect APP-123 --output qa-factory/artifacts/APP-123/work/source-inventory.json --relation task --json
```

`--relation` has no default — one call names the task, later calls name `subject`, `parent`,
`normative` or `referenced`. Only one `task`-relation source is accepted per story.

The inventory stores environment-variable names, source locators, hashes, and errors. It
does not store secret values. HTTP 401, 403, and 404 responses are not retried. Timeouts,
429, and 5xx responses receive at most two retries. A failed source or attachment remains
visible as `unavailable`; it is never converted to an empty successful result.

A key is uppercase with no letter or digit glued on either side (`fooTP1-9` and `TP1-9a`
are not keys, `MY_PROJ-12` is one whole key), and a `/browse/KEY` link counts behind a context
path too (`/jira/browse/KEY`). A key-shaped token mentioned in a description, a comment or an
attachment becomes a source once its project prefix is known — the task's own, its parent, its issue links, a
`/browse/KEY` url anywhere in the ticket, or the optional `adapters.ticket.project_keys`
string array (default `[]`, for a prefix onboarding already knows belongs to this tracker).
An unknown prefix costs one `GET /project/<PREFIX>` request, not one per key, cached for the
run; a project the tracker does not have is excluded in the same step, with the usual 404
caveat (Jira answers 404 for "no permission" too, so this is only trusted once some ticket of
the instance has actually been read).

A lost login is not a missing ticket. A 401, a 403, a login page (a redirect to ANOTHER host, the
single-sign-on page, is one; a redirect on the tracker's own host is not) or a CAPTCHA 403 - and a 404
on a ticket whose project is already known - is checked once, by re-reading something this run
already read (`?fields=updated`; `/myself` only before any read worked). Login fine: the
ticket is a not-found row. Login lost: the command exits 5 with ONE line naming the variable
to renew (`secret_ref`, `QA_JIRA_API_TOKEN`), nothing after that point is attempted or booked
as "not found", `source-inventory.json` carries `auth_stop`, and no `unavailable` prefix is
cached - after renewal the same prefix is asked again. An answer that did not come from the tracker
(a page from a firewall, a proxy or a protection service, or a body that could not be read) is not a lost
login: the run stops once (exit 5, owner `intermediary`), the line names what answered, and the token is left
unjudged. Requests carry the User-Agent `qa-factory/<version>`. 429, 5xx and timeouts stay
`unavailable` and retryable. Every REST call is a `command` span (`duration_ms`, `bytes`).

Request budget on TP1-15045 (comments embedded): S0 = 3 (issue, `/field`, `/remotelink`);
S1 `collect` = the issue, one request per downloaded attachment and one per UNKNOWN project
prefix (0 without a decoy, 1 with one) - at most 12 in all, tested.
