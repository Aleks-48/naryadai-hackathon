"""Temporal reports and explicit order/downtime links over the real local HTTP API."""
import unittest
import tempfile
from pathlib import Path
from tests import test_app as support
import server as app


class ReportingAcceptanceTest(unittest.TestCase):
    setUpClass = classmethod(support.LocalAPITest.setUpClass.__func__)
    tearDownClass = classmethod(support.LocalAPITest.tearDownClass.__func__)
    client = support.LocalAPITest.client
    create_order = support.LocalAPITest.create_order
    action = support.LocalAPITest.action

    def test_legacy_downtime_migration_preserves_unlinked_records(self):
        with tempfile.TemporaryDirectory(prefix="naryadai-downtime-migration-") as directory:
            root = Path(directory)
            db_path = root / "legacy.sqlite3"
            original_media = app.MEDIA
            app.MEDIA = root / "media"
            try:
                app.init_db(db_path)
                with app.connect(db_path) as db:
                    db.execute("DROP TABLE equipment_downtime")
                    db.execute("""CREATE TABLE equipment_downtime (id INTEGER PRIMARY KEY, equipment_id INTEGER NOT NULL,
                        started_at TEXT NOT NULL,ended_at TEXT NOT NULL,reason TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL UNIQUE,recorded_by INTEGER NOT NULL,created_at TEXT NOT NULL)""")
                    db.execute("""INSERT INTO equipment_downtime VALUES
                        (99,1,'2001-01-01T05:00:00Z','2001-01-01T06:00:00Z','Legacy interval',
                        'legacy-preserved-99',1,'2001-01-01T07:00:00Z')""")
                app.init_db(db_path)
                app.init_db(db_path)
                with app.connect(db_path) as db:
                    row = db.execute("SELECT * FROM equipment_downtime WHERE id=99").fetchone()
                    self.assertIsNone(row["order_id"])
                    self.assertEqual(row["reason"],"Legacy interval")
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM equipment_downtime").fetchone()[0],1)
                    self.assertFalse(db.execute("PRAGMA foreign_key_check").fetchall())
            finally:
                app.MEDIA = original_media

    def report(self, client, day, suffix=""):
        status, data = client.call(f"/api/reports?date_from={day}&date_to={day}"+suffix)
        self.assertEqual(status, 200, data)
        return data

    def test_independent_event_windows_current_load_and_filters(self):
        master = self.client("master01")
        worker = self.client("worker01")
        first = self.create_order(master, before_photo=False)["id"]
        second = self.create_order(master, before_photo=False)["id"]
        active = self.create_order(master, before_photo=False)["id"]
        day = "2001-01-01"
        with app.connect(self.db_path) as db:
            for oid, completed, closed in ((first,"05:59:59","14:00:00"),(second,"06:00:00","06:10:00")):
                db.execute("UPDATE orders SET status='closed',issued_at=?,completed_at=?,closed_at=?,labor_hours=2 WHERE id=?",
                    (day+"T07:00:00Z",day+"T"+completed+"Z",day+"T"+closed+"Z",oid))
            db.execute("UPDATE orders SET status='queued' WHERE id=?", (active,))
            db.commit()
        filters = f"&area_id={self.area_id}&equipment_id={self.equipment_id}&worker_id={self.worker_id}"
        result = self.report(master,day,filters+"&shift_code=A")
        self.assertEqual([r["id"] for r in result["items"]],[second])
        self.assertEqual(result["summary"]["issued"],2)
        self.assertEqual(result["summary"]["closed"],1)
        self.assertEqual(result["summary"]["labor_hours"],2)
        group = next(r for r in result["worker_totals"] if r["worker_id"] == self.worker_id)
        self.assertGreaterEqual(group["current_queued"],1)
        b = self.report(master,day,filters+"&shift_code=B")
        self.assertEqual(b["summary"]["completed"],0)
        self.assertEqual(b["summary"]["closed"],1)
        self.assertEqual(b["summary"]["current_active_orders"],result["summary"]["current_active_orders"])
        c = self.report(master,day,filters+"&shift_code=C")
        self.assertEqual([r["id"] for r in c["items"]],[first])
        self.assertEqual(sum(self.report(master,day,filters+"&shift_code="+s)["summary"]["completed"] for s in "ABC"),2)
        with app.connect(self.db_path) as db:
            other_area = db.execute("SELECT id FROM areas WHERE id<>? LIMIT 1",(self.area_id,)).fetchone()[0]
        self.assertEqual(self.report(master,day,f"&area_id={other_area}")["items"],[])
        self.assertEqual(self.report(worker,day,f"&worker_id={self.worker15_id}")["summary"]["current_active_orders"],0)
        self.assertEqual(self.report(self.client("master02"),day,filters)["items"],[])
        for value in ("-1","abc","1.5","9999999999","1%20OR%201=1"):
            self.assertEqual(master.call("/api/reports?equipment_id="+value)[0],400)

    def test_linked_downtime_rights_equipment_idempotency_and_card(self):
        master = self.client("master01")
        order = self.create_order(master,before_photo=False)
        body = {"equipment_id":self.equipment_id,"order_id":order["id"],"started_at":"2001-02-01T05:30:00Z",
            "ended_at":"2001-02-01T06:30:00Z","reason":"Учебная регистрация простоя","idempotency_key":"linked-downtime-001"}
        self.assertEqual(self.client("master02").call("/api/equipment/downtime","POST",body)[0],404)
        self.assertEqual(self.client("worker01").call("/api/equipment/downtime","POST",body)[0],403)
        with app.connect(self.db_path) as db:
            other_equipment = db.execute("SELECT id FROM equipment WHERE id<>? LIMIT 1",(self.equipment_id,)).fetchone()[0]
        self.assertEqual(master.call("/api/equipment/downtime","POST",{**body,"equipment_id":other_equipment})[0],400)
        for invalid in (True,0,-1,"1",1.5):
            self.assertEqual(master.call("/api/equipment/downtime","POST",{**body,"order_id":invalid})[0],400)
        self.assertEqual(master.call("/api/equipment/downtime","POST",body)[0],201)
        duplicate = master.call("/api/equipment/downtime","POST",body)
        self.assertEqual(duplicate[0],200); self.assertTrue(duplicate[1]["duplicate"])
        self.assertEqual(master.call("/api/equipment/downtime","POST",{**body,"order_id":None})[0],409)
        overlapping = {**body,"started_at":"2001-02-01T06:00:00Z","ended_at":"2001-02-01T07:00:00Z","idempotency_key":"linked-downtime-002"}
        self.assertEqual(master.call("/api/equipment/downtime","POST",overlapping)[0],201)
        unrelated = {**body,"order_id":None,"started_at":"2001-02-01T08:00:00Z","ended_at":"2001-02-01T09:00:00Z","idempotency_key":"unlinked-downtime-001"}
        self.assertEqual(master.call("/api/equipment/downtime","POST",unrelated)[0],201)
        for client in (master,self.client("worker01"),self.client("manager")):
            status,detail = client.call(f"/api/orders/{order['id']}")
            self.assertEqual(status,200,detail)
            self.assertEqual(detail["order"]["equipment_downtime"]["minutes"],90)
            self.assertEqual(len(detail["order"]["equipment_downtime"]["intervals"]),2)
        self.assertEqual(self.client("master02").call(f"/api/orders/{order['id']}")[0],404)
        filtered = self.report(master,"2001-02-01",f"&worker_id={self.worker_id}&shift_code=A")
        self.assertEqual(filtered["summary"]["equipment_downtime_minutes"],60)
        self.assertTrue(all(r["order_id"] == order["id"] for r in filtered["equipment_downtime_intervals"]))
        self.assertEqual(self.report(master,"2001-02-01")["summary"]["equipment_downtime_minutes"],150)

    def test_rating_shift_is_event_based_not_roster_filter(self):
        master = self.client("master01")
        oid = self.create_order(master,before_photo=False)["id"]
        day = "2001-03-01"
        with app.connect(self.db_path) as db:
            original_shift = db.execute("SELECT shift_code FROM users WHERE id=?",(self.worker_id,)).fetchone()[0]
            db.execute("UPDATE users SET shift_code='B' WHERE id=?",(self.worker_id,))
            db.execute("UPDATE orders SET status='closed',closed_at=?,completed_at=?,rating=4 WHERE id=?",
                (day+"T06:00:00Z",day+"T05:30:00Z",oid))
            for at in ("05:59:59","06:00:00","14:00:00","22:00:00"):
                db.execute("INSERT INTO audit(actor_id,order_id,event,payload_json,created_at) VALUES (?,?,'reject','{}',?)",
                    (self.worker_id,oid,day+"T"+at+"Z"))
            db.commit()
        try:
            result = master.call(f"/api/bootstrap?rating_from={day}&rating_to={day}&rating_shift=A")
            self.assertEqual(result[0],200,result[1])
            person = next(r for r in result[1]["members"] if r["id"] == self.worker_id)
            self.assertEqual(person["shift_code"],"B")
            self.assertEqual(person["rating_detail"]["evidence"]["closed"],1)
            self.assertEqual(person["rating_detail"]["evidence"]["rejections"],1)
            with app.connect(self.db_path) as db:
                self.assertEqual(app.worker_rating(db,self.worker_id,day,day,"B")["evidence"]["closed"],0)
                self.assertEqual(app.worker_rating(db,self.worker_id,day,day,"C")["evidence"]["rejections"],2)
            mine = self.client("worker01").call(f"/api/bootstrap?rating_from={day}&rating_to={day}&rating_shift=A")[1]["my_rating"]
            self.assertEqual(mine["factors"]["quality"],80)
            self.assertEqual(mine["shift_code"],"A")
            self.assertEqual(master.call("/api/bootstrap?rating_shift=invalid")[0],400)
        finally:
            with app.connect(self.db_path) as db:
                db.execute("UPDATE users SET shift_code=? WHERE id=?",(original_shift,self.worker_id))
                db.commit()

    def test_pauses_clipped_to_shift_for_unfinished_orders(self):
        master = self.client("master01")
        oid = self.create_order(master,before_photo=False)["id"]
        day = "2001-04-01"
        with app.connect(self.db_path) as db:
            # A previous completion survives a return for rework.
            db.execute("UPDATE orders SET status='paused',completed_at=? WHERE id=?",(day+"T05:00:00Z",oid))
            for event,at in (("pause","05:30:00"),("pause","05:45:00"),("resume","06:30:00"),("pause","21:30:00")):
                db.execute("INSERT INTO audit(actor_id,order_id,event,payload_json,created_at) VALUES (?,?,?,?,?)",
                    (self.worker_id,oid,event,"{}",day+"T"+at+"Z"))
            db.commit()
        self.assertEqual(self.report(master,day,"&shift_code=A")["summary"]["pause_minutes"],30)
        self.assertEqual(self.report(master,day,"&shift_code=B")["summary"]["pause_minutes"],30)
        self.assertEqual(self.report(master,day,"&shift_code=C")["summary"]["pause_minutes"],150)

    def test_refusals_stay_with_actor_after_reassignment(self):
        master = self.client("master01")
        oid = self.create_order(master,before_photo=False)["id"]
        day = "2001-05-01"
        with app.connect(self.db_path) as db:
            db.execute("INSERT INTO audit(actor_id,order_id,event,payload_json,created_at) VALUES (?,?,'reject','{}',?)",
                (self.worker_id,oid,day+"T07:00:00Z"))
            db.execute("UPDATE orders SET assigned_to=? WHERE id=?",(self.worker15_id,oid))
            db.commit()
        result = self.report(self.client("worker01"),day,f"&worker_id={self.worker_id}&equipment_id={self.equipment_id}&shift_code=A")
        self.assertEqual(result["summary"]["refusals"],1)
        self.assertEqual(result["worker_totals"][0]["worker_id"],self.worker_id)
        self.assertEqual(self.report(master,day,f"&worker_id={self.worker15_id}")["summary"]["refusals"],0)
