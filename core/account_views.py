"""Invitation-only accounts and school administration for the local pilot."""
from datetime import datetime
import time

from flask import abort, flash, g, redirect, render_template, request, session, url_for

from core.accounts import digest


def install_accounts(app, accounts, summaries):
    def start_session(user):
        session.clear()
        session['user_id'] = user['id']
        session['version'] = user['session_version']
        session.permanent = True

    def admin_only():
        if not g.user or g.user['role'] != 'admin':
            abort(403)

    def throttle(kind, username=''):
        buckets = [(kind + ':ip:' + digest(request.remote_addr or 'unknown'), 100)]
        if username:
            buckets.append((kind + ':name:' + digest(username.strip().lower()), 12))
        if not accounts.reserve_attempt(buckets):
            abort(429, 'Слишком много попыток. Повторите через 15 минут.')

    @app.before_request
    def authenticate():
        g.user = accounts.user(session.get('user_id')) if session.get('user_id') else None
        if g.user and (not accounts.enabled(g.user) or session.get('version') != g.user['session_version']):
            session.clear()
            g.user = None
        if request.endpoint not in ('static', 'login', 'join', 'setup') and not g.user:
            return redirect(url_for('login'))

    @app.context_processor
    def account_context():
        return {'current_user': getattr(g, 'user', None)}

    @app.template_filter('local_time')
    def local_time(value):
        return datetime.fromtimestamp(value).strftime('%d.%m.%Y %H:%M')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if g.user:
            return redirect(url_for('index'))
        if request.method == 'POST':
            username = request.form.get('username', '')[:80]
            throttle('login', username)
            password = request.form.get('password', '')
            user = accounts.login(username, password) if len(password) <= 128 else None
            if user:
                start_session(user)
                return redirect(url_for('admin_schools' if user['role'] == 'admin' else 'index'))
            flash('Не удалось войти. Проверьте логин и пароль или уточните доступ у координатора.')
        return render_template('login.html', needs_setup=not accounts.has_admin())

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'))

    def registration(setup_mode):
        if setup_mode and accounts.has_admin():
            abort(404)
        if not setup_mode and not accounts.has_admin():
            abort(404)
        if g.user:
            return redirect(url_for('index'))
        if request.method == 'POST':
            throttle('register')
            try:
                if request.form.get('password') != request.form.get('password_again'):
                    raise ValueError('Пароли не совпадают.')
                user = accounts.register(request.form.get('code', '').strip()[:100],
                                         request.form.get('username', ''), request.form.get('password', ''),
                                         request.form.get('name', ''), setup=setup_mode)
            except ValueError as exc:
                flash(str(exc))
            else:
                start_session(user)
                return redirect(url_for('admin_schools' if setup_mode else 'index'))
        return render_template('register.html', setup=setup_mode)

    @app.route('/setup', methods=['GET', 'POST'])
    def setup():
        return registration(True)

    @app.route('/join', methods=['GET', 'POST'])
    def join():
        return registration(False)

    @app.route('/admin/schools', methods=['GET', 'POST'])
    def admin_schools():
        admin_only()
        if request.method == 'POST':
            try:
                accounts.create_school(request.form.get('name', ''), request.form.get('expected', ''), g.user['id'])
            except ValueError as exc:
                flash(str(exc))
            else:
                flash('Школа добавлена. Теперь можно пригласить учителей.')
            return redirect(url_for('admin_schools'))
        data = accounts.lists()
        works = summaries()
        totals = {'schools': len(data['schools']), 'teachers': sum(u['role'] == 'teacher' for u in data['users']),
                  'pages': 0, 'reviewed': 0}
        for school in data['schools']:
            school_works = [w for w in works if w.get('school_id') == school['id']]
            school['pages'] = sum(w['count'] for w in school_works)
            school['reviewed'] = sum(w['reviewed'] for w in school_works)
            school['works'] = len(school_works)
            totals['pages'] += school['pages']
            totals['reviewed'] += school['reviewed']
        return render_template('schools.html', **data, totals=totals, now=time.time())

    @app.post('/admin/invite')
    def admin_invite():
        admin_only()
        school_id = request.form.get('school_id', '')
        try:
            code = accounts.invite(school_id, request.form.get('label', ''), g.user['id'])
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for('admin_schools'))
        school = next(s for s in accounts.lists()['schools'] if s['id'] == school_id)
        # The fragment is not transmitted in HTTP requests or access logs.
        link = app.config['PUBLIC_BASE_URL'].rstrip('/') + url_for('join') + '#' + code
        return render_template('invitation.html', code=code, link=link, school=school,
                               local_only=app.config['PUBLIC_BASE_URL'].startswith('http://127.0.0.1:'))

    @app.post('/admin/access')
    def admin_access():
        admin_only()
        try:
            accounts.change_access(request.form.get('kind', ''), request.form.get('target', ''),
                                   request.form.get('active') == '1', g.user['id'])
        except ValueError as exc:
            flash(str(exc))
        else:
            flash('Права доступа обновлены. Старые сеансы отключённых пользователей недействительны.')
        return redirect(url_for('admin_schools'))

    for status in (400, 403, 404, 409, 429):
        def error_page(error, status=status):
            messages = {403: 'Недостаточно прав для этого действия.', 404: 'Страница не найдена или недоступна.'}
            return render_template('error.html', message=messages.get(status, error.description)), status
        app.register_error_handler(status, error_page)
