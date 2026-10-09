"""Disposable cloud demo only. Never use real customers or wallet balances."""
import logging
import os
from pathlib import Path
from server import make_server
from service import Service


def demo_service():
    if os.environ.get('YALLA_DEMO') != '1':
        raise SystemExit('This entry point requires YALLA_DEMO=1; demo data only.')
    password = os.environ.get('YALLA_DEMO_PASSWORD', '')
    if len(password) < 16 or len(password) > 200 or password != password.strip():
        raise SystemExit('Set YALLA_DEMO_PASSWORD to 16-200 characters without surrounding spaces.')
    path = Path(os.environ.get('YALLA_DB', '/tmp/yalla-demo/yalla.sqlite3'))
    path.parent.mkdir(parents=True, exist_ok=True)
    service = Service(path)
    accounts = [
        ('مدير التجربة', 'demo-admin', 'admin', '*', 0),
        ('متجر تجريبي', 'demo-store', 'store', 'السابع', 0),
        ('كابتن تجريبي 1', 'demo-captain-1', 'captain', 'السابع', 10_000),
        ('كابتن تجريبي 2', 'demo-captain-2', 'captain', 'السابع', 10_000),
    ]
    with service.connection() as db:
        existing = {r['phone'] for r in db.execute('SELECT phone FROM users')}
    for name, phone, role, region, balance in accounts:
        if phone not in existing:
            service.add_user(name, phone, role, region, password, balance)
    return service


def main():
    service = demo_service()
    port = int(os.environ.get('PORT', '8000'))
    server = make_server(service, '0.0.0.0', port)
    logging.basicConfig(level=logging.INFO)
    logging.warning('DISPOSABLE DEMO: local data may be lost on sleep/restart. No real balances.')
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
