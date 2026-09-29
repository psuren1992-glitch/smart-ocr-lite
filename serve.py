"""Windows single-process WSGI runner. Backend is never bound publicly."""
import argparse
import logging
import os
import socket
from urllib.parse import urlsplit

from waitress import serve

from core.server_runtime import instance_lock, snapshot
from webapp import app, recover_queue, EXECUTOR


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backup-dir', required=True, help='Protected directory on a separate disk')
    parser.add_argument('--https', action='store_true', help='Behind a loopback HTTPS reverse proxy')
    args = parser.parse_args()
    port = int(os.environ.get('PORT', '5001'))
    if args.https:
        address = urlsplit(app.config['PUBLIC_BASE_URL'])
        if address.scheme != 'https' or not address.hostname or address.username or address.password or address.path not in ('', '/') or address.query or address.fragment:
            parser.error('Set MATH9_PUBLIC_URL to the actual HTTPS origin first')
        app.config.update(SESSION_COOKIE_SECURE=True, TRUSTED_HOSTS=[address.hostname])
    else:
        app.config.update(SESSION_COOKIE_SECURE=False, PUBLIC_BASE_URL=f'http://127.0.0.1:{port}',
                          TRUSTED_HOSTS=['127.0.0.1', 'localhost'])
    # Refuse a second legacy webapp.py listener before starting maintenance.
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
    with instance_lock(app.config['DATA_ROOT']):
        archive, count = snapshot(app.config['DATA_ROOT'], args.backup_dir)
        print(f'Backup verified: {archive} ({count} files)', flush=True)
        cleaner = app.extensions['trash_cleaner']
        cleaner.start()
        try:
            recovered = recover_queue(app.config['DATA_ROOT'])
            print(f'Recovered work queue: {recovered}', flush=True)
            options = dict(host='127.0.0.1', port=port, threads=4, connection_limit=64,
                           channel_timeout=120, max_request_body_size=80*1024*1024,
                           max_request_header_size=32768, ident='Blanks')
            if args.https:
                options.update(trusted_proxy='127.0.0.1', trusted_proxy_count=1,
                               trusted_proxy_headers={'x-forwarded-for', 'x-forwarded-proto'},
                               clear_untrusted_proxy_headers=True)
            serve(app, **options)
        finally:
            cleaner.stop()
            EXECUTOR.shutdown(wait=True)


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING)
    main()
