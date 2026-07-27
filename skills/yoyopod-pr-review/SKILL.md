---
name: yoyopod-pr-review
description: "Close YoYoPod pull requests through the complete Codex review loop. Use whenever creating, updating, pushing, or preparing a PR for handoff: request a fresh Codex review for each pushed head, triage every finding, fix or technically answer it, reply and resolve its thread, and continue until the current head receives a thumbs-up with no unresolved findings."
---

# YoYoPod PR Review

Do not treat a successful push, green CI, or an earlier review as PR completion.
The terminal condition is a fresh Codex thumbs-up for the current head commit
and zero unresolved review threads.

## Review Loop

1. Record the current branch and exact head SHA:

   ```bash
   git branch --show-current
   git rev-parse HEAD
   ```

2. After every push, trigger a new review by posting `@codex review` as a
   top-level PR comment. Record the comment ID and trigger time. Do not accept
   a review or reaction that predates the pushed head.

3. Wait for Codex to respond. Poll the PR review timeline, the trigger
   comment's reactions, and thread-aware review state. A flat comment list is
   not sufficient because it does not prove thread resolution.

4. Triage every unresolved finding against the current code:

   - Reproduce or prove valid findings before changing code.
   - Add a regression test that fails before and passes after a behavior fix.
   - For invalid, obsolete, or conflicting findings, reply with concrete code
     and test evidence instead of changing correct behavior.
   - Never silently dismiss a finding.

5. For each finding, post a reply in its inline review thread stating the
   disposition, commit, and verification. Resolve the thread only after the
   reply is posted and the finding is addressed.

6. Run focused verification for each fix, then the repository checks required
   by the changed surface. Inspect the diff and working tree before committing.

7. Commit and push the fixes. Return to step 1 for the new head. Every push,
   including documentation-only follow-ups, requires a fresh Codex review.

8. Finish only when all of these are true for the current head:

   - Codex responded to the latest review request with a thumbs-up.
   - Thread-aware inspection reports zero unresolved findings.
   - Required tests and checks pass on the final tree.
   - The local head equals the pushed remote head.

## GitHub Operations

Prefer the GitHub connector for PR metadata, inline replies, reactions, and
thread resolution. Use thread-aware review APIs for `isResolved` state. If the
connector cannot expose the latest review reaction, use authenticated
`gh api`/GraphQL rather than assuming approval.

When waiting, keep the user informed at least once per minute. Do not create
empty commits merely to retrigger review; post `@codex review` again if a
request needs retrying and the head has not changed.

## Handoff

Report the final SHA, PR URL, fresh Codex approval evidence, resolved-thread
count, and final verification commands. Do not say the PR is ready while any
review finding remains open or the latest pushed head lacks a thumbs-up.
