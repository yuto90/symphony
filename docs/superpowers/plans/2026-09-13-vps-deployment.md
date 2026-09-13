# VPS deployment implementation plan

**Goal:** Deploy each tested main commit and restart every running Symphony instance.

**Approved design:** Build on GitHub Actions, transfer a checksummed Linux executable,
switch the common release symlink, restart all running `symphony-*.service` units,
verify each State API, and roll back all targets on failure. Stopped instances stay stopped.

**Architecture:** A main-only deployment job follows the existing quality gate and a
Linux build/smoke job. A dedicated SSH key invokes a root-owned fixed Python helper;
it cannot execute arbitrary commands. Releases live under `/opt/symphony`. GitHub job concurrency and a latest-main
check prevent stale deployments; a host lock also covers rollback.

**Tech stack:** GitHub Actions, OpenSSH, Python standard library, systemd, Burrito.

## Tasks

- [x] Add transaction tests using temporary release directories and a fake service
  adapter: two-service success, failed second service and full rollback, checksum
  failure, stopped-service exclusion, invalid arguments, health stability and upload rejection.
- [x] Implement `deploy/deploy.py`: bounded SSH stdin upload, SHA validation, flock,
  atomic symlink replacement, automatic service/port discovery, PID and API checks,
  rollback with explicit recovery errors. Run `python3 -m unittest discover -s deploy/tests`.
- [x] Extend `make-all.yml` with deployment-script tests, Linux build and smoke,
  and a main-push-only deployment job. Validate with `actionlint`.
- [x] Add root-run bootstrap script and deployment operation documentation; configure
  a dedicated restricted SSH key on the VPS and GitHub environment secrets.
- [x] Review transaction and privilege boundaries, run a harmless real SSH protocol
  rejection test, open a Japanese PR and verify required CI. Do not merge main.

## Constraints

Keep existing workflow, credentials, workspaces and stopped instances unchanged.
Only services using `/opt/symphony/current/symphony` and an explicit unique localhost
API port can participate; fail before switching if any running target is incompatible.
Never cancel a running deployment automatically. Keep old releases for recovery.
Production activation occurs on human merge; no premature deployment of branch code.

The user requested a simpler operational design: no host run-number database or
byte-count protocol. Standard SSH stdin, checksums, GitHub concurrency and host flock
cover the transfer and ordering requirements. Main activation remains pending human merge.
