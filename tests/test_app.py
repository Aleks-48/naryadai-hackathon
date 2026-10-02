from __future__ import annotations

import base64
import io
import http.cookiejar
import json
import os
import struct
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import unittest
import unittest.mock
import urllib.error
import urllib.request
from pathlib import Path

import server as app
from PIL import Image, ImageDraw


def make_photo(fmt="PNG", size=(96,96), capture_time=None, offset=None, background=(56,72,88)):
    image=Image.new("RGB",size,background)
    draw=ImageDraw.Draw(image)
    width,height=size
    draw.rectangle((width//8,height//8,width*3//4,height//2),fill=(178,132,72))
    draw.line((0,height-1,width-1,0),fill=(220,220,220),width=max(1,width//32))
    exif=Image.Exif()
    if capture_time:
        exif[36867]=capture_time
        if offset: exif[36881]=offset
    output=io.BytesIO()
    options={"format":fmt}
    if fmt=="JPEG": options["quality"]=88
    if capture_time: options["exif"]=exif
    image.save(output,**options)
    return output.getvalue()


PNG_1PX=base64.b64encode(make_photo()).decode()


class Client:
    def __init__(self, base: str):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf = ""

    def call(self, path: str, method: str = "GET", body: dict | None = None, csrf: bool = True):
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        if method != "GET" and csrf and self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=10) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read()
        content = json.loads(raw) if raw else {}
        return status, content

    def login(self, username: str, password: str = "demo123"):
        status, body = self.call("/api/login", "POST", {"username": username, "password": password}, csrf=False)
        if status != 200:
            raise AssertionError(f"login failed ({status}): {body}")
        self.csrf = body["user"]["csrf"]
        return body["user"]

    def call_bytes(self, path: str):
        request=urllib.request.Request(self.base+path,headers={"Accept":"image/*"})
        try:
            with self.opener.open(request,timeout=10) as response: return response.status,response.read()
        except urllib.error.HTTPError as error:
            return error.code,error.read()


class LocalAPITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="naryadai-test-")
        root = Path(cls.temp.name)
        cls.db_path = root / "test.sqlite3"
        app.MEDIA = root / "media"
        env = {"NARYADAI_LLM_API_URL": "", "NARYADAI_LLM_API_KEY": "", "NARYADAI_LLM_MODEL": ""}
        cls.env_patch = unittest.mock.patch.dict(os.environ, env)
        cls.env_patch.start()
        app.init_db(cls.db_path)
        app.patch_get_photo()
        app.patch_cookie_login()
        cls.httpd = app.ThreadingHTTPServer(("127.0.0.1", 0), app.AppHandler)
        cls.httpd.daemon_threads = True
        cls.httpd.db_path = cls.db_path
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        with app.connect(cls.db_path) as db:
            cls.area_id = db.execute("SELECT id FROM areas ORDER BY id LIMIT 1").fetchone()[0]
            cls.equipment_id = db.execute("SELECT id FROM equipment WHERE area_id=? LIMIT 1", (cls.area_id,)).fetchone()[0]
            cls.fault_id = db.execute("SELECT id FROM fault_codes ORDER BY id LIMIT 1").fetchone()[0]
            cls.worker_id = db.execute("SELECT id FROM users WHERE username='worker01'").fetchone()[0]
            cls.worker15_id = db.execute("SELECT id FROM users WHERE username='worker15'").fetchone()[0]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=3)
        cls.env_patch.stop()
        cls.temp.cleanup()

    def client(self, name: str) -> Client:
        c = Client(self.base)
        c.login(name)
        return c

    def create_order(self, master: Client, worker_id: int | None = None, priority: str = "normal") -> dict:
        status, response = master.call("/api/orders", "POST", {
            "title": "Проверка насосного узла",
            "description": "Проверить вибрацию, закрепить узел и записать результат наблюдения.",
            "work_type": "unscheduled", "priority": priority, "area_id": self.area_id,
            "equipment_id": self.equipment_id, "worker_id": worker_id or self.worker_id,
            "norm_hours": 6,
        })
        self.assertEqual(status, 201, response)
        return response["order"]

    def action(self, client: Client, order_id: int, action: str, **kwargs):
        return client.call(f"/api/orders/{order_id}/action", "POST", {"action": action, **kwargs})

    def upload(self, client: Client, order_id: int, raw: bytes, mime="image/png", name="photo.png"):
        payload={"phase":"after","file_name":name,"data_url":f"data:{mime};base64,"+base64.b64encode(raw).decode()}
        return client.call(f"/api/orders/{order_id}/photos","POST",payload)

    def close_planned_order(self, master: Client, worker: Client, title="Плановая проверка узла") -> int:
        response=master.call("/api/orders","POST",{"title":title,"description":"Плановый осмотр и обслуживание оборудования.",
            "work_type":"planned","priority":"planned","area_id":self.area_id,"equipment_id":self.equipment_id,
            "worker_id":self.worker_id,"norm_hours":8})
        self.assertEqual(response[0],201,response[1]); oid=response[1]["order"]["id"]
        self.assertEqual(self.action(worker,oid,"accept")[0],200)
        self.assertEqual(self.action(worker,oid,"start")[0],200)
        report="Выполнена проверка соединения и регулировка; работа стабильна, отклонений не обнаружено."
        self.assertEqual(self.action(worker,oid,"complete",completion_text=report,fault_code_id=self.fault_id,
            labor_hours=1.0,materials=[],materials_not_used=True)[0],200)
        checked=self.action(worker,oid,"ai_check")
        self.assertEqual(checked[1]["order"]["status"],"ai_review",checked[1])
        closed=self.action(master,oid,"close")
        self.assertEqual(closed[0],200,closed[1])
        return oid

    def test_full_workflow_permissions_ai_rework_and_photo_upload(self):
        master = self.client("master01")
        worker = self.client("worker01")
        other_worker = self.client("worker02")
        other_master = self.client("master02")
        manager = self.client("manager")
        order = self.create_order(master)
        order_id = order["id"]

        # Data scope and CSRF are enforced by the server on every request.
        self.assertEqual(worker.call(f"/api/orders/{order_id}")[0], 200)
        self.assertEqual(other_worker.call(f"/api/orders/{order_id}")[0], 404)
        self.assertEqual(other_master.call(f"/api/orders/{order_id}")[0], 404)
        self.assertEqual(other_worker.call(f"/api/orders/{order_id}/assign", "POST", {"worker_id": self.worker_id})[0], 403)
        self.assertEqual(manager.call("/api/orders", "POST", {})[0], 403)
        self.assertEqual(worker.call(f"/api/orders/{order_id}/action", "POST", {"action":"accept"}, csrf=False)[0], 403)
        self.assertEqual(worker.call("/api/audit")[0], 403)

        # Graph: issued → queued → accepted → in progress; reason-required pause/resume.
        self.assertEqual(self.action(worker,order_id,"queue")[0],200)
        self.assertEqual(self.action(worker,order_id,"accept")[1]["order"]["status"],"accepted")
        self.assertEqual(self.action(worker,order_id,"start")[1]["order"]["status"],"in_progress")
        self.assertEqual(self.action(worker,order_id,"pause")[0],400)
        self.assertEqual(self.action(worker,order_id,"pause",reason="Ожидание запчасти")[1]["order"]["status"],"paused")
        self.assertEqual(self.action(worker,order_id,"resume")[1]["order"]["status"],"in_progress")
        self.assertEqual(self.action(worker,order_id,"complete",completion_text="Коротко")[0],400)

        report = "Выполнена замена уплотнения и проверена работа насоса; течь устранена, результат стабилен."
        completed = self.action(worker,order_id,"complete",completion_text=report,fault_code_id=self.fault_id,
                                 labor_hours=1.5,materials=[],materials_not_used=True)
        self.assertEqual(completed[0],200,completed[1])
        self.assertEqual(completed[1]["order"]["status"],"executed")
        reviewed = self.action(worker,order_id,"ai_check")
        self.assertEqual(reviewed[0],200,reviewed[1])
        self.assertEqual(reviewed[1]["order"]["status"],"rework")
        first_review=json.loads(reviewed[1]["order"]["ai_result"])
        self.assertEqual(first_review["mode"],"rules-only: configuration_missing")
        self.assertEqual(first_review["verdict"],"rework")
        self.assertTrue(any("фото" in issue.lower() for issue in first_review["issues"]))
        self.assertEqual(self.action(master,order_id,"close",reason="Принято")[0],409)

        # Rework cycle; binary content, digest duplicate detection and upload latency.
        self.assertEqual(self.action(worker,order_id,"start")[1]["order"]["status"],"in_progress")
        workflow_png=base64.b64encode(make_photo(background=(240,220,10))).decode()
        photo_payload={"phase":"after","file_name":"tiny.png","data_url":"data:image/png;base64,"+workflow_png}
        started=time.perf_counter()
        uploaded=worker.call(f"/api/orders/{order_id}/photos","POST",photo_payload)
        upload_seconds=time.perf_counter()-started
        self.assertEqual(uploaded[0],201,uploaded[1])
        self.assertLess(upload_seconds,10)
        duplicate=worker.call(f"/api/orders/{order_id}/photos","POST",photo_payload)
        self.assertEqual(duplicate[0],201,duplicate[1])
        self.assertTrue(duplicate[1]["photo"]["duplicate"])
        report2=self.action(worker,order_id,"complete",completion_text=report,fault_code_id=self.fault_id,
                            labor_hours=1.5,materials=[],materials_not_used=True)
        self.assertEqual(report2[0],200,report2[1])
        second_review=self.action(worker,order_id,"ai_check")
        self.assertEqual(second_review[1]["order"]["status"],"ai_review")
        second_json=json.loads(second_review[1]["order"]["ai_result"])
        self.assertEqual(second_json["verdict"],"comments")
        self.assertEqual(second_json["photo_check"]["verifiability_score"],3)
        self.assertTrue(second_json["master_confirmation_required"])
        self.assertEqual(self.action(master,order_id,"close")[0],400)
        closed=self.action(master,order_id,"close",reason="Фото проверено мастером; дата EXIF неизвестна.")
        self.assertEqual(closed[0],200,closed[1])
        self.assertEqual(closed[1]["order"]["status"],"closed")

        rated=master.call(f"/api/orders/{order_id}/rating","POST",{"rating":5,"reason":"Работа аккуратная и результат подтверждён.","repeat_confirmed":False})
        self.assertEqual(rated[0],200,rated[1])
        visible=worker.call(f"/api/orders/{order_id}")[1]["order"]
        self.assertEqual(visible["rating"],5)
        self.assertEqual(visible["photos"][0]["phase"],"after")
        audit=master.call("/api/audit")[1]["items"]
        names={r["event"] for r in audit if r["order_code"]==order["code"]}
        self.assertTrue({"queue","accept","start","pause","resume","complete","ai_check","close","rating_adjusted","photo_uploaded"}.issubset(names))
        self.assertGreaterEqual(upload_seconds,0)
        print(f"\nMeasured local upload request: {upload_seconds:.3f}s (limit 10s)")

    def test_polling_visibility_with_two_real_http_sessions(self):
        master=self.client("master01"); worker=self.client("worker15")
        initial_poll=threading.Event(); seen=threading.Event(); stop=threading.Event(); measure={}
        def poll_worker():
            while not stop.is_set():
                _,body=worker.call("/api/bootstrap")
                if measure.get("code") and any(o["code"]==measure["code"] for o in body.get("orders",[])):
                    measure["seen_at"]=time.perf_counter();seen.set();return
                initial_poll.set()
                if stop.wait(4):return
        poller=threading.Thread(target=poll_worker,daemon=True);poller.start()
        self.assertTrue(initial_poll.wait(5),"worker bootstrap did not respond")
        issued=self.create_order(master,self.worker15_id)
        measure["code"]=issued["code"];measure["issued_at"]=time.perf_counter()
        # Force one immediate API check: the second session reads the persisted state.
        status,body=worker.call("/api/bootstrap")
        measure["api_seen"]=time.perf_counter()
        self.assertEqual(status,200)
        self.assertTrue(any(o["code"]==issued["code"] for o in body["orders"]))
        self.assertLess(measure["api_seen"]-measure["issued_at"],5)
        stop.set();poller.join(timeout=1)
        print(f"Measured cross-session HTTP visibility: {(measure['api_seen']-measure['issued_at']):.3f}s (limit 5s)")

    def test_escalations_are_idempotent_and_stop_at_executed(self):
        master=self.client("master01");order=self.create_order(master,priority="normal");oid=order["id"]
        now=app.utcnow()
        with app.connect(self.db_path) as db:
            db.execute("UPDATE orders SET created_at=?,issued_at=?,due_at=? WHERE id=?",
                       (app.iso(now-app.timedelta(minutes=20)),app.iso(now-app.timedelta(minutes=11)),app.iso(now-app.timedelta(minutes=2)),oid))
            app.maybe_escalate(db);app.maybe_escalate(db)
            escalations=db.execute("SELECT COUNT(*) FROM audit WHERE order_id=? AND event='acceptance_escalated'",(oid,)).fetchone()[0]
            overdue=db.execute("SELECT COUNT(*) FROM audit WHERE order_id=? AND event='deadline_escalated'",(oid,)).fetchone()[0]
            notifications=db.execute("SELECT COUNT(*) FROM notifications WHERE order_id=?",(oid,)).fetchone()[0]
            self.assertEqual((escalations,overdue),(1,1))
            self.assertEqual(notifications,5) # initial issue + two recipients per acceptance/deadline escalation
            db.execute("UPDATE orders SET status='executed' WHERE id=?",(oid,))
            app.maybe_escalate(db)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM audit WHERE order_id=? AND event='deadline_repeat'",(oid,)).fetchone()[0],0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM audit WHERE order_id=? AND event='deadline_escalated'",(oid,)).fetchone()[0],1)

        emergency=self.create_order(master,priority="emergency"); eid=emergency["id"]
        with app.connect(self.db_path) as db:
            db.execute("UPDATE orders SET issued_at=?,due_at=? WHERE id=?",
                       (app.iso(now-app.timedelta(minutes=4)),app.iso(now+app.timedelta(minutes=8)),eid))
            app.maybe_escalate(db);app.maybe_escalate(db)
            event=db.execute("SELECT payload_json FROM audit WHERE order_id=? AND event='acceptance_escalated'",(eid,)).fetchone()
            self.assertEqual(json.loads(event[0])["threshold_minutes"],3)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM audit WHERE order_id=? AND event='deadline_reminder'",(eid,)).fetchone()[0],1)

    def test_exact_similar_exif_and_role_scoped_photo_files(self):
        master=self.client("master01");worker=self.client("worker01")
        other_worker=self.client("worker02");other_master=self.client("master02");manager=self.client("manager")
        order=self.create_order(master);oid=order["id"]
        self.assertEqual(self.action(worker,oid,"accept")[0],200);self.assertEqual(self.action(worker,oid,"start")[0],200)

        captured=make_photo("JPEG",capture_time="2026:10:02 17:40:00",offset="+00:00",background=(16,196,205))
        first=self.upload(worker,oid,captured,"image/jpeg","../../photo.jpg")
        self.assertEqual(first[0],201,first[1]);self.assertEqual(first[1]["photo"]["verifiability_score"],5)
        self.assertEqual(first[1]["photo"]["capture_datetime"],"2026-10-02T17:40:00+00:00")
        duplicate=self.upload(worker,oid,captured,"image/jpeg","reuse.jpg")
        self.assertEqual(duplicate[1]["photo"]["duplicate_type"],"exact")
        self.assertEqual(duplicate[1]["photo"]["verifiability_score"],1)

        with Image.open(io.BytesIO(captured)) as original:
            resized=original.resize((83,83),Image.Resampling.LANCZOS)
            output=io.BytesIO();resized.save(output,format="JPEG",quality=62)
        similar=self.upload(worker,oid,output.getvalue(),"image/jpeg","resized.jpg")
        self.assertEqual(similar[0],201,similar[1]);self.assertEqual(similar[1]["photo"]["duplicate_type"],"similar")
        self.assertEqual(similar[1]["photo"]["verifiability_score"],2)
        distinct=self.upload(worker,oid,make_photo("PNG",background=(15,25,225)),"image/png","different.png")
        self.assertEqual(distinct[0],201,distinct[1]);self.assertEqual(distinct[1]["photo"]["duplicate_type"],"none")
        self.assertEqual(distinct[1]["photo"]["capture_time_status"],"absent")

        photo_id=first[1]["photo"]["id"]
        self.assertEqual(worker.call_bytes(f"/api/photos/{photo_id}")[0],200)
        self.assertEqual(other_worker.call_bytes(f"/api/photos/{photo_id}")[0],404)
        self.assertEqual(other_master.call_bytes(f"/api/photos/{photo_id}")[0],404)
        self.assertEqual(manager.call_bytes(f"/api/photos/{photo_id}")[0],200)
        self.assertEqual(self.upload(manager,oid,make_photo())[0],403)
        with app.connect(self.db_path) as db:
            stored=db.execute("SELECT file_path,file_name FROM photos WHERE id=?",(photo_id,)).fetchone()
            self.assertEqual(Path(stored["file_path"]).parent.resolve(),app.MEDIA.resolve())
            self.assertNotIn("/",stored["file_name"]);self.assertNotIn("\\\\",stored["file_name"])
            outside=Path(self.temp.name)/"private.txt";outside.write_text("should never be served",encoding="utf-8")
            db.execute("UPDATE photos SET file_path=? WHERE id=?",(str(outside),photo_id))
        self.assertEqual(manager.call_bytes(f"/api/photos/{photo_id}")[0],404)

    def test_unsafe_photo_inputs_and_upload_limit(self):
        master=self.client("master01");worker=self.client("worker01")
        order=self.create_order(master);oid=order["id"]
        self.assertEqual(self.action(worker,oid,"accept")[0],200);self.assertEqual(self.action(worker,oid,"start")[0],200)
        png=make_photo()
        self.assertEqual(self.upload(worker,oid,png,"image/jpeg")[0],400) # Declared MIME differs from decoded format.
        self.assertEqual(self.upload(worker,oid,b"<script>alert(1)</script>","image/png")[0],400)
        svg=b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
        self.assertEqual(self.upload(worker,oid,svg,"image/svg+xml")[0],400)
        oversized_header=bytearray(png);oversized_header[16:24]=struct.pack(">II",5000,5000)
        self.assertEqual(self.upload(worker,oid,bytes(oversized_header))[0],400)
        too_many=b"\x89PNG\r\n\x1a\n"+b"x"*4_000_001
        self.assertEqual(self.upload(worker,oid,too_many)[0],413)
        with app.connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM photos WHERE order_id=?",(oid,)).fetchone()[0],0)

    def test_session_expiry_and_atomic_duplicate_action_race(self):
        master=self.client("master01");worker=self.client("worker01")
        order=self.create_order(master);oid=order["id"]
        cookie=next(iter(worker.jar)).value
        token_hash=app.hashlib.sha256(cookie.encode()).hexdigest()
        with app.connect(self.db_path) as db:
            db.execute("UPDATE sessions SET expires_at=? WHERE token_hash=?",(app.iso(app.utcnow()-timedelta(seconds=1)),token_hash))
        self.assertEqual(worker.call("/api/me")[0],401)

        fresh=self.client("worker01"); cookie=next(iter(fresh.jar)).value; csrf=fresh.csrf
        payload=json.dumps({"action":"accept"}).encode()
        def accept_once(_):
            req=urllib.request.Request(fresh.base+f"/api/orders/{oid}/action",data=payload,method="POST",
                headers={"Content-Type":"application/json","Cookie":f"naryadai_session={cookie}","X-CSRF-Token":csrf})
            try:
                with urllib.request.urlopen(req,timeout=10) as response: return response.status
            except urllib.error.HTTPError as error: return error.code
        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses=list(pool.map(accept_once,range(8)))
        self.assertEqual(statuses.count(200),1,statuses)
        self.assertEqual(statuses.count(409),7,statuses)
        with app.connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM audit WHERE order_id=? AND event='accept'",(oid,)).fetchone()[0],1)

    def test_rating_repeat_window_and_justified_refusal(self):
        master=self.client("master01");worker=self.client("worker01");other_master=self.client("master02");manager=self.client("manager")
        with app.connect(self.db_path) as db:
            old=app.iso(app.utcnow()-timedelta(days=31))
            db.execute("UPDATE orders SET completed_at=?,closed_at=? WHERE status='closed'",(old,old))
        previous=self.close_planned_order(master,worker,"Повтор · первый плановый наряд")
        current=self.close_planned_order(master,worker,"Повтор · второй плановый наряд")
        with app.connect(self.db_path) as db:
            current_created=app.parse_time(db.execute("SELECT created_at FROM orders WHERE id=?",(current,)).fetchone()[0])
            outside=app.iso(current_created-timedelta(days=7,seconds=1))
            db.execute("UPDATE orders SET completed_at=?,closed_at=? WHERE id=?",(outside,outside,previous))
        endpoint=f"/api/orders/{current}/repeat-link"
        payload={"previous_order_id":previous,"reason":"Мастер сверил повторный симптом и код неисправности."}
        self.assertEqual(other_master.call(endpoint,"POST",payload)[0],404)
        self.assertEqual(worker.call(endpoint,"POST",payload)[0],403)
        self.assertEqual(manager.call(endpoint,"POST",payload)[0],403)
        self.assertEqual(master.call(endpoint,"POST",{"previous_order_id":previous,"reason":"x"})[0],400)
        self.assertEqual(master.call(endpoint,"POST",payload)[0],409)
        with app.connect(self.db_path) as db:
            boundary=app.iso(current_created-timedelta(days=7))
            db.execute("UPDATE orders SET completed_at=?,closed_at=? WHERE id=?",(boundary,boundary,previous))
        linked=master.call(endpoint,"POST",payload)
        self.assertEqual(linked[0],200,linked[1]);self.assertEqual(linked[1]["attributed_worker_id"],self.worker_id)
        self.assertEqual(master.call(endpoint,"POST",payload)[0],409)
        detail=master.call(f"/api/orders/{current}")[1]
        self.assertEqual(detail["repeat_links"][0]["reason"],payload["reason"])
        self.assertTrue(detail["repeat_links"][0]["active"])
        with app.connect(self.db_path) as db:
            rating=app.worker_rating(db,self.worker_id)
            self.assertEqual(rating["evidence"]["confirmed_repeat_failures"],1)
            self.assertEqual(rating["factors"]["rework_repeat"],50.0)
            self.assertTrue(rating["evidence"]["repeat_attributions"][0]["linked_by"])
        # A legacy checkbox passed through the old rating API has no attribution or penalty semantics.
        self.assertEqual(master.call(f"/api/orders/{current}/rating","POST",{"rating":4,"reason":"Оценка мастера подтверждена проверкой.","repeat_confirmed":False})[0],200)
        revoke=f"/api/orders/{current}/repeat-link/revoke"
        self.assertEqual(master.call(revoke,"POST",{"reason":"x"})[0],400)
        revoked=master.call(revoke,"POST",{"reason":"Связь отменена после повторной проверки фактов."})
        self.assertEqual(revoked[0],200,revoked[1])
        with app.connect(self.db_path) as db:
            rating=app.worker_rating(db,self.worker_id)
            self.assertEqual(rating["evidence"]["confirmed_repeat_failures"],0)
            self.assertEqual(rating["factors"]["rework_repeat"],100.0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM audit WHERE event IN ('repeat_link_created','repeat_link_attributed','repeat_link_revoked','repeat_link_attribution_revoked')").fetchone()[0],4)

        refused=self.create_order(master)
        reason="Нет допуска к работе: инструктаж и внешняя подпись не оформлены."
        self.assertEqual(self.action(worker,refused["id"],"reject",reason=reason)[0],200)
        classify={"unjustified_refusal":False,"reason":"Причина принята мастером как обоснованная."}
        self.assertEqual(master.call(f"/api/orders/{refused['id']}/rating","POST",classify)[0],200)
        self.assertEqual(master.call(f"/api/orders/{refused['id']}/rating","POST",classify)[0],200)
        with app.connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM rejection_reviews WHERE order_id=?",(refused["id"],)).fetchone()[0],1)
            score=app.worker_rating(db,self.worker_id)
            self.assertEqual(score["factors"]["unjustified_refusal"],100.0)
            self.assertEqual(score["evidence"]["unjustified_rejections"],0)

    def test_model_low_confidence_explicitly_requires_master(self):
        model={"mode":"external-test","summary":"test","issues":[],"verdict":"accepted","confidence":0.35}
        with unittest.mock.patch.object(app,"llm_review",return_value=model):
            result=app.complete_review("Работа выполнена и результат стабилен.",[],1,1.0,"planned")
        self.assertEqual(result["verdict"],"comments")
        self.assertTrue(result["needs_master_attention"])
        self.assertTrue(result["master_confirmation_required"])
        self.assertTrue(any("низкую уверенность" in issue for issue in result["issues"]))

    def test_rejection_reassignment_cancellation_and_group_offer(self):
        master=self.client("master01");worker=self.client("worker01");replacement=self.client("worker02")
        order=self.create_order(master)
        self.assertEqual(self.action(worker,order["id"],"reject")[0],400)
        rejected=self.action(worker,order["id"],"reject",reason="Нет материалов на складе")
        self.assertEqual(rejected[1]["order"]["status"],"rejected")
        moved=master.call(f"/api/orders/{order['id']}/assign","POST",{"worker_id":int(replacement.call("/api/me")[1]["user"]["id"])})
        self.assertEqual(moved[0],200,moved[1])
        self.assertEqual(replacement.call(f"/api/orders/{order['id']}")[1]["order"]["status"],"issued")
        # The original executor retains read access to the recorded refusal.
        self.assertEqual(worker.call(f"/api/orders/{order['id']}")[0],200)
        self.assertEqual(master.call(f"/api/orders/{order['id']}/priority","POST",{"priority":"emergency"})[0],200)
        self.assertEqual(master.call(f"/api/orders/{order['id']}/priority","POST",{"priority":"bad"})[0],400)
        cancelled=self.action(master,order["id"],"cancel",reason="Наряд отменён после уточнения объёма")
        self.assertEqual(cancelled[1]["order"]["status"],"rejected")
        self.assertTrue(cancelled[1]["order"]["cancelled_by_master"])

        # A brigade receives the issue; the first accepting member becomes the assignee.
        group_payload={"title":"Осмотр конвейерного узла","description":"Осмотреть крепления, ролики и зафиксировать результат.",
            "work_type":"planned","priority":"planned","area_id":self.area_id,"equipment_id":self.equipment_id,"brigade":"A","norm_hours":8}
        group=master.call("/api/orders","POST",group_payload)
        self.assertEqual(group[0],201,group[1]);group_id=group[1]["order"]["id"]
        with app.connect(self.db_path) as db:
            group_user=db.execute("SELECT id,username FROM users WHERE role='worker' AND brigade='A' AND id NOT IN (?,?) ORDER BY id LIMIT 1",(group[1]["order"]["assigned_to"],replacement.call("/api/me")[1]["user"]["id"])).fetchone()
        group_worker=self.client(group_user["username"])
        self.assertEqual(group_worker.call(f"/api/orders/{group_id}")[0],200)
        self.assertEqual(self.action(group_worker,group_id,"accept")[1]["order"]["status"],"accepted")
        self.assertEqual(replacement.call(f"/api/orders/{group_id}")[0],404)

    def test_file_validation_and_shift_report(self):
        master=self.client("master01");worker=self.client("worker01")
        order=self.create_order(master);oid=order["id"]
        self.assertEqual(self.action(worker,oid,"accept")[0],200)
        self.assertEqual(self.action(worker,oid,"start")[0],200)
        bad=worker.call(f"/api/orders/{oid}/photos","POST",{"phase":"after","file_name":"bad.png","data_url":"data:image/png;base64,"+base64.b64encode(b"not an image").decode()})
        self.assertEqual(bad[0],400)
        report="Осмотрен подшипниковый узел и выполнена регулировка; шум устранён, результат стабилен."
        self.assertEqual(self.action(worker,oid,"complete",completion_text=report,fault_code_id=self.fault_id,labor_hours=1.2,materials=[],materials_not_used=True)[0],200)
        self.assertEqual(self.action(worker,oid,"ai_check")[1]["order"]["status"],"rework")

        # Non-production planned completion can proceed without after-photo; final manager-only close is still gated.
        planned=master.call("/api/orders","POST",{"title":"Плановый осмотр узла","description":"Плановая проверка подшипникового узла.","work_type":"planned","priority":"planned","area_id":self.area_id,"equipment_id":self.equipment_id,"worker_id":self.worker_id,"norm_hours":8})
        self.assertEqual(planned[0],201)
        pid=planned[1]["order"]["id"]
        self.assertEqual(self.action(worker,pid,"accept")[0],200);self.assertEqual(self.action(worker,pid,"start")[0],200)
        self.assertEqual(self.action(worker,pid,"complete",completion_text=report,fault_code_id=self.fault_id,labor_hours=1.2,materials=[],materials_not_used=True)[0],200)
        self.assertEqual(self.action(worker,pid,"ai_check")[1]["order"]["status"],"ai_review")
        self.assertEqual(self.action(worker,pid,"close")[0],403)
        accepted=self.action(master,pid,"close")
        self.assertEqual(accepted[0],200,accepted[1])
        today=app.utcnow().date().isoformat()
        shift=worker.call(f"/api/reports?date_from={today}&date_to={today}&brigade=A&shift_code=A")
        self.assertEqual(shift[0],200,shift[1])
        self.assertGreaterEqual(shift[1]["summary"]["completed"],1)
        self.assertEqual(shift[1]["summary"]["date_from"],today)
        self.assertEqual(shift[1]["summary"]["shift_code"],"A")
        self.assertIn("не является подтверждённым простоем",shift[1]["summary"]["pause_minutes_note"])
        self.assertEqual(worker.call("/api/reports?date_from=2026-09-02&date_to=2026-09-01")[0],400)
        self.assertEqual(worker.call("/api/reports?date_from=bad&date_to=2026-09-01")[0],400)
        profile=worker.call("/api/bootstrap?rating_from=2026-09-01&rating_to=2026-10-02")[1]
        self.assertTrue(profile["user"]["specialty"])
        self.assertEqual(profile["my_rating"]["period_from"],"2026-09-01")

    def test_pwa_shell_has_mobile_and_offline_assets(self):
        for path in ("/","/static/app.js","/static/styles.css","/static/sw.js","/static/manifest.webmanifest"):
            request=urllib.request.Request(self.base+path)
            with urllib.request.urlopen(request,timeout=5) as response:
                self.assertEqual(response.status,200,path)
                body=response.read().decode("utf-8")
                if path=="/": self.assertIn("manifest.webmanifest",body)
                if path.endswith("styles.css"): self.assertIn("max-width:760px",body)
                if path.endswith("sw.js"): self.assertIn("cache.addAll",body)
                if path.endswith("app.js"):
                    self.assertIn("setInterval(()=>refresh(true),4000)",body)
                    self.assertIn('action:"ai_check"',body)
                    self.assertIn("reader.readAsDataURL(compressed)",body)
                    self.assertIn("canvas.toBlob",body)
                    self.assertIn("insertJpegExif",body)
                    self.assertIn("EXIF не подтверждает",body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
