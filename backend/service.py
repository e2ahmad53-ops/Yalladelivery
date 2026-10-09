"""Yalla Delivery MVP. Money is stored as integer Jordanian fils (1 JOD = 1000)."""
import hashlib
import hmac
import json
import math
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class APIError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


def now():
    return int(time.time())


def uid():
    return uuid.uuid4().hex


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 200_000).hex()
    return salt + ':' + digest


def verify_password(password, value):
    return hmac.compare_digest(password_hash(password, value.split(':')[0]), value)


def text_field(data, key, limit=500, optional=False):
    value = data.get(key, '')
    if not isinstance(value, str) or len(value) > limit or (not optional and not value.strip()):
        raise APIError(400, 'قيمة غير صحيحة: ' + key)
    return value.strip()


def integer(data, key, minimum=1, maximum=1_000_000):
    value = data.get(key)
    if type(value) is not int or not minimum <= value <= maximum:
        raise APIError(400, 'قيمة غير صحيحة: ' + key)
    return value


def coords(data):
    values = data.get('lat'), data.get('lng')
    if values == (None, None):
        return values
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise APIError(400, 'إحداثيات غير صحيحة')
    if not (-90 <= values[0] <= 90 and -180 <= values[1] <= 180):
        raise APIError(400, 'إحداثيات خارج النطاق')
    return values


class Service:
    def __init__(self, database):
        self.database = str(database)
        with self.connection() as db:
            db.executescript(Path(__file__).with_name('schema.sql').read_text())
            db.execute('PRAGMA journal_mode=WAL')

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.database, timeout=20, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            if write:
                db.commit()
        except Exception:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def public_user(row):
        return {k: row[k] for k in ('id', 'name', 'phone', 'role', 'region', 'online')}

    @staticmethod
    def role(user, *roles):
        if user['role'] not in roles:
            raise APIError(403, 'لا تملك صلاحية هذه العملية')

    @staticmethod
    def region(user, region):
        if user['role'] == 'admin' and user['region'] == '*':
            return
        if user['region'] != region:
            raise APIError(403, 'الحساب خارج منطقة صلاحيتك')

    @staticmethod
    def audit(db, user, action, data):
        db.execute('INSERT INTO audit VALUES (?,?,?,?,?)',
                   (uid(), user['id'], action, json.dumps(data, ensure_ascii=False), now()))

    def add_user(self, name, phone, role, region, password, balance=0):
        if role not in ('admin', 'store', 'captain') or len(password) < 10:
            raise APIError(400, 'نوع الحساب أو كلمة المرور غير صحيح')
        if not region or (region == '*' and role != 'admin'):
            raise APIError(400, 'حدد منطقة الحساب')
        identity = uid()
        try:
            with self.connection(True) as db:
                db.execute('INSERT INTO users (id,name,phone,role,region,password_hash,balance) VALUES (?,?,?,?,?,?,?)',
                           (identity, name, phone, role, region, password_hash(password), balance))
                if balance:
                    db.execute('INSERT INTO ledger VALUES (?,?,?,?,?,?)', (uid(), identity, balance, 'opening', identity, now()))
        except sqlite3.IntegrityError:
            raise APIError(409, 'رقم الهاتف موجود أو الرصيد غير صحيح') from None
        return identity

    def login(self, data):
        phone = text_field(data, 'phone', 30)
        password = text_field(data, 'password', 200)
        with self.connection(True) as db:
            row = db.execute('SELECT * FROM users WHERE phone=?', (phone,)).fetchone()
            if not row or not verify_password(password, row['password_hash']):
                raise APIError(401, 'رقم الهاتف أو كلمة المرور غير صحيحة')
            token = secrets.token_urlsafe(32)
            db.execute('DELETE FROM sessions WHERE expires<?', (now(),))
            db.execute('INSERT INTO sessions VALUES (?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), row['id'], now()+86400))
            return {'token': token, 'user': self.public_user(row)}

    def authenticate(self, token):
        with self.connection() as db:
            row = db.execute('SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token_hash=? AND s.expires>?',
                             (hashlib.sha256(token.encode()).hexdigest(), now())).fetchone()
            if not row:
                raise APIError(401, 'سجل الدخول من جديد')
            return dict(row)

    def logout(self, token):
        with self.connection(True) as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))
        return {'ok': True}

    def accounts(self, user):
        self.role(user, 'admin')
        with self.connection() as db:
            rows = db.execute('SELECT * FROM users WHERE ?="*" OR region=?', (user['region'], user['region'])).fetchall()
            return [self.public_user(r) for r in rows]

    def create_account(self, user, data):
        self.role(user, 'admin')
        region = text_field(data, 'region', 80)
        self.region(user, region)
        role = text_field(data, 'role', 20)
        if role == 'admin' and user['region'] != '*':
            raise APIError(403, 'إنشاء الأدمن متاح للمدير فقط')
        identity = self.add_user(text_field(data, 'name', 100), text_field(data, 'phone', 30), role, region,
                                 text_field(data, 'password', 200))
        with self.connection(True) as db:
            self.audit(db, user, 'create_account', {'user_id': identity})
        return {'id': identity}

    def create_order(self, user, data):
        self.role(user, 'store')
        fee = integer(data, 'fee', maximum=100_000)
        scheduled = data.get('scheduled_at', now())
        if type(scheduled) is not int or not 0 <= scheduled <= now()+90*86400:
            raise APIError(400, 'موعد الطلب غير صحيح')
        lat, lng = coords(data)
        identity = uid()
        args = (identity, user['id'], user['region'], text_field(data, 'customer_name', 100),
                text_field(data, 'address', 500), text_field(data, 'phone', 30), fee,
                (fee*15+50)//100, text_field(data, 'route_group', 100), text_field(data, 'notes', 2000, True),
                scheduled, now(), lat, lng)
        with self.connection(True) as db:
            db.execute('INSERT INTO orders (id,store_id,region,customer_name,address,phone,fee,commission,route_group,notes,scheduled_at,created_at,lat,lng) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)', args)
            self.audit(db, user, 'create_order', {'order_id': identity})
        return {'id': identity}

    def orders(self, user):
        with self.connection() as db:
            if user['role'] == 'store':
                rows = db.execute('SELECT * FROM orders WHERE store_id=? ORDER BY created_at DESC', (user['id'],)).fetchall()
            elif user['role'] == 'captain':
                rows = db.execute('SELECT * FROM orders WHERE captain_id=? OR (region=? AND status="pending" AND scheduled_at<=?) ORDER BY created_at DESC',
                                  (user['id'], user['region'], now())).fetchall()
            else:
                rows = db.execute('SELECT * FROM orders WHERE ?="*" OR region=? ORDER BY created_at DESC', (user['region'], user['region'])).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                if user['role'] == 'captain' and row['captain_id'] != user['id']:
                    # Do not broadcast customer identity or exact coordinates.
                    for key in ('customer_name', 'phone', 'lat', 'lng', 'notes'):
                        item.pop(key, None)
                result.append(item)
            return result

    def order_access(self, db, user, identity):
        row = db.execute('SELECT * FROM orders WHERE id=?', (identity,)).fetchone()
        if not row:
            raise APIError(404, 'الطلب غير موجود')
        if user['role'] == 'admin':
            self.region(user, row['region'])
        elif (user['role'] == 'store' and row['store_id'] != user['id']) or (user['role'] == 'captain' and row['captain_id'] != user['id']):
            raise APIError(403, 'الطلب ليس مرتبطاً بحسابك')
        return row

    def assign(self, user, identity, data):
        self.role(user, 'admin', 'captain')
        captain_id = user['id'] if user['role'] == 'captain' else text_field(data, 'captain_id', 64)
        with self.connection(True) as db:
            order = db.execute('SELECT * FROM orders WHERE id=?', (identity,)).fetchone()
            if not order:
                raise APIError(404, 'الطلب غير موجود')
            self.region(user, order['region'])
            if order['status'] in ('delivered', 'cancelled'):
                raise APIError(409, 'الطلب مغلق')
            if user['role'] == 'captain' and (order['status'] != 'pending' or order['scheduled_at'] > now()):
                raise APIError(409, 'الطلب غير متاح للقبول')
            # Admin can reassign accepted orders, but not goods already picked up.
            if order['status'] == 'picked_up':
                raise APIError(409, 'لا يمكن تحويل طلب تم استلامه من المتجر')
            captain = db.execute('SELECT * FROM users WHERE id=? AND role="captain"', (captain_id,)).fetchone()
            if not captain or captain['region'] != order['region']:
                raise APIError(400, 'الكابتن غير موجود في منطقة الطلب')
            if not captain['online']:
                raise APIError(409, 'الكابتن غير متاح')
            if order['captain_id'] == captain_id:
                return {'ok': True}
            active = db.execute('SELECT route_group FROM orders WHERE captain_id=? AND status IN ("accepted","picked_up")', (captain_id,)).fetchall()
            if len(active) >= 3:
                raise APIError(409, 'الحد الأعلى ثلاثة طلبات نشطة')
            if active and any(r['route_group'] != order['route_group'] for r in active):
                raise APIError(409, 'الطلبات المتعددة يجب أن تكون ضمن نفس مجموعة الطريق')
            if captain['balance']-captain['reserved'] < order['commission']:
                raise APIError(409, 'رصيد الكابتن المتاح لا يكفي للعمولة')
            if order['captain_id']:
                db.execute('UPDATE users SET reserved=reserved-? WHERE id=?', (order['commission'], order['captain_id']))
            db.execute('UPDATE users SET reserved=reserved+? WHERE id=?', (order['commission'], captain_id))
            db.execute('UPDATE orders SET captain_id=?,status="accepted" WHERE id=?', (captain_id, identity))
            db.execute('INSERT OR IGNORE INTO threads VALUES (?,?,?,?,?)', ('order-'+identity, 'order', order['store_id'], identity, order['region']))
            self.audit(db, user, 'assign_order', {'order_id': identity, 'from': order['captain_id'], 'to': captain_id})
        return {'ok': True}

    def order_status(self, user, identity, data):
        status = text_field(data, 'status', 30)
        with self.connection(True) as db:
            order = self.order_access(db, user, identity)
            if status == order['status']:
                return {'ok': True}
            if status == 'cancelled':
                self.role(user, 'store', 'admin')
                allowed = ('pending',) if user['role'] == 'store' else ('pending', 'accepted')
                if order['status'] not in allowed:
                    raise APIError(409, 'لا يمكن إلغاء الطلب بهذه الحالة')
                if order['captain_id']:
                    db.execute('UPDATE users SET reserved=reserved-? WHERE id=?', (order['commission'], order['captain_id']))
            else:
                self.role(user, 'captain')
                expected = {'picked_up': 'accepted', 'delivered': 'picked_up'}
                if expected.get(status) != order['status']:
                    raise APIError(409, 'انتقال حالة الطلب غير صحيح')
                if status == 'delivered':
                    db.execute('UPDATE users SET balance=balance-?,reserved=reserved-? WHERE id=?', (order['commission'], order['commission'], user['id']))
                    db.execute('INSERT INTO ledger VALUES (?,?,?,?,?,?)', (uid(), user['id'], -order['commission'], 'commission', identity, now()))
            db.execute('UPDATE orders SET status=? WHERE id=?', (status, identity))
            self.audit(db, user, 'order_status', {'order_id': identity, 'status': status})
        return {'ok': True}

    def wallet(self, user):
        self.role(user, 'captain')
        with self.connection() as db:
            row = db.execute('SELECT balance,reserved FROM users WHERE id=?', (user['id'],)).fetchone()
            entries = [dict(r) for r in db.execute('SELECT * FROM ledger WHERE user_id=? ORDER BY created_at DESC,rowid DESC LIMIT 100', (user['id'],))]
            return {'balance': row['balance'], 'reserved': row['reserved'], 'available': row['balance']-row['reserved'], 'entries': entries}

    def transfer(self, user, data):
        self.role(user, 'captain')
        amount = integer(data, 'amount', maximum=1_000_000)
        phone = text_field(data, 'recipient_phone', 30)
        key = text_field(data, 'idempotency_key', 128)
        with self.connection(True) as db:
            recipient = db.execute('SELECT * FROM users WHERE phone=? AND role="captain"', (phone,)).fetchone()
            if not recipient or recipient['id'] == user['id']:
                raise APIError(400, 'رقم المستلم غير صحيح')
            old = db.execute('SELECT * FROM transfers WHERE sender_id=? AND idem_key=?', (user['id'], key)).fetchone()
            if old:
                if old['amount'] != amount or old['recipient_id'] != recipient['id']:
                    raise APIError(409, 'المفتاح مستخدم لعملية مختلفة')
                return {'id': old['id'], 'recipient_name': recipient['name'], 'replayed': True}
            sender = db.execute('SELECT * FROM users WHERE id=?', (user['id'],)).fetchone()
            if sender['balance']-sender['reserved'] < amount:
                raise APIError(409, 'الرصيد المتاح غير كافٍ')
            identity = uid()
            db.execute('UPDATE users SET balance=balance-? WHERE id=?', (amount, user['id']))
            db.execute('UPDATE users SET balance=balance+? WHERE id=?', (amount, recipient['id']))
            db.execute('INSERT INTO transfers VALUES (?,?,?,?,?,?)', (identity, user['id'], recipient['id'], amount, key, now()))
            for account, delta in ((user['id'], -amount), (recipient['id'], amount)):
                db.execute('INSERT INTO ledger VALUES (?,?,?,?,?,?)', (uid(), account, delta, 'transfer', identity, now()))
            self.audit(db, user, 'wallet_transfer', {'id': identity, 'amount': amount, 'recipient': recipient['id']})
        return {'id': identity, 'recipient_name': recipient['name'], 'replayed': False}

    def credit(self, user, data):
        self.role(user, 'admin')
        amount = integer(data, 'amount', maximum=1_000_000)
        identity = text_field(data, 'captain_id', 64)
        key = text_field(data, 'idempotency_key', 128)
        reference = user['id']+':'+key
        with self.connection(True) as db:
            row = db.execute('SELECT * FROM users WHERE id=? AND role="captain"', (identity,)).fetchone()
            if not row:
                raise APIError(404, 'الكابتن غير موجود')
            self.region(user, row['region'])
            old = db.execute('SELECT * FROM ledger WHERE kind="credit" AND reference=?', (reference,)).fetchone()
            if old:
                if old['user_id'] != identity or old['amount'] != amount:
                    raise APIError(409, 'المفتاح مستخدم لعملية مختلفة')
                return {'ok': True, 'replayed': True}
            db.execute('UPDATE users SET balance=balance+? WHERE id=?', (amount, identity))
            db.execute('INSERT INTO ledger VALUES (?,?,?,?,?,?)', (uid(), identity, amount, 'credit', reference, now()))
            self.audit(db, user, 'wallet_credit', {'captain_id': identity, 'amount': amount})
        return {'ok': True, 'replayed': False}

    def availability(self, user, data):
        self.role(user, 'captain')
        if type(data.get('online')) is not bool:
            raise APIError(400, 'حالة التوفر غير صحيحة')
        with self.connection(True) as db:
            db.execute('UPDATE users SET online=? WHERE id=?', (int(data['online']), user['id']))
        return {'ok': True}

    def location(self, user, data):
        self.role(user, 'captain')
        lat, lng = coords(data)
        if lat is None:
            raise APIError(400, 'الموقع مطلوب')
        with self.connection(True) as db:
            db.execute('UPDATE users SET lat=?,lng=?,location_at=? WHERE id=?', (lat, lng, now(), user['id']))
        return {'ok': True}

    def tracking(self, user, identity):
        with self.connection() as db:
            order = self.order_access(db, user, identity)
            if order['status'] not in ('accepted', 'picked_up') or not order['captain_id']:
                raise APIError(409, 'التتبع متاح أثناء الطلب النشط فقط')
            row = db.execute('SELECT id,name,lat,lng,location_at FROM users WHERE id=?', (order['captain_id'],)).fetchone()
            return dict(row)

    def captains(self, user):
        self.role(user, 'admin')
        with self.connection() as db:
            rows = db.execute('SELECT id,name,phone,region,online,lat,lng,location_at,balance,reserved FROM users WHERE role="captain" AND (?="*" OR region=?)', (user['region'], user['region'])).fetchall()
            return [dict(r) for r in rows]

    def threads(self, user):
        with self.connection() as db:
            rows = db.execute('SELECT t.*,u.name AS owner_name,u.role AS owner_role,(SELECT body FROM messages WHERE thread_id=t.id ORDER BY rowid DESC LIMIT 1) AS last_message FROM threads t JOIN users u ON u.id=t.owner_id').fetchall()
            result = []
            for row in rows:
                try:
                    self.thread_access(db, user, row['id'])
                    result.append(dict(row))
                except APIError:
                    pass
            return result

    def support(self, user):
        self.role(user, 'store', 'captain')
        identity = 'support-'+user['id']
        with self.connection(True) as db:
            db.execute('INSERT OR IGNORE INTO threads VALUES (?,?,?,?,?)', (identity, 'support', user['id'], None, user['region']))
        return {'id': identity}

    def thread_access(self, db, user, identity, write=False):
        thread = db.execute('SELECT * FROM threads WHERE id=?', (identity,)).fetchone()
        if not thread:
            raise APIError(404, 'المحادثة غير موجودة')
        if user['role'] == 'admin':
            self.region(user, thread['region'])
        elif thread['kind'] == 'support':
            if thread['owner_id'] != user['id']:
                raise APIError(403, 'المحادثة ليست لك')
        else:
            self.order_access(db, user, thread['order_id'])
        if write and thread['kind'] == 'order':
            order = db.execute('SELECT status FROM orders WHERE id=?', (thread['order_id'],)).fetchone()
            if order['status'] not in ('accepted', 'picked_up'):
                raise APIError(409, 'محادثة الطلب المغلق للقراءة فقط')
        return thread

    def messages(self, user, identity):
        with self.connection() as db:
            self.thread_access(db, user, identity)
            return [dict(r) for r in db.execute('SELECT m.*,u.name AS sender_name FROM messages m JOIN users u ON u.id=m.sender_id WHERE thread_id=? ORDER BY m.rowid', (identity,))]

    def send_message(self, user, identity, data):
        body = text_field(data, 'body', 2000)
        with self.connection(True) as db:
            self.thread_access(db, user, identity, True)
            db.execute('INSERT INTO messages VALUES (?,?,?,?,?)', (uid(), identity, user['id'], body, now()))
        return {'ok': True}

    def dispatch(self, method, path, user, data):
        if method == 'GET' and path == '/api/me':
            return self.public_user(user)
        routes = {
            ('GET', '/api/orders'): lambda: self.orders(user),
            ('POST', '/api/orders'): lambda: self.create_order(user, data),
            ('GET', '/api/accounts'): lambda: self.accounts(user),
            ('POST', '/api/accounts'): lambda: self.create_account(user, data),
            ('GET', '/api/captains'): lambda: self.captains(user),
            ('GET', '/api/wallet'): lambda: self.wallet(user),
            ('POST', '/api/wallet/transfer'): lambda: self.transfer(user, data),
            ('POST', '/api/wallet/credit'): lambda: self.credit(user, data),
            ('POST', '/api/availability'): lambda: self.availability(user, data),
            ('POST', '/api/location'): lambda: self.location(user, data),
            ('GET', '/api/threads'): lambda: self.threads(user),
            ('POST', '/api/support'): lambda: self.support(user),
        }
        action = routes.get((method, path))
        if action:
            return action()
        match = re.fullmatch(r'/api/orders/([a-z0-9]+)/([a-z]+)', path)
        if match:
            identity, operation = match.groups()
            if method == 'POST' and operation == 'assign':
                return self.assign(user, identity, data)
            if method == 'POST' and operation == 'status':
                return self.order_status(user, identity, data)
            if method == 'GET' and operation == 'tracking':
                return self.tracking(user, identity)
        match = re.fullmatch(r'/api/threads/([a-z0-9-]+)/messages', path)
        if match and method == 'GET':
            return self.messages(user, match[1])
        if match and method == 'POST':
            return self.send_message(user, match[1], data)
        raise APIError(404, 'المسار غير موجود')
