"""Single-instance launch and verified offline snapshots for the local server."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import zipfile

from core.trash import checked_tree


@contextmanager
def instance_lock(root):
    path = Path(root) / '_access/server.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open('a+b')
    try:
        if path.stat().st_size == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        import msvcrt
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        stream.close()
        raise RuntimeError('Another server is already using this data directory') from None
    try:
        yield
    finally:
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        stream.close()


def snapshot(root, destination):
    """Call before accepting requests or starting OCR; preserve SQLite consistently."""
    root, destination = Path(root).resolve(), Path(destination).resolve()
    if destination == root or destination.is_relative_to(root):
        raise ValueError('Backup must be outside the data directory')
    checked_tree(root, root)
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = destination / ('blanks-' + stamp + '.zip')
    pending = target.with_suffix('.partial')
    hashes = {}
    with tempfile.TemporaryDirectory(prefix='blanks-snapshot-') as tmp:
        db_copy = Path(tmp) / 'accounts.sqlite3'
        database = root / '_access/accounts.sqlite3'
        if database.exists():
            source = sqlite3.connect(database)
            output = sqlite3.connect(db_copy)
            try:
                source.backup(output)
                if output.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Account database failed integrity check')
            finally:
                output.close()
                source.close()
        with zipfile.ZipFile(pending, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(root.rglob('*')):
                if not path.is_file() or path.name in ('server.lock', 'accounts.sqlite3-wal', 'accounts.sqlite3-shm') or path.suffix == '.tmp':
                    continue
                relative = path.relative_to(root).as_posix()
                content = (db_copy if path == database else path).read_bytes()
                archive.writestr('data/' + relative, content)
                hashes[relative] = hashlib.sha256(content).hexdigest()
            archive.writestr('manifest.json', json.dumps({'created_utc': stamp, 'sha256': hashes}, indent=2))
        with zipfile.ZipFile(pending) as archive:
            for name, expected in hashes.items():
                if hashlib.sha256(archive.read('data/' + name)).hexdigest() != expected:
                    raise ValueError('Backup verification failed')
    pending.replace(target)
    return target, len(hashes)
