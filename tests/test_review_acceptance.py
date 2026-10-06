"""Acceptance regressions for synthetic references and separate AI/human scores."""
import json
import os
import unittest
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from tests import test_app as support
import server as app

MODEL = {"verdict":"accepted","summary":"Работа описана, результат указан.","issues":[],
         "confidence":0.95,"report_score":5,"score_reason":"Отчёт соответствует задаче и содержит результат.",
         "needs_master_attention":False}
SETTINGS = {"NARYADAI_LLM_ENABLED":"1","NARYADAI_LLM_API_KEY":"unit-test-key","NARYADAI_LLM_MODEL":"fixture",
            "NARYADAI_LLM_API_URL":"https://example.invalid/completions"}


class ReviewAcceptanceTest(unittest.TestCase):
    setUpClass = classmethod(support.LocalAPITest.setUpClass.__func__)
    tearDownClass = classmethod(support.LocalAPITest.tearDownClass.__func__)
    client = support.LocalAPITest.client
    create_order = support.LocalAPITest.create_order
    action = support.LocalAPITest.action

    def issuance_body(self):
        return {"title":"Комментарий при выдаче", "description":"Осмотреть насос и записать результат проверки.",
                "work_type":"planned", "priority":"normal", "area_id":self.area_id,
                "equipment_id":self.equipment_id, "worker_id":self.worker_id, "norm_hours":8}

    def test_issuance_comment_optional_strict_and_atomic(self):
        master = self.client("master01")
        def counts():
            with app.connect(self.db_path) as db:
                return tuple(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                             for table in ("orders", "audit", "photos", "notifications"))
        before = counts()
        for value in (None, True, 7, [], {}, "я"*1001):
            with self.subTest(value_type=type(value).__name__):
                status, result = master.call("/api/orders", "POST", {**self.issuance_body(), "issuance_comment":value})
                self.assertEqual(status, 400, result)
                self.assertIn("Комментарий", result["error"])
                self.assertEqual(counts(), before)
        for value in (None, "", "  ", "я"*1000):
            body = self.issuance_body()
            if value is not None:
                body["issuance_comment"] = value
            status, result = master.call("/api/orders", "POST", body)
            self.assertEqual(status, 201, result)
            self.assertEqual(result["order"]["issuance_comment"], (value or "").strip())
        status, _ = master.call("/api/orders", "POST", {**self.issuance_body(), "description":"", "issuance_comment":"Есть только комментарий"})
        self.assertEqual(status, 400, "optional comment must not replace the required problem description")

    def test_issuance_comment_audit_visibility_and_external_context(self):
        master, worker = self.client("master01"), self.client("worker01")
        comment = "<script>учебная заметка</script>\nКонтакт: private@example.invalid"
        status, result = master.call("/api/orders", "POST", {**self.issuance_body(), "issuance_comment":"  "+comment+"  "})
        self.assertEqual(status, 201, result)
        oid = result["order"]["id"]
        for client in (master, worker, self.client("manager")):
            status, detail = client.call(f"/api/orders/{oid}")
            self.assertEqual(status, 200, detail)
            self.assertEqual(detail["order"]["issuance_comment"], comment)
            issued = next(event for event in detail["history"] if event["event"] == "issued")
            self.assertEqual(issued["payload"]["issuance_comment"], comment)
        for name in ("worker15", "master02"):
            self.assertEqual(self.client(name).call(f"/api/orders/{oid}")[0], 404)
        for name in ("worker01", "manager"):
            self.assertEqual(self.client(name).call("/api/orders", "POST", self.issuance_body())[0], 403)
        with app.connect(self.db_path) as db:
            order = dict(db.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone())
        bounded = app._bounded_llm_review_context(order)
        self.assertNotIn("issuance_comment", bounded)
        self.assertNotIn("private@example.invalid", json.dumps(bounded))

    def test_legacy_issuance_comment_migration_is_nullable_and_repeatable(self):
        with tempfile.TemporaryDirectory(prefix="naryadai-issuance-migration-") as directory:
            root = Path(directory)
            path = root/"legacy.sqlite3"
            with patch.object(app, "MEDIA", root/"media"):
                app.init_db(path)
                with app.connect(path) as db:
                    before = [tuple(row) for row in db.execute("SELECT id,code,title,status,description FROM orders ORDER BY id")]
                    db.execute("ALTER TABLE orders DROP COLUMN issuance_comment")
                app.init_db(path)
                app.init_db(path)
                with app.connect(path) as db:
                    after = [tuple(row) for row in db.execute("SELECT id,code,title,status,description FROM orders ORDER BY id")]
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM orders WHERE issuance_comment IS NOT NULL").fetchone()[0], 0)
                self.assertEqual(before, after)

    def test_demo_dataset_inventory_three_months_and_four_patterns(self):
        with tempfile.TemporaryDirectory(prefix="naryadai-demo-acceptance-") as directory:
            root = Path(directory)
            fixed_now = datetime(2026,10,6,12,tzinfo=timezone.utc)
            with patch.object(app,"MEDIA",root/"media"),patch.object(app,"utcnow",return_value=fixed_now):
                app.init_db(root/"demo.sqlite3")
            with app.connect(root/"demo.sqlite3") as db:
                for table,count in (("areas",4),("equipment",25),("fault_codes",20),("materials",40),("orders",550)):
                    self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],count)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM users WHERE role='master'").fetchone()[0],2)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM users WHERE role='worker'").fetchone()[0],15)
                self.assertEqual(db.execute("SELECT COUNT(DISTINCT brigade) FROM users WHERE role='worker'").fetchone()[0],3)
                earliest,latest = db.execute("SELECT MIN(created_at),MAX(created_at) FROM orders WHERE code LIKE 'DEMO-%'").fetchone()
                self.assertGreaterEqual((app.parse_time(latest)-app.parse_time(earliest)).total_seconds(),90*86400)
                months = {r[0] for r in db.execute("SELECT DISTINCT substr(created_at,1,7) FROM orders WHERE code LIKE 'DEMO-%'")}
                self.assertTrue({"2026-07","2026-08","2026-09"}.issubset(months))
                patterns = db.execute("""SELECT o.title,e.code,o.work_type,COUNT(*) AS n FROM orders o
                    JOIN equipment e ON e.id=o.equipment_id WHERE o.code LIKE 'DEMO-%'
                    GROUP BY o.title,e.code,o.work_type ORDER BY e.code""").fetchall()
                self.assertEqual([(r["code"],r["work_type"],r["n"]) for r in patterns],
                    [("EQ-002","unscheduled",135),("EQ-003","unscheduled",135),
                     ("EQ-004","planned",135),("EQ-005","unscheduled",135)])
                states = {r[0] for r in db.execute("SELECT status FROM orders WHERE code LIKE 'LIVE-%'")}
                self.assertEqual(states,set(app.STATUS_LABELS))
                print(f"Verified synthetic seed: 550 orders; history {earliest} — {latest}; four patterns x 135, ten lifecycle examples.")

    def ready(self, master, worker, work_type="planned"):
        response = master.call("/api/orders","POST",{"title":"Учебная проверка насоса",
            "description":"Осмотреть соединение и проверить отсутствие течи.",
            "work_type":work_type,"priority":"normal","area_id":self.area_id,
            "equipment_id":self.equipment_id,"worker_id":self.worker_id,"norm_hours":8})
        self.assertEqual(response[0],201,response[1])
        oid = response[1]["order"]["id"]
        self.assertEqual(self.action(worker,oid,"accept")[0],200)
        self.assertEqual(self.action(worker,oid,"start")[0],200)
        self.assertEqual(self.action(worker,oid,"complete",
            completion_text="Выполнен осмотр соединения, закрепление восстановлено; течь устранена, результат записан.",
            fault_code_id=self.fault_id,labor_hours=2.5,materials=[],materials_not_used=True)[0],200)
        return oid

    def test_reference_is_bounded_anonymized_and_unknown_is_not_zero(self):
        reference = {"status":"synthetic_reference","is_synthetic":True,
            "source_name":"Catalogue token=PRIVATE_TOKEN","source_version":"v1",
            "labor":{"quantity":3,"actual_hours":2,"difference_hours":999},
            "materials_evidence_status":"reported_usage",
            "materials":[{"sku":"S-1","name":"Seal email: private@example.invalid","unit":"kg",
                "reference_quantity":0.002,"actual_quantity":0.001,"difference_quantity":999,
                "private":"PRIVATE_NESTED"}]*25,"instructions":"PRIVATE_INSTRUCTIONS","worker_id":1}
        bounded = app._bounded_llm_review_context({"norm_reference":reference})
        norm = bounded["norm_reference"]
        self.assertEqual(norm["labor"]["difference_hours"],-1)
        self.assertEqual(norm["materials"][0]["difference_quantity"],-0.001)
        self.assertEqual(norm["materials"][0]["actual_quantity"],0.001)
        self.assertEqual(len(norm["materials"]),20)
        self.assertIn("norm_reference.materials",bounded["truncated_fields"])
        self.assertFalse(norm["affects_rating"])
        encoded = json.dumps(bounded)
        for secret in ("PRIVATE_TOKEN","PRIVATE_NESTED","PRIVATE_INSTRUCTIONS","private@example.invalid","worker_id"):
            self.assertNotIn(secret,encoded)
        for evidence in ("unknown","conflict"):
            norm = app._bounded_llm_review_context({"norm_reference":{**reference,"materials_evidence_status":evidence}})["norm_reference"]
            self.assertIsNone(norm["materials"][0]["difference_quantity"])
            if evidence == "unknown": self.assertIsNone(norm["materials"][0]["actual_quantity"])
        for invalid in (None,[],{"status":"approved","is_synthetic":False},{"status":"synthetic_reference","is_synthetic":False}):
            norm = app._bounded_llm_review_context({"norm_reference":invalid})["norm_reference"]
            self.assertEqual(norm["status"],"unknown")
            self.assertEqual(norm["materials"],[])

    def test_score_schema_validates_null_integer_range_and_reason(self):
        with patch.dict(os.environ,SETTINGS):
            for value in (1,5,None):
                with patch.object(app,"llm_json_completion",return_value=({**MODEL,"report_score":value},"fixture")):
                    result = app.llm_review("Проверена задача; наблюдаемый результат записан.")
                    self.assertEqual(result["mode"],"llm:fixture")
                    self.assertEqual(result["report_score"],value)
            invalids = [{**MODEL,"report_score":v} for v in (True,False,0,6,4.5,"5",[],float("nan"))]
            invalids += [{**MODEL,"score_reason":v} for v in (""," ",None,12)]
            invalids += [{k:v for k,v in MODEL.items() if k!="report_score"}, {**MODEL,"extra":"forbidden"}]
            for invalid in invalids:
                with patch.object(app,"llm_json_completion",return_value=(invalid,"fixture")):
                    result = app.llm_review("Проверена задача; наблюдаемый результат записан.")
                    self.assertEqual(result["mode"],"rules-only: adapter_error",invalid)
                    self.assertIsNone(result["report_score"])
        with patch.dict(os.environ,{**SETTINGS,"NARYADAI_LLM_ENABLED":"0"}),patch.object(app,"llm_json_completion") as external:
            result = app.llm_review("Выполнена проверка, результат записан.")
            external.assert_not_called()
            self.assertIsNone(result["report_score"])

    def test_rules_reference_snapshot_survives_catalog_change(self):
        master,worker = self.client("master01"),self.client("worker01")
        oid = self.ready(master,worker)
        checked = self.action(worker,oid,"ai_check")
        self.assertEqual(checked[0],200,checked[1])
        review = json.loads(checked[1]["order"]["ai_result"])
        self.assertEqual(review["norm_reference"]["status"],"synthetic_reference")
        self.assertEqual(review["time_check"]["actual_hours"],2.5)
        self.assertFalse(review["time_check"]["compared_to_approved_norm"])
        self.assertEqual(review["materials_check"]["evidence_status"],"confirmed_not_used")
        self.assertTrue(all(m["actual_quantity"] == 0 for m in review["materials_check"]["reference_items"]))
        self.assertIsNone(review["report_score"])
        self.assertIsNone(checked[1]["order"]["rating"])
        with app.connect(self.db_path) as db:
            equipment_type = db.execute("SELECT equipment_type FROM equipment WHERE id=?",(self.equipment_id,)).fetchone()[0]
            db.execute("UPDATE equipment SET equipment_type='unknown' WHERE id=?",(self.equipment_id,))
            db.commit()
        try:
            detail = worker.call(f"/api/orders/{oid}")[1]["order"]
            self.assertEqual(detail["norm_reference"]["status"],"unknown")
            self.assertEqual(json.loads(detail["ai_result"])["norm_reference"],review["norm_reference"])
            unknown_id = self.ready(master,worker)
            unknown = self.action(worker,unknown_id,"ai_check")[1]["order"]
            self.assertEqual(unknown["status"],checked[1]["order"]["status"])
            self.assertEqual(json.loads(unknown["ai_result"])["norm_reference"]["status"],"unknown")
        finally:
            with app.connect(self.db_path) as db:
                db.execute("UPDATE equipment SET equipment_type=? WHERE id=?",(equipment_type,self.equipment_id))
                db.commit()

    def test_llm_receives_reference_but_never_sets_human_rating(self):
        master,worker = self.client("master01"),self.client("worker01")
        oid = self.ready(master,worker)
        with patch.dict(os.environ,SETTINGS),patch.object(app,"llm_json_completion",return_value=(dict(MODEL),"fixture")) as model:
            response = self.action(worker,oid,"ai_check")
        self.assertEqual(response[0],200,response[1])
        prompt = model.call_args.args[0]
        payload = json.loads(prompt.split("UNTRUSTED_JSON_DATA_BEGIN\n")[1].split("\nUNTRUSTED_JSON_DATA_END")[0])
        reference = payload["order_context"]["norm_reference"]
        self.assertEqual(reference["status"],"synthetic_reference")
        self.assertEqual(reference["labor"]["actual_hours"],2.5)
        self.assertNotIn("material_id",json.dumps(reference))
        self.assertIn("Do not reduce the score or change the verdict solely",prompt)
        order = response[1]["order"]
        self.assertIsNone(order["rating"])
        review = json.loads(order["ai_result"])
        self.assertEqual(review["report_score"],5)
        self.assertEqual(review["verdict"],"accepted")
        self.assertEqual(self.action(worker,oid,"close",rating=5,closure_comment="Моя оценка")[0],403)

    def test_closure_requires_explicit_rating_and_is_atomic_auditable(self):
        master,worker = self.client("master01"),self.client("worker01")
        oid = self.ready(master,worker)
        self.assertEqual(self.action(worker,oid,"ai_check")[0],200)
        for invalid in (None,True,False,0,6,4.5,"5"):
            result = self.action(master,oid,"close",rating=invalid,closure_comment="Проверено мастером.")
            self.assertEqual(result[0],400,result[1])
            order = worker.call(f"/api/orders/{oid}")[1]["order"]
            self.assertEqual(order["status"],"ai_review")
            self.assertIsNone(order["rating"])
        self.assertEqual(self.action(master,oid,"close",closure_comment="Проверено мастером.")[0],400)
        self.assertEqual(self.action(self.client("master02"),oid,"close",rating=4,closure_comment="Проверено мастером.")[0],404)
        self.assertEqual(self.action(self.client("manager"),oid,"close",rating=4,closure_comment="Проверено мастером.")[0],403)
        other_session = self.client("master01")
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda c:self.action(c,oid,"close",rating=4,closure_comment="Принято после проверки результата."),[master,other_session]))
        self.assertEqual(sorted(r[0] for r in outcomes),[200,409])
        detail = worker.call(f"/api/orders/{oid}")[1]
        self.assertEqual(detail["order"]["rating"],4)
        self.assertEqual(detail["order"]["rating_reason"],"Принято после проверки результата.")
        closures = [e for e in detail["history"] if e["event"]=="close"]
        self.assertEqual(len(closures),1)
        self.assertEqual(closures[0]["payload"]["rating"],4)
        self.assertEqual(closures[0]["payload"]["rating_source"],"master")
        for invalid in (True,4.5,"5"):
            self.assertEqual(master.call(f"/api/orders/{oid}/rating","POST",{"rating":invalid,"reason":"Попытка неверной оценки"})[0],400)
        self.assertEqual(master.call(f"/api/orders/{oid}/rating","POST",{"rating":3,"reason":"Уточнение после проверки записей"})[0],200)
        detail = worker.call(f"/api/orders/{oid}")[1]
        self.assertEqual(detail["order"]["rating"],3)
        adjustment = next(e for e in reversed(detail["history"]) if e["event"]=="rating_adjusted")
        self.assertEqual(adjustment["payload"]["previous_rating"],4)
        self.assertEqual(adjustment["payload"]["previous_reason"],"Принято после проверки результата.")

    def test_high_model_score_cannot_bypass_mandatory_photo(self):
        master,worker = self.client("master01"),self.client("worker01")
        oid = self.ready(master,worker,"unscheduled")
        with patch.dict(os.environ,SETTINGS),patch.object(app,"llm_json_completion",return_value=(dict(MODEL),"fixture")):
            checked = self.action(worker,oid,"ai_check")[1]["order"]
        self.assertEqual(checked["status"],"rework")
        self.assertEqual(json.loads(checked["ai_result"])["report_score"],5)
        self.assertIsNone(checked["rating"])
        self.assertEqual(self.action(master,oid,"close",rating=5,closure_comment="Попытка закрытия без фотографии.")[0],409)
