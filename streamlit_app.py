"""Thin optional demo UI over the canonical НарядAI HTTP API. No mock state or business rules live here."""
from __future__ import annotations

import base64
import atexit
import os
import tempfile
import threading
from datetime import date
from pathlib import Path
from urllib.parse import urlencode
from typing import Any

import requests
import streamlit as st

ROOT = Path(__file__).resolve().parent
EXTERNAL_API_URL = os.environ.get("NARYADAI_API_URL", "").strip().rstrip("/")
EMBEDDED_MODE = not bool(EXTERNAL_API_URL)
TIMEOUT = (3, 20)
st.set_page_config(page_title="НарядAI · демо", page_icon="🛠️", layout="wide")


class EmbeddedBackend:
    """One process-local loopback API with disposable synthetic storage."""

    def __init__(self, base_url: str, httpd: Any, http_thread: threading.Thread,
                 watchdog_thread: threading.Thread, stop_event: threading.Event,
                 temp_dir: tempfile.TemporaryDirectory):
        self.base_url = base_url
        self.httpd = httpd
        self.http_thread = http_thread
        self.watchdog_thread = watchdog_thread
        self.stop_event = stop_event
        self.temp_dir = temp_dir
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.stop_event.set()
        if self.http_thread.is_alive():
            self.httpd.shutdown()
        self.httpd.server_close()
        if self.http_thread.ident is not None:
            self.http_thread.join(timeout=3)
        if self.watchdog_thread.ident is not None:
            self.watchdog_thread.join(timeout=3)
        self.temp_dir.cleanup()


@st.cache_resource(show_spinner=False)
def _start_embedded_backend() -> EmbeddedBackend:
    """Start the canonical API once per Streamlit process, bound to loopback."""
    temp_dir = tempfile.TemporaryDirectory(prefix="naryadai-streamlit-demo-")
    data_dir = Path(temp_dir.name)
    os.environ["NARYADAI_DATA_DIR"] = str(data_dir)
    # The shared Cloud demo must never call an external model or notification service.
    for variable in ("NARYADAI_LLM_API_URL", "NARYADAI_LLM_API_KEY", "NARYADAI_LLM_MODEL"):
        os.environ.pop(variable, None)

    httpd = None
    stop_event = threading.Event()
    http_thread = None
    watchdog_thread = None
    try:
        import server as api_server

        db_path = data_dir / "naryadai.sqlite3"
        api_server.init_db(db_path)
        api_server.patch_get_photo()
        api_server.patch_cookie_login()
        class QuietAppHandler(api_server.AppHandler):
            def log_message(self, format: str, *args: Any) -> None:
                return

        httpd = api_server.ThreadingHTTPServer(("127.0.0.1", 0), QuietAppHandler)
        httpd.daemon_threads = True
        httpd.block_on_close = False
        httpd.request_queue_size = 16
        httpd.db_path = db_path
        http_thread = threading.Thread(
            target=httpd.serve_forever, kwargs={"poll_interval": 0.25},
            name="naryadai-loopback-api", daemon=True,
        )
        watchdog_thread = threading.Thread(
            target=api_server.watchdog_loop, args=(db_path, stop_event),
            name="naryadai-demo-watchdog", daemon=True,
        )
        http_thread.start()
        watchdog_thread.start()
        host, port = httpd.server_address[:2]
        base_url = f"http://{host}:{port}"
        health = requests.get(base_url + "/api/health", timeout=3)
        health.raise_for_status()
        backend = EmbeddedBackend(base_url, httpd, http_thread, watchdog_thread, stop_event, temp_dir)
        atexit.register(backend.close)
        return backend
    except Exception:
        stop_event.set()
        if httpd is not None:
            if http_thread is not None and http_thread.is_alive():
                httpd.shutdown()
            httpd.server_close()
        if http_thread is not None and http_thread.ident is not None:
            http_thread.join(timeout=3)
        if watchdog_thread is not None and watchdog_thread.ident is not None:
            watchdog_thread.join(timeout=3)
        temp_dir.cleanup()
        raise


if EXTERNAL_API_URL:
    API_URL = EXTERNAL_API_URL
else:
    try:
        _BACKEND = _start_embedded_backend()
        API_URL = _BACKEND.base_url
    except Exception as error:
        st.error(f"Не удалось запустить встроенный API демо: {type(error).__name__}")
        st.stop()


def api(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    session: requests.Session = st.session_state.api_session
    headers = {"Accept": "application/json"}
    if method != "GET":
        headers["X-CSRF-Token"] = st.session_state.csrf
    response = session.request(method, API_URL + path, json=body, headers=headers, timeout=TIMEOUT)
    if response.status_code == 401:
        st.session_state.clear()
        st.error("Сессия завершилась. Войдите снова.")
        st.stop()
    try:
        data = response.json()
    except ValueError:
        data = {}
    if not response.ok:
        raise RuntimeError(data.get("error", f"HTTP {response.status_code}"))
    return data


def login_panel() -> None:
    st.title("НарядAI")
    st.caption("Общий синтетический демо-стенд поверх настоящего API нарядов.")
    if EMBEDDED_MODE:
        st.warning("Общие демо-аккаунты: изменения и синтетические фото видны другим участникам. Перезапуск может удалить все данные. Не загружайте реальные сведения.")
    else:
        st.caption(f"Локальный режим подключён к {API_URL}.")
    with st.form("login"):
        username = st.text_input("Логин")
        password = st.text_input("Пароль", type="password")
        submit = st.form_submit_button("Войти", type="primary")
    if submit:
        session = requests.Session()
        try:
            response = session.post(API_URL + "/api/login", json={"username": username, "password": password}, timeout=TIMEOUT)
            data = response.json()
            if not response.ok:
                raise RuntimeError(data.get("error", "Не удалось войти"))
            st.session_state.api_session = session
            st.session_state.user = data["user"]
            st.session_state.csrf = data["user"]["csrf"]
            st.rerun()
        except (requests.RequestException, ValueError, RuntimeError) as error:
            st.error(f"Вход не выполнен: {error}")


def order_label(order: dict[str, Any]) -> str:
    return f"{order['code']} · {order['status_label']} · {order['title']} · {order['worker']['display_name']}"


def show_photos(order: dict[str, Any]) -> None:
    photos = order.get("photos", [])
    if not photos:
        st.caption("Фото отсутствуют. Фото не подтверждает свежесть съёмки или исправность оборудования.")
        return
    columns = st.columns(min(3, len(photos)))
    for index, photo in enumerate(photos):
        response = st.session_state.api_session.get(API_URL + photo["url"], timeout=TIMEOUT)
        if response.ok:
            with columns[index % len(columns)]:
                st.image(response.content, caption=f"{photo['phase']} · {photo['duplicate_type']} · {photo['uploaded_at']}")
                metadata = photo.get("metadata", {})
                st.caption("EXIF — неподтверждённая подсказка" if metadata.get("capture_datetime") else "Время съёмки неизвестно")


def add_photo(order_id: int, phase: str) -> None:
    if EMBEDDED_MODE:
        sample_dir = ROOT / "demo_photos"
        choices = {
            "Синтетический образец A": sample_dir / "synthetic-sample-a.jpg",
            "Синтетический образец B": sample_dir / "synthetic-sample-b.jpg",
        }
        selected = st.selectbox("Только встроенный образец", list(choices), key=f"demo-sample-{order_id}-{phase}")
        photo_path = choices[selected]
        if not photo_path.is_file():
            st.error("Образец не найден в составе приложения.")
            return
        st.image(str(photo_path), caption="Синтетическая иллюстрация — не фото оборудования и не доказательство ремонта.")
        raw = photo_path.read_bytes()
        if len(raw) > 150_000:
            st.error("Встроенный образец превышает лимит демонстрационной загрузки.")
            return
        st.caption("В Cloud принимаются только два встроенных образца JPEG размером до 150 КБ.")
        if st.button("Загрузить синтетический образец", key=f"upload-demo-{order_id}-{phase}"):
            payload = {"phase": phase, "file_name": photo_path.name,
                       "data_url": "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")}
            try:
                api("POST", f"/api/orders/{order_id}/photos", payload)
                st.success("Синтетический образец сохранён.")
                st.rerun()
            except (RuntimeError, requests.RequestException) as error:
                st.error(f"Образец не загружен: {error}")
        return

    uploads = st.file_uploader("Фото сжатого размера до 4 МБ каждое", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True, key=f"photos-{order_id}-{phase}")
    if st.button("Загрузить фото", key=f"upload-{order_id}-{phase}", disabled=not uploads):
        try:
            for image in uploads or []:
                raw = image.getvalue()
                if len(raw) > 4_000_000:
                    raise RuntimeError(f"{image.name}: файл больше 4 МБ; используйте основное PWA-сжатие перед загрузкой.")
                payload = {"phase": phase, "file_name": image.name, "data_url": f"data:{image.type};base64," + base64.b64encode(raw).decode("ascii")}
                api("POST", f"/api/orders/{order_id}/photos", payload)
            st.success("Фото сохранено на сервере.")
            st.rerun()
        except (RuntimeError, requests.RequestException) as error:
            st.error(f"Фото не загружено: {error}")


def show_worker_actions(order: dict[str, Any], constants: dict[str, Any]) -> None:
    oid, status = order["id"], order["status"]
    if status == "issued":
        c1, c2 = st.columns(2)
        if c1.button("В очередь", key=f"queue-{oid}"):
            api("POST", f"/api/orders/{oid}/action", {"action": "queue"}); st.rerun()
        if c2.button("Принять", key=f"accept-{oid}", type="primary"):
            api("POST", f"/api/orders/{oid}/action", {"action": "accept"}); st.rerun()
        with st.form(f"reject-{oid}"):
            reason = st.text_input("Причина отказа")
            if st.form_submit_button("Отклонить наряд"):
                api("POST", f"/api/orders/{oid}/action", {"action": "reject", "reason": reason}); st.rerun()
    elif status == "queued":
        if st.button("Принять из очереди", key=f"accept-queued-{oid}", type="primary"):
            api("POST", f"/api/orders/{oid}/action", {"action": "accept"}); st.rerun()
    elif status in ("accepted", "rework"):
        if status == "rework":
            st.warning(f"Замечания: {order.get('reject_reason') or 'см. журнал'}")
        if st.button("Начать работу", key=f"start-{oid}", type="primary"):
            api("POST", f"/api/orders/{oid}/action", {"action": "start"}); st.rerun()
    elif status == "in_progress":
        with st.form(f"pause-{oid}"):
            reason = st.text_input("Причина приостановки")
            if st.form_submit_button("Приостановить"):
                api("POST", f"/api/orders/{oid}/action", {"action": "pause", "reason": reason}); st.rerun()
        faults = constants.get("fault_codes", [])
        materials = constants.get("materials", [])
        with st.form(f"complete-{oid}"):
            report = st.text_area("Что сделано и какой результат наблюдался")
            fault_ids = [item["id"] for item in faults]
            fault_labels = {item["id"]: f"{item['code']} · {item['label']}" for item in faults}
            fault_id = st.selectbox("Код неисправности", fault_ids, format_func=lambda key: fault_labels[key]) if fault_ids else None
            hours = st.number_input("Фактическая работа, ч", min_value=0.1, max_value=72.0, value=1.0)
            material_ids = st.multiselect("Использованные материалы", [x["id"] for x in materials], format_func=lambda key: next(f"{x['sku']} · {x['name']} ({x['unit']})" for x in materials if x["id"] == key))
            if st.form_submit_button("Зафиксировать исполнение"):
                payload = {"action": "complete", "completion_text": report, "fault_code_id": fault_id, "labor_hours": hours,
                           "materials": [{"material_id": item, "quantity": 1} for item in material_ids], "materials_not_used": not material_ids}
                api("POST", f"/api/orders/{oid}/action", payload); st.rerun()
        add_photo(oid, "after")
    elif status == "paused":
        if st.button("Возобновить", key=f"resume-{oid}", type="primary"):
            api("POST", f"/api/orders/{oid}/action", {"action": "resume"}); st.rerun()
    elif status == "executed":
        if st.button("Проверить текст и фото", key=f"check-{oid}", type="primary"):
            result = api("POST", f"/api/orders/{oid}/action", {"action": "ai_check"})
            st.session_state.last_review = result["order"].get("ai_result")
            st.rerun()
    elif status == "ai_review":
        st.info("Мастер проверяет отчёт. Автоматическая проверка не разрешает опасную работу и не принимает наряд окончательно.")


def show_master_actions(order: dict[str, Any]) -> None:
    oid, status = order["id"], order["status"]
    if status == "issued":
        add_photo(oid, "before")
        with st.form(f"cancel-{oid}"):
            reason = st.text_input("Основание отмены")
            if st.form_submit_button("Отменить наряд"):
                api("POST", f"/api/orders/{oid}/action", {"action": "cancel", "reason": reason}); st.rerun()
    if status == "ai_review":
        c1, c2 = st.columns(2)
        with c1.form(f"close-{oid}"):
            reason = st.text_input("Комментарий мастера к приёмке")
            if st.form_submit_button("Принять и закрыть", type="primary"):
                api("POST", f"/api/orders/{oid}/action", {"action": "close", "reason": reason}); st.rerun()
        with c2.form(f"rework-{oid}"):
            reason = st.text_input("Что исправить")
            if st.form_submit_button("На доработку"):
                api("POST", f"/api/orders/{oid}/action", {"action": "request_rework", "reason": reason}); st.rerun()
    if status == "closed":
        with st.form(f"rating-{oid}"):
            rating = st.selectbox("Рейтинг 1–5", [1, 2, 3, 4, 5], index=4)
            reason = st.text_area("Обоснование оценки")
            if st.form_submit_button("Сохранить оценку"):
                api("POST", f"/api/orders/{oid}/rating", {"rating": rating, "reason": reason}); st.rerun()
        st.caption("Повторный фактор меняется только через явную связь мастера в основном PWA. Автоматических штрафов нет.")


def create_order(constants: dict[str, Any], workers: list[dict[str, Any]]) -> None:
    st.subheader("Выдать наряд мастером")
    areas = constants.get("areas", [])
    equipment = constants.get("equipment", [])
    area_id = st.selectbox("Участок", [x["id"] for x in areas],
                           format_func=lambda key: next(x["name"] for x in areas if x["id"] == key),
                           key="new-order-area",
                           on_change=lambda: st.session_state.pop("new-order-equipment", None)) if areas else None
    choices = [x for x in equipment if x["area_id"] == area_id]
    with st.form("new-order"):
        title = st.text_input("Название")
        description = st.text_area("Описание")
        equipment_id = st.selectbox("Оборудование", [x["id"] for x in choices],
                                    format_func=lambda key: next(f"{x['code']} · {x['name']}" for x in choices if x["id"] == key),
                                    key="new-order-equipment") if choices else None
        user_id = st.selectbox("Исполнитель (синтетический профиль)", [x["id"] for x in workers],
            format_func=lambda key: next(f"{x['username']} · {x['display_name']} · {x['specialty']} · разряд {x['qualification_level']} · смена {x['shift_code']}" for x in workers if x["id"] == key)) if workers else None
        work_type = st.selectbox("Тип", ["planned", "unscheduled"], format_func=lambda x: {"planned":"Плановая", "unscheduled":"Внеплановая"}[x])
        priority = st.selectbox("Приоритет", ["normal", "high", "emergency", "planned"], format_func=lambda x: {"normal":"Обычный", "high":"Высокий", "emergency":"Аварийный", "planned":"Плановый"}[x])
        hours = st.number_input("Срок, часов", 0.5, 720.0, 8.0, step=0.5)
        if st.form_submit_button("Выдать через API", type="primary"):
            body = {"title": title, "description": description, "area_id": area_id, "equipment_id": equipment_id,
                    "worker_id": user_id, "work_type": work_type, "priority": priority, "norm_hours": hours}
            api("POST", "/api/orders", body); st.success("Наряд сохранён на сервере."); st.rerun()


def reports_panel() -> None:
    with st.form("reports"):
        c1,c2,c3,c4=st.columns(4)
        from_day=c1.date_input("С", value=date.today());to_day=c2.date_input("По", value=date.today())
        brigade=c3.selectbox("Бригада",["","A","B","C"]);shift_label=c4.selectbox("Смена",["Все","A","B","C"])
        submit=st.form_submit_button("Сформировать")
    if submit:
        if to_day<from_day: st.error("Дата окончания раньше даты начала.");return
        params={"date_from":from_day.isoformat(),"date_to":to_day.isoformat(),"brigade":brigade,"shift_code":"" if shift_label=="Все" else shift_label}
        data=api("GET","/api/reports?"+urlencode(params))
        st.json(data["summary"])
        st.caption("Пауза — события журнала; это не подтверждённый простой оборудования. Сводка rules-only.")
        st.dataframe(data.get("worker_totals",[]),width="stretch")
        st.dataframe(data.get("material_totals",[]),width="stretch")
        st.dataframe(data.get("items",[]),width="stretch")


@st.fragment(run_every=5.0)
def live_orders_panel(user: dict[str, Any], constants: dict[str, Any]) -> None:
    """Refresh orders without rerunning unrelated page widgets or losing form drafts."""
    bootstrap = api("GET", "/api/bootstrap")
    orders = bootstrap.get("orders", [])
    st.caption("\u0421\u0442\u0430\u0442\u0443\u0441\u044b \u0438 \u043e\u0447\u0435\u0440\u0435\u0434\u044c \u043e\u0431\u043d\u043e\u0432\u043b\u044f\u044e\u0442\u0441\u044f \u043a\u0430\u0436\u0434\u044b\u0435 5 \u0441\u0435\u043a\u0443\u043d\u0434, \u043f\u043e\u043a\u0430 \u0441\u0435\u0441\u0441\u0438\u044f \u043e\u0442\u043a\u0440\u044b\u0442\u0430.")
    st.dataframe([{"\u041d\u0430\u0440\u044f\u0434":o["code"],"\u0421\u0442\u0430\u0442\u0443\u0441":o["status_label"],"\u0420\u0430\u0431\u043e\u0442\u0430":o["title"],"\u041e\u0431\u043e\u0440\u0443\u0434\u043e\u0432\u0430\u043d\u0438\u0435":o["equipment"]["name"],"\u0418\u0441\u043f\u043e\u043b\u043d\u0438\u0442\u0435\u043b\u044c":o["worker"]["display_name"],"\u0421\u0440\u043e\u043a UTC":o["due_at"]} for o in orders[:100]], width="stretch")
    if not orders:
        return
    selected = st.selectbox("\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043d\u0430\u0440\u044f\u0434", [o["id"] for o in orders], format_func=lambda key: next(order_label(o) for o in orders if o["id"] == key), key="live-selected-order")
    detail = api("GET", f"/api/orders/{selected}")
    order = detail["order"]
    st.subheader(f"{order['code']} · {order['status_label']} · {order['title']}")
    c1,c2,c3 = st.columns(3)
    c1.write(f"\u0423\u0447\u0430\u0441\u0442\u043e\u043a: {order['area']}")
    c2.write(f"\u041e\u0431\u043e\u0440\u0443\u0434\u043e\u0432\u0430\u043d\u0438\u0435: {order['equipment']['name']}")
    c3.write(f"\u0418\u0441\u043f\u043e\u043b\u043d\u0438\u0442\u0435\u043b\u044c: {order['worker']['display_name']} / \u0431\u0440\u0438\u0433\u0430\u0434\u0430 {order['worker'].get('brigade')}")
    st.write(order["description"])
    if order.get("completion_text"): st.write("\u041e\u0442\u0447\u0451\u0442 \u0438\u0441\u043f\u043e\u043b\u043d\u0438\u0442\u0435\u043b\u044f:", order["completion_text"])
    if order.get("ai_result"): st.json(order["ai_result"])
    show_photos(order)
    if user["role"] == "worker": show_worker_actions(order, constants)
    elif user["role"] == "master": show_master_actions(order)
    else: st.caption("\u0422\u043e\u043b\u044c\u043a\u043e \u043f\u0440\u043e\u0441\u043c\u043e\u0442\u0440.")
    with st.expander("\u0410\u0443\u0434\u0438\u0442 \u043d\u0430\u0440\u044f\u0434\u0430"):
        st.dataframe(detail.get("history", []), width="stretch")


def main() -> None:
    if "user" not in st.session_state:
        login_panel()
        return
    user = st.session_state.user
    st.session_state.naryadai_api_url = API_URL
    with st.sidebar:
        st.title("НарядAI")
        st.write(user["display_name"])
        st.caption(user["role_label"])
        st.caption(f"Профиль: {user.get('specialty') or '-'} · разряд {user.get('qualification_level') or '-'} · смена {user.get('shift_code') or '-'} · синтетика")
        pages = ["Очередь", "Отчёт"] if user["role"] == "worker" else ["Доска", "Команда", "Отчёт"]
        page = st.radio("Раздел", pages)
        if st.button("Обновить данные"):
            st.rerun()
        if st.button("Выход"):
            try:
                api("POST", "/api/logout", {})
            finally:
                session = st.session_state.get("api_session")
                if session is not None:
                    session.close()
                st.session_state.clear()
                st.rerun()
    try:
        bootstrap = api("GET", "/api/bootstrap")
        constants = bootstrap["constants"]
        st.title(page)
        st.info("Синтетическая демонстрация. ИИ и фото не являются допуском к опасной работе и не подтверждают исправность оборудования.")
        if EMBEDDED_MODE:
            st.warning("Общие демо-аккаунты, наряды и синтетические фото видны другим участникам; перезапуск может очистить данные. Используйте только встроенные образцы.")
        if page == "Отчёт":
            reports_panel()
            return
        if page == "Команда":
            st.dataframe([ {k:x.get(k) for k in ("display_name","brigade","availability_label","specialty","qualification_level","shift_code","active_orders")} for x in bootstrap.get("members",[]) ], width="stretch")
            st.caption("Доступность, квалификация и график смен показаны для синтетических профилей.")
        if user["role"] == "master":
            create_order(constants, bootstrap.get("free_workers", []))
        live_orders_panel(user, constants)
    except (RuntimeError, requests.RequestException) as error:
        st.error(f"Ошибка API НарядAI: {error}")

if __name__ == "__main__":
    main()
