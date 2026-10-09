import concurrent.futures
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import APIError, Service, now
from server import make_server

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = Service(Path(self.tmp.name)/'test.db')
        self.admin = self.user('admin', '*', 'admin')
        self.store = self.user('store', 'السابع', 'store')
        self.other_store = self.user('store', 'صويلح', 'other-store')
        self.c1 = self.user('captain', 'السابع', 'captain1', 2000)
        self.c2 = self.user('captain', 'السابع', 'captain2', 2000)
        self.regional = self.user('admin', 'صويلح', 'regional')
        self.s.availability(self.c1, {'online': True})
        self.s.availability(self.c2, {'online': True})

    def tearDown(self):
        self.tmp.cleanup()

    def user(self, role, region, phone, balance=0):
        identity = self.s.add_user(phone, phone, role, region, 'testing-password', balance)
        with self.s.connection() as db:
            return dict(db.execute('SELECT * FROM users WHERE id=?', (identity,)).fetchone())

    def order(self, group='west', **changes):
        data = {'customer_name': 'زبون', 'phone': '0790000000', 'address': 'عنوان تجريبي', 'fee': 2000, 'route_group': group}
        data.update(changes)
        return self.s.create_order(self.store, data)['id']

    def transfer(self, amount=500, key='key'):
        return {'recipient_phone': self.c2['phone'], 'amount': amount, 'idempotency_key': key}

    def assertError(self, status, fn, *args):
        with self.assertRaises(APIError) as context:
            fn(*args)
        self.assertEqual(context.exception.status, status)

    def test_authentication_logout_and_no_password_in_response(self):
        self.assertError(401, self.s.login, {'phone': 'store', 'password': 'wrong'})
        result = self.s.login({'phone': 'store', 'password': 'testing-password'})
        self.assertNotIn('password_hash', result['user'])
        self.assertEqual(self.s.authenticate(result['token'])['id'], self.store['id'])
        self.s.logout(result['token'])
        self.assertError(401, self.s.authenticate, result['token'])

    def test_simultaneous_accept_has_one_winner(self):
        identity = self.order()
        def accept(captain):
            try:
                self.s.assign(captain, identity, {})
                return True
            except APIError:
                return False
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            self.assertEqual(sum(pool.map(accept, (self.c1, self.c2))), 1)
        self.assertEqual(self.s.wallet(self.c1)['reserved']+self.s.wallet(self.c2)['reserved'], 300)

    def test_transfer_idempotency(self):
        a = self.s.transfer(self.c1, self.transfer())
        b = self.s.transfer(self.c1, self.transfer())
        self.assertEqual(a['id'], b['id'])
        self.assertEqual(self.s.wallet(self.c1)['balance'], 1500)
        self.assertEqual(self.s.wallet(self.c2)['balance'], 2500)
        self.assertError(409, self.s.transfer, self.c1, self.transfer(700))

    def test_parallel_transfers_cannot_overdraw(self):
        def transfer(key):
            try:
                self.s.transfer(self.c1, self.transfer(1500, key))
                return True
            except APIError:
                return False
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            self.assertEqual(sum(pool.map(transfer, ('a', 'b'))), 1)
        self.assertEqual(self.s.wallet(self.c1)['balance'], 500)
        self.assertEqual(self.s.wallet(self.c1)['balance']+self.s.wallet(self.c2)['balance'], 4000)

    def test_reserved_funds_cannot_transfer(self):
        self.s.assign(self.c1, self.order(), {})
        self.assertError(409, self.s.transfer, self.c1, self.transfer(1800))
        self.s.transfer(self.c1, self.transfer(1700))
        self.assertEqual(self.s.wallet(self.c1)['available'], 0)

    def test_three_orders_same_route_only(self):
        for _ in range(3):
            self.s.assign(self.c1, self.order(), {})
        self.assertError(409, self.s.assign, self.c1, self.order(), {})
        self.s.assign(self.c2, self.order(), {})
        self.assertError(409, self.s.assign, self.c2, self.order('east'), {})

    def test_reassignment_releases_hold_and_removes_old_access(self):
        identity = self.order()
        self.s.assign(self.c1, identity, {})
        self.s.assign(self.admin, identity, {'captain_id': self.c2['id']})
        self.assertEqual(self.s.wallet(self.c1)['reserved'], 0)
        self.assertEqual(self.s.wallet(self.c2)['reserved'], 300)
        self.assertError(403, self.s.messages, self.c1, 'order-'+identity)
        self.assertError(403, self.s.order_status, self.c1, identity, {'status': 'picked_up'})

    def test_failed_reassignment_is_atomic(self):
        identity = self.order()
        self.s.assign(self.c1, identity, {})
        self.s.transfer(self.c2, {'recipient_phone': 'captain1', 'amount': 2000, 'idempotency_key': 'drain'})
        self.assertError(409, self.s.assign, self.admin, identity, {'captain_id': self.c2['id']})
        self.assertEqual(self.s.wallet(self.c1)['reserved'], 300)
        self.assertEqual(self.s.orders(self.store)[0]['captain_id'], self.c1['id'])

    def test_commission_settles_once_and_tracking_closes(self):
        identity = self.order()
        self.s.assign(self.c1, identity, {})
        self.s.location(self.c1, {'lat': 31.96, 'lng': 35.85})
        self.assertEqual(self.s.tracking(self.store, identity)['lat'], 31.96)
        self.assertError(409, self.s.order_status, self.c1, identity, {'status': 'delivered'})
        self.s.order_status(self.c1, identity, {'status': 'picked_up'})
        self.assertError(409, self.s.assign, self.admin, identity, {'captain_id': self.c2['id']})
        self.s.order_status(self.c1, identity, {'status': 'delivered'})
        self.s.order_status(self.c1, identity, {'status': 'delivered'})
        self.assertEqual(self.s.wallet(self.c1)['balance'], 1700)
        self.assertEqual(self.s.wallet(self.c1)['reserved'], 0)
        self.assertEqual(len([e for e in self.s.wallet(self.c1)['entries'] if e['kind']=='commission']), 1)
        self.assertError(409, self.s.tracking, self.store, identity)

    def test_cancel_releases_hold(self):
        identity = self.order()
        self.s.assign(self.c1, identity, {})
        self.assertError(409, self.s.order_status, self.store, identity, {'status': 'cancelled'})
        self.s.order_status(self.admin, identity, {'status': 'cancelled'})
        self.assertEqual(self.s.wallet(self.c1)['reserved'], 0)

    def test_region_permissions_and_store_isolation(self):
        identity = self.order()
        self.assertEqual(self.s.orders(self.other_store), [])
        self.assertError(403, self.s.tracking, self.other_store, identity)
        self.assertError(403, self.s.assign, self.regional, identity, {'captain_id': self.c1['id']})
        self.assertError(403, self.s.credit, self.regional, {'captain_id': self.c1['id'], 'amount': 100, 'idempotency_key': 'x'})
        self.assertEqual(self.s.captains(self.regional), [])

    def test_future_order_not_broadcast_or_accepted(self):
        identity = self.order(scheduled_at=now()+3600)
        self.assertEqual(self.s.orders(self.c1), [])
        self.assertError(409, self.s.assign, self.c1, identity, {})

    def test_pending_broadcast_redacts_private_fields(self):
        self.order(lat=31.95, lng=35.8)
        row = self.s.orders(self.c1)[0]
        for field in ('phone', 'customer_name', 'notes', 'lat', 'lng'):
            self.assertNotIn(field, row)

    def test_support_and_order_chat_permissions(self):
        thread = self.s.support(self.store)['id']
        self.s.send_message(self.store, thread, {'body': 'مساعدة'})
        self.assertEqual(len(self.s.messages(self.admin, thread)), 1)
        self.assertError(403, self.s.messages, self.c1, thread)
        self.assertError(403, self.s.messages, self.regional, thread)
        identity = self.order()
        self.s.assign(self.c1, identity, {})
        self.s.send_message(self.c1, 'order-'+identity, {'body': 'وصلت'})
        self.assertEqual(self.s.messages(self.store, 'order-'+identity)[0]['body'], 'وصلت')
        self.assertError(403, self.s.messages, self.c2, 'order-'+identity)
        self.s.order_status(self.admin, identity, {'status': 'cancelled'})
        self.assertError(409, self.s.send_message, self.c1, 'order-'+identity, {'body': 'test'})

    def test_money_and_location_validation(self):
        for amount in (0, -1, 1.5, True, '10'):
            self.assertError(400, self.s.transfer, self.c1, self.transfer(amount))
        self.assertError(400, self.s.location, self.c1, {'lat': 91, 'lng': 0})
        self.assertError(400, self.s.location, self.c1, {'lat': float('nan'), 'lng': 0})
        self.assertError(400, self.s.transfer, self.c1, {'recipient_phone': 'captain1', 'amount': 100, 'idempotency_key': 'self'})

    def test_credit_idempotency(self):
        data = {'captain_id': self.c1['id'], 'amount': 700, 'idempotency_key': 'credit'}
        self.s.credit(self.admin, data)
        self.s.credit(self.admin, data)
        self.assertEqual(self.s.wallet(self.c1)['balance'], 2700)

    def test_http_login_order_and_invalid_payload(self):
        server = make_server(self.s, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:'+str(server.server_port)
        def request(path, payload=None, token=None):
            headers = {'Content-Type': 'application/json'}
            if token:
                headers['Authorization'] = 'Bearer '+token
            req = urllib.request.Request(base+path, data=None if payload is None else json.dumps(payload).encode(), headers=headers)
            with urllib.request.urlopen(req) as response:
                return json.load(response)
        try:
            self.assertTrue(request('/api/health')['ok'])
            login = request('/api/login', {'phone': 'store', 'password': 'testing-password'})
            identity = request('/api/orders', {'customer_name': 'a', 'phone': 'b', 'address': 'c', 'fee': 2000, 'route_group': 'd'}, login['token'])['id']
            self.assertEqual(request('/api/orders', token=login['token'])[0]['id'], identity)
            with self.assertRaises(urllib.error.HTTPError) as error:
                request('/api/orders')
            self.assertEqual(error.exception.code, 401)
            with self.assertRaises(urllib.error.HTTPError) as error:
                request('/api/login', [])
            self.assertEqual(error.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

if __name__ == '__main__':
    unittest.main()
