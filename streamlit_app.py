"""Thin optional demo UI over the canonical НарядAI HTTP API. No mock state or business rules live here."""
from __future__ import annotations

import base64
import atexit
import json
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

STREAMLIT_STYLE = """
<style>
:root {
  color-scheme: light;
  --nai-ink: #152525;
  --nai-muted: #72817d;
  --nai-line: #e8ece8;
  --nai-paper: #f6f7f4;
  --nai-white: #ffffff;
  --nai-green: #159b7a;
  --nai-green-dark: #0d745d;
  --nai-mint: #dff4ed;
  --nai-amber: #d98a23;
  --nai-red: #ca5b4a;
  font-size: 16px;
}
[data-testid="stAppViewContainer"] { background: var(--nai-paper); color: var(--nai-ink); }
[data-testid="stHeader"] { background: transparent; }
div.block-container { max-width: 1520px; padding-top: 2rem; padding-bottom: 3rem; }
h1, h2, h3 { color: var(--nai-ink); letter-spacing: -.025em; }
h1 { font-size: clamp(1.85rem, 2.6vw, 2.35rem); line-height: 1.18; font-weight: 800; }
h2 { font-size: 1.55rem; line-height: 1.25; font-weight: 750; }
h3 { font-size: 1.2rem; line-height: 1.3; font-weight: 700; }
p, [data-testid="stCaptionContainer"] { line-height: 1.5; }
[data-testid="stSidebar"] { background: #102a2a; }
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
[data-testid="stSidebar"] [data-testid="stWidgetLabel"],
[data-testid="stSidebar"] label { color: #d6e5df; }
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] { color: #a7bdb4; }
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] { background: #1d4a40; color: #effaf4; border-color: #326554; }
[data-testid="stForm"] {
  padding: 1.1rem 1.2rem 1.2rem;
  background: var(--nai-white);
  border: 1px solid var(--nai-line);
  border-radius: 12px;
}
[data-testid="stMetric"] {
  min-height: 112px;
  padding: 1rem 1.1rem;
  background: var(--nai-white);
  border: 1px solid var(--nai-line);
  border-radius: 12px;
  box-shadow: 0 5px 18px rgba(22, 49, 43, .035);
}
[data-testid="stMetricLabel"] { color: var(--nai-muted); font-size: .95rem; }
[data-testid="stMetricValue"] { color: var(--nai-ink); font-size: 1.8rem; font-weight: 750; }
/* Streamlit 1.64 renders st.columns wrappers with .stColumn (not data-testid="column"). */
.st-key-status-summary .stColumn:nth-child(1) [data-testid="stMetric"] { border-top: 4px solid #567cb5; }
.st-key-status-summary .stColumn:nth-child(2) [data-testid="stMetric"] { border-top: 4px solid var(--nai-green); }
.st-key-status-summary .stColumn:nth-child(3) [data-testid="stMetric"] { border-top: 4px solid var(--nai-amber); }
.st-key-status-summary .stColumn:nth-child(4) [data-testid="stMetric"] { border-top: 4px solid #278362; }
[data-testid="stBaseButton-primary"] { background: var(--nai-green); border-color: var(--nai-green); border-radius: 9px; min-height: 44px; font-weight: 700; }
[data-testid="stBaseButton-primary"]:hover { background: var(--nai-green-dark); border-color: var(--nai-green-dark); }
[data-testid="stBaseButton-secondary"] { border-radius: 9px; min-height: 42px; font-weight: 650; }
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stNumberInput"] input,
[data-baseweb="select"] > div {
  min-height: 44px;
  border-radius: 9px;
  font-size: 1rem;
}
[data-testid="stTextArea"] textarea { line-height: 1.45; }
[data-testid="stWidgetLabel"] { color: #42544c; font-size: .95rem; font-weight: 650; }
[data-testid="stAlert"] { border-radius: 10px; line-height: 1.5; }
[data-testid="stDataFrame"] { border: 1px solid var(--nai-line); border-radius: 10px; overflow: hidden; }
[data-testid="stExpander"] { border: 1px solid var(--nai-line); border-radius: 10px; background: #fff; }
.st-key-create-order-panel, .st-key-order-queue, .st-key-order-detail, .st-key-report-summary {
  padding: 1rem 1.1rem;
  border: 1px solid var(--nai-line);
  border-radius: 12px;
  background: #fff;
  margin: .4rem 0 1rem;
}
@media (max-width: 760px) {
  div.block-container { padding: 1.15rem .9rem 2.2rem; }
  h1 { font-size: 1.75rem; }
  h2 { font-size: 1.38rem; }
  [data-testid="stForm"] { padding: .9rem; }
  [data-testid="stMetric"] { min-height: 96px; padding: .8rem; }
  [data-testid="stMetricValue"] { font-size: 1.5rem; }
  [data-testid="stDataFrame"] { max-width: 100%; }
  .st-key-status-summary [data-testid="stHorizontalBlock"] {
    display: grid !important;
    grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
    gap: .65rem !important;
  }
  .st-key-status-summary .stColumn { width: auto !important; min-width: 0 !important; flex: initial !important; }
  .st-key-report-summary [data-testid="stHorizontalBlock"] {
    display: grid !important;
    grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
    gap: .65rem !important;
  }
  .st-key-report-summary .stColumn { width: auto !important; min-width: 0 !important; flex: initial !important; }
  .st-key-create-order-panel [data-testid="stHorizontalBlock"],
  .st-key-order-detail [data-testid="stHorizontalBlock"] {
    display: grid !important;
    grid-template-columns: minmax(0, 1fr) !important;
    gap: .55rem !important;
  }
  .st-key-create-order-panel .stColumn,
  .st-key-order-detail .stColumn { width: auto !important; min-width: 0 !important; flex: initial !important; }
  .st-key-create-order-panel, .st-key-order-queue, .st-key-order-detail, .st-key-report-summary { padding: .8rem; }
}
@media (max-width: 420px) {
  div.block-container { padding-left: .65rem; padding-right: .65rem; }
  [data-testid="stMetricLabel"] { font-size: .83rem; }
  [data-testid="stMetricValue"] { font-size: 1.35rem; }
}
</style>
"""


def apply_streamlit_theme() -> None:
    """Style Streamlit's real widgets to follow the PWA palette; no UI logic is HTML-backed."""
    st.markdown(STREAMLIT_STYLE, unsafe_allow_html=True)


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
    for variable in ("NARYADAI_LLM_API_URL", "NARYADAI_LLM_API_KEY", "NARYADAI_LLM_MODEL",
                     "NARYADAI_LLM_ENABLED", "NARYADAI_LLM_REPORT_SUMMARY",
                     "NARYADAI_TELEGRAM_ENABLED", "NARYADAI_TELEGRAM_BOT_TOKEN", "NARYADAI_TELEGRAM_WEBHOOK_SECRET"):
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
            report = st.text_area("Что сделано и какой результат наблюдался", height=100)
            fault_ids = [item["id"] for item in faults]
            fault_labels = {item["id"]: f"{item['code']} · {item['label']}" for item in faults}
            fault_col, hours_col = st.columns([1.4, .8])
            fault_id = fault_col.selectbox("Код неисправности", fault_ids, format_func=lambda key: fault_labels[key]) if fault_ids else None
            hours = hours_col.number_input("Фактическая работа, ч", min_value=0.1, max_value=72.0, value=1.0)
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
    with st.container(key="create-order-panel"):
        st.subheader("Выдать наряд мастером")
        st.caption("Назначение и ограничения проверяет API; демопрофили синтетические.")
        areas = constants.get("areas", [])
        equipment = constants.get("equipment", [])
        area_id = st.selectbox("Участок", [x["id"] for x in areas],
                               format_func=lambda key: next(x["name"] for x in areas if x["id"] == key),
                               key="new-order-area",
                               on_change=lambda: st.session_state.pop("new-order-equipment", None)) if areas else None
        choices = [x for x in equipment if x["area_id"] == area_id]
        with st.form("new-order"):
            title = st.text_input("Название")
            description = st.text_area("Описание", height=100)
            left, right = st.columns(2)
            equipment_id = left.selectbox("Оборудование", [x["id"] for x in choices],
                                          format_func=lambda key: next(f"{x['code']} · {x['name']}" for x in choices if x["id"] == key),
                                          key="new-order-equipment") if choices else None
            user_id = right.selectbox("Исполнитель (синтетический профиль)", [x["id"] for x in workers],
                format_func=lambda key: next(f"{x['username']} · {x['display_name']} · {x['specialty']} · разряд {x['qualification_level']} · смена {x['shift_code']}" for x in workers if x["id"] == key)) if workers else None
            type_col, priority_col, hours_col = st.columns([1, 1, .8])
            work_type = type_col.selectbox("Тип", ["planned", "unscheduled"], format_func=lambda x: {"planned":"Плановая", "unscheduled":"Внеплановая"}[x])
            priority = priority_col.selectbox("Приоритет", ["normal", "high", "emergency", "planned"], format_func=lambda x: {"normal":"Обычный", "high":"Высокий", "emergency":"Аварийный", "planned":"Плановый"}[x])
            hours = hours_col.number_input("Срок, часов", 0.5, 720.0, 8.0, step=0.5)
            if st.form_submit_button("Выдать через API", type="primary"):
                body = {"title": title, "description": description, "area_id": area_id, "equipment_id": equipment_id,
                        "worker_id": user_id, "work_type": work_type, "priority": priority, "norm_hours": hours}
                api("POST", "/api/orders", body); st.success("Наряд сохранён на сервере."); st.rerun()


def reports_panel() -> None:
    with st.form("reports"):
        c1,c2=st.columns(2)
        from_day=c1.date_input("С", value=date.today());to_day=c2.date_input("По", value=date.today())
        c3,c4=st.columns(2)
        brigade=c3.selectbox("Бригада",["","A","B","C"]);shift_label=c4.selectbox("Смена",["Все","A","B","C"])
        submit=st.form_submit_button("Сформировать")
    if submit:
        if to_day<from_day: st.error("Дата окончания раньше даты начала.");return
        params={"date_from":from_day.isoformat(),"date_to":to_day.isoformat(),"brigade":brigade,"shift_code":"" if shift_label=="Все" else shift_label}
        data=api("GET","/api/reports?"+urlencode(params))
        summary=data["summary"]
        with st.container(key="report-summary"):
            st.subheader("Итоги периода")
            metric_columns=st.columns(4)
            metric_columns[0].metric("Исполнено",summary.get("completed",0))
            metric_columns[1].metric("Закрыто мастером",summary.get("closed",0))
            metric_columns[2].metric("Просрочено",summary.get("late_completions",0))
            metric_columns[3].metric("Трудозатраты, ч",summary.get("labor_hours",0))
            st.caption(f"{summary.get('date_from')} — {summary.get('date_to')} · {summary.get('summary_mode','rules-only')} · {summary.get('pause_minutes_note','')}")
            st.info(data.get("ai_summary",""))
        st.subheader("По исполнителям")
        st.dataframe(data.get("worker_totals",[]),width="stretch")
        st.subheader("Материалы")
        st.dataframe(data.get("material_totals",[]),width="stretch")
        st.subheader("Наряды периода")
        st.dataframe(data.get("items",[]),width="stretch")


@st.fragment(run_every=5.0)
def live_orders_panel(user: dict[str, Any], constants: dict[str, Any]) -> None:
    """Refresh orders without rerunning unrelated page widgets or losing form drafts."""
    bootstrap = api("GET", "/api/bootstrap")
    orders = bootstrap.get("orders", [])
    status_counts: dict[str, int] = {}
    for item in orders:
        status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1
    st.caption("\u0421\u0442\u0430\u0442\u0443\u0441\u044b \u0438 \u043e\u0447\u0435\u0440\u0435\u0434\u044c \u043e\u0431\u043d\u043e\u0432\u043b\u044f\u044e\u0442\u0441\u044f \u043a\u0430\u0436\u0434\u044b\u0435 5 \u0441\u0435\u043a\u0443\u043d\u0434, \u043f\u043e\u043a\u0430 \u0441\u0435\u0441\u0441\u0438\u044f \u043e\u0442\u043a\u0440\u044b\u0442\u0430.")
    with st.container(key="status-summary"):
        columns = st.columns(4)
        waiting = status_counts.get("issued", 0) + status_counts.get("queued", 0)
        active = status_counts.get("accepted", 0) + status_counts.get("in_progress", 0) + status_counts.get("paused", 0)
        review = status_counts.get("executed", 0) + status_counts.get("ai_review", 0) + status_counts.get("rework", 0)
        columns[0].metric("Ожидают", waiting)
        columns[0].caption(f"Выдано {status_counts.get('issued',0)} · очередь {status_counts.get('queued',0)}")
        columns[1].metric("Приняты / в работе", active)
        columns[1].caption(f"Принято {status_counts.get('accepted',0)} · работа {status_counts.get('in_progress',0)} · пауза {status_counts.get('paused',0)}")
        columns[2].metric("Проверка / доработка", review)
        columns[2].caption(f"Исполнено {status_counts.get('executed',0)} · проверка {status_counts.get('ai_review',0)} · доработка {status_counts.get('rework',0)}")
        columns[3].metric("Закрыты мастером", status_counts.get("closed", 0))
        columns[3].caption(f"Отклонено: {status_counts.get('rejected',0)}")
    st.subheader("Список нарядов")
    with st.container(key="order-queue"):
        st.dataframe([{"\u041d\u0430\u0440\u044f\u0434":o["code"],"\u0421\u0442\u0430\u0442\u0443\u0441":o["status_label"],"\u0420\u0430\u0431\u043e\u0442\u0430":o["title"],"\u041e\u0431\u043e\u0440\u0443\u0434\u043e\u0432\u0430\u043d\u0438\u0435":o["equipment"]["name"],"\u0418\u0441\u043f\u043e\u043b\u043d\u0438\u0442\u0435\u043b\u044c":o["worker"]["display_name"],"\u0421\u0440\u043eк UTC":o["due_at"]} for o in orders[:100]], width="stretch", height=330, hide_index=True)
    if not orders:
        return
    selected = st.selectbox("\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043d\u0430\u0440\u044f\u0434", [o["id"] for o in orders], format_func=lambda key: next(order_label(o) for o in orders if o["id"] == key), key="live-selected-order")
    detail = api("GET", f"/api/orders/{selected}")
    order = detail["order"]
    with st.container(key="order-detail"):
        st.subheader(f"{order['code']} · {order['status_label']} · {order['title']}")
        c1,c2,c3 = st.columns(3)
        c1.markdown(f"**Участок**  \n{order['area']}")
        c2.markdown(f"**Оборудование**  \n{order['equipment']['name']}")
        c3.markdown(f"**Исполнитель**  \n{order['worker']['display_name']} · бригада {order['worker'].get('brigade')}")
        st.markdown("**Описание неисправности**")
        st.write(order["description"])
        if order.get("completion_text"):
            st.markdown("**Отчёт исполнителя**")
            st.write(order["completion_text"])
        if order.get("ai_result"):
            with st.expander("Результат автоматической проверки", expanded=False):
                try:
                    ai_result = json.loads(order["ai_result"]) if isinstance(order["ai_result"], str) else order["ai_result"]
                except (TypeError, ValueError):
                    ai_result = {}
                if isinstance(ai_result, dict):
                    st.caption(f"Режим: {ai_result.get('mode','unknown')} · вердикт: {ai_result.get('verdict','не указан')}")
                    if ai_result.get("summary"):
                        st.write(ai_result["summary"])
                    if ai_result.get("issues"):
                        st.warning("Замечания: " + " · ".join(str(item) for item in ai_result["issues"]))
                    if ai_result.get("master_confirmation_required"):
                        st.info("Требуется решение мастера.")
                else:
                    st.caption("Результат не удалось прочитать.")
                st.caption("Это подсказка по тексту/фото. Допуск и окончательная приёмка остаются за уполномоченным персоналом.")
        show_photos(order)
        if user["role"] == "worker": show_worker_actions(order, constants)
        elif user["role"] == "master": show_master_actions(order)
        else: st.caption("\u0422\u043e\u043b\u044c\u043a\u043e \u043f\u0440\u043e\u0441\u043c\u043e\u0442\u0440.")
        with st.expander("\u0410\u0443\u0434\u0438\u0442 \u043d\u0430\u0440\u044f\u0434\u0430"):
            st.dataframe(detail.get("history", []), width="stretch", hide_index=True)


def main() -> None:
    apply_streamlit_theme()
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
            st.subheader("Занятость команды")
            st.dataframe([ {k:x.get(k) for k in ("display_name","brigade","availability_label","specialty","qualification_level","shift_code","active_orders")} for x in bootstrap.get("members",[]) ], width="stretch")
            st.caption("Доступность, квалификация и график смен показаны для синтетических профилей.")
        if user["role"] == "master":
            create_order(constants, bootstrap.get("free_workers", []))
        live_orders_panel(user, constants)
    except (RuntimeError, requests.RequestException) as error:
        st.error(f"Ошибка API НарядAI: {error}")

if __name__ == "__main__":
    main()
