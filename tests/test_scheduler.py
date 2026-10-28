import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

APP = Path(__file__).resolve().parents[1] / 'scripts' / 'codex_scheduler.py'


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.project = self.root / 'project'
        self.project.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.project)], check=True)
        self.other = self.root / 'other'
        self.other.mkdir()
        self.session = str(uuid.uuid4())
        self.other_session = str(uuid.uuid4())
        folder = self.root / 'codex-home' / 'sessions' / '2026' / '10' / '28'
        folder.mkdir(parents=True)
        for sid, folderpath in ((self.session, self.project), (self.other_session, self.other)):
            rollout = folder / f'rollout-2026-10-28T01-01-01-{sid}.jsonl'
            rollout.write_text(json.dumps({'type':'session_meta', 'payload':{'id':sid, 'cwd':str(folderpath)}})+'\n')
        self.env = os.environ.copy()
        self.env.update({
            'PATH': str(self.bin) + os.pathsep + os.environ['PATH'],
            'CODEX_HOME': str(self.root / 'codex-home'),
            'CODEX_SCHEDULER_STATE': str(self.root / 'state'),
            'FAKE_RUN': str(self.root / 'systemd-run.log'),
            'FAKE_CODEX': str(self.root / 'codex.log'),
        })
        for cmd, content in {
            'systemctl': '#!/bin/sh\nif [ "$2" = "stop" ]; then echo "$*" >> "$FAKE_RUN"; fi\nexit 0\n',
            'systemd-run': '#!/bin/sh\necho "$*" >> "$FAKE_RUN"\nexit 0\n',
            'codex': '#!/bin/sh\npwd >> "$FAKE_CODEX"\nprintf "%s\\n" "$@" >> "$FAKE_CODEX"\nexit 0\n',
        }.items():
            path = self.bin / cmd
            path.write_text(content)
            path.chmod(0o755)
        self.when = (dt.datetime.now() + dt.timedelta(days=2)).strftime('%Y-%m-%d %H:%M')

    def cli(self, *arguments, ok=True):
        result = subprocess.run([sys.executable, str(APP), *arguments], env=self.env, capture_output=True, text=True, cwd=self.project)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return result

    def schedule(self):
        self.cli('schedule', '--project', str(self.project), '--session', self.session, '--at', self.when)
        jobs = list((self.root / 'state' / 'jobs').glob('*.json'))
        return sorted(jobs, key=lambda f: f.stat().st_mtime)[-1].stem

    def test_sessions_are_scoped_by_project(self):
        result = self.cli('sessions', '--project', str(self.project))
        self.assertIn(self.session, result.stdout)
        self.assertNotIn(self.other_session, result.stdout)

    def test_dry_run_does_not_register_a_job(self):
        self.cli('schedule', '--project', str(self.project), '--latest', '--at', self.when, '--dry-run')
        self.assertFalse((self.root / 'state').exists())

    def test_schedule_and_resume_exact_session(self):
        jobid = self.schedule()
        self.assertIn('--on-calendar=' + self.when, (self.root / 'systemd-run.log').read_text())
        self.assertIn(jobid, self.cli('jobs').stdout)
        self.cli('run', jobid)
        job = json.loads((self.root / 'state' / 'jobs' / f'{jobid}.json').read_text())
        self.assertEqual(job['status'], 'completed')
        cmd = (self.root / 'codex.log').read_text()
        self.assertIn(str(self.project), cmd)
        self.assertIn('exec\n--sandbox\nworkspace-write\nresume\n' + self.session, cmd)
        self.assertIn('Exit code: 0', self.cli('logs', jobid).stdout)
        self.assertNotIn(self.other_session, cmd)

    def test_cancel_only_scheduled_jobs(self):
        jobid = self.schedule()
        self.cli('cancel', jobid)
        self.assertIn('cancelled', self.cli('jobs').stdout)
        self.assertIn('codex-scheduler-'+jobid+'.timer', (self.root/'systemd-run.log').read_text())
        result = self.cli('run', jobid, ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root/'codex.log').exists())

    def test_reject_other_project_session(self):
        result = self.cli('schedule', '--project', str(self.project), '--session', self.other_session,
                          '--at', self.when, ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('non trovata', result.stderr)


if __name__ == '__main__':
    unittest.main()
