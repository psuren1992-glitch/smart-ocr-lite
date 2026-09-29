"""Three-day retention for deleted work folders; single-process server only."""
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import re
import shutil
import stat
import threading

logger = logging.getLogger(__name__)
RETENTION = timedelta(days=3)


def expires_at(meta):
    value = meta.get('deleted_at')
    if not isinstance(value, str) or not value:
        return None
    try:
        deleted = datetime.fromisoformat(value)
        # Old versions stored local timestamps without an offset.
        return deleted.astimezone(timezone.utc) + RETENTION
    except (ValueError, OverflowError, OSError):
        return None


def checked_tree(folder, root, recursive=True):
    """Reject symlinks/junctions and any resolved path outside the data root."""
    pending = [folder]
    while pending:
        path = pending.pop()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError('Linked paths cannot be purged')
        if not path.resolve().is_relative_to(root):
            raise ValueError('Path outside data root')
        if recursive and path.is_dir():
            pending.extend(path.iterdir())


class TrashCleaner:
    def __init__(self, root, lock, active):
        self.root = Path(root).resolve()
        self.lock = lock
        self.active = active
        self.stop_event = threading.Event()
        self.thread = None

    def sweep(self, now=None):
        now = now or datetime.now(timezone.utc)
        removed = []
        for folder in self.root.iterdir():
            if not re.fullmatch(r'[a-f0-9]{32}', folder.name):
                continue
            with self.lock:
                if folder.name in self.active:
                    continue
                try:
                    # Validate before reading metadata as well as before deletion.
                    checked_tree(folder, self.root, recursive=False)
                    metadata = folder / 'work.json'
                    if not metadata.is_file():
                        continue
                    checked_tree(metadata, self.root, recursive=False)
                    meta = json.loads(metadata.read_text(encoding='utf-8'))
                    deadline = expires_at(meta)
                    if meta.get('id') != folder.name or not deadline or deadline > now:
                        continue
                    checked_tree(folder, self.root)
                    for child in folder.iterdir():
                        if child == metadata:
                            continue
                        checked_tree(child, self.root)
                        if child.is_dir():
                            shutil.rmtree(child)
                        else:
                            child.unlink()
                    # Keep the deletion marker until all payload files are gone,
                    # allowing retry after a locked file or interrupted cleanup.
                    metadata.unlink()
                    folder.rmdir()
                    removed.append(folder.name)
                    logger.info('Expired work purged: %s', folder.name)
                except (OSError, ValueError, TypeError, AttributeError):
                    logger.warning('Trash cleanup skipped work %s; retry on next sweep', folder.name)
        return removed

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.sweep()
        def loop():
            while not self.stop_event.wait(60):
                try:
                    self.sweep()
                except OSError:
                    logger.warning('Trash storage unavailable; retry on next sweep')
        self.thread = threading.Thread(target=loop, name='trash-cleaner', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
