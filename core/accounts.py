"""Local account database. Raw invitation codes and passwords are never stored here."""
from contextlib import contextmanager
import hashlib
import re
import secrets
import sqlite3
import time
import uuid

from werkzeug.security import check_password_hash, generate_password_hash


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def credentials(username, password, name):
    username = username.strip().lower()
    name = name.strip()
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.@-]{2,79}', username):
        raise ValueError('Логин: 3–80 символов, латинские буквы, цифры, точка, @, дефис или подчёркивание.')
    if not 12 <= len(password) <= 128:
        raise ValueError('Пароль должен содержать от 12 до 128 символов.')
    if not 2 <= len(name) <= 100:
        raise ValueError('Укажите имя длиной от 2 до 100 символов.')
    return username, generate_password_hash(password), name


class Accounts:
    def __init__(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        self.directory = directory
        self.path = directory / 'accounts.sqlite3'
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS schools (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, expected INTEGER,
                    active INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
                    name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','teacher')),
                    school_id TEXT REFERENCES schools(id), active INTEGER NOT NULL DEFAULT 1,
                    session_version INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL,
                    CHECK((role='admin' AND school_id IS NULL) OR (role='teacher' AND school_id IS NOT NULL)));
                CREATE TABLE IF NOT EXISTS invitations (
                    id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, school_id TEXT NOT NULL REFERENCES schools(id),
                    label TEXT NOT NULL, expires REAL NOT NULL, used_by TEXT REFERENCES users(id),
                    revoked INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts (
                    bucket TEXT PRIMARY KEY, count INTEGER NOT NULL, reset_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY, at REAL NOT NULL, actor TEXT, action TEXT NOT NULL, target TEXT NOT NULL);
            ''')
            db.execute('INSERT OR IGNORE INTO settings VALUES (?,?)', ('session_secret', secrets.token_hex(32)))
            self.secret = db.execute("SELECT value FROM settings WHERE key='session_secret'").fetchone()[0]
            if not db.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
                code_file = directory / 'setup-code.txt'
                if not code_file.exists():
                    with code_file.open('x', encoding='ascii') as stream:
                        stream.write(secrets.token_urlsafe(32))
                code = code_file.read_text(encoding='ascii').strip()
                db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('setup_hash', digest(code)))
        self.dummy_hash = generate_password_hash(secrets.token_hex(16))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def audit(db, actor, action, target):
        db.execute('INSERT INTO audit(at,actor,action,target) VALUES (?,?,?,?)',
                   (time.time(), actor, action, target))

    def has_admin(self):
        with self.connect() as db:
            return bool(db.execute("SELECT 1 FROM users WHERE role='admin'").fetchone())

    def user(self, uid):
        with self.connect() as db:
            row = db.execute('''SELECT u.*, s.name school_name, s.active school_active FROM users u
                LEFT JOIN schools s ON s.id=u.school_id WHERE u.id=?''', (uid,)).fetchone()
            return dict(row) if row else None

    @staticmethod
    def enabled(user):
        return bool(user and user['active'] and (user['role'] == 'admin' or user['school_active']))

    def login(self, username, password):
        with self.connect() as db:
            row = db.execute('SELECT id,password_hash FROM users WHERE username=?', (username.strip().lower(),)).fetchone()
        valid = check_password_hash(row['password_hash'] if row else self.dummy_hash, password)
        user = self.user(row['id']) if row else None
        return user if valid and self.enabled(user) else None

    def reserve_attempt(self, buckets):
        now = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM attempts WHERE reset_at<=?', (now,))
            for bucket, limit in buckets:
                row = db.execute('SELECT count FROM attempts WHERE bucket=?', (bucket,)).fetchone()
                if row and row['count'] >= limit:
                    return False
            for bucket, _ in buckets:
                db.execute('''INSERT INTO attempts VALUES (?,1,?) ON CONFLICT(bucket)
                    DO UPDATE SET count=count+1''', (bucket, now + 900))
        return True

    def register(self, code, username, password, name, setup=False):
        username, password_hash, name = credentials(username, password, name)
        uid, now = uuid.uuid4().hex, time.time()
        try:
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if setup:
                    saved = db.execute("SELECT value FROM settings WHERE key='setup_hash'").fetchone()
                    if (db.execute("SELECT 1 FROM users WHERE role='admin'").fetchone() or not saved
                            or not secrets.compare_digest(saved[0], digest(code))):
                        raise ValueError('Код настройки недействителен или уже использован.')
                    school_id = None
                else:
                    invite = db.execute('''SELECT i.* FROM invitations i JOIN schools s ON s.id=i.school_id
                        WHERE i.token_hash=? AND i.used_by IS NULL AND i.revoked=0 AND i.expires>? AND s.active=1''',
                        (digest(code), now)).fetchone()
                    if not invite:
                        raise ValueError('Приглашение недействительно, отозвано или срок действия истёк.')
                    school_id = invite['school_id']
                db.execute('''INSERT INTO users(id,username,password_hash,name,role,school_id,created)
                    VALUES (?,?,?,?,?,?,?)''', (uid, username, password_hash, name,
                                               'admin' if setup else 'teacher', school_id, now))
                if setup:
                    db.execute("DELETE FROM settings WHERE key='setup_hash'")
                else:
                    db.execute('UPDATE invitations SET used_by=? WHERE id=?', (uid, invite['id']))
                self.audit(db, uid, 'admin_created' if setup else 'invitation_accepted', uid)
        except sqlite3.IntegrityError as exc:
            raise ValueError('Этот логин уже занят. Выберите другой.') from exc
        if setup:
            (self.directory / 'setup-code.txt').unlink(missing_ok=True)
        return self.user(uid)

    def create_school(self, name, expected, actor):
        name = name.strip()
        if not 2 <= len(name) <= 160:
            raise ValueError('Название школы: от 2 до 160 символов.')
        if expected.strip():
            try:
                expected = int(expected)
            except ValueError as exc:
                raise ValueError('Ожидаемое число бланков должно быть целым числом.') from exc
            if not 0 <= expected <= 100000:
                raise ValueError('Укажите ожидаемое число бланков от 0 до 100000 или оставьте поле пустым.')
        else:
            expected = None
        sid = uuid.uuid4().hex
        with self.connect() as db:
            db.execute('INSERT INTO schools(id,name,expected,created) VALUES (?,?,?,?)', (sid, name, expected, time.time()))
            self.audit(db, actor, 'school_created', sid)
        return sid

    def invite(self, school_id, label, actor):
        code, iid = secrets.token_urlsafe(32), uuid.uuid4().hex
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM schools WHERE id=? AND active=1', (school_id,)).fetchone():
                raise ValueError('Школа не найдена или её доступ приостановлен.')
            db.execute('INSERT INTO invitations(id,token_hash,school_id,label,expires,created) VALUES (?,?,?,?,?,?)',
                       (iid, digest(code), school_id, label.strip()[:100], time.time() + 48*3600, time.time()))
            self.audit(db, actor, 'invitation_created', iid)
        return code

    def lists(self):
        with self.connect() as db:
            return {name: [dict(r) for r in db.execute(query)] for name, query in {
                'schools': 'SELECT * FROM schools ORDER BY created',
                'users': '''SELECT u.id,u.username,u.name,u.role,u.school_id,u.active,s.name school_name
                    FROM users u LEFT JOIN schools s ON s.id=u.school_id ORDER BY u.created''',
                'invitations': '''SELECT i.id,i.label,i.school_id,i.expires,i.used_by,i.revoked,s.name school_name
                    FROM invitations i JOIN schools s ON s.id=i.school_id ORDER BY i.created DESC'''
            }.items()}

    def change_access(self, kind, target, active, actor):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if kind == 'school':
                found = db.execute('UPDATE schools SET active=? WHERE id=?', (active, target)).rowcount
                db.execute('UPDATE users SET session_version=session_version+1 WHERE school_id=?', (target,))
            elif kind == 'user':
                found = db.execute("UPDATE users SET active=?,session_version=session_version+1 WHERE id=? AND role='teacher'",
                                   (active, target)).rowcount
            elif kind == 'invitation':
                found = db.execute('UPDATE invitations SET revoked=1 WHERE id=? AND used_by IS NULL', (target,)).rowcount
            else:
                raise ValueError('Неизвестное действие.')
            if not found:
                raise ValueError('Запись не найдена или действие недоступно.')
            self.audit(db, actor, kind + ('_enabled' if active else '_disabled'), target)


def can_access(user, meta):
    if not user:
        return False
    if user['role'] == 'admin':
        return True
    return bool(meta.get('school_id') and meta.get('owner_id') and
                meta['school_id'] == user['school_id'] and meta['owner_id'] == user['id'])
