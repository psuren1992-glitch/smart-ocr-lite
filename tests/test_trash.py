import tempfile
import unittest
import stat
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from webapp import ACTIVE, create_app, read_json, write_json
from core.trash import expires_at


class TrashTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.wid = 'b' * 32
        self.folder = self.root / self.wid
        (self.folder / '1').mkdir(parents=True)
        write_json(self.folder / 'work.json', {'id': self.wid, 'title': 'Keep my answers',
                   'class_name': '9B', 'count': 1, 'created': '2026-09-26', 'finished': True})
        write_json(self.folder / 'keys.json', {'1': {'1': '32'}})
        write_json(self.folder / '1/page.json', {'number': 1, 'status': 'ready', 'reviewed': True,
                   'name': 'Example', 'variant': '1', 'raw': {'1': '3,2'}, 'answers': {'1': '32'},
                   'notes': {}, 'corrections': []})
        (self.folder / 'source.pdf').write_bytes(b'preserve original source')
        (self.folder / '1/scan.png').write_bytes(b'preserve original scan')
        self.before = {p.relative_to(self.folder): p.read_bytes() for p in self.folder.rglob('*') if p.is_file()}
        self.app = create_app(self.root)
        self.app.testing = True
        self.client = self.app.test_client()
        accounts = self.app.extensions['accounts']
        admin = accounts.register((self.root / '_access/setup-code.txt').read_text(),
                                  'admin', 'test-password-long', 'Test Admin', setup=True)
        with self.client.session_transaction() as session:
            session['user_id'], session['version'] = admin['id'], admin['session_version']
        self.client.get('/')
        with self.client.session_transaction() as session:
            self.csrf = session['csrf']
        self.url = '/work/' + self.wid
        self.addCleanup(ACTIVE.discard, self.wid)

    def delete(self):
        return self.client.post(self.url + '/delete', data={'csrf': self.csrf, 'confirm': 'yes'})

    def test_get_and_unconfirmed_post_never_delete(self):
        self.assertEqual(self.client.get(self.url + '/delete').status_code, 200)
        self.client.post(self.url + '/delete', data={'csrf': self.csrf})
        self.assertNotIn('deleted_at', read_json(self.folder / 'work.json'))

    def test_delete_hides_work_and_blocks_old_links(self):
        self.assertEqual(self.delete().status_code, 302)
        self.assertIn('deleted_at', read_json(self.folder / 'work.json'))
        home = self.client.get('/').data.decode()
        self.assertNotIn('Keep my answers', home)
        self.assertIn('Keep my answers', self.client.get('/trash').data.decode())
        for suffix in ['', '/page/1', '/key', '/export', '/image/1/scan.png', '/delete']:
            self.assertEqual(self.client.get(self.url + suffix).status_code, 404, suffix)
        with patch('webapp.enqueue') as queued:
            self.assertEqual(self.client.post(self.url + '/resume', data={'csrf': self.csrf}).status_code, 404)
            queued.assert_not_called()
        for suffix in ['/page/1', '/key']:
            self.assertEqual(self.client.post(self.url + suffix, data={'csrf': self.csrf}).status_code, 404)

    def test_restore_preserves_all_source_and_review_data(self):
        self.delete()
        for name, original in self.before.items():
            if str(name) != 'work.json':
                self.assertEqual((self.folder / name).read_bytes(), original)
        response = self.client.post(self.url + '/restore', data={'csrf': self.csrf})
        self.assertEqual(response.status_code, 302)
        for name, original in self.before.items():
            self.assertEqual((self.folder / name).read_bytes(), original)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertNotIn('Keep my answers', self.client.get('/trash').data.decode())

    def test_processing_and_queued_work_cannot_be_deleted(self):
        ACTIVE.add(self.wid)
        self.assertEqual(self.client.get(self.url + '/delete').status_code, 409)
        self.assertEqual(self.delete().status_code, 409)
        self.assertNotIn('deleted_at', read_json(self.folder / 'work.json'))

    def test_delete_and_restore_require_csrf(self):
        self.assertEqual(self.client.post(self.url + '/delete', data={'confirm': 'yes'}).status_code, 400)
        self.delete()
        self.assertEqual(self.client.post(self.url + '/restore').status_code, 400)
        self.assertEqual(self.client.get(self.url + '/restore').status_code, 405)
        self.assertIn('deleted_at', read_json(self.folder / 'work.json'))

    def test_unknown_and_live_restore_rejected(self):
        self.assertEqual(self.client.get('/work/not-valid/delete').status_code, 404)
        self.assertEqual(self.client.post(self.url + '/restore', data={'csrf': self.csrf}).status_code, 404)

    def test_title_is_escaped_on_confirmation_and_trash(self):
        meta = read_json(self.folder / 'work.json')
        meta['title'] = '<script>alert(1)</script>'
        write_json(self.folder / 'work.json', meta)
        self.assertNotIn(meta['title'], self.client.get(self.url + '/delete').data.decode())
        self.delete()
        self.assertNotIn(meta['title'], self.client.get('/trash').data.decode())

    def mark_deleted(self, value):
        meta = read_json(self.folder / 'work.json')
        meta['deleted_at'] = value
        write_json(self.folder / 'work.json', meta)

    def test_purge_exactly_after_72_hours(self):
        deleted = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
        self.mark_deleted(deleted.isoformat())
        cleaner = self.app.extensions['trash_cleaner']
        self.assertEqual(cleaner.sweep(deleted + timedelta(hours=72, microseconds=-1)), [])
        self.assertTrue((self.folder / 'source.pdf').exists())
        self.assertEqual(cleaner.sweep(deleted + timedelta(hours=72)), [self.wid])
        self.assertFalse(self.folder.exists())
        self.assertTrue((self.root / '_access/accounts.sqlite3').exists())
        self.assertEqual(cleaner.sweep(deleted + timedelta(days=4)), [])

    def test_live_restored_active_and_invalid_dates_never_purged(self):
        cleaner = self.app.extensions['trash_cleaner']
        future = datetime.now(timezone.utc) + timedelta(days=10)
        self.assertEqual(cleaner.sweep(future), [])
        for value in ['not-a-date', 100, None, '']:
            self.mark_deleted(value)
            self.assertEqual(cleaner.sweep(future), [])
        self.delete()
        ACTIVE.add(self.wid)
        self.assertEqual(cleaner.sweep(future), [])
        ACTIVE.discard(self.wid)
        self.client.post(self.url + '/restore', data={'csrf': self.csrf})
        self.assertEqual(cleaner.sweep(future), [])
        self.assertTrue(self.folder.exists())

    def test_expired_work_cannot_be_restored(self):
        self.mark_deleted((datetime.now(timezone.utc) - timedelta(days=4)).isoformat())
        response = self.client.post(self.url + '/restore', data={'csrf': self.csrf})
        self.assertEqual(response.status_code, 409)
        self.assertIn('deleted_at', read_json(self.folder / 'work.json'))

    def test_locked_file_retried_with_metadata_preserved(self):
        self.mark_deleted((datetime.now(timezone.utc) - timedelta(days=4)).isoformat())
        cleaner = self.app.extensions['trash_cleaner']
        with patch('core.trash.shutil.rmtree', side_effect=PermissionError('locked')):
            self.assertEqual(cleaner.sweep(), [])
        self.assertTrue((self.folder / 'work.json').exists())
        self.assertEqual(cleaner.sweep(), [self.wid])

    def test_restart_sweeps_and_periodic_worker_stops(self):
        self.mark_deleted((datetime.now(timezone.utc) - timedelta(days=4)).isoformat())
        second = create_app(self.root)
        cleaner = second.extensions['trash_cleaner']
        cleaner.start()
        try:
            self.assertFalse(self.folder.exists())
            self.assertTrue(cleaner.thread.is_alive())
        finally:
            cleaner.stop()
        self.assertFalse(cleaner.thread.is_alive())

    def test_legacy_local_timestamp_and_offsets(self):
        local = datetime(2026, 9, 26, 13, 59, 7)
        self.assertEqual(expires_at({'deleted_at': local.isoformat()}), local.astimezone(timezone.utc) + timedelta(days=3))
        self.assertEqual(expires_at({'deleted_at': '2026-09-26T13:00:00+03:00'}),
                         datetime(2026, 9, 29, 10, tzinfo=timezone.utc))

    def test_id_mismatch_and_links_not_followed(self):
        self.mark_deleted((datetime.now(timezone.utc) - timedelta(days=4)).isoformat())
        meta = read_json(self.folder / 'work.json')
        meta['id'] = 'a' * 32
        write_json(self.folder / 'work.json', meta)
        cleaner = self.app.extensions['trash_cleaner']
        self.assertEqual(cleaner.sweep(), [])
        meta['id'] = self.wid
        write_json(self.folder / 'work.json', meta)
        with tempfile.TemporaryDirectory() as external:
            sentinel = Path(external) / 'keep.txt'
            sentinel.write_text('keep')
            link = self.folder / 'linked'
            try:
                link.symlink_to(external, target_is_directory=True)
            except OSError:
                self.skipTest('Creating symlinks requires Windows developer mode')
            try:
                self.assertEqual(cleaner.sweep(), [])
                self.assertEqual(sentinel.read_text(), 'keep')
                self.assertTrue((self.folder / 'source.pdf').exists())
            finally:
                link.unlink()

    def test_windows_reparse_point_is_rejected_before_traversal(self):
        self.mark_deleted((datetime.now(timezone.utc) - timedelta(days=4)).isoformat())
        original_stat = Path.lstat
        def linked_stat(path):
            if path == self.folder:
                return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
            return original_stat(path)
        with patch.object(Path, 'lstat', linked_stat):
            self.assertEqual(self.app.extensions['trash_cleaner'].sweep(), [])
        self.assertTrue((self.folder / 'source.pdf').exists())
