"""Development HTTP server; deploy behind HTTPS/reverse proxy, never directly publicly."""
import argparse
import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from service import APIError, Service

ROOT = Path(__file__).resolve().parents[1]


def make_server(service, host='127.0.0.1', port=8000):
    attempts = defaultdict(deque)
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # Never log tokens, request bodies, or query strings.
            logging.info('%s %s', self.command, urlparse(self.path).path)

        def respond(self, status, value, content_type='application/json; charset=utf-8'):
            raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Frame-Options', 'DENY')
            self.end_headers()
            self.wfile.write(raw)

        def run_request(self):
            path = urlparse(self.path).path
            try:
                if self.command == 'GET' and path in ('/', '/admin.js', '/admin.css'):
                    filename = {'/': 'index.html', '/admin.js': 'admin.js', '/admin.css': 'admin.css'}[path]
                    kind = {'/': 'text/html', '/admin.js': 'text/javascript', '/admin.css': 'text/css'}[path]
                    return self.respond(200, (ROOT/'apps'/'admin'/filename).read_bytes(), kind+'; charset=utf-8')
                if self.command == 'GET' and path == '/api/health':
                    return self.respond(200, {'ok': True, 'stage': 'mvp'})
                data = {}
                if self.command == 'POST':
                    try:
                        size = int(self.headers.get('Content-Length', '0'))
                    except ValueError:
                        raise APIError(400, 'حجم الطلب غير صحيح') from None
                    if size < 0 or size > 32_768:
                        raise APIError(413, 'حجم الطلب كبير')
                    try:
                        data = json.loads(self.rfile.read(size) or b'{}', parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
                    except (ValueError, UnicodeDecodeError):
                        raise APIError(400, 'JSON غير صحيح') from None
                    if not isinstance(data, dict):
                        raise APIError(400, 'يجب إرسال كائن JSON')
                if self.command == 'POST' and path == '/api/login':
                    with lock:
                        bucket = attempts[self.client_address[0]]
                        stamp = time.monotonic()
                        while bucket and stamp-bucket[0] > 60:
                            bucket.popleft()
                        if len(bucket) >= 10:
                            raise APIError(429, 'حاول مجدداً بعد دقيقة')
                        bucket.append(stamp)
                    return self.respond(200, service.login(data))
                auth = self.headers.get('Authorization', '')
                if not auth.startswith('Bearer '):
                    raise APIError(401, 'سجل الدخول')
                token = auth[7:]
                user = service.authenticate(token)
                if self.command == 'POST' and path == '/api/logout':
                    result = service.logout(token)
                else:
                    result = service.dispatch(self.command, path, user, data)
                return self.respond(200, result)
            except APIError as error:
                return self.respond(error.status, {'error': error.message})
            except Exception:
                logging.exception('Request failed')
                return self.respond(500, {'error': 'خطأ داخلي؛ راجع سجل الخادم'})

        do_GET = run_request
        do_POST = run_request

    return ThreadingHTTPServer((host, port), Handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    service = Service(os.environ.get('YALLA_DB', str(ROOT/'data'/'yalla.sqlite3')))
    server = make_server(service, args.host, args.port)
    print(f'Yalla Delivery: http://{args.host}:{args.port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
