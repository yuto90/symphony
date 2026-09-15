# GitHub Issues workflow

This fork uses the upstream GitHub Issues adapter; no additional adapter package
is needed. The repository-root `WORKFLOW.md` is the GitHub entry point. The
upstream `elixir/WORKFLOW.md` remains the Linear example.

## Configure and run

Enable Issues in the target repository's GitHub settings and create a `symphony`
label. Apply it only to issues approved for implementation.

Set these variables in the service environment (never commit token values):

```bash
export GITHUB_REPO=yuto90/symphony
export SYMPHONY_WORKSPACE_ROOT="$HOME/symphony-workspaces/yuto90-symphony"
# Set GITHUB_TOKEN through your host's secret manager/environment.
```

Use a repository-scoped token with Issues read/write permission for polling,
workpad comments, and label removal. Grant Pull requests read/write if the agent
uses `github_api` to create/update PRs. The raw tool is bounded by token permissions,
not by `GITHUB_REPO`, so scope the token to the intended repository.

Configure Git clone/push authentication separately, such as a host Git credential
helper with a repository-scoped credential. Symphony strips tracker tokens from
the Codex child environment; `GITHUB_TOKEN` alone does not configure agent Git
push authentication. Codex must also be signed in on the execution host.

Install the runtime and build using the [Elixir instructions](../elixir/README.md).
Then explicitly select the GitHub workflow from the repository root:

```bash
cd elixir
mise exec -- ./bin/symphony ../WORKFLOW.md
```

With a self-contained release binary, pass the absolute path to the repository's
root `WORKFLOW.md` instead. Starting the service processes eligible issues.

The GitHub workflow pins Codex to `gpt-5.6-luna` with `max` reasoning effort
through `codex.command` CLI overrides, independently of the host's default model
and reasoning effort. It also sets `codex.approval_policy: never` for unattended
execution and compatibility with Codex versions that accept string approval
policies but not object-form rejection policies. The execution host must have a
Codex CLI version and account that support this model and effort. If the service
uses a separate deployed copy of `WORKFLOW.md`, update that copy as well; merging
this repository change alone does not update the deployed workflow. The settings
apply to newly started Codex app-server sessions.

The fixed workflow prompt requires PR titles and bodies to be written in
Japanese, including summaries, validation results, and manual verification
steps. Exact headings required by a repository PR template remain unchanged;
all other free-form PR text is written in Japanese.

## Ticket lifecycle

- Open without `symphony`: backlog or waiting for human review; not dispatched.
- Open with `symphony`: eligible for implementation, one agent at a time.
- PR ready or blocked: the agent updates its workpad, then removes `symphony`.
- Rework: a human adds `symphony` again; the agent resumes the existing PR.
- Closed: terminal; Symphony stops the agent and cleans its workspace.

Removing the label stops active work at reconciliation, so the handoff comment
must be saved before label removal. This is a workflow convention, not a native
GitHub custom status or an automatic review watcher. Humans merge PRs and close
issues. Branch protection and credential permissions should enforce that policy
on the host; the workflow prompt is not an authorization boundary.

For another app, run a separate Symphony instance with its own `GITHUB_REPO`,
repository-scoped credentials, and unique `SYMPHONY_WORKSPACE_ROOT`. One instance
polls one repository. Do not share a workspace root between repositories because
issue identifiers use `GH-<number>`.
