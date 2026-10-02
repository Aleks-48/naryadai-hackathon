"""Thin optional demo UI over the canonical НарядAI HTTP API. No mock state or business rules live here."""
from __future__ import annotations

import base64
import os
from datetime import date
from urllib.parse import urlencode
from typing import Any

import requests
import streamlit as st

API_URL = os.environ.get("NARYADAI_API_URL", "http://127.0.0.1:8765").rstrip("/")
TIMEOUT = (3, 20)
st.set_page_config(page_title="НарядAI · демо", page_icon="🛠️", layout="wide")


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
    st.caption("Неизменённый локальный MVP через реальный API. Данные остаются в серверной SQLite и каталоге фотографий.")
    st.info(f"API: {API_URL}. Streamlit Cloud без отдельного HTTPS API и постоянного диска не подходит для этого демо.")
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
    elif status in ("accepted", "queued", "rework"):
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
    with st.form("new-order"):
        title = st.text_input("Название")
        description = st.text_area("Описание")
        areas = constants.get("areas", [])
        equipment = constants.get("equipment", [])
        area_id = st.selectbox("Участок", [x["id"] for x in areas], format_func=lambda key: next(x["name"] for x in areas if x["id"] == key)) if areas else None
        choices = [x for x in equipment if x["area_id"] == area_id]
        equipment_id = st.selectbox("Оборудование", [x["id"] for x in choices], format_func=lambda key: next(f"{x['code']} · {x['name']}" for x in choices if x["id"] == key)) if choices else None
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


def main() -> None:
    if "user" not in st.session_state:
        login_panel();return
    user=st.session_state.user
    with st.sidebar:
        st.title("НарядAI")
        st.write(user["display_name"])
        st.caption(user["role_label"])
        st.caption(f"Профиль: {user.get('specialty') or '—'} · разряд {user.get('qualification_level') or '—'} · смена {user.get('shift_code') or '—'} · синтетика")
        page=st.radio("Раздел",["Наряды","Отчёт" ] if user["role"]=="worker" else ["Наряды","Команда","Отчёт"])
        if st.button("Обновить данные"): st.rerun()
        if st.button("Выйти"):
            try: api("POST","/api/logout",{})
            finally: st.session_state.clear();st.rerun()
    try:
        bootstrap=api("GET","/api/bootstrap")
        constants=bootstrap["constants"]
        st.title(page)
        st.info("Синтетические демонстрационные данные. ИИ и фото не являются допуском по безопасности и не доказывают исправность оборудования.")
        if page=="Отчёт": reports_panel();return
        if page=="Команда":
            st.dataframe([{k:x.get(k) for k in ("display_name","brigade","availability_label","specialty","qualification_level","shift_code","active_orders")} for x in bootstrap.get("members",[])],width="stretch")
            st.caption("Специальность, квалификация и график сгенерированы для демо и не подтверждают фактические допуски.")
        if user["role"]=="master": create_order(constants,bootstrap.get("free_workers",[]))
        orders=bootstrap.get("orders",[])
        st.dataframe([{ "Наряд":o["code"],"Статус":o["status_label"],"Работа":o["title"],"Оборудование":o["equipment"]["name"],"Исполнитель":o["worker"]["display_name"],"Срок UTC":o["due_at"]} for o in orders[:100]],width="stretch")
        if not orders: return
        selected=st.selectbox("Открыть наряд",[o["id"] for o in orders],format_func=lambda key: next(order_label(o) for o in orders if o["id"]==key))
        detail=api("GET",f"/api/orders/{selected}")
        order=detail["order"]
        st.subheader(f"{order['code']} · {order['status_label']} · {order['title']}")
        c1,c2,c3=st.columns(3);c1.write(f"Участок: {order['area']}");c2.write(f"Оборудование: {order['equipment']['name']}");c3.write(f"Исполнитель: {order['worker']['display_name']} / бригада {order['worker'].get('brigade')}")
        st.write(order["description"])
        if order.get("completion_text"): st.write("Отчёт исполнителя:",order["completion_text"])
        if order.get("ai_result"): st.json(order["ai_result"])
        show_photos(order)
        if user["role"]=="worker": show_worker_actions(order,constants)
        elif user["role"]=="master": show_master_actions(order)
        else: st.caption("Руководительский просмотр: только чтение.")
        with st.expander("Аудит наряда"):
            st.dataframe(detail.get("history",[]),width="stretch")
    except (RuntimeError, requests.RequestException) as error:
        st.error(f"Запрос к НарядAI API не выполнен: {error}")


if __name__ == "__main__":
    main()
