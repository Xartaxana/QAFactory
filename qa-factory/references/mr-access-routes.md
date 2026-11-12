# Reading MR evidence through an available route

Git/SSH proves access to repository refs and objects. MR descriptions, comments and review
discussions are separate server data. API authentication is one way to read that data, not
a mandatory transport when an authorized connector or browser provides equivalent evidence.

## The ladder: every route is tried before a person is asked

Material the story needs — above all the task's own source data — is fetched by trying the routes
in order, and each attempt is recorded with what it actually answered:

1. **the authenticated API** — `vcs_evidence.py --url` for a GitLab MR, the ticket adapter for a
   tracker key. This is the only route that gives description *and* discussions.
2. **git / SSH on a local checkout** — the MR's own ref (`refs/merge-requests/<iid>/head`, which
   exists only while the MR is open: githost prunes it on merge) or, for a merged MR, its commits in
   the history. This route gives the change and nothing else, so what it produces is recorded
   `partial`, never `read`.
3. **a configured connector**, when the project declares one.
4. **a browser — which the factory does not have.** Roles and the conductor run headless with
   `Bash,Read,Write,Edit,Glob,Grep` (the conductor: `Bash,Read,Grep`); no role carries a browser
   tool, and the rule below forbids feeding one a session or a credential. The browser route
   therefore belongs to whoever holds the session: the person, or an agent acting for them in their
   own browser. Its result enters the factory as recorded material with `provenance: browser`.
5. **the person**, who gets three answers, not one: *it is not needed* (recorded as an accepted gap
   in their words), *here is how to reach it* (a token, a CLI, a VPN to reconnect — the collection
   runs again), or *here is the content* (they read it themselves and paste what matters; it is
   saved as material with `provenance: person_pasted`).

A partial result is a state, not a failure: "we have the MR, we do not have its comments" is a fact
the person can act on, and relevance is decided on what was collected before anyone is asked to
supply the rest. `status: unavailable` carries a cause from the closed list in
`references/source-causes.json` plus the fact observed. `host_unreachable` that the collector's own
receipt carries (`--probe-ref`; a dropped VPN answers exactly that way) is a gap by default, named in
the report and collected again at the next scout handover once access is back; `auth_required` is an
access problem and is offered as a road, with the person's choice to go on without it.

Prefer the configured connector or `vcs_evidence.py` collector. If that route fails,
record its precise error and inspect an available authorized browser/connector for the
same MR. This is a read-only recovery route; it does not change the configured write adapter.
Do not copy browser cookies into shell tools, create credentials, or bypass a login prompt.
If sign-in is needed, ask the user to sign in or configure the CLI locally. Do not ask them
to paste passwords or tokens into the conversation.

For browser collection:

- Record the canonical MR URL, project, IID, source/target branches, head SHA and base SHA
  of the inspected diff. Save the original visible description and metadata, with capture time.
- Read the full activity/discussion view, including resolved threads, older pages and collapsed
  replies. Save the actual content and provenance. A comments-only filter or the initial
  viewport is not proof of complete history. Record expected/retrieved counts where available;
  otherwise require observable end-of-pagination evidence. Unknown completeness stays unknown.
- Capture all diff pages, or obtain the exact base/head Git objects over verified SSH and
  save `git diff BASE HEAD` for those pinned SHAs. A branch tip guessed from its name or
  the current default branch does not identify the MR's comparison base.
- Recheck MR revision/update information after collection. A changed or unverifiable
  snapshot remains partial. Store content under the task's `work/` with hashes and inspection
  receipts; record the route per material. Keep a failed API receipt as evidence of that
  attempt, and link successful replacement material in the source inventory.

Do not mark `vcs_api` verified from browser or SSH evidence. Source completeness is decided
from collected/inspected material, independently of API capability. Missing mandatory
content still blocks S1. Report which material and route are blocked, rather than declaring
all Git access unavailable or requiring an API token when another route is already usable.
