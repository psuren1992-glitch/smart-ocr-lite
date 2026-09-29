import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from core.accounts import Accounts
from core.server_runtime import instance_lock, snapshot
from webapp import ACTIVE, enqueue, recover_queue, run_work, write_json, read_json


class ServerRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'data'
        self.root.mkdir()
        self.accounts = Accounts(self.root / '_access')
        self.addCleanup(ACTIVE.clear)

    def work(self, letter, **extra):
        folder = self.root / (letter * 32)
        folder.mkdir()
        write_json(folder / 'work.json', dict(id=folder.name, count=1, created=letter, **extra))
        (folder / 'source.pdf').write_bytes(b'original')
        return folder

    def test_backup_hashes_sqlite_and_restore_payload(self):
        folder = self.work('a', finished=True)
        archive, count = snapshot(self.root, self.root.parent / 'backups')
        self.assertGreater(count, 2)
        with zipfile.ZipFile(archive) as z:
            self.assertIsNone(z.testzip())
            self.assertEqual(z.read('data/' + folder.name + '/source.pdf'), b'original')
            manifest = json.loads(z.read('manifest.json'))
            self.assertEqual(len(manifest['sha256']), count)
            restored = self.root.parent / 'restored.sqlite3'
            restored.write_bytes(z.read('data/_access/accounts.sqlite3'))
            with closing(sqlite3.connect(restored)) as db:
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(db.execute("SELECT value FROM settings WHERE key='session_secret'").fetchone()[0], self.accounts.secret)
        with self.assertRaises(ValueError):
            snapshot(self.root, self.root / 'backups')

    def test_single_server_lock(self):
        with instance_lock(self.root):
            with self.assertRaises(RuntimeError):
                with instance_lock(self.root):
                    self.fail('second server acquired same lock')
        with instance_lock(self.root):
            pass

    def test_queue_recovery_skips_done_deleted_failed_and_other_subjects(self):
        waiting = self.work('a', finished=False, queue_state='queued')
        interrupted = self.work('b', finished=False, queue_state='processing')
        self.work('c', finished=True)
        self.work('d', finished=False, deleted_at='2026-09-26')
        self.work('e', finished=False, queue_state='failed')
        self.work('f', finished=False, subject='russian')
        with patch('webapp.enqueue') as submit:
            self.assertEqual(recover_queue(self.root), 2)
            self.assertEqual([call.args[0] for call in submit.call_args_list], [waiting, interrupted])

    def test_queue_marker_written_before_submission_and_deduplicates(self):
        folder = self.work('a', finished=False)
        def check(function, path):
            self.assertEqual(read_json(path / 'work.json')['queue_state'], 'queued')
        with patch('webapp.EXECUTOR.submit', side_effect=check) as submit:
            enqueue(folder)
            enqueue(folder)
            self.assertEqual(submit.call_count, 1)
        self.assertIn(folder.name, ACTIVE)

    def test_unreadable_pdf_records_failure_and_allows_explicit_retry(self):
        folder = self.work('a', finished=False)
        ACTIVE.add(folder.name)
        run_work(folder)
        self.assertNotIn(folder.name, ACTIVE)
        self.assertEqual(read_json(folder / 'work.json')['queue_state'], 'failed')
        with patch('webapp.EXECUTOR.submit'):
            enqueue(folder)
        self.assertEqual(read_json(folder / 'work.json')['queue_state'], 'queued')
