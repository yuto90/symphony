import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'deploy.py'


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(), 'deployment helper must exist')
        spec = importlib.util.spec_from_file_location('deploy', SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        old = self.root / 'releases' / 'old'
        old.mkdir(parents=True)
        (old / 'symphony').write_bytes(b'old')
        (self.root / 'current').symlink_to(old)
        self.payload = b'new executable'
        self.sha = 'a' * 40
        self.digest = hashlib.sha256(self.payload).hexdigest()
        self.release = f'{self.sha}-{self.digest}'
        self.services = FakeServices(self.root)

    def run_deploy(self, sequence=2, digest=None):
        command = f'deploy {self.sha} {sequence} {digest or self.digest} {len(self.payload)}'
        return self.module.deploy(command, io.BytesIO(self.payload), self.root, self.services)

    def test_all_running_services_switch_to_new_release(self):
        self.run_deploy()
        self.assertEqual((self.root / 'current' / 'symphony').read_bytes(), self.payload)
        self.assertEqual(self.services.restarts, [('symphony-a.service', self.release), ('symphony-b.service', self.release)])
        self.assertEqual(self.services.checks, ['symphony-a.service', 'symphony-b.service'])

    def test_failed_second_service_restores_every_target(self):
        self.services.fail_new = 'symphony-b.service'
        with self.assertRaisesRegex(RuntimeError, 'rolled back'):
            self.run_deploy()
        self.assertEqual((self.root / 'current').resolve().name, 'old')
        self.assertEqual(self.services.restarts[-2:], [('symphony-a.service', 'old'), ('symphony-b.service', 'old')])

    def test_bad_checksum_never_restarts(self):
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.run_deploy(digest='0' * 64)
        self.assertEqual(self.services.restarts, [])
        self.assertEqual((self.root / 'current').resolve().name, 'old')

    def test_older_deployment_is_rejected(self):
        self.run_deploy(sequence=5)
        self.services.restarts.clear()
        with self.assertRaisesRegex(ValueError, 'older'):
            self.run_deploy(sequence=4)
        self.assertEqual(self.services.restarts, [])

    def test_invalid_command_is_rejected(self):
        for command in ['sh', 'deploy ../../escape 1 x 3', f'deploy {self.sha} 1 {self.digest} 9999999999']:
            with self.assertRaises(ValueError):
                self.module.deploy(command, io.BytesIO(b''), self.root, self.services)
        self.assertEqual(self.services.restarts, [])

    def test_no_running_services_does_not_switch(self):
        self.services.targets = []
        with self.assertRaisesRegex(RuntimeError, 'No running'):
            self.run_deploy()
        self.assertEqual((self.root / 'current').resolve().name, 'old')

    def test_truncated_upload_does_not_switch(self):
        with self.assertRaisesRegex(ValueError, 'Truncated'):
            self.module.deploy(f'deploy {self.sha} 2 {self.digest} 100', io.BytesIO(self.payload), self.root, self.services)
        self.assertEqual(self.services.restarts, [])

    def test_same_commit_can_be_rebuilt_and_retried(self):
        self.run_deploy()
        self.payload = b'rebuilt executable'
        self.digest = hashlib.sha256(self.payload).hexdigest()
        self.run_deploy()
        self.assertEqual((self.root / 'current' / 'symphony').read_bytes(), self.payload)

    def test_rollback_failure_still_attempts_every_instance(self):
        self.services.fail_new = 'symphony-b.service'
        original_restart = self.services.restart
        def restart(name):
            original_restart(name)
            if name == 'symphony-a.service' and (self.root / 'current').resolve().name == 'old':
                raise RuntimeError('rollback restart failed')
        self.services.restart = restart
        with self.assertRaisesRegex(RuntimeError, 'ROLLBACK FAILED'):
            self.run_deploy()
        self.assertEqual(self.services.restarts[-1], ('symphony-b.service', 'old'))

    def test_health_failure_rolls_back(self):
        def healthy(name, port, old_pid):
            if (self.root / 'current').resolve().name != 'old':
                raise RuntimeError('API unhealthy')
        self.services.healthy = healthy
        with self.assertRaisesRegex(RuntimeError, 'rolled back'):
            self.run_deploy()
        self.assertEqual((self.root / 'current').resolve().name, 'old')

    def test_discovery_excludes_stopped_units_and_validates_shared_path(self):
        service = self.module.Services()
        def command(*args):
            if args[0] == 'list-units':
                self.assertIn('--state=running', args)
                return 'symphony-a.service loaded active running Symphony'
            if '--property=ExecStart' in args:
                return '{ path=/opt/symphony/current/symphony ; argv[]=/opt/symphony/current/symphony --port 4001 /etc/symphony/WORKFLOW.md ; }'
            return '42'
        with patch.object(service, 'command', side_effect=command):
            self.assertEqual(service.discover(), [('symphony-a.service', 4001, '42')])
        with patch.object(service, 'command', side_effect=[
            'symphony-a.service loaded active running Symphony',
            '{ path=/some/other/symphony ; argv[]=symphony --port 4001 ; }',
        ]):
            with self.assertRaisesRegex(RuntimeError, 'shared executable'):
                service.discover()

    def test_health_stability_requires_same_pid(self):
        service = self.module.Services()
        pids = iter(['101', '102', '102', '102'])
        calls = []
        def command(*args):
            if '--property=SubState' in args:
                return 'running'
            pid = next(pids)
            calls.append(pid)
            return pid
        class Opener:
            def open(self, *args, **kwargs):
                return io.BytesIO(b'{"counts": {}}')
        with patch.object(service, 'command', side_effect=command), \
                patch.object(self.module.urllib.request, 'build_opener', return_value=Opener()), \
                patch.object(self.module.time, 'sleep'):
            service.healthy('symphony-a.service', 4001, '10')
        self.assertEqual(calls, ['101', '102', '102', '102'])


class FakeServices:
    def __init__(self, root):
        self.root = root
        self.targets = [('symphony-a.service', 4001, '10'), ('symphony-b.service', 4002, '20')]
        self.restarts = []
        self.checks = []
        self.fail_new = None

    def discover(self):
        return self.targets

    def restart(self, name):
        release = (self.root / 'current').resolve().name
        self.restarts.append((name, release))
        if name == self.fail_new and release != 'old':
            raise RuntimeError('restart failure')

    def healthy(self, name, port, old_pid):
        self.checks.append(name)


if __name__ == '__main__':
    unittest.main()
