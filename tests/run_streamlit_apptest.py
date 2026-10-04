"""AppTest checks using the real embedded loopback API (no server.py process)."""
from __future__ import annotations

import json
import logging
import os
import time
import unittest
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
    "rework": _u("041d 0430 0020 0434 043e 0440 0430 0431 043e 0442 043a 0443"),
    "close": _u("041f 0440 0438 043d 044f 0442 044c 0020 0438 0020 0437 0430 043a 0440 044b 0442 044c"),
    "save_rating": _u("0421 043e 0445 0440 0430 043d 0438 0442 044c 0020 043e 0446 0435 043d 043a 0443"),
    "make_report": _u("0421 0444 043e 0440 043c 0438 0440 043e 0432 0430 0442 044c"),
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

        csrf = manager.session_state["csrf"]
        denied = self.app_session(manager).post(
            self.api_base(manager) + "/api/orders",
            json={},
            headers={"X-CSRF-Token": csrf},
            timeout=10,
        )
        self.assertEqual(denied.status_code, 403)

        section = next(item for item in manager.radio if item.label == LABELS["section"])
        section.set_value(section.options[-1]).run()
        self.assertFalse(manager.exception, self.exceptions(manager))
        self.click(manager, "make_report")
        self.assertGreaterEqual(len(manager.dataframe), 3)

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

        worker.text_area[-1].set_value("Draft: checked the synthetic bearing housing and recorded the reading.").run()
        self.assertEqual(worker.text_area[-1].value, "Draft: checked the synthetic bearing housing and recorded the reading.")
        worker.text_area[-1].set_value("Checked the bearing housing and recorded stable vibration after adjustment.")
        self.click(worker, "complete")
        self.assert_status(worker, order_id, "executed")
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
        worker.text_area[-1].set_value("Updated report with final measured clearance and verified record.")
        self.click(worker, "complete")
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
