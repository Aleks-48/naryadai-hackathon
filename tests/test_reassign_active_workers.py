"""Assignment eligibility regressions; all HTTP calls use disposable synthetic data."""
from __future__ import annotations

import unittest

import server as app
from tests import test_app as support


class ReassignActiveWorkersTest(unittest.TestCase):
    def setUp(self):
        # Reuse the project's existing loopback fixture without inheriting and
        # rerunning its entire test class. Every case gets a fresh database.
        support.LocalAPITest.setUpClass()
        self.addCleanup(support.LocalAPITest.tearDownClass)
        self.fixture = support.LocalAPITest()
        self.master = self.fixture.client('master01')
        self.order = self.fixture.create_order(self.master, before_photo=False)
        self.order_id = self.order['id']
        self.path = f'/api/orders/{self.order_id}/assign'

    def _seed_queue_state(self):
        with app.connect(self.fixture.db_path) as db:
            order = db.execute('SELECT * FROM orders WHERE id=?', (self.order_id,)).fetchone()
            scope = app.queue_scope_key(order)
            db.execute('INSERT OR REPLACE INTO manual_queue_state(scope_key,revision,updated_at,updated_by) VALUES (?,?,?,?)',
                       (scope, 17, app.iso(), order['assigned_master_id']))
            db.execute('INSERT OR REPLACE INTO manual_queue_items(order_id,scope_key,position) VALUES (?,?,?)',
                       (self.order_id, scope, 1))
            # A purely local pending row catches accidental cancellation too.
            # No binding, bot credentials, or delivery worker is created.
            db.execute("""INSERT INTO telegram_outbox
                (recipient_user_id,order_id,recipient_role,event,payload_json,status,created_at)
                VALUES (?,?,'worker','synthetic_reassignment_probe','{}','queued_local',?)""",
                (order['assigned_to'], self.order_id, app.iso()))
            db.commit()

    def _snapshot(self):
        # Covers row changes as well as inserts: a failed assignment must not
        # alter deadlines/status, queue revisions, audit, notifications or outbox.
        tables = ('orders', 'audit', 'notifications', 'telegram_outbox',
                  'manual_queue_items', 'manual_queue_state')
        with app.connect(self.fixture.db_path) as db:
            return {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')]
                    for table in tables}

    def test_all_inactive_brigade_is_409_and_changes_nothing(self):
        self._seed_queue_state()
        with app.connect(self.fixture.db_path) as db:
            db.execute("UPDATE users SET is_active=0 WHERE role='worker' AND brigade='B'")
            db.commit()
        before = self._snapshot()
        status, body = self.master.call(self.path, 'POST', {'brigade': 'B'})
        self.assertEqual(status, 409, body)
        self.assertEqual(body['error'], 'В бригаде нет активного исполнителя.')
        self.assertEqual(self._snapshot(), before)

    def test_mixed_brigade_selects_active_least_loaded_and_notifies_only_active(self):
        with app.connect(self.fixture.db_path) as db:
            ids = [row[0] for row in db.execute("SELECT id FROM users WHERE role='worker' AND brigade='B' ORDER BY id")]
            self.assertGreaterEqual(len(ids), 3)
            idle, busy = ids[-1], ids[-2]
            db.execute("UPDATE users SET is_active=0 WHERE role='worker' AND brigade='B'")
            db.execute('UPDATE users SET is_active=1 WHERE id IN (?,?)', (idle, busy))
            # Give the disabled workers and chosen idle worker zero active jobs.
            placeholders = ','.join('?' for _ in ids)
            db.execute(f"UPDATE orders SET status='closed' WHERE assigned_to IN ({placeholders})", ids)
            db.commit()
        busy_order = self.fixture.create_order(self.master, worker_id=busy, before_photo=False)
        with app.connect(self.fixture.db_path) as db:
            db.execute("UPDATE orders SET status='accepted' WHERE id=?", (busy_order['id'],))
            notification_start = db.execute('SELECT COALESCE(MAX(id),0) FROM notifications').fetchone()[0]
            audit_start = db.execute('SELECT COALESCE(MAX(id),0) FROM audit').fetchone()[0]
            db.commit()
        status, body = self.master.call(self.path, 'POST', {'brigade': 'B'})
        self.assertEqual(status, 200, body)
        with app.connect(self.fixture.db_path) as db:
            assigned = db.execute('SELECT assigned_to,assigned_brigade,status FROM orders WHERE id=?', (self.order_id,)).fetchone()
            self.assertEqual(tuple(assigned), (idle, 'B', 'issued'))
            notified = [row[0] for row in db.execute('SELECT user_id FROM notifications WHERE id>? AND order_id=?',
                                                   (notification_start, self.order_id))]
            self.assertCountEqual(notified, [idle, busy])
            reassigned = db.execute("SELECT COUNT(*) FROM audit WHERE id>? AND order_id=? AND event='reassigned'",
                                    (audit_start, self.order_id)).fetchone()[0]
            self.assertEqual(reassigned, 1)
            self.assertEqual(db.execute('SELECT is_active FROM users WHERE id=?', (idle,)).fetchone()[0], 1)

    def test_inactive_individual_is_rejected_and_changes_nothing(self):
        self._seed_queue_state()
        with app.connect(self.fixture.db_path) as db:
            inactive = db.execute("SELECT id FROM users WHERE role='worker' AND brigade='B' ORDER BY id LIMIT 1").fetchone()[0]
            db.execute('UPDATE users SET is_active=0 WHERE id=?', (inactive,))
            db.commit()
        before = self._snapshot()
        status, body = self.master.call(self.path, 'POST', {'worker_id': inactive})
        self.assertEqual(status, 400, body)
        self.assertEqual(body['error'], 'Исполнитель не найден')
        self.assertEqual(self._snapshot(), before)

    def test_empty_brigade_is_409_not_500_and_changes_nothing(self):
        self._seed_queue_state()
        with app.connect(self.fixture.db_path) as db:
            db.execute("UPDATE users SET brigade='A' WHERE role='worker' AND brigade='B'")
            db.commit()
        before = self._snapshot()
        status, body = self.master.call(self.path, 'POST', {'brigade': 'B'})
        self.assertEqual(status, 409, body)
        self.assertEqual(body['error'], 'В бригаде нет активного исполнителя.')
        self.assertEqual(self._snapshot(), before)


if __name__ == '__main__':
    unittest.main()
