---
tracker:
  kind: github
  provider:
    repo: $GITHUB_REPO
    token: $GITHUB_TOKEN
  active_states: [open]
  terminal_states: [closed]
  required_labels: [symphony]
polling:
  interval_ms: 15000
workspace:
  root: $SYMPHONY_WORKSPACE_ROOT
hooks:
  after_create: |
    set -eu
    git clone -- "https://github.com/${GITHUB_REPO:?Set GITHUB_REPO}.git" .
agent:
  max_concurrent_agents: 1
  max_turns: 20
codex:
  command: codex app-server -c model='"gpt-5.6-luna"' -c model_reasoning_effort='"max"'
  turn_sandbox_policy:
    type: workspaceWrite
    networkAccess: true
---

You are implementing GitHub issue {{ issue.identifier }} in an isolated workspace.

Title: {{ issue.title }}
URL: {{ issue.url }}
Description:
{{ issue.description }}

Use the session's `github_api` tool for issue reads and updates. Read the current
issue and all comments before working. Only work while the issue is open and has
the `symphony` label. Follow the repository's AGENTS.md and the issue's approved
scope and acceptance criteria.

Maintain one `## Codex Workpad` issue comment with the plan, acceptance criteria,
validation evidence, branch, and PR URL. Reuse an existing workpad and open PR on
retries instead of creating duplicates. Preserve unrelated changes.

Create a `codex/` branch from the remote default branch for new work. Implement
the issue, run the required checks, review the diff, commit, and push only that
branch. Open or update a PR in the configured repository, following its PR
template. Include a link to this issue, validation results, and Japanese manual
verification steps with expected outcomes. Resolve actionable review feedback
and verify checks on the latest PR head before reporting it ready.

When ready for human review, first record the PR URL and final verification in
the workpad, then remove only the `symphony` label from this issue using
`DELETE /repos/{owner}/{repo}/issues/{number}/labels/symphony`. Keep the issue open.
The label removal pauses scheduling, including after a service restart. A human
can add the label again to request changes; resume the existing branch and PR.
If blocked on missing access or a required decision, record the blocker and
required human action in the workpad, then remove the label to pause retries.

Never merge a PR, enable auto-merge, push to or delete the default branch, or
close the issue. Human reviewers own merging and issue closure. Do not invoke
the `land` skill. Never expose credentials in files, comments, or logs.
