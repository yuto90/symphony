#!/usr/bin/python3
"""Root-owned forced SSH command. Never execute caller-supplied shell text."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request


ROOT = Path('/opt/symphony')
MAX_BYTES = 256 * 1024 * 1024


def log(message):
    try:
        print(message, flush=True)
    except OSError:
        # SSH may disconnect while recovery is still running.
        pass


class Services:
    @staticmethod
    def command(*args):
        return subprocess.check_output(
            ['/usr/bin/systemctl', *args], text=True, timeout=150
        ).strip()

    def discover(self):
        output = self.command('list-units', '--type=service', '--state=running',
                              '--no-legend', '--plain', '--no-pager', 'symphony-*.service')
        targets = []
        ports = set()
        for line in output.splitlines():
            name = line.split()[0]
            if not re.fullmatch(r'symphony-[A-Za-z0-9_.@-]+\.service', name):
                raise RuntimeError('Invalid Symphony service name')
            executable = self.command('show', name, '--property=ExecStart', '--value')
            if not re.search(r'path=/opt/symphony/current/symphony\s*;', executable):
                raise RuntimeError(f'{name} does not use the shared executable')
            match = re.search(r'--port\s+(\d+)(?:\s|;)', executable)
            if not match or not 1 <= int(match[1]) <= 65535 or int(match[1]) in ports:
                raise RuntimeError(f'{name} needs a unique explicit --port')
            port = int(match[1])
            ports.add(port)
            pid = self.command('show', name, '--property=MainPID', '--value')
            if not pid.isdigit() or pid == '0':
                raise RuntimeError(f'{name} has no running PID')
            targets.append((name, port, pid))
        return sorted(targets)

    def restart(self, name):
        self.command('restart', name)

    def healthy(self, name, port, old_pid):
        deadline = time.monotonic() + 90
        stable = 0
        stable_pid = None
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        while time.monotonic() < deadline:
            try:
                state = self.command('show', name, '--property=SubState', '--value')
                pid = self.command('show', name, '--property=MainPID', '--value')
                with opener.open(f'http://127.0.0.1:{port}/api/v1/state', timeout=3) as response:
                    data = json.load(response)
                if state != 'running' or pid in ('0', old_pid) or not isinstance(data.get('counts'), dict):
                    raise ValueError('Service is not ready')
                stable = stable + 1 if pid == stable_pid else 1
                stable_pid = pid
                if stable >= 3:
                    log(f'Healthy: {name} PID={pid}')
                    return
            except (OSError, ValueError, subprocess.SubprocessError):
                stable = 0
            time.sleep(2)
        raise RuntimeError(f'Health check failed: {name}')


def atomic_link(link, target):
    temporary = link.with_name(link.name + '.next')
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    os.replace(temporary, link)


def deploy(command, stream, root=ROOT, services=None):
    match = re.fullmatch(r'deploy ([0-9a-f]{40}) ([1-9][0-9]{0,15}) ([0-9a-f]{64}) ([1-9][0-9]{0,8})', command)
    if not match:
        raise ValueError('Expected: deploy SHA SEQUENCE SHA256 SIZE')
    sha, sequence, digest, size = match.groups()
    sequence, size = int(sequence), int(size)
    if size > MAX_BYTES:
        raise ValueError('Artifact too large')
    services = services or Services()
    with (root / '.deploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        marker = root / 'deploy-sequence.json'
        if marker.exists():
            previous = json.loads(marker.read_text())
            if sequence < previous['sequence']:
                raise ValueError('Refusing older deployment')
            if sequence == previous['sequence'] and sha != previous['sha']:
                raise ValueError('Sequence already belongs to another commit')

        releases = root / 'releases'
        releases.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.upload-', dir=releases) as temporary:
            binary = Path(temporary) / 'symphony'
            checksum = hashlib.sha256()
            remaining = size
            with binary.open('wb') as output:
                while remaining:
                    chunk = stream.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        raise ValueError('Truncated artifact')
                    checksum.update(chunk)
                    output.write(chunk)
                    remaining -= len(chunk)
                output.flush()
                os.fsync(output.fileno())
            if checksum.hexdigest() != digest:
                raise ValueError('Artifact checksum mismatch')
            targets = services.discover()
            if not targets:
                raise RuntimeError('No running Symphony services found')
            current = root / 'current'
            if not current.is_symlink():
                raise RuntimeError('current must be a release symlink')
            old = current.resolve(strict=True)
            if not (old / 'symphony').is_file():
                raise RuntimeError('Rollback executable missing')
            # Rebuilding the same commit can produce different executable bytes.
            release = releases / f'{sha}-{digest}'
            if release.exists():
                if hashlib.sha256((release / 'symphony').read_bytes()).hexdigest() != digest:
                    raise ValueError('Existing release checksum differs')
            else:
                binary.chmod(0o755)
                Path(temporary).chmod(0o755)
                os.rename(temporary, release)

        next_marker = marker.with_suffix('.next')
        next_marker.write_text(json.dumps({'sequence': sequence, 'sha': sha}))
        os.replace(next_marker, marker)
        log(f'Deploying {sha} to {len(targets)} instances')
        try:
            atomic_link(current, release)
            for name, port, pid in targets:
                services.restart(name)
                services.healthy(name, port, pid)
        except BaseException as error:
            # Do not let a second termination signal interrupt recovery.
            if root == ROOT:
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
                signal.signal(signal.SIGINT, signal.SIG_IGN)
                signal.signal(signal.SIGHUP, signal.SIG_IGN)
                signal.alarm(0)
            atomic_link(current, old)
            failures = []
            for name, port, _ in targets:
                try:
                    services.restart(name)
                    services.healthy(name, port, '0')
                except Exception as recovery_error:
                    failures.append(f'{name}: {recovery_error}')
            if failures:
                raise RuntimeError(f'Deployment failed; ROLLBACK FAILED: {failures}') from error
            raise RuntimeError('Deployment failed; all instances rolled back') from error
        log(f'Deployed {sha}; all instances healthy')


def interrupted(signum, frame):
    raise RuntimeError(f'Deployment interrupted by signal {signum}')


if __name__ == '__main__':
    os.umask(0o022)
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGALRM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    signal.alarm(1800)
    try:
        if os.geteuid() != 0 or len(sys.argv) != 2:
            raise ValueError('Run through the installed forced SSH command')
        deploy(sys.argv[1], sys.stdin.buffer)
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
