# Automatic VPS deployment

Every push to `main` (including a merged PR) runs `make-all`, deployment tests,
and a Linux x86-64 Burrito build/smoke test. Only after all three succeed does
`deploy-vps` use the `vps-production` environment to send the executable over SSH.
PR builds never receive deployment secrets and never deploy. Tag releases retain
their existing workflow.

The deployment job checks that its commit is still main's head before sending.
GitHub concurrency serializes deployment jobs without cancelling an active job.
The VPS additionally holds a file lock through the whole transaction and recovery.
If jobs are scheduled out of order, the latest-main check skips the older commit.
Superseded commits can be skipped; the latest successful head is the target.

## VPS contract

- Linux x86-64, Python 3, OpenSSH, systemd and sudo.
- Root-owned `/opt/symphony/releases` and `/opt/symphony/current` release symlink.
- Each running `symphony-*.service` must use
  `/opt/symphony/current/symphony` as its ExecStart executable and have a unique,
  explicit `--port NUMBER` with its State API available on localhost.
- Configuration, Codex credentials, logs and workspaces remain outside the release.
- Only units in the `running` substate at discovery are restarted. Stopped units
  remain stopped; new units following this contract are discovered automatically.
  A running incompatible unit or zero running units fails deployment before switching.
- Coordinate manual service/configuration changes outside a deployment window.

The helper accepts only `deploy COMMIT_SHA SHA256` and accepts
at most 256 MiB from SSH stdin. It verifies the checksum, stages an immutable
`releases/<commit>-<sha256>/symphony`, and atomically replaces the common symlink.
It restarts each target and requires three consecutive healthy API samples with
the same new PID. Services switch sequentially, so there is a short mixed-version
window. Active tasks may be interrupted; this is not a drain or zero-downtime rollout.

On switch/restart/health failure, the helper restores the previous symlink and
attempts restart and health verification for **every** original target. CI fails
even when recovery succeeds. A recovery failure is printed as `ROLLBACK FAILED`
and requires operator attention. Ordinary termination/disconnect signals trigger
recovery, but power loss or SIGKILL cannot be automatically handled. Existing
releases are retained for manual recovery; monitor available disk space.

## One-time installation

1. Create a dedicated Ed25519 key, separate from human SSH and Git credentials.
2. On the VPS, as root, run `bash deploy/install.sh /path/to/public-key.pub` from
   a reviewed copy of this directory. This installs root-owned helper scripts,
   the `symphony-deploy` system account, forced-command authorized key and a
   sudo rule allowing only the validating helper. It does not restart services.
   Re-running replaces this dedicated account's deployment key and helper.
3. Create GitHub environment `vps-production` restricted to the `main` branch.
   Configure environment secrets:

   | Secret | Value |
   | --- | --- |
   | `VPS_HOST` | VPS DNS name or IPv4 address |
   | `VPS_PORT` | SSH port |
   | `VPS_SSH_PRIVATE_KEY` | Dedicated private key |
   | `VPS_SSH_KNOWN_HOSTS` | Verified server host key entry for this host/port |

   Obtain host keys through an already trusted administrative connection. Do not
   trust an unauthenticated `ssh-keyscan` result by itself.
4. Verify that connecting with this key and command `true` is rejected with
   `Expected: deploy SHA SHA256`. Shell, SCP/SFTP, forwarding and PTY
   access are intentionally unavailable.
5. Merge the PR as a human. Inspect the `deploy-vps` job and each service's API.
   Check `/opt/symphony/current` resolves to the expected commit plus checksum.

The helper is deliberately **not** replaced by a routine deployment. Changes to
the privileged protocol/helper must be reviewed and installed by an operator
before merging a workflow that needs the updated protocol. The key authorizes
deploying code under the existing Symphony service users, so keep the environment
restricted to trusted main code and protect main merges.

## Retry and recovery

Re-run failed jobs after resolving the underlying issue. Content-addressed releases
allow retries and rebuilt binaries. If main has advanced, the latest-main check
skips the old run; use the latest commit's CI instead. Always deploy through this
workflow so its concurrency and freshness checks apply; the root helper does not
maintain a separate version-order database.

If automatic recovery fails, an administrator should restore a known-good release
symlink, restart the original affected units and verify their APIs. The helper's
job output identifies the failing services. Do not delete old releases during a
deployment.

## Validation

```sh
python3 -m unittest discover -s deploy/tests -v
bash -n deploy/install.sh
actionlint .github/workflows/make-all.yml
```

Tests exercise the real file transaction with a fake systemd adapter to avoid
restarting developer services. Real production activation is verified after merge.
