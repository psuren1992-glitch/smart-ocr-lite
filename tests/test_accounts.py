import io
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import fitz

from core.accounts import Accounts, can_access
from webapp import create_app, read_json, write_json


class AccountsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = create_app(self.root)
        self.app.testing = True
        self.accounts = self.app.extensions['accounts']
        self.admin = self.accounts.register((self.root / '_access/setup-code.txt').read_text(),
                                            'admin', 'test-password-long', 'Admin', setup=True)
        self.school = self.accounts.create_school('School One', '10', self.admin['id'])
        self.other_school = self.accounts.create_school('School Two', '100', self.admin['id'])
        self.teacher = self.teacher_for(self.school, 'teacher1')
        self.peer = self.teacher_for(self.school, 'teacher2')
        self.other = self.teacher_for(self.other_school, 'teacher3')

    def teacher_for(self, school, login):
        code = self.accounts.invite(school, 'test', self.admin['id'])
        return self.accounts.register(code, login, 'test-password-long', login)

    def client_for(self, user=None):
        client = self.app.test_client()
        if user:
            with client.session_transaction() as s:
                s['user_id'], s['version'] = user['id'], user['session_version']
        client.get('/login')
        return client

    def post(self, client, url, **data):
        with client.session_transaction() as s:
            token = s.get('csrf', '')
        return client.post(url, data={'csrf': token, **data})

    def make_work(self, user=None):
        wid = 'c' * 32
        folder = self.root / wid
        (folder / '1').mkdir(parents=True)
        meta = {'id': wid, 'title': 'PrivateWork', 'count': 1, 'class_name': '9B',
                'created': '2026-09-27', 'finished': True}
        if user:
            meta.update(owner_id=user['id'], school_id=user['school_id'])
        write_json(folder / 'work.json', meta)
        write_json(folder / 'keys.json', {})
        write_json(folder / '1/page.json', {'number': 1, 'status': 'ready', 'reviewed': True,
                    'answers': {'1': '32'}, 'raw': {'1': '3,2'}, 'notes': {}, 'corrections': [],
                    'variant': '1', 'name': 'Student'})
        (folder / '1/scan.png').write_bytes(b'private scan')
        return folder, '/work/' + wid

    def test_all_work_endpoints_isolate_teacher_and_school(self):
        folder, url = self.make_work(self.teacher)
        before = (folder / '1/page.json').read_bytes()
        for outsider in [self.peer, self.other]:
            client = self.client_for(outsider)
            for suffix in ['', '/page/1', '/key', '/export', '/image/1/scan.png', '/delete']:
                self.assertEqual(client.get(url + suffix).status_code, 404, suffix)
            for suffix in ['/page/1', '/key', '/resume', '/delete', '/restore']:
                self.assertEqual(self.post(client, url + suffix, confirm='yes').status_code, 403 if suffix == '/restore' else 404, suffix)
            self.assertNotIn('PrivateWork', client.get('/').data.decode())
            self.assertNotIn('PrivateWork', client.get('/trash').data.decode())
        self.assertEqual((folder / '1/page.json').read_bytes(), before)
        self.assertEqual(self.client_for(self.admin).get(url).status_code, 200)
        self.assertEqual(self.client_for(self.teacher).get(url).status_code, 200)

    def test_legacy_work_is_admin_only(self):
        _, url = self.make_work()
        self.assertEqual(self.client_for(self.teacher).get(url).status_code, 404)
        self.assertEqual(self.client_for(self.admin).get(url).status_code, 200)

    def test_anonymous_cannot_see_student_data(self):
        _, url = self.make_work(self.teacher)
        client = self.client_for()
        for path in ['/', '/trash', '/admin/schools', url, url + '/export', url + '/image/1/scan.png']:
            result = client.get(path)
            self.assertEqual(result.status_code, 302)
            self.assertNotIn(b'Student', result.data)
        self.assertEqual(client.get('/setup').status_code, 404)

    def test_https_session_and_host_restriction(self):
        self.app.config.update(SESSION_COOKIE_SECURE=True,
                               TRUSTED_HOSTS=['203.0.113.10'])
        client = self.app.test_client()
        origin = 'https://203.0.113.10'
        response = client.get('/login', base_url=origin)
        self.assertEqual(response.status_code, 200)
        cookie = response.headers['Set-Cookie']
        for attribute in ('Secure', 'HttpOnly', 'SameSite=Strict'):
            self.assertIn(attribute, cookie)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(client.get('/login', base_url='https://untrusted.example').status_code, 400)
        self.assertEqual(client.post('/login', base_url=origin,
                                    data={'username': 'admin', 'password': 'test-password-long'}).status_code, 400)
        with client.session_transaction(base_url=origin) as session:
            token = session['csrf']
        response = client.post('/login', base_url=origin,
                               data={'csrf': token, 'username': 'admin', 'password': 'test-password-long'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(client.get('/admin/schools', base_url=origin).status_code, 200)

    def test_teacher_cannot_admin_or_self_assign_school(self):
        client = self.client_for(self.teacher)
        self.assertNotIn(b'name="exam"', client.get('/').data)
        self.assertNotIn(b'name="subject"', client.get('/').data)
        self.assertEqual(self.post(client, '/upload', exam='ege', subject='russian').status_code, 403)
        self.assertEqual(client.get('/admin/schools').status_code, 403)
        for path in ['/admin/schools', '/admin/invite', '/admin/access']:
            self.assertEqual(self.post(client, path).status_code, 403)
        with fitz.open() as doc:
            doc.new_page()
            content = doc.tobytes()
        with patch('webapp.enqueue'):
            result = self.post(client, '/upload', school_id=self.other_school, owner_id=self.other['id'],
                               pdf=(io.BytesIO(content), 'scan.pdf'))
        wid = result.location.rsplit('/', 1)[-1]
        meta = read_json(self.root / wid / 'work.json')
        self.assertEqual(meta['school_id'], self.school)
        self.assertEqual(meta['owner_id'], self.teacher['id'])

    def test_invitation_single_use_expiry_revocation_and_disabled_school(self):
        code = self.accounts.invite(self.school, 'single', self.admin['id'])
        user = self.accounts.register(code, 'single', 'test-password-long', 'Single')
        self.assertEqual(user['school_id'], self.school)
        with self.assertRaises(ValueError):
            self.accounts.register(code, 'again', 'test-password-long', 'Again')
        code = self.accounts.invite(self.school, 'expired', self.admin['id'])
        with self.accounts.connect() as db:
            db.execute('UPDATE invitations SET expires=? WHERE label=?', (time.time() - 1, 'expired'))
        with self.assertRaises(ValueError):
            self.accounts.register(code, 'expired', 'test-password-long', 'Expired')
        code = self.accounts.invite(self.school, 'revoked', self.admin['id'])
        invite = next(i for i in self.accounts.lists()['invitations'] if i['label'] == 'revoked')
        self.accounts.change_access('invitation', invite['id'], False, self.admin['id'])
        with self.assertRaises(ValueError):
            self.accounts.register(code, 'revoked', 'test-password-long', 'Revoked')
        code = self.accounts.invite(self.school, 'disabled', self.admin['id'])
        self.accounts.change_access('school', self.school, False, self.admin['id'])
        with self.assertRaises(ValueError):
            self.accounts.register(code, 'disabled', 'test-password-long', 'Disabled')

    def test_concurrent_invite_redemption_only_one_wins(self):
        code = self.accounts.invite(self.school, 'race', self.admin['id'])
        def redeem(n):
            try:
                self.accounts.register(code, 'race' + str(n), 'test-password-long', 'Race')
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(redeem, [1, 2])), 1)

    def test_disabling_user_or_school_invalidates_existing_sessions(self):
        client = self.client_for(self.teacher)
        self.accounts.change_access('user', self.teacher['id'], False, self.admin['id'])
        self.assertEqual(client.get('/').status_code, 302)
        self.accounts.change_access('user', self.teacher['id'], True, self.admin['id'])
        self.assertEqual(client.get('/').status_code, 302)
        client = self.client_for(self.accounts.user(self.teacher['id']))
        self.accounts.change_access('school', self.school, False, self.admin['id'])
        self.assertEqual(client.get('/').status_code, 302)
        self.assertIsNone(self.accounts.login('teacher1', 'test-password-long'))

    def test_login_logout_csrf_and_session_rotation(self):
        client = self.client_for()
        with client.session_transaction() as s:
            previous = s['csrf']
        self.assertEqual(client.post('/login', data={'username': 'admin', 'password': 'test-password-long'}).status_code, 400)
        result = self.post(client, '/login', username='admin', password='test-password-long')
        self.assertEqual(result.status_code, 302)
        client.get('/')
        with client.session_transaction() as s:
            self.assertNotEqual(s['csrf'], previous)
        self.assertEqual(self.post(client, '/logout').status_code, 302)
        self.assertEqual(client.get('/').status_code, 302)

    def test_persistent_secret_and_no_raw_password_or_invitation_in_db(self):
        code = self.accounts.invite(self.school, 'private', self.admin['id'])
        other_store = Accounts(self.root / '_access')
        self.assertEqual(other_store.secret, self.accounts.secret)
        content = self.accounts.path.read_bytes()
        self.assertNotIn(code.encode(), content)
        self.assertNotIn(b'test-password-long', content)

    def test_throttle_and_disabled_admin_bootstrap(self):
        for _ in range(3):
            self.assertTrue(self.accounts.reserve_attempt([('test', 3)]))
        self.assertFalse(self.accounts.reserve_attempt([('test', 3)]))
        with self.assertRaises(ValueError):
            self.accounts.register('anything', 'secondadmin', 'test-password-long', 'Admin', setup=True)

    def test_thirty_schools_and_variable_expected_counts(self):
        for n in range(28):
            self.accounts.create_school(f'Extra {n}', '' if n % 2 else '250', self.admin['id'])
        result = self.client_for(self.admin).get('/admin/schools')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(self.accounts.lists()['schools']), 30)
        self.assertIn(b'250', result.data)
        self.assertIsNone(next(s for s in self.accounts.lists()['schools'] if s['name'] == 'Extra 1')['expected'])

    def test_valid_invite_web_flow_and_school_cannot_be_overridden(self):
        code = self.accounts.invite(self.school, 'web', self.admin['id'])
        client = self.client_for()
        result = self.post(client, '/join', code=code, username='webteacher', name='Web Teacher',
                           password='test-password-long', password_again='test-password-long',
                           role='admin', school_id=self.other_school)
        self.assertEqual(result.status_code, 302)
        with client.session_transaction() as s:
            user = self.accounts.user(s['user_id'])
        self.assertEqual(user['school_id'], self.school)
        self.assertEqual(user['role'], 'teacher')
        self.assertFalse(can_access(user, {'school_id': self.other_school, 'owner_id': user['id']}))

    def test_admin_render_and_invite_uses_configured_origin_not_host_header(self):
        client = self.client_for(self.admin)
        self.assertEqual(client.get('/admin/schools').status_code, 200)
        with client.session_transaction() as s:
            token = s['csrf']
        client.set_cookie('session', client.get_cookie('session').value, domain='attacker.invalid')
        response = client.post('/admin/invite', data={'csrf': token, 'school_id': self.school},
                               headers={'Host': 'attacker.invalid'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'attacker.invalid', response.data)
        self.assertIn(b'http://127.0.0.1:5001/join#', response.data)

    def test_first_admin_setup_web_flow_is_one_time(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory))
            app.testing = True
            client = app.test_client()
            code_file = Path(directory) / '_access/setup-code.txt'
            code = code_file.read_text()
            self.assertEqual(client.get('/setup').status_code, 200)
            self.assertEqual(client.get('/join').status_code, 404)
            fields = dict(username='coordinator', name='Coordinator', password='test-password-long',
                          password_again='test-password-long')
            self.assertEqual(self.post(client, '/setup', code='wrong', **fields).status_code, 200)
            self.assertFalse(app.extensions['accounts'].has_admin())
            self.assertEqual(self.post(client, '/setup', code=code, **fields).status_code, 302)
            self.assertFalse(code_file.exists())
            self.assertEqual(client.get('/admin/schools').status_code, 200)
            self.assertEqual(client.get('/setup').status_code, 404)

    def test_trash_preserves_ownership_and_security_headers(self):
        _, url = self.make_work(self.teacher)
        owner = self.client_for(self.teacher)
        self.assertEqual(self.post(owner, url + '/delete', confirm='yes').status_code, 302)
        self.assertEqual(owner.get('/trash').status_code, 403)
        self.assertNotIn(b'href="/trash"', owner.get('/').data)
        admin = self.client_for(self.admin)
        response = admin.get('/trash')
        self.assertIn(b'PrivateWork', response.data)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
        outsider = self.client_for(self.other)
        self.assertNotIn(b'PrivateWork', outsider.get('/trash').data)
        self.assertEqual(self.post(outsider, url + '/restore').status_code, 403)
        self.assertEqual(self.post(owner, url + '/restore').status_code, 403)
        self.assertEqual(self.post(admin, url + '/restore').status_code, 302)
        self.assertEqual(owner.get(url).status_code, 200)


if __name__ == '__main__':
    unittest.main()
