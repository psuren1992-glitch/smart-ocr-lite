"""Math 9: upload a PDF, check each answer against its crop, export results."""
import csv
import io
import json
import logging
import os
import re
import secrets
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import fitz
import numpy as np
from flask import Flask, abort, flash, g, redirect, render_template, request, send_file, session, url_for
from werkzeug.exceptions import SecurityError

from core.answer_key import normalize_answer
from core.math_form import form_config, recognize_page, write_image
from core.accounts import Accounts, can_access
from core.account_views import install_accounts
from core.trash import TrashCleaner, expires_at
from core.work_profiles import EXAMS, SUBJECTS, profile_for

ROOT = Path(__file__).resolve().parent
TASKS = tuple(str(i) for i in range(1, 20))
LOCK = threading.RLock()
EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix='math-ocr')
ACTIVE = set()
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, data):
    with LOCK:
        temp = path.with_suffix('.tmp')
        with temp.open('w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(path)


def grade(page, keys):
    key = keys.get(page.get('variant', '1'), {})
    if not key or not page.get('reviewed'):
        return None
    correct = sum(bool(page['answers'].get(t)) and normalize_answer(page['answers'][t]) in
                  [normalize_answer(x) for x in value.split('|')] for t, value in key.items() if value)
    return {'correct': correct, 'total': sum(bool(v) for v in key.values())}


def run_work(folder):
    try:
        meta = read_json(folder / 'work.json')
        if meta.get('deleted_at') or not profile_for(meta)['supported']:
            return
        meta['queue_state'] = 'processing'
        write_json(folder / 'work.json', meta)
        with fitz.open(folder / 'source.pdf') as doc:
            for number in range(1, len(doc)+1):
                page_dir = folder / str(number)
                page_dir.mkdir(exist_ok=True)
                path = page_dir / 'page.json'
                if path.exists() and read_json(path).get('status') in ('ready', 'error'):
                    continue
                write_json(path, {'number': number, 'status': 'processing'})
                try:
                    pix = doc[number-1].get_pixmap(dpi=200, colorspace=fitz.csRGB, alpha=False)
                    image = cv2.cvtColor(np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3), cv2.COLOR_RGB2BGR)
                    write_image(page_dir / 'scan.png', image)
                    result = recognize_page(image, page_dir)
                    result['number'] = number
                    write_json(path, result)
                except Exception:
                    logger.exception('Page %s failed', number)
                    write_json(path, {'number': number, 'status': 'error', 'name': '', 'variant': '1',
                                      'answers': {t: '' for t in TASKS}, 'raw': {}, 'reviewed': False,
                                      'corrections': [], 'notes': {},
                                      'error': 'Распознавание не завершено. Сверьте все ответы по скану вручную.'})
        with LOCK:
            meta = read_json(folder / 'work.json')
            meta.update(finished=True, queue_state='done')
            meta.pop('processing_error', None)
            write_json(folder / 'work.json', meta)
    except Exception:
        logger.exception('Work processing failed')
        try:
            with LOCK:
                meta = read_json(folder / 'work.json')
                meta.update(queue_state='failed', processing_error=True)
                write_json(folder / 'work.json', meta)
        except (OSError, ValueError):
            logger.error('Could not persist failure state')
    finally:
        with LOCK:
            ACTIVE.discard(folder.name)


def enqueue(folder):
    with LOCK:
        meta = read_json(folder / 'work.json')
        if meta.get('deleted_at') or not profile_for(meta)['supported']:
            return
        if folder.name in ACTIVE:
            return
        meta.update(queue_state='queued', finished=False)
        meta.pop('processing_error', None)
        write_json(folder / 'work.json', meta)
        ACTIVE.add(folder.name)
        try:
            EXECUTOR.submit(run_work, folder)
        except RuntimeError:
            ACTIVE.discard(folder.name)
            raise


def recover_queue(data_root):
    """Rebuild the one-worker queue from durable work metadata after restart."""
    pending = []
    for path in Path(data_root).glob('*/work.json'):
        if not re.fullmatch(r'[a-f0-9]{32}', path.parent.name):
            continue
        try:
            meta = read_json(path)
            if (not meta.get('finished') and not meta.get('deleted_at')
                    and meta.get('queue_state') != 'failed' and profile_for(meta)['supported']):
                pending.append((meta.get('created', ''), path.parent))
        except (OSError, ValueError):
            logger.warning('Cannot recover invalid work metadata')
    for _, folder in sorted(pending):
        enqueue(folder)
    return len(pending)


def create_app(data_dir=None):
    app = Flask(__name__, template_folder='ui/templates', static_folder='ui/static')
    data_root = Path(data_dir or ROOT / 'data/math9')
    data_root.mkdir(parents=True, exist_ok=True)
    accounts = Accounts(data_root / '_access')
    app.extensions['accounts'] = accounts
    app.extensions['trash_cleaner'] = TrashCleaner(data_root, LOCK, ACTIVE)
    app.config.update(DATA_ROOT=data_root, MAX_CONTENT_LENGTH=80*1024*1024,
                      SECRET_KEY=os.environ.get('MATH9_SECRET') or accounts.secret,
                      SESSION_COOKIE_SAMESITE='Strict', SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SECURE=os.environ.get('MATH9_HTTPS') == '1',
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
                      PUBLIC_BASE_URL=os.environ.get('MATH9_PUBLIC_URL', 'http://127.0.0.1:5001'),
                      MAX_FORM_MEMORY_SIZE=256*1024, MAX_FORM_PARTS=100)

    def folder_for(work_id, include_deleted=False):
        if not re.fullmatch(r'[a-f0-9]{32}', work_id):
            abort(404)
        folder = data_root / work_id
        if not (folder / 'work.json').is_file():
            abort(404)
        meta = read_json(folder / 'work.json')
        if not can_access(g.user, meta):
            abort(404)
        if not include_deleted and meta.get('deleted_at'):
            abort(404)
        return folder

    def details(folder):
        meta = read_json(folder / 'work.json')
        meta['profile'] = profile_for(meta)
        pages = []
        keys = read_json(folder / 'keys.json') if (folder / 'keys.json').exists() else {}
        for number in range(1, meta['count']+1):
            path = folder / str(number) / 'page.json'
            page = read_json(path) if path.exists() else {'number': number, 'status': 'waiting'}
            page['score'] = grade(page, keys)
            pages.append(page)
        meta['done'] = sum(p['status'] in ('ready', 'error') for p in pages)
        meta['reviewed'] = sum(bool(p.get('reviewed')) for p in pages)
        meta['active'] = folder.name in ACTIVE
        return meta, pages, keys

    @app.before_request
    def csrf_protection():
        # Host rejection happens before routing; URL-based templates cannot run yet.
        if isinstance(request.routing_exception, SecurityError):
            return 'Invalid Host', 400
        session.setdefault('csrf', secrets.token_hex(24))
        if request.method == 'POST' and not secrets.compare_digest(session['csrf'].encode(), request.form.get('csrf', '').encode()):
            abort(400, 'Обновите страницу и повторите действие.')

    @app.context_processor
    def common():
        return {'tasks': TASKS, 'csrf': session.get('csrf', ''), 'exams': EXAMS, 'subjects': SUBJECTS}

    @app.errorhandler(413)
    def too_large(error):
        return render_template('error.html', message='PDF слишком большой. Максимум 80 МБ.'), 413

    @app.get('/')
    def index():
        works = []
        trash_count = 0
        for path in data_root.glob('*/work.json'):
            try:
                meta = read_json(path)
                if not can_access(g.user, meta):
                    continue
                if meta.get('deleted_at'):
                    trash_count += 1
                    continue
                works.append(details(path.parent)[0])
            except (ValueError, OSError):
                logger.exception('Invalid work metadata')
        works.sort(key=lambda w: w['created'], reverse=True)
        schools = accounts.lists()['schools'] if g.user['role'] == 'admin' else []
        school_filter = request.args.get('school', '')
        if school_filter and g.user['role'] == 'admin':
            works = [w for w in works if w.get('school_id') == school_filter]
        school_names = {s['id']: s['name'] for s in schools}
        for work in works:
            work['school_name'] = school_names.get(work.get('school_id'), 'Личная работа администратора')
        return render_template('index.html', works=works, trash_count=trash_count, schools=schools, school_filter=school_filter)

    @app.get('/trash')
    def trash():
        if g.user['role'] != 'admin':
            abort(403)
        works = []
        for path in data_root.glob('*/work.json'):
            try:
                meta = read_json(path)
                if not can_access(g.user, meta):
                    continue
                if meta.get('deleted_at'):
                    deadline = expires_at(meta)
                    meta['purge_date'] = deadline.astimezone().strftime('%d.%m.%Y %H:%M') if deadline else None
                    meta['expired'] = bool(deadline and deadline <= datetime.now(timezone.utc))
                    works.append(meta)
            except (ValueError, OSError):
                logger.exception('Invalid work metadata')
        works.sort(key=lambda w: w['deleted_at'], reverse=True)
        return render_template('trash.html', works=works)

    @app.route('/work/<work_id>/delete', methods=['GET', 'POST'])
    def delete_work(work_id):
        with LOCK:
            folder = folder_for(work_id)
            meta = read_json(folder / 'work.json')
            if work_id in ACTIVE:
                return render_template('error.html', message='Дождитесь завершения распознавания, затем удалите работу.'), 409
            if request.method == 'GET':
                return render_template('delete_work.html', work=meta)
            if request.form.get('confirm') != 'yes':
                flash('Подтвердите перемещение работы в корзину.')
                return redirect(url_for('delete_work', work_id=work_id))
            # Soft deletion preserves the PDF, crops and teacher corrections.
            meta['deleted_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
            write_json(folder / 'work.json', meta)
        flash('Работа в корзине. Координатор может восстановить её в течение 3 дней, затем файлы удалятся автоматически.')
        return redirect(url_for('index'))

    @app.post('/work/<work_id>/restore')
    def restore_work(work_id):
        if g.user['role'] != 'admin':
            abort(403)
        with LOCK:
            folder = folder_for(work_id, include_deleted=True)
            meta = read_json(folder / 'work.json')
            if not meta.get('deleted_at'):
                abort(404)
            deadline = expires_at(meta)
            if deadline and deadline <= datetime.now(timezone.utc):
                abort(409, 'Срок хранения истёк. Работа ожидает окончательного удаления.')
            meta.pop('deleted_at')
            write_json(folder / 'work.json', meta)
        flash('Работа восстановлена вместе с ответами и отметками проверки.')
        return redirect(url_for('index'))

    @app.post('/upload')
    def upload():
        exam = request.form.get('exam', 'oge')
        subject = request.form.get('subject', 'math')
        if exam not in EXAMS or subject not in SUBJECTS:
            abort(400, 'Выберите ОГЭ или ЕГЭ и предмет из списка.')
        if g.user['role'] != 'admin' and (exam != 'oge' or subject != 'math'):
            abort(403)
        supported = profile_for({'exam': exam, 'subject': subject})['supported']
        if shutil.disk_usage(data_root).free < 5 * 1024**3:
            abort(503, 'Недостаточно свободного места. Обратитесь к координатору.')
        upload = request.files.get('pdf')
        if not upload or not upload.filename or not upload.filename.lower().endswith('.pdf'):
            flash('Выберите PDF со сканами бланков.')
            return redirect(url_for('index'))
        content = upload.read()
        try:
            with fitz.open(stream=content, filetype='pdf') as doc:
                if doc.needs_pass or not 1 <= len(doc) <= 100:
                    raise ValueError('Expected 1 to 100 unencrypted pages')
                count = len(doc)
                for p in doc:
                    if p.rect.width > 1000 or p.rect.height > 1300 or p.rect.width < 100 or p.rect.height < 100:
                        raise ValueError('Unsupported page dimensions')
        except Exception:
            flash('Не удалось прочитать PDF. Нужны 1–100 страниц обычного формата без пароля.')
            return redirect(url_for('index'))
        work_id = uuid.uuid4().hex
        folder = data_root / work_id
        folder.mkdir()
        (folder / 'source.pdf').write_bytes(content)
        # Publishing work.json last makes a completed upload recoverable.
        write_json(folder / 'keys.json', {})
        write_json(folder / 'work.json', {'id': work_id, 'title': request.form.get('title', '').strip()[:100] or Path(upload.filename).stem,
                    'class_name': request.form.get('class_name', '').strip()[:30], 'count': count,
                    'created': datetime.now().isoformat(timespec='seconds'), 'finished': False,
                    'exam': exam, 'subject': subject,
                    'queue_state': 'queued' if supported else 'awaiting_template',
                    'template': form_config()['id'] if supported else None,
                    'owner_id': g.user['id'], 'school_id': g.user['school_id']})
        if supported:
            enqueue(folder)
        else:
            flash('PDF сохранён. Шаблон для этого экзамена и предмета ещё не настроен; распознавание не запускалось.')
        return redirect(url_for('work', work_id=work_id))

    @app.get('/work/<work_id>')
    def work(work_id):
        meta, pages, keys = details(folder_for(work_id))
        return render_template('work.html', work=meta, pages=pages, keys=keys)

    @app.post('/work/<work_id>/resume')
    def resume(work_id):
        with LOCK:
            folder = folder_for(work_id)
            if not profile_for(read_json(folder / 'work.json'))['supported']:
                abort(409, 'Сначала необходимо настроить шаблон этого экзамена и предмета.')
            enqueue(folder)
        return redirect(url_for('work', work_id=work_id))

    @app.route('/work/<work_id>/key', methods=['GET', 'POST'])
    def key(work_id):
        folder = folder_for(work_id)
        meta, _, keys = details(folder)
        if not meta['profile']['supported']:
            abort(409, 'Ключи станут доступны после настройки шаблона.')
        variant = request.values.get('variant', '1').strip()[:30] or '1'
        if request.method == 'POST':
            answers = {t: request.form.get('key_'+t, '').strip()[:100] for t in TASKS}
            with LOCK:
                folder_for(work_id)
                keys = read_json(folder / 'keys.json')
                keys[variant] = {t: a for t,a in answers.items() if a}
                write_json(folder / 'keys.json', keys)
            flash('Ключ сохранён. Баллы рассчитаны для проверенных бланков этого варианта.')
            return redirect(url_for('work', work_id=work_id))
        return render_template('key.html', work=meta, variant=variant, key=keys.get(variant, {}), variants=keys)

    @app.route('/work/<work_id>/page/<int:number>', methods=['GET', 'POST'])
    def review(work_id, number):
        folder = folder_for(work_id)
        meta, pages, keys = details(folder)
        if not 1 <= number <= meta['count']:
            abort(404)
        page = pages[number-1]
        if page['status'] not in ('ready', 'error'):
            return redirect(url_for('work', work_id=work_id))
        if request.method == 'POST':
            if request.form.get('action') == 'verify' and not request.form.get('checked_corrections'):
                flash('Подтвердите, что сверили блок замен ответов внизу бланка.')
                return redirect(url_for('review', work_id=work_id, number=number))
            path = folder / str(number) / 'page.json'
            with LOCK:
                folder_for(work_id)
                page = read_json(path)
                page['answers'] = {t: request.form.get('answer_'+t, '').strip()[:40] for t in TASKS}
                page['name'] = request.form.get('name', '').strip()[:160]
                page['variant'] = request.form.get('variant', '1').strip()[:30] or '1'
                page['reviewed'] = request.form.get('action') == 'verify'
                page['updated'] = datetime.now().isoformat(timespec='seconds')
                write_json(path, page)
            flash('Бланк проверен.' if page['reviewed'] else 'Изменения сохранены как черновик.')
            if page['reviewed'] and number < meta['count'] and pages[number]['status'] in ('ready','error'):
                return redirect(url_for('review', work_id=work_id, number=number+1))
            return redirect(url_for('work', work_id=work_id))
        page_dir = folder / str(number)
        return render_template('review.html', work=meta, page=page, keys=keys,
                               has_crops=(page_dir / 'answer_1.png').exists(),
                               has_scan=(page_dir / 'scan.png').exists(),
                               has_corrections=(page_dir / 'corrections.png').exists())

    @app.get('/work/<work_id>/image/<int:number>/<name>')
    def image(work_id, number, name):
        folder = folder_for(work_id)
        if not re.fullmatch(r'(scan|corrections|answer_([1-9]|1[0-9]))\.png', name):
            abort(404)
        path = folder / str(number) / name
        if not path.is_file():
            abort(404)
        return send_file(path, max_age=0)

    @app.get('/work/<work_id>/export')
    def export(work_id):
        meta, pages, _ = details(folder_for(work_id))
        if not meta['profile']['supported']:
            abort(409, 'Результатов пока нет: ожидается настройка шаблона.')
        stream = io.StringIO(newline='')
        writer = csv.writer(stream, delimiter=';')
        writer.writerow(['Страница','ФИО','Класс','Вариант','Статус','Верных ответов','Заданий в ключе', *TASKS])
        def safe(value):
            text = str(value)
            return "'"+text if text.startswith(('=','+','-','@','\t','\r','\n')) else text
        for p in pages:
            score = p['score'] or {}
            writer.writerow([p['number'],safe(p.get('name','')),safe(meta['class_name']),safe(p.get('variant','')),
                             'Проверен' if p.get('reviewed') else 'Не проверен', score.get('correct',''),score.get('total',''),
                             *[safe(p.get('answers',{}).get(t,'')) for t in TASKS]])
        return send_file(io.BytesIO(stream.getvalue().encode('utf-8-sig')), mimetype='text/csv; charset=utf-8',
                         as_attachment=True, download_name='blanks_results.csv')

    @app.after_request
    def privacy_headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
        return response

    def school_summaries():
        works = []
        for path in data_root.glob('*/work.json'):
            try:
                if not read_json(path).get('deleted_at'):
                    works.append(details(path.parent)[0])
            except (ValueError, OSError):
                logger.exception('Invalid work metadata')
        return works

    install_accounts(app, accounts, school_summaries)
    return app


app = create_app()

if __name__ == '__main__':
    from core.server_runtime import instance_lock
    with instance_lock(app.config['DATA_ROOT']):
        cleaner = app.extensions['trash_cleaner']
        cleaner.start()
        recover_queue(app.config['DATA_ROOT'])
        try:
            app.run(host='127.0.0.1', port=int(os.environ.get('PORT', '5001')), debug=False, use_reloader=False)
        finally:
            cleaner.stop()
