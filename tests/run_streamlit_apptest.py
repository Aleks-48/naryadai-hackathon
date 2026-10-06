"""AppTest checks using the real embedded loopback API (no server.py process)."""
from __future__ import annotations

import json
import logging
import os
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "streamlit_app.py"


def _u(codepoints: str) -> str:
    return "".join(chr(int(value, 16)) for value in codepoints.split())


LABELS = {
    "login": _u("0412 043e 0439 0442 0438"),
    "title": _u("041d 0430 0437 0432 0430 043d 0438 0435"),
    "description": _u("041e 043f 0438 0441 0430 043d 0438 0435"),
    "order": _u("041e 0442 043a 0440 044b 0442 044c 0020 043d 0430 0440 044f 0434"),
    "assignee": _u("0418 0441 043f 043e 043b 043d 0438 0442 0435 043b 044c 0020 0028 0441 0438 043d 0442 0435 0442 0438 0447 0435 0441 043a 0438 0439 0020 043f 0440 043e 0444 0438 043b 044c 0029"),
    "pause_reason": _u("041f 0440 0438 0447 0438 043d 0430 0020 043f 0440 0438 043e 0441 0442 0430 043d 043e 0432 043a 0438"),
    "rework_reason": _u("0427 0442 043e 0020 0438 0441 043f 0440 0430 0432 0438 0442 044c"),
    "close_note": _u("041a 043e 043c 043c 0435 043d 0442 0430 0440 0438 0439 0020 043c 0430 0441 0442 0435 0440 0430 0020 043a 0020 043f 0440 0438 0451 043c 043a 0435"),
    "rating": _u("0420 0435 0439 0442 0438 043d 0433 0020 0031 2013 0035"),
    "rating_reason": _u("041e 0431 043e 0441 043d 043e 0432 0430 043d 0438 0435 0020 043e 0446 0435 043d 043a 0438"),
    "work_type": _u("0422 0438 043f"),
    "create": _u("0412 044b 0434 0430 0442 044c 0020 0447 0435 0440 0435 0437 0020 0041 0050 0049"),
    "accept": _u("041f 0440 0438 043d 044f 0442 044c"),
    "queue": _u("0412 0020 043e 0447 0435 0440 0435 0434 044c"),
    "accept_queued": _u("041f 0440 0438 043d 044f 0442 044c 0020 0438 0437 0020 043e 0447 0435 0440 0435 0434 0438"),
    "upload_sample": _u("0417 0430 0433 0440 0443 0437 0438 0442 044c 0020 0441 0438 043d 0442 0435 0442 0438 0447 0435 0441 043a 0438 0439 0020 043e 0431 0440 0430 0437 0435 0446"),
    "area": _u("0423 0447 0430 0441 0442 043e 043a"),
    "equipment": _u("041e 0431 043e 0440 0443 0434 043e 0432 0430 043d 0438 0435"),
    "start": _u("041d 0430 0447 0430 0442 044c 0020 0440 0430 0431 043e 0442 0443"),
    "pause": _u("041f 0440 0438 043e 0441 0442 0430 043d 043e 0432 0438 0442 044c"),
    "resume": _u("0412 043e 0437 043e 0431 043d 043e 0432 0438 0442 044c"),
    "complete": _u("0417 0430 0444 0438 043a 0441 0438 0440 043e 0432 0430 0442 044c 0020 0438 0441 043f 043e 043b 043d 0435 043d 0438 0435"),
    "review": _u("041f 0440 043e 0432 0435 0440 0438 0442 044c 0020 0442 0435 043a 0441 0442 0020 0438 0020 0444 043e 0442 043e"),
    "refresh": _u("041e 0431 043d 043e 0432 0438 0442 044c 0020 0434 0430 043d 043d 044b 0435"),
    "queue_up": "↑ Выше",
    "rework": _u("041d 0430 0020 0434 043e 0440 0430 0431 043e 0442 043a 0443"),
    "close": _u("041f 0440 0438 043d 044f 0442 044c 0020 0438 0020 0437 0430 043a 0440 044b 0442 044c"),
    "save_rating": _u("0421 043e 0445 0440 0430 043d 0438 0442 044c 0020 043e 0446 0435 043d 043a 0443"),
    "make_report": _u("0421 0444 043e 0440 043c 0438 0440 043e 0432 0430 0442 044c"),
    "register_downtime": "Сохранить интервал",
    "section": _u("0420 0430 0437 0434 0435 043b"),
}


class StreamlitApiAppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        logging.disable(logging.WARNING)
        cls.previous_api_url = os.environ.pop("NARYADAI_API_URL", None)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.previous_api_url is not None:
            os.environ["NARYADAI_API_URL"] = cls.previous_api_url

    def new_app(self, username: str, role: str) -> AppTest:
        app = AppTest.from_file(str(APP), default_timeout=30).run()
        self.assertFalse(app.exception, self.exceptions(app))
        app.text_input[0].set_value(username)
        app.text_input[1].set_value("demo123")
        self.click(app, "login")
        self.assertEqual(app.session_state["user"]["role"], role)
        return app

    @staticmethod
    def exceptions(app: AppTest) -> str:
        return json.dumps([str(item.value) for item in app.exception], ensure_ascii=True)

    def click(self, app: AppTest, name: str) -> None:
        label = LABELS[name]
        matches = [item for item in app.button if item.label == label]
        state = {
            "buttons": [item.label for item in app.button],
            "selects": [{"label": item.label, "value": item.value, "options": len(item.options)} for item in app.selectbox],
            "radios": [{"label": item.label, "value": item.value} for item in app.radio],
        }
        self.assertEqual(len(matches), 1, f"expected one {name} button; state={json.dumps(state, ensure_ascii=True)}")
        matches[0].click().run()
        self.assertFalse(app.exception, self.exceptions(app))

    def app_session(self, app: AppTest) -> requests.Session:
        return app.session_state["api_session"]

    def api_base(self, app: AppTest) -> str:
        return app.session_state["naryadai_api_url"]

    def api_json(self, app: AppTest, path: str) -> dict[str, Any]:
        response = self.app_session(app).get(self.api_base(app) + path, timeout=10)
        response.raise_for_status()
        return response.json()

    def select_order(self, app: AppTest, order_id: int) -> None:
        label = _u("0412 044b 0431 0435 0440 0438 0442 0435 0020 043d 0430 0440 044f 0434")
        widget = next(item for item in app.selectbox if item.label == label)
        widget.set_value(order_id).run()
        self.assertFalse(app.exception, self.exceptions(app))

    def assert_status(self, app: AppTest, order_id: int, expected: str) -> None:
        self.assertEqual(self.api_json(app, f"/api/orders/{order_id}")["order"]["status"], expected)

    def test_master_worker_manager_and_isolated_sessions(self) -> None:
        master = self.new_app("master01", "master")
        worker = self.new_app("worker02", "worker")
        manager = self.new_app("manager", "manager")
        bases = [self.api_base(app) for app in (master, worker, manager)]
        self.assertEqual(len(set(bases)), 1)
        self.assertRegex(bases[0], r"^http://127\.0\.0\.1:\d+$")
        cookies = [self.app_session(app).cookies.get_dict() for app in (master, worker, manager)]
        self.assertEqual(len({tuple(sorted(cookie.items())) for cookie in cookies}), 3)

        self.assertTrue(any(item.label == LABELS["create"] for item in master.button))
        self.assertFalse(any(item.label == LABELS["create"] for item in worker.button))
        self.assertFalse(any(item.label == LABELS["create"] for item in manager.button))
        worker_metrics = {item.label for item in worker.metric}
        self.assertIn("Рейтинг / 100", worker_metrics)
        worker_frames = [item.value for item in worker.dataframe if hasattr(item.value, "columns")]
        self.assertTrue(any({"Фактор", "Значение / 100", "Базовый вес, %"}.issubset(frame.columns) for frame in worker_frames))
        self.assertTrue(any({"Отказы — события", "Обоснованы мастером", "Необоснованы мастером", "Pending · ждут решения мастера"}.issubset(frame.columns) for frame in worker_frames))
        dashboard_metrics = {item.label for item in manager.metric}
        self.assertTrue({"Ожидают", "Приняты / в работе", "Проверка / доработка", "Закрыты мастером"}.issubset(dashboard_metrics))

        csrf = manager.session_state["csrf"]
        denied = self.app_session(manager).post(
            self.api_base(manager) + "/api/orders",
            json={},
            headers={"X-CSRF-Token": csrf},
            timeout=10,
        )
        self.assertEqual(denied.status_code, 403)

        section = next(item for item in manager.radio if item.label == LABELS["section"])
        section.set_value(section.options[1]).run()
        self.assertFalse(manager.exception, self.exceptions(manager))
        team_frames = [item.value for item in manager.dataframe if hasattr(item.value, "columns")]
        self.assertTrue(any("Общий рейтинг / 100" in frame.columns for frame in team_frames))
        self.assertTrue(any("Качество закрытых нарядов" in frame.columns for frame in team_frames))
        self.assertTrue(any("Pending · ждут решения мастера" in frame.columns for frame in team_frames))

        section.set_value(section.options[-1]).run()
        self.assertFalse(manager.exception, self.exceptions(manager))
        self.click(manager, "make_report")
        self.assertGreaterEqual(len(manager.dataframe), 3)
        report_metrics = {item.label for item in manager.metric}
        self.assertTrue({"Исполнено", "Закрыто мастером", "Просрочено", "Трудозатраты, ч", "Отказы по событиям"}.issubset(report_metrics))

    def test_master_registers_equipment_downtime_from_streamlit_report(self) -> None:
        master=self.new_app("master01","master")
        section=next(item for item in master.radio if item.label==LABELS["section"])
        section.set_value(section.options[-1]).run()
        self.assertFalse(master.exception,self.exceptions(master))
        equipment=next(item for item in master.selectbox if item.label=="Оборудование")
        now_utc=datetime.now(timezone.utc).replace(second=0,microsecond=0)
        started=now_utc-timedelta(hours=2);ended=now_utc-timedelta(hours=1)
        equipment.set_value(equipment.options[0])
        dates={item.label:item for item in master.date_input}
        dates["Начало · дата UTC"].set_value(started.date())
        dates["Окончание · дата UTC"].set_value(ended.date())
        clocks={item.label:item for item in master.time_input}
        clocks["Начало · время UTC"].set_value(started.time())
        clocks["Окончание · время UTC"].set_value(ended.time())
        reason=next(item for item in master.text_input if item.label=="Причина регистрации")
        reason.set_value("Synthetic maintenance stop")
        master.run()
        self.assertFalse(master.exception,self.exceptions(master))
        self.click(master,"register_downtime")
        params=f"date_from={started.date().isoformat()}&date_to={ended.date().isoformat()}"
        data=self.api_json(master,"/api/equipment/downtime?"+params)
        self.assertGreaterEqual(data["minutes"],60)
        self.assertTrue(any(item["reason"]=="Synthetic maintenance stop" for item in data["intervals"]))

    def test_area_change_refreshes_equipment_before_form_submission(self) -> None:
        master = self.new_app("master01", "master")
        constants = self.api_json(master, "/api/bootstrap")["constants"]
        areas = constants["areas"]
        self.assertGreaterEqual(len(areas), 2)
        area_widget = next(item for item in master.selectbox if item.label == LABELS["area"])
        second_area = areas[1]["id"]
        area_widget.set_value(second_area).run()
        self.assertFalse(master.exception, self.exceptions(master))
        equipment_widget = next(item for item in master.selectbox if item.label == LABELS["equipment"])
        expected = {f"{item['code']} · {item['name']}" for item in constants["equipment"] if item["area_id"] == second_area}
        self.assertTrue(expected)
        self.assertEqual(set(equipment_widget.options), expected)
        expected_ids = {item["id"] for item in constants["equipment"] if item["area_id"] == second_area}
        self.assertIn(equipment_widget.value, expected_ids)

    def test_before_photo_is_optional_on_first_submit_for_both_work_types(self) -> None:
        master = self.new_app("master01", "master")
        worker = next(item for item in self.api_json(master, "/api/bootstrap")["free_workers"] if item["username"] == "worker01")
        import io
        import random
        from PIL import Image

        def unique_photo(seed: int) -> bytes:
            rng = random.Random(seed)
            image = Image.new("RGB", (64, 64))
            image.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(64 * 64)])
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=90)
            return output.getvalue()

        photo_a = unique_photo(time.time_ns())
        photo_b = unique_photo(time.time_ns() + 1)

        first_title = "First-submit unscheduled " + str(time.time_ns())
        description = "Inspect the synthetic pump and record the condition before work."
        next(item for item in master.text_input if item.label == LABELS["title"]).set_value(first_title)
        next(item for item in master.text_area if item.label == LABELS["description"]).set_value(description)
        next(item for item in master.selectbox if item.label == LABELS["assignee"]).set_value(worker["id"])
        work_type = next(item for item in master.selectbox if item.label == LABELS["work_type"])
        self.assertEqual(work_type.value, "planned")
        self.assertEqual(len(master.file_uploader), 1, "optional photo picker must be present before selecting work type")

        # Attach a before photo on the first submit; the same form must also work without one.
        work_type.set_value("unscheduled")
        master.file_uploader[0].upload("unique-a.jpg", photo_a, "image/jpeg")
        self.click(master, "create")
        self.assertFalse(master.exception, self.exceptions(master))
        first = next(order for order in self.api_json(master, "/api/bootstrap")["orders"] if order["title"] == first_title)
        first_order = self.api_json(master, f"/api/orders/{first['id']}")["order"]
        self.assertTrue(any(item["phase"] == "before" for item in first_order.get("photos", [])))

        missing_title = "No-before-photo unscheduled " + str(time.time_ns())
        next(item for item in master.text_input if item.label == LABELS["title"]).set_value(missing_title)
        next(item for item in master.selectbox if item.label == LABELS["work_type"]).set_value("unscheduled")
        master.file_uploader[0].set_value(None)
        # No intermediate .run(): the first submit must create this order without a photo.
        self.click(master, "create")
        self.assertFalse(master.exception, self.exceptions(master))
        self.assertFalse(master.error, [item.value for item in master.error])
        missing = next(order for order in self.api_json(master, "/api/bootstrap")["orders"] if order["title"] == missing_title)
        missing_order = self.api_json(master, f"/api/orders/{missing['id']}")["order"]
        self.assertFalse(any(item["phase"] == "before" for item in missing_order.get("photos", [])))

        retry_title = "Repeated type switch " + str(time.time_ns())
        next(item for item in master.text_input if item.label == LABELS["title"]).set_value(retry_title)
        work_type = next(item for item in master.selectbox if item.label == LABELS["work_type"])
        work_type.set_value("planned")
        work_type.set_value("unscheduled")
        master.file_uploader[0].upload("unique-b.jpg", photo_b, "image/jpeg")
        self.click(master, "create")
        self.assertFalse(master.error, [item.value for item in master.error])
        retry = next(order for order in self.api_json(master, "/api/bootstrap")["orders"] if order["title"] == retry_title)
        retry_order = self.api_json(master, f"/api/orders/{retry['id']}")["order"]
        self.assertTrue(any(item["phase"] == "before" for item in retry_order.get("photos", [])))

        planned_title = "Planned optional before photo " + str(time.time_ns())
        next(item for item in master.text_input if item.label == LABELS["title"]).set_value(planned_title)
        next(item for item in master.selectbox if item.label == LABELS["work_type"]).set_value("planned")
        master.file_uploader[0].upload("unique-planned.jpg", unique_photo(time.time_ns() + 2), "image/jpeg")
        self.click(master, "create")
        planned = next(order for order in self.api_json(master, "/api/bootstrap")["orders"] if order["title"] == planned_title)
        planned_order = self.api_json(master, f"/api/orders/{planned['id']}")["order"]
        self.assertEqual(planned_order["work_type"], "planned")
        self.assertTrue(any(item["phase"] == "before" for item in planned_order.get("photos", [])))

    def test_master_moves_manual_queue_and_worker_reads_same_position(self) -> None:
        master = self.new_app("master01", "master")
        csrf = master.session_state["csrf"]
        bootstrap = self.api_json(master, "/api/bootstrap")
        worker = next(item for item in bootstrap["free_workers"] if item["username"] == "worker15")
        area = bootstrap["constants"]["areas"][0]
        equipment = next(item for item in bootstrap["constants"]["equipment"] if item["area_id"] == area["id"])
        payload = {"title":"Queue order scenario", "description":"Synthetic ordering acceptance scenario.",
                   "work_type":"planned", "priority":"normal", "area_id":area["id"],
                   "equipment_id":equipment["id"], "worker_id":worker["id"], "norm_hours":2}
        for suffix in ("A", "B", "C"):
            response = self.app_session(master).post(self.api_base(master)+"/api/orders",
                json={**payload,"title":f"Queue order scenario {suffix}"},
                headers={"X-CSRF-Token":csrf},timeout=10)
            self.assertEqual(response.status_code,201,response.text)
        master.run()
        self.assertFalse(master.exception,self.exceptions(master))
        fresh = self.api_json(master,"/api/bootstrap")
        queues = fresh["work_queues"]
        new_ids = {item["id"] for item in fresh["orders"] if item["title"].startswith("Queue order scenario")}
        scope = next(queue["scope"] for queue in queues if new_ids.intersection(queue["order_ids"]))
        queue = next(item for item in queues if item["scope"] == scope)
        selected = queue["order_ids"][1]
        self.select_order(master,selected)
        self.click(master,"queue_up")
        updated = next(item for item in self.api_json(master,"/api/bootstrap")["work_queues"] if item["scope"] == scope)
        self.assertEqual(updated["order_ids"][0],selected)
        self.assertTrue(any(frame.value is not None and "Позиция" in getattr(frame.value,"columns",[])
                            for frame in master.dataframe))

        # A second session retains the rendered revision. Another session updates
        # the server; the stale up-button must submit its old snapshot and show
        # 409 instead of transferring that intent onto the refreshed queue.
        stale_master = self.new_app("master01","master")
        stale_queue = next(item for item in self.api_json(stale_master,"/api/bootstrap")["work_queues"] if item["scope"] == scope)
        self.assertEqual(stale_queue["revision"],updated["revision"])
        stale_selected = stale_queue["order_ids"][1]
        self.select_order(stale_master,stale_selected)
        externally_reordered = stale_queue["order_ids"][1:] + stale_queue["order_ids"][:1]
        external_update = self.app_session(master).post(self.api_base(master)+"/api/work-queues/reorder",
            json={"scope":scope,"expected_revision":stale_queue["revision"],"order_ids":externally_reordered},
            headers={"X-CSRF-Token":master.session_state["csrf"]},timeout=10)
        self.assertEqual(external_update.status_code,200,external_update.text)
        relevant_ids = set(stale_queue["order_ids"])
        audit_before = sum(item["event"]=="work_queue_reordered" and item["order_id"] in relevant_ids
                          for item in self.api_json(stale_master,"/api/audit")["items"])
        self.click(stale_master,"queue_up")
        self.assertFalse(stale_master.exception,self.exceptions(stale_master))
        self.assertTrue(any("\u0434\u0440\u0443\u0433\u043e\u0439 \u0441\u0435\u0430\u043d\u0441" in item.value.lower()
                            for item in stale_master.warning), [item.value for item in stale_master.warning])
        final_queue = next(item for item in self.api_json(stale_master,"/api/bootstrap")["work_queues"] if item["scope"] == scope)
        self.assertEqual(final_queue["order_ids"],externally_reordered)
        audit_after = sum(item["event"]=="work_queue_reordered" and item["order_id"] in relevant_ids
                         for item in self.api_json(stale_master,"/api/audit")["items"])
        self.assertEqual(audit_after,audit_before,"stale UI action must add no audit rows")

        # Preserve an actual Streamlit WidgetStates click from revision N,
        # refresh this fragment to N+1, then deliver the delayed old event.
        # Its revision-specific widget ID must be discarded, never rebound to
        # the latest callback context.
        delayed_revision_queue = next(item for item in self.api_json(stale_master,"/api/bootstrap")["work_queues"]
                                      if item["scope"] == scope)
        delayed_selected = delayed_revision_queue["order_ids"][1]
        self.select_order(stale_master,delayed_selected)
        old_up_button = next(item for item in stale_master.button
                             if item.key and item.key.startswith(f"queue-up-{scope}-{delayed_selected}-r"))
        self.assertIn(f"-r{delayed_revision_queue['revision']}",old_up_button.key)
        delayed_widget_states = stale_master._tree.get_widget_states()
        old_up_state = next(item for item in delayed_widget_states.widgets if item.id == old_up_button.id)
        old_up_state.trigger_value = True

        next_order = delayed_revision_queue["order_ids"][1:] + delayed_revision_queue["order_ids"][:1]
        next_update = self.app_session(master).post(self.api_base(master)+"/api/work-queues/reorder",
            json={"scope":scope,"expected_revision":delayed_revision_queue["revision"],"order_ids":next_order},
            headers={"X-CSRF-Token":master.session_state["csrf"]},timeout=10)
        self.assertEqual(next_update.status_code,200,next_update.text)
        # This run models the five-second fragment refresh arriving first.
        stale_master.run()
        self.assertFalse(stale_master.exception,self.exceptions(stale_master))
        refreshed_queue = next(item for item in self.api_json(stale_master,"/api/bootstrap")["work_queues"]
                               if item["scope"] == scope)
        self.assertEqual(refreshed_queue["order_ids"],next_order)
        self.assertGreater(refreshed_queue["revision"],delayed_revision_queue["revision"])
        new_up_button = next(item for item in stale_master.button
                             if item.key and item.key.startswith(f"queue-up-{scope}-{delayed_selected}-r"))
        self.assertNotEqual(old_up_button.key,new_up_button.key)
        self.assertNotEqual(old_up_button.id,new_up_button.id)
        audit_before_delayed = sum(item["event"]=="work_queue_reordered" and item["order_id"] in relevant_ids
                                   for item in self.api_json(stale_master,"/api/audit")["items"])
        stale_master._run(delayed_widget_states)
        self.assertFalse(stale_master.exception,self.exceptions(stale_master))
        after_delayed = next(item for item in self.api_json(stale_master,"/api/bootstrap")["work_queues"]
                             if item["scope"] == scope)
        self.assertEqual(after_delayed["order_ids"],next_order,
                         "old WidgetStates must not transfer the reorder intent to the refreshed revision")
        self.assertEqual(after_delayed["revision"],refreshed_queue["revision"])
        audit_after_delayed = sum(item["event"]=="work_queue_reordered" and item["order_id"] in relevant_ids
                                  for item in self.api_json(stale_master,"/api/audit")["items"])
        self.assertEqual(audit_after_delayed,audit_before_delayed,
                         "discarded delayed WidgetStates must not send a reorder request")

        worker_app = self.new_app("worker15","worker")
        worker_queue = next(item for item in self.api_json(worker_app,"/api/bootstrap")["work_queues"] if item["scope"] == scope)
        self.assertEqual(worker_queue["order_ids"],next_order)
        self.assertFalse(any(item.label == LABELS["queue_up"] for item in worker_app.button))
        manager = self.new_app("manager","manager")
        self.assertFalse(any(item.label == LABELS["queue_up"] for item in manager.button))

    def test_full_order_flow_through_streamlit_and_real_api(self) -> None:
        master = self.new_app("master01", "master")
        worker_info = next(item for item in self.api_json(master, "/api/bootstrap")["free_workers"] if item["username"] == "worker01")

        title = "AppTest flow " + str(time.time_ns())
        master.text_input[0].set_value(title)
        master.text_area[0].set_value("Inspect synthetic pump bearing and record the measured result.")
        assignee = next(item for item in master.selectbox if item.label == LABELS["assignee"])
        assignee.set_value(worker_info["id"])
        self.click(master, "create")

        created = next(item for item in self.api_json(master, "/api/bootstrap")["orders"] if item["title"] == title)
        order_id = created["id"]
        self.assert_status(master, order_id, "issued")

        unrelated_worker = self.new_app("worker02", "worker")
        other_session = self.app_session(unrelated_worker)
        self.assertNotEqual(self.app_session(master).cookies.get_dict(), other_session.cookies.get_dict())
        forbidden = other_session.get(self.api_base(unrelated_worker) + f"/api/orders/{order_id}", timeout=10)
        self.assertIn(forbidden.status_code, (403, 404))

        worker = self.new_app("worker01", "worker")
        self.select_order(worker, order_id)
        self.click(worker, "queue")
        self.assert_status(worker, order_id, "queued")
        self.select_order(master, order_id)
        self.click(master, "upload_sample")
        before_order = self.api_json(master, f"/api/orders/{order_id}")["order"]
        self.assertTrue(any(photo["phase"] == "before" for photo in before_order.get("photos", [])))
        self.select_order(worker, order_id)
        self.click(worker, "accept_queued")
        self.assert_status(worker, order_id, "accepted")
        self.select_order(worker, order_id)
        self.click(worker, "start")
        self.assert_status(worker, order_id, "in_progress")
        self.select_order(worker, order_id)
        self.assertEqual(len(worker.file_uploader), 0, "embedded demo should not accept arbitrary uploads")
        self.click(worker, "upload_sample")
        order_after_sample = self.api_json(worker, f"/api/orders/{order_id}")["order"]
        self.assertTrue(any(photo["file_name"].startswith("synthetic-sample-") for photo in order_after_sample.get("photos", [])))
        self.assertTrue(all(photo["size_bytes"] <= 150_000 for photo in order_after_sample.get("photos", [])))
        self.select_order(worker, order_id)

        reason = next(item for item in worker.text_input if item.label == LABELS["pause_reason"])
        reason.set_value("Waiting for synthetic spare part confirmation.")
        self.click(worker, "pause")
        self.assert_status(worker, order_id, "paused")
        self.select_order(worker, order_id)
        self.click(worker, "resume")
        self.assert_status(worker, order_id, "in_progress")
        self.select_order(worker, order_id)

        report_widget = next(item for item in worker.text_area if item.label == "Что сделано и какой результат наблюдался")
        comment_widget = next(item for item in worker.text_area if item.label == "Комментарий исполнителя · необязательно")
        report_widget.set_value("Draft: checked the synthetic bearing housing and recorded the reading.").run()
        report_widget = next(item for item in worker.text_area if item.label == "Что сделано и какой результат наблюдался")
        self.assertEqual(report_widget.value, "Draft: checked the synthetic bearing housing and recorded the reading.")
        report_widget.set_value("Checked the bearing housing and recorded stable vibration after adjustment.")
        comment_widget = next(item for item in worker.text_area if item.label == "Комментарий исполнителя · необязательно")
        comment_widget.set_value("Measured after adjustment; no abnormal vibration remained.")
        material_picker = next(item for item in worker.multiselect if item.label == "Использованные материалы")
        material_id = material_picker.options[0]
        # Select and submit in the same AppTest run. This catches a quantity
        # widget that is only created by an artificial rerun after form submit.
        material_picker.set_value([material_id])
        self.click(worker, "complete")
        self.assert_status(worker, order_id, "executed")
        completed_order = self.api_json(worker, f"/api/orders/{order_id}")["order"]
        self.assertEqual(completed_order["materials"][0]["quantity"], 1.0)
        self.assertEqual(completed_order["worker_completion_comment"], "Measured after adjustment; no abnormal vibration remained.")
        self.select_order(worker, order_id)
        self.click(worker, "review")
        self.assert_status(worker, order_id, "ai_review")

        self.click(master, "refresh")
        self.select_order(master, order_id)
        rework_note = next(item for item in master.text_input if item.label == LABELS["rework_reason"])
        rework_note.set_value("Add the final measured clearance to the report.")
        self.click(master, "rework")
        self.assert_status(master, order_id, "rework")

        self.click(worker, "refresh")
        self.select_order(worker, order_id)
        self.click(worker, "start")
        self.select_order(worker, order_id)
        report_widget = next(item for item in worker.text_area if item.label == "Что сделано и какой результат наблюдался")
        report_widget.set_value("Updated report with final measured clearance and verified record.")
        material_picker = worker.multiselect[-1]
        material_picker.set_value([material_id]).run()
        quantity_widget = worker.number_input[-1]
        quantity_widget.set_value(0.001)
        self.click(worker, "complete")
        completed_order = self.api_json(worker, f"/api/orders/{order_id}")["order"]
        self.assertEqual(completed_order["materials"][0]["quantity"], 0.001)
        self.select_order(worker, order_id)
        self.click(worker, "review")
        self.assert_status(worker, order_id, "ai_review")

        self.click(master, "refresh")
        self.select_order(master, order_id)
        close_note = next(item for item in master.text_input if item.label == LABELS["close_note"])
        close_note.set_value("Reviewed the report and accepted the measured result.")
        self.click(master, "close")
        self.assert_status(master, order_id, "closed")
        self.select_order(master, order_id)

        rating = next(item for item in master.selectbox if item.label == LABELS["rating"])
        rating.set_value(5)
        rating_note = next(item for item in master.text_area if item.label == LABELS["rating_reason"])
        rating_note.set_value("Clear notes and helpful measurement detail.")
        self.click(master, "save_rating")
        final_order = self.api_json(master, f"/api/orders/{order_id}")["order"]
        self.assertEqual(final_order["status"], "closed")
        self.assertEqual(final_order["rating"], 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
