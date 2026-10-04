"""НарядAI: локальный MVP на Python stdlib + SQLite.

Запуск: python server.py
Все записи сохраняются в data/naryadai.sqlite3 и data/media/ рядом с приложением.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import io
import json
import math
import mimetypes
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import warnings
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DATA = Path(os.environ.get("NARYADAI_DATA_DIR", str(ROOT / "data"))).expanduser().resolve()
MEDIA = DATA / "media"
DB_PATH = DATA / "naryadai.sqlite3"
POLL_SECONDS = 4
SESSION_SECONDS = 12 * 60 * 60
ACTIVE_STATUSES = {"issued", "accepted", "queued", "in_progress", "paused", "executed", "ai_review", "rework"}
STATUS_LABELS = {
    "issued": "Выдан", "accepted": "Принят", "queued": "Очередь", "rejected": "Отклонён",
    "in_progress": "В работе", "paused": "Приостановлен", "executed": "Исполнено",
    "ai_review": "Проверка ИИ", "rework": "Доработка", "closed": "Закрыт",
}
ROLE_LABELS = {"master": "Мастер", "worker": "Исполнитель", "manager": "Руководитель · просмотр"}
PRIORITY_LABELS = {"planned": "Плановый", "normal": "Обычный", "high": "Высокий", "emergency": "Аварийный"}
DEMO_PASSWORD = "demo123"
SHIFT_WINDOWS_UTC = {"A": (6, 14), "B": (14, 22), "C": (22, 6)}
SHIFT_LABELS = {"A": "A · 06:00–14:00 UTC", "B": "B · 14:00–22:00 UTC", "C": "C · 22:00–06:00 UTC"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime | None = None) -> str:
    return (dt or utcnow()).isoformat().replace("+00:00", "Z")


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None
    except (TypeError, AttributeError, ValueError):
        return None


def active_shift_code(now: datetime | None = None) -> str:
    hour = (now or utcnow()).astimezone(timezone.utc).hour
    for code, (start_hour, end_hour) in SHIFT_WINDOWS_UTC.items():
        if start_hour < end_hour and start_hour <= hour < end_hour:
            return code
        if start_hour > end_hour and (hour >= start_hour or hour < end_hour):
            return code
    return "A"


def shift_is_active(shift_code: str | None, now: datetime | None = None) -> bool:
    return bool(shift_code and shift_code == active_shift_code(now))


def date_window(from_value: str | None, to_value: str | None, default_days: int = 30) -> tuple[str, str, str, str, int]:
    today = utcnow().date()
    try:
        if not from_value and not to_value:
            end_day = today
            start_day = today - timedelta(days=default_days - 1)
        elif from_value and not to_value:
            start_day = datetime.fromisoformat(from_value).date()
            end_day = today
        elif to_value and not from_value:
            end_day = datetime.fromisoformat(to_value).date()
            start_day = end_day - timedelta(days=default_days - 1)
        else:
            start_day = datetime.fromisoformat(str(from_value)).date()
            end_day = datetime.fromisoformat(str(to_value)).date()
    except (TypeError, ValueError):
        raise ApiError(400, "Даты периода должны быть в формате ГГГГ-ММ-ДД")
    if end_day < start_day:
        raise ApiError(400, "Начало периода не может быть позже его окончания")
    days = (end_day - start_day).days + 1
    if days > 3650:
        raise ApiError(400, "Период ограничен десятью годами")
    start = datetime.fromisoformat(start_day.isoformat()).replace(tzinfo=timezone.utc)
    until = datetime.fromisoformat((end_day + timedelta(days=1)).isoformat()).replace(tzinfo=timezone.utc)
    return iso(start), iso(until), start_day.isoformat(), end_day.isoformat(), days


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=15, factory=ClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(path: Path | str = DB_PATH) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    MEDIA.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('master','worker','manager')), brigade TEXT,
            specialty TEXT NOT NULL DEFAULT 'Механика', qualification_level INTEGER NOT NULL DEFAULT 1,
            shift_code TEXT NOT NULL DEFAULT 'A',
            password_salt TEXT NOT NULL, password_hash TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            csrf TEXT NOT NULL, expires_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS areas (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
        CREATE TABLE IF NOT EXISTS equipment (
            id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
            area_id INTEGER NOT NULL REFERENCES areas(id)
        );
        CREATE TABLE IF NOT EXISTS fault_codes (
            id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, label TEXT NOT NULL, category TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS materials (
            id INTEGER PRIMARY KEY, sku TEXT UNIQUE NOT NULL, name TEXT NOT NULL, unit TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
            description TEXT NOT NULL, work_type TEXT NOT NULL DEFAULT 'unscheduled' CHECK(work_type IN ('planned','unscheduled')),
            priority TEXT NOT NULL CHECK(priority IN ('planned','normal','high','emergency')),
            area_id INTEGER NOT NULL REFERENCES areas(id), equipment_id INTEGER NOT NULL REFERENCES equipment(id),
            assigned_to INTEGER NOT NULL REFERENCES users(id), assigned_brigade TEXT,
            assigned_master_id INTEGER NOT NULL REFERENCES users(id),
            status TEXT NOT NULL CHECK(status IN ('issued','accepted','queued','rejected','in_progress','paused','executed','ai_review','rework','closed')),
            created_at TEXT NOT NULL, issued_at TEXT NOT NULL, due_at TEXT NOT NULL,
            accepted_at TEXT, started_at TEXT, completed_at TEXT, closed_at TEXT,
            reject_reason TEXT, pause_reason TEXT, labor_hours REAL, fault_code_id INTEGER REFERENCES fault_codes(id),
            cancelled_by_master INTEGER NOT NULL DEFAULT 0,
            completion_text TEXT, materials_not_used INTEGER NOT NULL DEFAULT 0,
            ai_mode TEXT, ai_result TEXT, ai_checked_at TEXT,
            rating INTEGER CHECK(rating IS NULL OR rating BETWEEN 1 AND 5), rating_reason TEXT, rated_by INTEGER REFERENCES users(id),
            unjustified_refusal INTEGER NOT NULL DEFAULT 0, repeat_confirmed INTEGER NOT NULL DEFAULT 0,
            repeat_reason TEXT, complexity REAL NOT NULL DEFAULT 1.0
        );
        CREATE TABLE IF NOT EXISTS order_materials (
            order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            material_id INTEGER NOT NULL REFERENCES materials(id), quantity REAL NOT NULL CHECK(quantity > 0),
            PRIMARY KEY(order_id, material_id)
        );
        CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            file_name TEXT NOT NULL, phase TEXT NOT NULL DEFAULT 'after' CHECK(phase IN ('before','after')),
            media_type TEXT NOT NULL, file_path TEXT NOT NULL,
            size_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, duplicate INTEGER NOT NULL DEFAULT 0,
            duplicate_type TEXT NOT NULL DEFAULT 'none', perceptual_hash TEXT, color_signature TEXT,
            uploaded_at TEXT NOT NULL, metadata_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY, actor_id INTEGER REFERENCES users(id), order_id INTEGER REFERENCES orders(id),
            event TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rejection_reviews (
            id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id), reject_audit_id INTEGER REFERENCES audit(id),
            worker_id INTEGER NOT NULL REFERENCES users(id), classified_by INTEGER NOT NULL REFERENCES users(id),
            unjustified INTEGER NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_rejection_review_event ON rejection_reviews(reject_audit_id) WHERE reject_audit_id IS NOT NULL;
        CREATE TABLE IF NOT EXISTS repeat_links (
            id INTEGER PRIMARY KEY, current_order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            previous_order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            previous_worker_id INTEGER NOT NULL REFERENCES users(id),
            linked_by_master_id INTEGER NOT NULL REFERENCES users(id), reason TEXT NOT NULL,
            linked_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
            revoked_by_master_id INTEGER REFERENCES users(id), revoked_at TEXT, revoke_reason TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_repeat_link_active_current ON repeat_links(current_order_id) WHERE active=1;
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), order_id INTEGER REFERENCES orders(id),
            message TEXT NOT NULL, created_at TEXT NOT NULL, read_at TEXT
        );
        CREATE TABLE IF NOT EXISTS telegram_outbox (
            id INTEGER PRIMARY KEY, event TEXT NOT NULL, payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued_local', created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
        CREATE INDEX IF NOT EXISTS idx_orders_assignee_status ON orders(assigned_to,status);
        CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);
        CREATE INDEX IF NOT EXISTS idx_audit_order ON audit(order_id,created_at);
        """)
        user_columns = {r[1] for r in db.execute("PRAGMA table_info(users)")}
        for name, definition in (("specialty", "TEXT NOT NULL DEFAULT 'Механика'"),
                                 ("qualification_level", "INTEGER NOT NULL DEFAULT 1"),
                                 ("shift_code", "TEXT NOT NULL DEFAULT 'A'")):
            if name not in user_columns:
                db.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
        photo_columns = {r[1] for r in db.execute("PRAGMA table_info(photos)")}
        if "duplicate_type" not in photo_columns:
            db.execute("ALTER TABLE photos ADD COLUMN duplicate_type TEXT NOT NULL DEFAULT 'none'")
        if "perceptual_hash" not in photo_columns:
            db.execute("ALTER TABLE photos ADD COLUMN perceptual_hash TEXT")
        if "color_signature" not in photo_columns:
            db.execute("ALTER TABLE photos ADD COLUMN color_signature TEXT")
        db.execute("UPDATE photos SET duplicate_type='exact' WHERE duplicate=1 AND duplicate_type='none'")
        db.execute("CREATE INDEX IF NOT EXISTS idx_photos_sha256 ON photos(sha256)")
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            seed_demo(db)


def password_record(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 160_000)
    return salt.hex(), derived.hex()


def verify_password(password: str, salt_hex: str, expected_hex: str) -> bool:
    _, actual = password_record(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(actual, expected_hex)


def seed_demo(db: sqlite3.Connection) -> None:
    """Creates deterministic fictional demo content; no site or personal data is imported."""
    import random

    for name in ["Дробильно-сортировочный участок", "Конвейерный участок", "Насосная", "Компрессорная"]:
        db.execute("INSERT INTO areas(name) VALUES (?)", (name,))
    areas = db.execute("SELECT id,name FROM areas ORDER BY id").fetchall()
    equip_names = [
        ("Дробилка", "Щековая дробилка"), ("Конвейер", "Ленточный конвейер"),
        ("Насос", "Насос шламовый"), ("Компрессор", "Компрессор винтовой"),
        ("Вентилятор", "Вентилятор вытяжной"),
    ]
    for i in range(25):
        family, label = equip_names[i % len(equip_names)]
        area = areas[i % len(areas)]
        db.execute("INSERT INTO equipment(code,name,area_id) VALUES (?,?,?)",
                   (f"EQ-{i+1:03d}", f"{label} {i // len(equip_names)+1:02d}", area["id"]))
    code_labels = [
        "Вибрация выше обычной", "Шум подшипникового узла", "Износ уплотнения", "Утечка рабочей жидкости",
        "Перегрев электродвигателя", "Проскальзывание ленты", "Смещение ленты", "Нарушение натяжения",
        "Засорение фильтра", "Падение давления", "Повреждение крепежа", "Ослабление соединения",
        "Загрязнение датчика", "Сбой индикации", "Износ ролика", "Повреждение ограждения",
        "Плановый осмотр", "Очистка узла", "Смазка узла", "Проверка соединения",
    ]
    for i, label in enumerate(code_labels, 1):
        db.execute("INSERT INTO fault_codes(code,label,category) VALUES (?,?,?)",
                   (f"FC-{i:02d}", label, "Плановое" if i >= 17 else "Механика" if i < 10 else "Общее"))
    material_names = [
        ("Подшипник радиальный", "шт"), ("Манжета уплотнительная", "шт"), ("Ремень приводной", "шт"),
        ("Ролик конвейерный", "шт"), ("Фильтр воздушный", "шт"), ("Смазка промышленная", "кг"),
        ("Болт крепежный", "шт"), ("Гайка крепежная", "шт"), ("Шайба", "шт"),
        ("Муфта соединительная", "шт"), ("Прокладка", "шт"), ("Шланг технический", "м"),
        ("Клемма электрическая", "шт"), ("Кабель силовой", "м"), ("Датчик температуры", "шт"),
        ("Датчик вибрации", "шт"), ("Предохранитель", "шт"), ("Контактор", "шт"),
        ("Краска защитная", "л"), ("Растворитель", "л"), ("Электрод сварочный", "кг"),
        ("Лента конвейерная", "м"), ("Втулка", "шт"), ("Шпонка", "шт"),
        ("Сетка фильтровальная", "м²"), ("Манометр", "шт"), ("Крыльчатка", "шт"),
        ("Уплотнительный шнур", "м"), ("Кольцо стопорное", "шт"), ("Ролик натяжной", "шт"),
        ("Масло техническое", "л"), ("Фланец", "шт"), ("Элемент фильтрующий", "шт"),
        ("Кожух защитный", "шт"), ("Реле", "шт"), ("Выключатель", "шт"),
        ("Пластина износостойкая", "шт"), ("Шайба пружинная", "шт"), ("Хомут", "шт"),
        ("Сальник", "шт"),
    ]
    for i, (name, unit) in enumerate(material_names, 1):
        db.execute("INSERT INTO materials(sku,name,unit) VALUES (?,?,?)", (f"MAT-{i:03d}", name, unit))
    users: dict[str, int] = {}

    def add_user(username: str, display: str, role: str, brigade: str | None = None,
                 specialty: str = "Механика", qualification_level: int = 1,
                 shift_code: str | None = None) -> None:
        salt, digest = password_record(DEMO_PASSWORD)
        cur = db.execute("""INSERT INTO users(username,display_name,role,brigade,specialty,qualification_level,shift_code,password_salt,password_hash)
                            VALUES (?,?,?,?,?,?,?,?,?)""",
                         (username, display, role, brigade, specialty, qualification_level, shift_code or brigade or "A", salt, digest))
        users[username] = cur.lastrowid

    add_user("master01", "Алия Касымова · мастер", "master")
    add_user("master02", "Данияр Омаров · мастер", "master")
    add_user("manager", "Руководитель участка", "manager")
    names = ["Арман Сейт", "Бекзат Иман", "Ерлан Жума", "Нурлан Ахмет", "Тимур Садык",
             "Айбек Марат", "Самат Ермек", "Руслан Кайрат", "Даулет Аскар", "Мирас Олжас",
             "Азамат Рустем", "Едиль Болат", "Канат Серик", "Алихан Ринат", "Дамир Нурсултан"]
    brigades = ["A", "B", "C"]
    specialties = ["Механика", "Электрика", "Гидравлика", "Конвейерное оборудование"]
    for i, name in enumerate(names, 1):
        shift = brigades[(i - 1) // 5]
        add_user(f"worker{i:02d}", name, "worker", shift, specialties[(i - 1) % len(specialties)],
                 1 + ((i - 1) % 3), shift)

    rng = random.Random(20261002)
    equipment = db.execute("SELECT id,name,area_id FROM equipment ORDER BY id").fetchall()
    fault_ids = [r[0] for r in db.execute("SELECT id FROM fault_codes ORDER BY id")]
    pattern_specs = [
        ("Повторная вибрация насосного узла", "Вибрация выше обычной", "EQ-003"),
        ("Проскальзывание конвейерной ленты", "Проскальзывание ленты", "EQ-002"),
        ("Шум вентиляционного подшипника", "Шум подшипникового узла", "EQ-005"),
        ("Плановый осмотр перед сменой", "Плановый осмотр", "EQ-004"),
    ]
    fault_lookup = {r["label"]: r["id"] for r in db.execute("SELECT id,label FROM fault_codes")}
    equipment_lookup = {r["code"]: r["id"] for r in db.execute("SELECT id,code FROM equipment")}
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    now = utcnow()
    statuses = ["closed"] * 8 + ["issued", "accepted", "queued", "in_progress", "paused", "rejected", "executed", "ai_review", "rework"]
    for n in range(540):
        pat = n % 4
        title, pattern_fault, eq_code = pattern_specs[pat]
        created = start + timedelta(minutes=(92 * 24 * 60 * n) // 540, hours=rng.randrange(0, 23))
        if created > now - timedelta(minutes=5):
            created = now - timedelta(minutes=5 + (n % 240))
        status = statuses[n % len(statuses)]
        # Historical synthetic jobs stay historical; avoid seeding expired open work.
        if status not in ("closed", "rejected") and created < now - timedelta(hours=2):
            status = "closed"
        priority = "emergency" if n % 37 == 0 else "high" if n % 13 == 0 else "planned" if n % 17 == 0 else "normal"
        tech_id = users[f"worker{(n % 15)+1:02d}"]
        master_id = users["master01"] if n % 2 == 0 else users["master02"]
        eq_id = equipment_lookup[eq_code]
        eq_row = next(row for row in equipment if row["id"] == eq_id)
        issued = created
        accepted = created + timedelta(minutes=(2 + n % 8)) if status not in ("issued", "rejected") else None
        started = accepted + timedelta(minutes=8) if accepted and status not in ("accepted", "queued") else None
        completed = created + timedelta(hours=2 + n % 5) if status in ("closed", "executed", "ai_review") else None
        closed = completed + timedelta(minutes=15) if status == "closed" and completed else None
        due = created + timedelta(minutes=180 if priority == "emergency" else 480)
        text = "Осмотр выполнен; результат и дальнейшие действия зафиксированы в синтетической демонстрационной записи." if completed else None
        cur = db.execute("""INSERT INTO orders(code,title,description,priority,area_id,equipment_id,assigned_to,assigned_master_id,status,
                          created_at,issued_at,due_at,accepted_at,started_at,completed_at,closed_at,reject_reason,pause_reason,
                          labor_hours,fault_code_id,completion_text,ai_mode,ai_result,ai_checked_at,rating,rating_reason,rated_by)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (f"DEMO-{n+1:04d}", title, f"Синтетический повторяемый паттерн {pat+1}. Требуется осмотр и описание результата.",
                          priority, eq_row["area_id"], eq_id, tech_id, master_id, status, iso(created), iso(issued), iso(due),
                          iso(accepted) if accepted else None, iso(started) if started else None, iso(completed) if completed else None,
                          iso(closed) if closed else None, "Синтетическая причина отказа" if status == "rejected" else None,
                          "Синтетическая причина паузы" if status == "paused" else None, round(1 + (n % 8) * 0.25, 2) if completed else None,
                          fault_lookup.get(pattern_fault, fault_ids[n % len(fault_ids)]) if completed else None, text,
                          "rules-only" if status in ("closed", "executed", "ai_review") else None,
                          json.dumps({"mode":"rules-only: seeded-demo","verdict":"comments","summary":"Синтетическая запись; не является экспертным выводом.","issues":[]},ensure_ascii=False) if status in ("closed", "executed", "ai_review") else None,
                          iso(completed) if status in ("closed", "executed", "ai_review") else None,
                          (4 + n % 2) if status == "closed" and n % 6 == 0 else None,
                          "Демо-оценка мастера" if status == "closed" and n % 6 == 0 else None,
                          master_id if status == "closed" and n % 6 == 0 else None))
        order_id = cur.lastrowid
        if status in ("closed", "executed", "ai_review") and n % 3 == 0:
            mat_id = db.execute("SELECT id FROM materials ORDER BY id LIMIT 1 OFFSET ?", (n % len(material_names),)).fetchone()[0]
            db.execute("INSERT INTO order_materials(order_id,material_id,quantity) VALUES (?,?,?)", (order_id, mat_id, 1 + (n % 4)))
    # One current synthetic example per lifecycle state keeps the walkthrough reproducible.
    live_statuses = ["issued","accepted","queued","rejected","in_progress","paused","executed","ai_review","rework","closed"]
    for i, live_status in enumerate(live_statuses):
        stamp = iso(now)
        tech_id = users[f"worker{i+1:02d}"]
        master_id = users["master01"] if i in (0,1,2,6,7) else users["master02"]
        eq = equipment[i]
        title = f"Демо · {pattern_specs[i % 4][0]}"
        completed = stamp if live_status in ("executed","ai_review","closed") else None
        accepted = stamp if live_status in ("accepted","queued","in_progress","paused","executed","ai_review","rework","closed") else None
        started = stamp if live_status in ("in_progress","paused","executed","ai_review","rework","closed") else None
        closed_at = stamp if live_status == "closed" else None
        cur = db.execute("""INSERT INTO orders(code,title,description,work_type,priority,area_id,equipment_id,assigned_to,assigned_master_id,status,
                          created_at,issued_at,due_at,accepted_at,started_at,completed_at,closed_at,reject_reason,pause_reason,labor_hours,
                          fault_code_id,completion_text,materials_not_used,ai_mode,ai_result,ai_checked_at,rating,rating_reason,rated_by,complexity)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (f"LIVE-{i+1:02d}",title,"Синтетический наряд для воспроизводимого показа интерфейса.",
                          "planned" if live_status in ("executed","ai_review","closed") else "unscheduled",
                          "emergency" if i == 0 else "normal",eq["area_id"],eq["id"],tech_id,master_id,live_status,
                          stamp,stamp,iso(now+timedelta(hours=3 if i == 0 else 6)),accepted,started,completed,closed_at,
                          "Синтетическая причина отказа" if live_status == "rejected" else None,
                          "Синтетическая причина паузы" if live_status == "paused" else None,
                          1.5 if completed else None,fault_ids[i],
                          "Выполнена проверка и регулировка узла; результат зафиксирован, дополнительное наблюдение не выявлено." if completed else None,
                          int(bool(completed)),"rules-only" if live_status in ("ai_review","closed") else None,
                          json.dumps({"mode":"rules-only: seeded-demo","verdict":"comments","summary":"Синтетическая запись; не является экспертным выводом.","issues":["Демо-наряд без фото после выполнения."]},ensure_ascii=False) if live_status == "ai_review" else None,
                          stamp if live_status == "ai_review" else None,4 if live_status == "closed" else None,
                          "Синтетическая оценка мастера" if live_status == "closed" else None,master_id if live_status == "closed" else None,
                          1.5 if i == 0 else 1.0))
        if live_status == "closed":
            db.execute("UPDATE orders SET materials_not_used=1 WHERE id=?",(cur.lastrowid,))
    db.execute("INSERT INTO audit(actor_id,order_id,event,payload_json,created_at) VALUES (NULL,NULL,'demo_seed',?,?)",
               (json.dumps({"orders": 550, "synthetic": True, "seed": 20261002, "history":540,"walkthrough":10}), iso()))
    db.commit()


def audit(db: sqlite3.Connection, actor_id: int | None, order_id: int | None, event: str, payload: dict) -> None:
    db.execute("INSERT INTO audit(actor_id,order_id,event,payload_json,created_at) VALUES (?,?,?,?,?)",
               (actor_id, order_id, event, json.dumps(payload, ensure_ascii=False), iso()))
    # Adapter boundary only: this row stays local and no Telegram API call is made.
    db.execute("INSERT INTO telegram_outbox(event,payload_json,status,created_at) VALUES (?,?,?,?)",
               (event, json.dumps({"order_id": order_id, **payload}, ensure_ascii=False), "queued_local", iso()))


def notify(db: sqlite3.Connection, user_ids: set[int], order_id: int, message: str) -> None:
    for user_id in user_ids:
        db.execute("INSERT INTO notifications(user_id,order_id,message,created_at) VALUES (?,?,?,?)", (user_id, order_id, message, iso()))


def maybe_escalate(db: sqlite3.Connection) -> None:
    # Idempotent time rules. AI review is not counted as overdue; deadline clock ends at "executed".
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")  # Serialize watchdog and concurrent bootstrap sweeps.
    reminder_minutes = bounded_setting("NARYADAI_REMINDER_MINUTES", 30, 1, 1440)
    repeat_minutes = bounded_setting("NARYADAI_REPEAT_MINUTES", 30, 1, 10080)
    rows = db.execute("SELECT * FROM orders WHERE status IN ('issued','accepted','queued','in_progress','paused','rework')").fetchall()
    now = utcnow()
    for row in rows:
        recipients = {row["assigned_to"], row["assigned_master_id"]}
        if row["status"] == "issued" and row["assigned_brigade"]:
            recipients.update(r[0] for r in db.execute("SELECT id FROM users WHERE role='worker' AND brigade=?",(row["assigned_brigade"],)))
        issued = parse_time(row["issued_at"])
        if row["status"] == "issued" and issued:
            limit = timedelta(minutes=3 if row["priority"] == "emergency" else 10)
            issue_event = db.execute("SELECT COALESCE(MAX(id),0) FROM audit WHERE order_id=? AND event IN ('issued','reassigned','reissue')", (row["id"],)).fetchone()[0]
            if now >= issued + limit and not db.execute("SELECT 1 FROM audit WHERE order_id=? AND event='acceptance_escalated' AND id>? LIMIT 1", (row["id"],issue_event)).fetchone():
                alternative = db.execute("""SELECT u.display_name FROM users u LEFT JOIN orders o ON o.assigned_to=u.id
                    AND o.status IN ('accepted','queued','in_progress','paused','executed','ai_review','rework')
                    WHERE u.role='worker' AND u.id<>? GROUP BY u.id HAVING COUNT(o.id)=0 ORDER BY u.id LIMIT 1""",(row["assigned_to"],)).fetchone()
                payload = {"threshold_minutes": int(limit.total_seconds() // 60), "priority": row["priority"],
                           "suggested_worker": alternative[0] if alternative else None}
                audit(db, None, row["id"], "acceptance_escalated", payload)
                suggestion = f" Свободный исполнитель: {alternative[0]}." if alternative else " Свободных исполнителей нет."
                notify(db, recipients, row["id"], f"Эскалация: наряд {row['code']} не принят за {int(limit.total_seconds()//60)} мин.{suggestion}")
        due = parse_time(row["due_at"])
        if due and now <= due <= now + timedelta(minutes=reminder_minutes):
            prior_reminder = db.execute("SELECT created_at FROM audit WHERE order_id=? AND event='deadline_reminder' ORDER BY id DESC LIMIT 1",(row["id"],)).fetchone()
            if not prior_reminder or now-parse_time(prior_reminder[0]) >= timedelta(minutes=repeat_minutes):
                audit(db, None, row["id"], "deadline_reminder", {"due_at": row["due_at"], "minutes_before": reminder_minutes})
                notify(db, recipients, row["id"], f"Срок наряда {row['code']} наступит через {max(0,int((due-now).total_seconds()//60))} мин.")
        if due and now > due:
            equipment = db.execute("SELECT name FROM equipment WHERE id=?", (row["equipment_id"],)).fetchone()[0]
            area = db.execute("SELECT name FROM areas WHERE id=?", (row["area_id"],)).fetchone()[0]
            worker = db.execute("SELECT display_name FROM users WHERE id=?", (row["assigned_to"],)).fetchone()[0]
            last = db.execute("SELECT payload_json FROM audit WHERE order_id=? AND json_extract(payload_json,'$.reason') IS NOT NULL ORDER BY id DESC LIMIT 1", (row["id"],)).fetchone()
            comment = json.loads(last[0]).get("reason", "Нет комментария") if last else "Нет комментария"
            elapsed = max(0, int((now-due).total_seconds()//60))
            first = not db.execute("SELECT 1 FROM audit WHERE order_id=? AND event='deadline_escalated' LIMIT 1",(row["id"],)).fetchone()
            last_repeat = db.execute("SELECT created_at FROM audit WHERE order_id=? AND event IN ('deadline_escalated','deadline_repeat') ORDER BY id DESC LIMIT 1",(row["id"],)).fetchone()
            should_repeat = not last_repeat or now-parse_time(last_repeat[0]) >= timedelta(minutes=repeat_minutes)
            if first or should_repeat:
                event = "deadline_escalated" if first else "deadline_repeat"
                audit(db, None, row["id"], event, {"due_at": row["due_at"], "minutes_late": elapsed})
                msg = (f"Просрочка {row['code']} · {equipment} · {area} · {worker} · "
                       f"{STATUS_LABELS[row['status']]} · {elapsed} мин · {comment}")
                notify(db, recipients, row["id"], msg)
    db.commit()


def bounded_setting(name: str, default: int, low: int, high: int) -> int:
    try: value = int(os.environ.get(name, default))
    except (TypeError, ValueError): value = default
    return max(low, min(high, value))


def llm_review(text: str, context: dict | None = None) -> dict:
    """OpenAI-compatible adapter via explicit environment settings; never fabricates an AI result."""
    endpoint = os.environ.get("NARYADAI_LLM_API_URL", "").strip()
    key = os.environ.get("NARYADAI_LLM_API_KEY", "").strip()
    model = os.environ.get("NARYADAI_LLM_MODEL", "").strip()
    if not endpoint or not key or not model:
        return rules_review(text, "rules-only: configuration_missing")
    prompt = ("Проверь только текст отчёта ремонтного наряда: ясность, выполненную работу, результат, полноту и внутренние противоречия. "
              "Выбери verdict из accepted, comments, rework. Не оценивай допуск к опасной работе, безопасность оборудования, пригодность к пуску "
              "или право выполнять работу. Отсутствие обязательных фото/материалов будет проверено серверными правилами отдельно. "
              "Ответь JSON-объектом: verdict, summary, issues (массив строк), confidence (число 0..1 о надёжности именно текстовой проверки) "
              "и needs_master_attention (boolean). Если уверенность низкая или недостаточно данных, снизь confidence. Это подсказка, мастер решает окончательно. "
              "Не делай выводов о безопасности или соответствии нормам, если нормы не переданы.\n\nДанные наряда:\n" +
              json.dumps(context or {},ensure_ascii=False)[:3000] + "\n\nТекст отчёта:\n" + text[:8000])
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "response_format": {"type": "json_object"}}, ensure_ascii=False).encode()
    req = urllib.request.Request(endpoint, data=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=18) as response:
            result = json.loads(response.read(128_000))
        content = result["choices"][0]["message"]["content"]
        parsed = json.loads(content) if isinstance(content, str) else content
        if not isinstance(parsed, dict) or not isinstance(parsed.get("summary"), str):
            raise ValueError("unexpected response shape")
        parsed["mode"] = f"llm:{model}"
        parsed["summary"] = parsed["summary"][:4000]
        if not isinstance(parsed.get("issues", []), list) or any(not isinstance(item, str) for item in parsed.get("issues", [])):
            raise ValueError("unexpected issue shape")
        parsed["issues"] = [item[:1000] for item in parsed.get("issues", [])[:20]]
        try:
            confidence = float(parsed.get("confidence"))
            if not 0 <= confidence <= 1: raise ValueError("confidence out of range")
            parsed["confidence"] = confidence
        except (TypeError, ValueError):
            parsed["confidence"] = 0.0
            parsed["confidence_missing"] = True
        if parsed.get("verdict") not in {"accepted", "comments", "rework"}:
            parsed["verdict"] = "comments" if parsed["issues"] else "accepted"
        return parsed
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        # No claim of AI success when remote call fails.
        return rules_review(text, "rules-only: adapter_error", note=type(exc).__name__)


def rules_review(text: str, mode: str, note: str | None = None) -> dict:
    issues: list[str] = []
    normalized = text.strip()
    if len(normalized) < 40:
        issues.append("Отчёт короткий: добавьте конкретику о выполненной работе и результате.")
    if not re.search(r"\b(замен|восстанов|очист|отрегулир|осмотр|провер|смаз|устран|закреп|выполн)\w*", normalized, re.I):
        issues.append("Не найдено явного описания выполненной операции.")
    if not re.search(r"\b(работает|норма|устран|замен|исправ|результат|неисправ|требует|обнаруж)\w*", normalized, re.I):
        issues.append("Добавьте наблюдаемый результат или остаточную проблему.")
    return {"mode": mode, "summary": "Автоматическая проверка правил заполнения; экспертной оценки нет.",
            "issues": issues, "needs_master_attention": bool(issues), **({"note": note} if note else {})}


IMAGE_MIME_FORMAT = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
MAX_IMAGE_PIXELS = 24_000_000
SIMILAR_HASH_DISTANCE = 6


def inspect_image(raw: bytes, declared_mime: str) -> dict:
    """Decode a still image safely, extract capture EXIF, and compute a 64-bit dHash."""
    if declared_mime not in IMAGE_MIME_FORMAT:
        raise ValueError("Поддерживаются только JPEG, PNG и WebP")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format != IMAGE_MIME_FORMAT[declared_mime]:
                    raise ValueError("MIME не совпадает с распознанным форматом изображения")
                width, height = image.size
                if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
                    raise ValueError("Разрешение изображения превышает допустимый предел")
                if getattr(image, "n_frames", 1) != 1:
                    raise ValueError("Анимированные изображения не поддерживаются")
                exif = image.getexif()
                try:
                    exif_ifd = exif.get_ifd(34665)
                except (AttributeError, KeyError, TypeError, ValueError):
                    exif_ifd = {}
                captured_raw = exif_ifd.get(36867) or exif_ifd.get(36868) or exif.get(36867) or exif.get(36868)
                offset_raw = exif_ifd.get(36881) or exif.get(36881)
                try:
                    image.load()
                    oriented = ImageOps.exif_transpose(image)
                    color = oriented.convert("RGB").resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
                    normalized = oriented.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
                except (OSError, ValueError, Image.DecompressionBombError) as exc:
                    raise ValueError("Изображение не удалось полностью декодировать") from exc
                pixels = normalized.tobytes()
                bits = 0
                for y in range(8):
                    for x in range(8):
                        bits = (bits << 1) | int(pixels[y * 9 + x] > pixels[y * 9 + x + 1])
    except (Image.UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Файл не является безопасным читаемым JPEG, PNG или WebP") from exc

    capture_datetime = None
    capture_status = "absent" if not exif else "capture_time_missing"
    offset = str(offset_raw).strip() if offset_raw else None
    if captured_raw:
        try:
            parsed = datetime.strptime(str(captured_raw).strip(), "%Y:%m:%d %H:%M:%S")
            capture_datetime = parsed.isoformat(timespec="seconds")
            if offset and re.fullmatch(r"[+-](?:0\d|1[0-4]):[0-5]\d", offset):
                capture_datetime += offset
            else:
                offset = None
            capture_status = "capture_time_present"
        except (TypeError, ValueError):
            capture_status = "capture_time_unparseable"
            capture_datetime = str(captured_raw)[:64]

    if capture_datetime and capture_status == "capture_time_present":
        score = 5 if offset else 4
    else:
        score = 3
    return {
        "perceptual_hash": f"{bits:016x}",
        "color_signature": "".join(f"{value // 16:x}" for value in color),
        "width": width,
        "height": height,
        "exif_present": bool(exif),
        "capture_datetime": capture_datetime,
        "capture_offset": offset,
        "capture_time_status": capture_status,
        "capture_time_uncertainty": "EXIF не подтверждён: часы устройства и часовой пояс могут быть неверны." if capture_datetime else "EXIF-даты съёмки нет; время съёмки неизвестно.",
        "verifiability_score": score,
    }


def hamming_distance(left: str, right: str) -> int:
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except (TypeError, ValueError):
        return 64


def complete_review(text: str, photo_rows: list[sqlite3.Row], material_count: int, hours: float | None, work_type: str, context: dict | None = None) -> dict:
    result = llm_review(text,context)
    issues = list(result.get("issues", []))
    unique_photos = [p for p in photo_rows if not p["duplicate"]]
    if not photo_rows and work_type == "unscheduled":
        issues.append("После выполнения внеплановой работы не загружено фото результата.")
    elif photo_rows and not unique_photos:
        issues.append("Приложены только дубли фото; загрузите уникальное изображение.")
    if material_count == 0:
        issues.append("В отчёте не указаны материалы. Подтвердите, что материалы не использовались.")
    if not hours or hours <= 0:
        issues.append("Не указано время выполнения.")
    mandatory_photo_missing = work_type == "unscheduled" and not unique_photos
    photo_scores = []
    capture_checks = []
    completion_time = parse_time((context or {}).get("completed_at")) or utcnow()
    capture_window = bounded_setting("NARYADAI_PHOTO_CAPTURE_WINDOW_MINUTES", 60, 1, 1440)
    for photo in unique_photos:
        try:
            metadata = json.loads(photo["metadata_json"])
            if isinstance(metadata.get("verifiability_score"), int):
                photo_scores.append(metadata["verifiability_score"])
            captured = parse_time(metadata.get("capture_datetime"))
            gap = round(abs((completion_time-captured).total_seconds())/60, 1) if captured else None
            capture_checks.append({"capture_datetime":metadata.get("capture_datetime"),"gap_minutes":gap,
                                   "within_window":gap is not None and gap <= capture_window})
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
    photo_score = max(photo_scores) if photo_scores else (None if not photo_rows else 1)
    capture_needs_review = bool(unique_photos) and not any(check["within_window"] for check in capture_checks)
    low_photo_confidence = (photo_score is not None and photo_score <= 3) or capture_needs_review
    model_confidence = result.get("confidence")
    try:
        model_confidence = float(model_confidence) if model_confidence is not None else None
    except (TypeError, ValueError):
        model_confidence = None
    low_model_confidence = model_confidence is not None and model_confidence < 0.60
    if low_photo_confidence:
        issues.append("Низкая проверяемость фото или отсутствует надёжная дата EXIF; нужно решение мастера.")
    if capture_needs_review:
        issues.append(f"Дата съёмки EXIF отсутствует, не имеет часового пояса или отличается от исполнения более чем на {capture_window} мин.; нужна проверка мастером.")
    if low_model_confidence:
        issues.append("Модель сообщила низкую уверенность; обязательно решение мастера.")
    model_verdict = result.get("verdict")
    verdict = "rework" if mandatory_photo_missing or model_verdict == "rework" else "comments" if issues or model_verdict == "comments" or low_model_confidence else "accepted"
    result.update({"issues": issues, "verdict": verdict,
                   "needs_master_attention": bool(issues) or low_photo_confidence or low_model_confidence,
                   "master_confirmation_required": low_photo_confidence or low_model_confidence,
                   "photo_check": {"uploaded": len(photo_rows), "unique": len(unique_photos),
                                    "exact_duplicates": sum(1 for p in photo_rows if p["duplicate_type"] == "exact"),
                                    "similar_duplicates": sum(1 for p in photo_rows if p["duplicate_type"] == "similar"),
                                    "duplicate_detected": len(unique_photos) != len(photo_rows),
                                    "verifiability_score": photo_score,
                                    "low_confidence_requires_master": low_photo_confidence,
                                    "capture_window_minutes":capture_window,"capture_checks":capture_checks,
                                    "explanation": "Оценка 1–5 описывает проверяемость файла (читаемость, повторы и EXIF), не качество ремонта. EXIF может отсутствовать или быть изменён; дата загрузки не подтверждает дату съёмки. Фото не подтверждает исправность."}})
    return result


RATING_WEIGHTS = {"quality": 40, "on_time": 20, "rework_repeat": 20, "quantity_complexity": 10, "unjustified_refusal": 10}


def worker_rating(db: sqlite3.Connection, worker_id: int, from_date: str | None = None,
                  to_date: str | None = None) -> dict:
    """Transparent score for a selected UTC date interval; no repeat penalty without a master link."""
    since, until, start_day, end_day, period_days = date_window(from_date, to_date, default_days=30)
    closed = db.execute("SELECT * FROM orders WHERE assigned_to=? AND status='closed' AND closed_at>=? AND closed_at<?", (worker_id,since,until)).fetchall()
    rated = [r["rating"] for r in closed if r["rating"] is not None]
    quality = round(sum(rated)/len(rated)*20, 1) if rated else None
    timed = [r for r in closed if r["completed_at"] and r["due_at"]]
    on_time = round(sum(1 for r in timed if r["completed_at"] <= r["due_at"])/len(timed)*100,1) if timed else None
    review_count = len(closed)
    rework_ids = {r[0] for r in db.execute("""SELECT DISTINCT a.order_id FROM audit a JOIN orders o ON o.id=a.order_id
        WHERE (a.event='request_rework' OR (a.event='ai_check' AND json_extract(a.payload_json,'$.verdict')='rework'))
        AND o.status='closed' AND o.assigned_to=? AND o.closed_at>=? AND o.closed_at<?""", (worker_id,since,until))}
    legacy_repeat_count = sum(1 for r in closed if r["repeat_confirmed"])
    repeat_rows = db.execute("""SELECT rl.id,rl.current_order_id,cur.code AS current_code,rl.previous_order_id,prev.code AS previous_code,
        cur.created_at AS repeat_created_at,rl.reason,master.display_name AS linked_by,prior_worker.display_name AS previous_worker
        FROM repeat_links rl JOIN orders cur ON cur.id=rl.current_order_id JOIN orders prev ON prev.id=rl.previous_order_id
        JOIN users master ON master.id=rl.linked_by_master_id JOIN users prior_worker ON prior_worker.id=rl.previous_worker_id
        WHERE rl.active=1 AND rl.previous_worker_id=? AND cur.created_at>=? AND cur.created_at<? ORDER BY cur.created_at,rl.id""",
        (worker_id,since,until)).fetchall()
    closed_ids = {r["id"] for r in closed}
    linked_prior_ids = {r["previous_order_id"] for r in repeat_rows if r["previous_order_id"] in closed_ids}
    penalized_ids = rework_ids | linked_prior_ids
    repeat_attributions = [dict(r) for r in repeat_rows]
    repeat_count = len(repeat_rows)
    rework_repeat = round(max(0,1-len(penalized_ids)/max(1,review_count))*100,1) if review_count else None
    points = round(sum(float(r["complexity"] or 1) for r in closed),2)
    quantity_complexity = round(min(100, points/12*100),1) if closed else None
    rejected = db.execute("SELECT COUNT(DISTINCT a.id) FROM audit a WHERE a.actor_id=? AND a.event='reject' AND a.created_at>=? AND a.created_at<?", (worker_id,since,until)).fetchone()[0]
    unjustified = db.execute("SELECT COUNT(DISTINCT a.id) FROM rejection_reviews rr JOIN audit a ON a.id=rr.reject_audit_id WHERE rr.worker_id=? AND rr.unjustified=1 AND a.created_at>=? AND a.created_at<?", (worker_id,since,until)).fetchone()[0]
    refusal_score = round((1-unjustified/rejected)*100,1) if rejected else None
    factors = {"quality": quality,"on_time": on_time,"rework_repeat": rework_repeat,
               "quantity_complexity": quantity_complexity,"unjustified_refusal": refusal_score}
    observed = [(name,value,RATING_WEIGHTS[name]) for name,value in factors.items() if value is not None]
    denominator = sum(weight for _,_,weight in observed)
    score = round(sum(value*weight for _,value,weight in observed)/denominator,1) if denominator else None
    return {"score":score,"factors":factors,"factor_weights":RATING_WEIGHTS,"period_days":period_days,
            "period_from":start_day,"period_to":end_day,"period_timezone":"UTC",
            "evidence":{"closed":len(closed),"rated":len(rated),"on_time_orders":len(timed),"rework_orders":len(rework_ids),
                        "confirmed_repeat_failures":repeat_count,"unattributed_repeat_failures":legacy_repeat_count,
                        "repeat_penalty_status":"explicit_master_link_only","repeat_attributions":repeat_attributions,
                        "orders_with_rework_or_repeat":len(penalized_ids),"complexity_points":points,"rejections":rejected,
                        "unjustified_rejections":unjustified,"observed_weight":denominator}}


def order_dict(db: sqlite3.Connection, row: sqlite3.Row, include_history: bool = False) -> dict:
    area = db.execute("SELECT name FROM areas WHERE id=?", (row["area_id"],)).fetchone()[0]
    equipment = db.execute("SELECT code,name FROM equipment WHERE id=?", (row["equipment_id"],)).fetchone()
    worker = db.execute("SELECT id,display_name,brigade,specialty,qualification_level,shift_code FROM users WHERE id=?", (row["assigned_to"],)).fetchone()
    master = db.execute("SELECT id,display_name FROM users WHERE id=?", (row["assigned_master_id"],)).fetchone()
    fault = db.execute("SELECT code,label FROM fault_codes WHERE id=?", (row["fault_code_id"],)).fetchone() if row["fault_code_id"] else None
    materials = [dict(r) for r in db.execute("SELECT m.id,m.sku,m.name,m.unit,om.quantity FROM order_materials om JOIN materials m ON m.id=om.material_id WHERE om.order_id=? ORDER BY m.sku", (row["id"],))]
    photos = [dict(r) for r in db.execute("SELECT id,file_name,phase,media_type,size_bytes,duplicate,duplicate_type,uploaded_at,metadata_json FROM photos WHERE order_id=? ORDER BY id", (row["id"],))]
    for photo in photos:
        photo["metadata"] = json.loads(photo.pop("metadata_json"))
        photo["metadata"].pop("sha256", None)
        photo["metadata"].pop("perceptual_hash", None)
        photo["url"] = f"/api/photos/{photo['id']}"
    data = dict(row)
    start = parse_time(row["started_at"])
    stop = parse_time(row["completed_at"]) or (utcnow() if row["status"] in ("in_progress","paused") else None)
    cycle_minutes = max(0,int((stop-start).total_seconds()//60)) if start and stop else None
    downtime = 0
    pause_start = None
    if start and stop:
        events = db.execute("SELECT event,created_at FROM audit WHERE order_id=? AND event IN ('pause','resume') ORDER BY id",(row["id"],)).fetchall()
        for event in events:
            event_at=parse_time(event["created_at"])
            if event["event"]=="pause" and event_at: pause_start=event_at
            elif event["event"]=="resume" and pause_start and event_at:
                downtime += max(0,int((event_at-pause_start).total_seconds()//60)); pause_start=None
        if pause_start: downtime += max(0,int((stop-pause_start).total_seconds()//60))
    elif row["status"]=="paused":
        # Synthetic examples may have no event trail; do not infer a lifetime downtime.
        downtime = 0
    due = parse_time(row["due_at"])
    is_late = row["status"] in {"issued", "accepted", "queued", "in_progress", "paused", "rework"} and due and utcnow() > due
    data.update({"status_label": STATUS_LABELS[row["status"]], "priority_label": PRIORITY_LABELS.get(row["priority"], row["priority"]), "is_overdue": bool(is_late),
                 "work_type_label": "Плановый" if row["work_type"] == "planned" else "Внеплановый",
                 "area": area, "equipment": dict(equipment), "worker": {**dict(worker), "on_shift": shift_is_active(worker["shift_code"])}, "master": dict(master),
                 "fault_code": dict(fault) if fault else None, "materials": materials, "photos": photos,
                  "cycle_minutes": cycle_minutes, "paused_minutes": downtime,
                  "active_work_minutes": max(0,cycle_minutes-downtime) if cycle_minutes is not None else None,
                 "acceptance_limit_minutes": 3 if row["priority"] == "emergency" else 10})
    return data


def get_visible_order(db: sqlite3.Connection, user: sqlite3.Row, order_id: int) -> sqlite3.Row | None:
    row = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not row:
        return None
    if user["role"] == "worker" and row["assigned_to"] != user["id"]:
        eligible_team_offer = row["status"] == "issued" and row["assigned_brigade"] and row["assigned_brigade"] == user["brigade"]
        past_involvement = db.execute("SELECT 1 FROM audit WHERE order_id=? AND actor_id=? LIMIT 1",(order_id,user["id"])).fetchone()
        if not eligible_team_offer and not past_involvement:
            return None
    if user["role"] == "master" and row["assigned_master_id"] != user["id"]:
        return None
    return row


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message


class AppHandler(BaseHTTPRequestHandler):
    server_version = "NaryadAI/0.1"

    def log_message(self, fmt: str, *args) -> None:
        # Keep access logs useful but omit request bodies, cookies and credentials.
        super().log_message(fmt, *args)

    def send_json(self, value: dict | list, status: int = 200) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self, limit: int = 6_000_000) -> dict:
        raw_len = self.headers.get("Content-Length", "0")
        try:
            size = int(raw_len)
        except ValueError:
            raise ApiError(400, "Некорректный размер запроса")
        if size < 0 or size > limit:
            raise ApiError(413, "Файл/запрос слишком большой")
        try:
            value = json.loads(self.rfile.read(size) or b"{}")
        except json.JSONDecodeError:
            raise ApiError(400, "Ожидался JSON")
        if not isinstance(value, dict):
            raise ApiError(400, "Ожидался объект JSON")
        return value

    def auth(self) -> sqlite3.Row | None:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            return None
        morsel = cookie.get("naryadai_session")
        if not morsel:
            return None
        token_hash = hashlib.sha256(morsel.value.encode()).hexdigest()
        with connect(self.server.db_path) as db:
            row = db.execute("SELECT u.*,s.csrf,s.expires_at FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?", (token_hash,)).fetchone()
            expiry = parse_time(row["expires_at"]) if row else None
            if not row or not row["is_active"] or not expiry or expiry <= utcnow():
                db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
                return None
            return row

    def require_auth(self) -> sqlite3.Row:
        user = self.auth()
        if not user:
            raise ApiError(401, "Войдите в систему")
        if self.command in ("POST", "PUT", "PATCH", "DELETE") and self.path != "/api/login":
            if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), user["csrf"]):
                raise ApiError(403, "Проверка запроса не пройдена; обновите страницу")
        return user

    def do_GET(self) -> None:
        try:
            path = urlparse(self.path).path
            if path.startswith("/api/"):
                return self.api_get(path)
            if path == "/sw.js":
                return self.static_file("sw.js")
            if path.startswith("/static/"):
                return self.static_file(path[len("/static/"):])
            if path in ("/", "/index.html"):
                return self.static_file("index.html")
            self.send_error(404)
        except ApiError as exc:
            self.send_json({"error": exc.message}, exc.status)
        except Exception as exc:
            self.log_error("GET failed: %s", type(exc).__name__)
            self.send_json({"error": "Внутренняя ошибка сервера"}, 500)

    def do_POST(self) -> None:
        try:
            path = urlparse(self.path).path
            if path == "/api/login":
                return self.login()
            user = self.require_auth()
            if user["role"] == "manager" and path != "/api/logout":
                raise ApiError(403,"Кабинет руководителя доступен только для просмотра")
            if path == "/api/logout":
                return self.logout(user)
            match = re.fullmatch(r"/api/orders/(\d+)/action", path)
            if match:
                return self.order_action(user, int(match.group(1)))
            match = re.fullmatch(r"/api/orders/(\d+)/photos", path)
            if match:
                return self.upload_photo(user, int(match.group(1)))
            match = re.fullmatch(r"/api/orders/(\d+)/assign", path)
            if match:
                return self.reassign(user, int(match.group(1)))
            match = re.fullmatch(r"/api/orders/(\d+)/priority", path)
            if match:
                return self.change_priority(user, int(match.group(1)))
            match = re.fullmatch(r"/api/orders/(\d+)/rating", path)
            if match:
                return self.set_rating(user, int(match.group(1)))
            match = re.fullmatch(r"/api/orders/(\d+)/repeat-link", path)
            if match:
                return self.create_repeat_link(user, int(match.group(1)))
            match = re.fullmatch(r"/api/orders/(\d+)/repeat-link/revoke", path)
            if match:
                return self.revoke_repeat_link(user, int(match.group(1)))
            if path == "/api/orders":
                return self.create_order(user)
            if path == "/api/notifications/read":
                return self.mark_notifications_read(user)
            raise ApiError(404, "Маршрут не найден")
        except ApiError as exc:
            self.send_json({"error": exc.message}, exc.status)
        except Exception as exc:
            self.log_error("POST failed: %s", type(exc).__name__)
            self.send_json({"error": "Внутренняя ошибка сервера"}, 500)

    def login(self) -> None:
        body = self.read_json(20_000)
        username, password = str(body.get("username", ""))[:80], str(body.get("password", ""))[:200]
        with connect(self.server.db_path) as db:
            user = db.execute("SELECT * FROM users WHERE username=? AND is_active=1", (username,)).fetchone()
            if not user or not verify_password(password, user["password_salt"], user["password_hash"]):
                raise ApiError(401, "Неверный логин или пароль")
            raw = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(raw.encode()).hexdigest()
            csrf = secrets.token_urlsafe(24)
            expires = iso(utcnow() + timedelta(seconds=SESSION_SECONDS))
            db.execute("INSERT INTO sessions(token_hash,user_id,csrf,expires_at) VALUES (?,?,?,?)", (token_hash, user["id"], csrf, expires))
            audit(db, user["id"], None, "login", {"role": user["role"]})
            db.commit()
        cookie = f"naryadai_session={raw}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_SECONDS}"
        self.send_json({"user": {"id": user["id"], "username": user["username"], "display_name": user["display_name"],
                                  "role": user["role"], "role_label": ROLE_LABELS[user["role"]], "brigade": user["brigade"], "csrf": csrf}}, 200)
        # send_json already sent headers, so login sets cookie through dedicated path below.

    def logout(self, user: sqlite3.Row) -> None:
        cookie = SimpleCookie(); cookie.load(self.headers.get("Cookie", ""))
        morsel = cookie.get("naryadai_session")
        if morsel:
            token_hash = hashlib.sha256(morsel.value.encode()).hexdigest()
            with connect(self.server.db_path) as db:
                db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
                audit(db, user["id"], None, "logout", {})
                db.commit()
        self.send_json({"ok": True})

    def api_get(self, path: str) -> None:
        if path == "/api/health":
            return self.send_json({"ok": True, "app": "НарядAI", "mode": "local-mvp"})
        user = self.require_auth()
        if path == "/api/me":
            return self.send_json({"user": self.user_public(user)})
        with connect(self.server.db_path) as db:
            maybe_escalate(db)
            if path == "/api/bootstrap":
                return self.bootstrap(db, user)
            if path == "/api/reports":
                return self.reports(db, user)
            if path == "/api/audit":
                if user["role"] not in ("master", "manager"):
                    raise ApiError(403, "Журнал доступен мастеру и руководителю")
                scope = "WHERE (a.actor_id=? OR o.assigned_master_id=?)" if user["role"] == "master" else ""
                scope_args = [user["id"],user["id"]] if user["role"] == "master" else []
                rows = db.execute("""SELECT a.*,u.display_name AS actor_name,o.code AS order_code
                                    FROM audit a LEFT JOIN users u ON u.id=a.actor_id LEFT JOIN orders o ON o.id=a.order_id
                                    """+scope+" ORDER BY a.id DESC LIMIT 100",scope_args).fetchall()
                return self.send_json({"items": [dict(r) for r in rows]})
            match = re.fullmatch(r"/api/orders/(\d+)", path)
            if match:
                row = get_visible_order(db, user, int(match.group(1)))
                if not row:
                    raise ApiError(404, "Наряд не найден")
                equipment_history = [dict(r) for r in db.execute("""SELECT o.id,o.code,o.title,o.status,o.created_at,o.completed_at,o.labor_hours,
                    o.fault_code_id,o.assigned_to,u.display_name AS worker_name,fc.code AS fault_code,fc.label AS fault_label
                    FROM orders o LEFT JOIN fault_codes fc ON fc.id=o.fault_code_id LEFT JOIN users u ON u.id=o.assigned_to
                    WHERE o.equipment_id=? AND o.id<>? ORDER BY o.created_at DESC LIMIT 12""",(row["equipment_id"],row["id"]))]
                repeat_links = [dict(r) for r in db.execute("""SELECT rl.id,rl.current_order_id,rl.previous_order_id,rl.previous_worker_id,
                    rl.reason,rl.linked_at,rl.active,rl.revoke_reason,rl.revoked_at,master.display_name AS linked_by,
                    revoker.display_name AS revoked_by,prev.code AS previous_code,prior.display_name AS previous_worker
                    FROM repeat_links rl JOIN users master ON master.id=rl.linked_by_master_id
                    LEFT JOIN users revoker ON revoker.id=rl.revoked_by_master_id JOIN orders prev ON prev.id=rl.previous_order_id
                    JOIN users prior ON prior.id=rl.previous_worker_id WHERE rl.current_order_id=? ORDER BY rl.id DESC""",(row["id"],))]
                return self.send_json({"order": order_dict(db, row), "history": self.order_history(db, row["id"], user),
                                       "equipment_history": equipment_history,"repeat_links":repeat_links})
        raise ApiError(404, "Маршрут не найден")

    @staticmethod
    def user_public(user: sqlite3.Row, csrf: str | None = None) -> dict:
        return {"id": user["id"], "username": user["username"], "display_name": user["display_name"],
                "role": user["role"], "role_label": ROLE_LABELS[user["role"]], "brigade": user["brigade"],
                "specialty": user["specialty"], "qualification_level": user["qualification_level"],
                "shift_code": user["shift_code"], "shift_label": SHIFT_LABELS.get(user["shift_code"], "—"),
                "on_shift": shift_is_active(user["shift_code"]), "csrf": csrf or (user["csrf"] if "csrf" in user.keys() else "")}

    def bootstrap(self, db: sqlite3.Connection, user: sqlite3.Row) -> None:
        filters = parse_qs(urlparse(self.path).query)
        rating_from = filters.get("rating_from", [None])[0] or None
        rating_to = filters.get("rating_to", [None])[0] or None
        roster_shift = filters.get("shift_code", [""])[0]
        if roster_shift and roster_shift not in SHIFT_WINDOWS_UTC:
            raise ApiError(400, "Код смены не распознан")
        # Validate ranges before building any ratings; invalid filters must never become 500s.
        date_window(rating_from, rating_to, default_days=30)
        where, args = "", []
        if user["role"] == "worker":
            where, args = "WHERE o.assigned_to=? OR (o.status='issued' AND o.assigned_brigade=?)", [user["id"], user["brigade"]]
        elif user["role"] == "master":
            where, args = "WHERE o.assigned_master_id=?", [user["id"]]
        rows = db.execute(f"SELECT o.* FROM orders o {where} ORDER BY CASE o.priority WHEN 'emergency' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, o.due_at,o.id DESC", args).fetchall()
        orders = [order_dict(db, r) for r in rows]
        notifications = [dict(r) for r in db.execute("SELECT n.id,n.message,n.created_at,n.read_at,n.order_id,o.code AS order_code FROM notifications n LEFT JOIN orders o ON o.id=n.order_id WHERE n.user_id=? ORDER BY n.id DESC LIMIT 25", (user["id"],))]
        members = []
        if user["role"] in ("master", "manager"):
            order_filter, filter_args = ("AND o.assigned_master_id=?", [user["id"]]) if user["role"] == "master" else ("", [])
            member_where = ["u.role='worker'"]
            if roster_shift:
                member_where.append("u.shift_code=?"); filter_args.append(roster_shift)
            members = [dict(r) for r in db.execute(f"""SELECT u.id,u.display_name,u.brigade,u.specialty,u.qualification_level,u.shift_code,
                    SUM(CASE WHEN o.status IN ('accepted','queued','in_progress','paused','executed','ai_review','rework') THEN 1 ELSE 0 END) AS active_orders,
                    SUM(CASE WHEN o.status='closed' THEN 1 ELSE 0 END) AS closed_orders,
                    ROUND(AVG(CASE WHEN o.rating IS NOT NULL THEN o.rating END),1) AS rating_avg,
                    COUNT(o.rating) AS rating_count
                    FROM users u LEFT JOIN orders o ON o.assigned_to=u.id {order_filter}
                    WHERE {' AND '.join(member_where)} GROUP BY u.id ORDER BY u.shift_code,u.brigade,u.display_name""", filter_args)]
            for member in members:
                member["rating_detail"] = worker_rating(db, member["id"], rating_from, rating_to)
                self.add_presence(db, member)
        area_counts = [dict(r) for r in db.execute("SELECT a.name,COUNT(o.id) AS count FROM areas a LEFT JOIN orders o ON o.area_id=a.id GROUP BY a.id ORDER BY a.id")]
        recurring = [dict(r) for r in db.execute("""SELECT fc.label,e.name AS equipment,COUNT(*) AS count
                    FROM orders o JOIN fault_codes fc ON fc.id=o.fault_code_id JOIN equipment e ON e.id=o.equipment_id
                    WHERE o.created_at>=? GROUP BY fc.id,e.id HAVING count>=5 ORDER BY count DESC LIMIT 6""",
                    (iso(utcnow()-timedelta(days=30)),))]
        constants = {
            "statuses": STATUS_LABELS, "roles": ROLE_LABELS, "poll_seconds": POLL_SECONDS,
            "shift_labels": SHIFT_LABELS, "shift_windows_utc": SHIFT_WINDOWS_UTC,
            "shift_schedule_is_synthetic": True,
            "areas": [dict(r) for r in db.execute("SELECT * FROM areas ORDER BY id")],
            "equipment": [dict(r) for r in db.execute("SELECT e.*,a.name AS area FROM equipment e JOIN areas a ON a.id=e.area_id ORDER BY e.code")],
            "fault_codes": [dict(r) for r in db.execute("SELECT * FROM fault_codes ORDER BY code")],
            "materials": [dict(r) for r in db.execute("SELECT * FROM materials ORDER BY sku")],
            "users": [dict(r) for r in db.execute("SELECT id,display_name,role,brigade,specialty,qualification_level,shift_code FROM users ORDER BY role,display_name")]
        }
        free_workers = [dict(r) for r in db.execute("""SELECT u.id,u.username,u.display_name,u.brigade,u.specialty,u.qualification_level,u.shift_code,
                    SUM(CASE WHEN o.status IN ('accepted','queued','in_progress','paused','executed','ai_review','rework') THEN 1 ELSE 0 END) AS active_orders
                    FROM users u LEFT JOIN orders o ON o.assigned_to=u.id WHERE u.role='worker' GROUP BY u.id ORDER BY active_orders,u.display_name""")] if user["role"] in ("master", "manager") else []
        for person in free_workers:
            person["rating_detail"] = worker_rating(db, person["id"], rating_from, rating_to)
            self.add_presence(db, person)
        my_rating = worker_rating(db,user["id"],rating_from,rating_to) if user["role"] == "worker" else None
        return self.send_json({"user": self.user_public(user), "orders": orders, "notifications": notifications,
                               "members": members, "free_workers": free_workers, "area_counts": area_counts, "recurring": recurring,
                               "my_rating": my_rating, "constants": constants, "server_time": iso(), "synthetic": True})

    @staticmethod
    def add_presence(db: sqlite3.Connection, person: dict) -> None:
        if not person.get("id"): return
        person["on_shift"] = shift_is_active(person.get("shift_code"))
        open_rows = db.execute("SELECT id,code,title,status FROM orders WHERE assigned_to=? AND status IN ('issued','accepted','queued','in_progress','paused','rework') ORDER BY due_at",(person["id"],)).fetchall()
        executing = next((r for r in open_rows if r["status"] in ("in_progress","paused")),None)
        queued = [r for r in open_rows if r["status"] in ("accepted","queued","rework")]
        offer = next((r for r in open_rows if r["status"]=="issued"),None)
        person["queue_count"] = len(queued)
        person["current_order"] = dict(executing) if executing else None
        person["availability"] = "off_shift" if not person["on_shift"] else "busy" if executing else "queued" if queued else "offered" if offer else "free"
        person["availability_label"] = {"busy":"Выполняет наряд","queued":"Есть очередь","offered":"Есть новый наряд","free":"Свободен","off_shift":"Не на смене"}[person["availability"]]

    def reports(self, db: sqlite3.Connection, user: sqlite3.Row) -> None:
        query = parse_qs(urlparse(self.path).query)
        day = query.get("date", [utcnow().date().isoformat()])[0]
        from_value = query.get("date_from", [day])[0] or day
        to_value = query.get("date_to", [day])[0] or day
        start, until, start_day, end_day, days = date_window(from_value, to_value, default_days=1)
        brigade = query.get("brigade", [""])[0]
        shift_code = query.get("shift_code", [""])[0]
        if brigade and brigade not in ("A", "B", "C"): raise ApiError(400, "Неизвестная бригада")
        if shift_code and shift_code not in SHIFT_WINDOWS_UTC: raise ApiError(400, "Неизвестная смена")
        where = ["o.completed_at>=?", "o.completed_at<?"]
        params: list = [start, until]
        if user["role"] == "worker": where.append("o.assigned_to=?"); params.append(user["id"])
        elif user["role"] == "master": where.append("o.assigned_master_id=?"); params.append(user["id"])
        if brigade: where.append("u.brigade=?"); params.append(brigade)
        if shift_code: where.append("u.shift_code=?"); params.append(shift_code)
        items = [dict(r) for r in db.execute(f"""SELECT o.id,o.code,o.title,o.status,o.created_at,o.completed_at,o.closed_at,o.issued_at,o.due_at,
                    o.labor_hours,o.completion_text,o.rating,o.rating_reason,o.reject_reason,u.display_name AS worker,u.brigade,u.shift_code,
                    fc.code AS fault_code,e.name AS equipment
                    FROM orders o JOIN users u ON u.id=o.assigned_to JOIN equipment e ON e.id=o.equipment_id
                    LEFT JOIN fault_codes fc ON fc.id=o.fault_code_id WHERE {' AND '.join(where)} ORDER BY o.completed_at""", params)]
        hours = round(sum(r["labor_hours"] or 0 for r in items), 2)
        top = max(items, key=lambda r: sum(1 for x in items if x["fault_code"] and x["fault_code"] == r["fault_code"]), default=None)
        late = sum(1 for r in items if r["due_at"] and r["completed_at"] and r["completed_at"] > r["due_at"])
        pause_total = 0; worker_totals: dict[str, dict] = {}; materials: dict[str, dict] = {}
        item_ids = [r["id"] for r in items]
        for item in items:
            group = worker_totals.setdefault(item["worker"], {"worker": item["worker"], "brigade": item["brigade"],
                "shift_code": item["shift_code"], "completed": 0, "closed": 0, "labor_hours": 0.0})
            group["completed"] += 1; group["closed"] += int(item["status"] == "closed"); group["labor_hours"] += item["labor_hours"] or 0
            events = db.execute("SELECT event,created_at FROM audit WHERE order_id=? AND event IN ('pause','resume') ORDER BY id", (item["id"],)).fetchall()
            pause_start = None; end_time = parse_time(item["closed_at"] or item["completed_at"])
            for event in events:
                at = parse_time(event["created_at"])
                if event["event"] == "pause" and at: pause_start = at
                elif event["event"] == "resume" and pause_start and at:
                    pause_total += max(0, int((at-pause_start).total_seconds()//60)); pause_start = None
            if pause_start and end_time: pause_total += max(0, int((end_time-pause_start).total_seconds()//60))
        if item_ids:
            placeholders = ",".join("?" for _ in item_ids)
            for row in db.execute(f"""SELECT m.sku,m.name,m.unit,SUM(om.quantity) AS quantity FROM order_materials om
                JOIN materials m ON m.id=om.material_id WHERE om.order_id IN ({placeholders}) GROUP BY m.id ORDER BY m.sku""", item_ids):
                materials[row["sku"]] = dict(row)
        scope = []; scope_args: list = []
        if user["role"] == "worker": scope.append("o.assigned_to=?"); scope_args.append(user["id"])
        elif user["role"] == "master": scope.append("o.assigned_master_id=?"); scope_args.append(user["id"])
        if brigade: scope.append("u.brigade=?"); scope_args.append(brigade)
        if shift_code: scope.append("u.shift_code=?"); scope_args.append(shift_code)
        scope_sql = (" AND " + " AND ".join(scope)) if scope else ""
        issued = db.execute("SELECT COUNT(*) FROM orders o JOIN users u ON u.id=o.assigned_to WHERE o.issued_at>=? AND o.issued_at<?" + scope_sql,
                            [start, until, *scope_args]).fetchone()[0]
        overdue = db.execute("SELECT COUNT(*) FROM orders o JOIN users u ON u.id=o.assigned_to WHERE o.status IN ('issued','accepted','queued','in_progress','paused','rework') AND o.due_at<?" + scope_sql,
                             [iso(), *scope_args]).fetchone()[0]
        closed = sum(1 for r in items if r["status"] == "closed")
        summary_text = (f"За {start_day} — {end_day} завершено {closed} из {len(items)} нарядов; трудозатраты {hours} ч" +
                        (f"; чаще указан код {top['fault_code']} на {top['equipment']}" if top and top["fault_code"] else "."))
        summary = {"date_from":start_day,"date_to":end_day,"period_days":days,"brigade":brigade or "все",
                   "shift_code":shift_code or "все","shift_is_synthetic":True,"issued":issued,"completed":len(items),
                   "closed":closed,"labor_hours":hours,"late_completions":late,"current_overdue_orders":overdue,
                   "pause_minutes":pause_total,"pause_minutes_note":"Пауза вычислена только по событиям журнала и не является подтверждённым простоем оборудования.",
                   "synthetic":True,"summary_mode":"rules-only"}
        for group in worker_totals.values(): group["labor_hours"] = round(group["labor_hours"], 2)
        return self.send_json({"summary":summary,"items":items,"worker_totals":list(worker_totals.values()),
                               "material_totals":list(materials.values()),"ai_summary":summary_text})

    def order_history(self, db: sqlite3.Connection, order_id: int, user: sqlite3.Row) -> list[dict]:
        rows = db.execute("""SELECT a.event,a.payload_json,a.created_at,u.display_name AS actor_name
                             FROM audit a LEFT JOIN users u ON u.id=a.actor_id WHERE a.order_id=? ORDER BY a.id""", (order_id,)).fetchall()
        return [{**dict(r), "payload": json.loads(r["payload_json"])} for r in rows]

    def create_order(self, user: sqlite3.Row) -> None:
        if user["role"] != "master": raise ApiError(403, "Новый наряд может выдать мастер")
        body = self.read_json(30_000)
        title, description = str(body.get("title", "")).strip()[:160], str(body.get("description", "")).strip()[:3000]
        if len(title) < 4 or len(description) < 10: raise ApiError(400, "Добавьте название и описание неисправности")
        work_type = str(body.get("work_type", "unscheduled"))
        priority = str(body.get("priority", "normal"))
        if work_type not in ("planned", "unscheduled"): raise ApiError(400, "Выберите плановый или внеплановый тип")
        if priority not in PRIORITY_LABELS: raise ApiError(400, "Выберите один из четырёх приоритетов")
        try: area_id, equipment_id = int(body.get("area_id")), int(body.get("equipment_id"))
        except (TypeError, ValueError): raise ApiError(400, "Выберите участок и оборудование")
        with connect(self.server.db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            equipment = db.execute("SELECT id FROM equipment WHERE id=? AND area_id=?", (equipment_id, area_id)).fetchone()
            if not equipment: raise ApiError(400, "Оборудование не относится к выбранному участку")
            brigade = str(body.get("brigade", "")).strip() or None
            worker_id = body.get("worker_id")
            if bool(brigade) == bool(worker_id): raise ApiError(400, "Выберите исполнителя либо бригаду")
            if brigade:
                if brigade not in {"A", "B", "C"}: raise ApiError(400, "Бригада не найдена")
                worker = db.execute("""SELECT u.id FROM users u LEFT JOIN orders o ON o.assigned_to=u.id
                    AND o.status IN ('accepted','queued','in_progress','paused','executed','ai_review','rework')
                    WHERE u.role='worker' AND u.brigade=? GROUP BY u.id ORDER BY COUNT(o.id),u.id LIMIT 1""", (brigade,)).fetchone()
                targets = {r[0] for r in db.execute("SELECT id FROM users WHERE role='worker' AND brigade=?", (brigade,))}
            else:
                try: worker_id = int(worker_id)
                except (TypeError, ValueError): raise ApiError(400, "Исполнитель не выбран")
                worker = db.execute("SELECT id,brigade FROM users WHERE id=? AND role='worker' AND is_active=1", (worker_id,)).fetchone()
                if not worker: raise ApiError(400, "Исполнитель не найден")
                brigade = None; targets = {worker["id"]}
            due_value = str(body.get("due_at", "")).strip()
            if due_value:
                deadline = parse_time(due_value)
                if not deadline: raise ApiError(400, "Срок должен содержать дату и время")
                if deadline <= utcnow(): raise ApiError(400, "Срок должен быть в будущем")
                due_value = iso(deadline.astimezone(timezone.utc))
            else:
                try: hours = float(body.get("norm_hours", 8))
                except (TypeError, ValueError): raise ApiError(400, "Укажите срок")
                if not math.isfinite(hours) or hours <= 0 or hours > 720: raise ApiError(400, "Норматив срока должен быть до 720 часов")
                due_value = iso(utcnow()+timedelta(hours=hours))
            now = iso()
            code = f"NA-{utcnow():%y%m%d}-{secrets.token_hex(2).upper()}"
            cur = db.execute("""INSERT INTO orders(code,title,description,work_type,priority,area_id,equipment_id,assigned_to,assigned_brigade,
                           assigned_master_id,status,created_at,issued_at,due_at,complexity)
                           VALUES (?,?,?,?,?,?,?,?,?,?,'issued',?,?,?,?)""", (code,title,description,work_type,priority,area_id,equipment_id,worker["id"],brigade,user["id"],now,now,due_value,
                             1.5 if priority in ("high","emergency") else 1.0))
            order_id = cur.lastrowid
            audit(db,user["id"],order_id,"issued",{"code":code,"work_type":work_type,"priority":priority,"assigned_brigade":brigade})
            notify(db,targets,order_id,f"Новый наряд {code}: {title}")
            db.commit()
            return self.send_json({"order": order_dict(db,db.execute("SELECT * FROM orders WHERE id=?",(order_id,)).fetchone())},201)

    def reassign(self, user: sqlite3.Row, order_id: int) -> None:
        if user["role"] != "master": raise ApiError(403,"Переназначать может только мастер")
        body = self.read_json(10_000)
        with connect(self.server.db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = get_visible_order(db,user,order_id)
            if not row: raise ApiError(404,"Наряд не найден")
            if row["status"] not in ("issued","rejected") or row["cancelled_by_master"]: raise ApiError(409,"Переназначение доступно только до принятия либо после отказа исполнителя")
            brigade = str(body.get("brigade", "")).strip() or None
            worker_id = body.get("worker_id")
            if bool(brigade) == bool(worker_id): raise ApiError(400,"Выберите исполнителя либо бригаду")
            if brigade:
                if brigade not in {"A","B","C"}: raise ApiError(400,"Бригада не найдена")
                worker = db.execute("""SELECT u.id FROM users u LEFT JOIN orders o ON o.assigned_to=u.id AND o.status IN ('accepted','queued','in_progress','paused','executed','ai_review','rework')
                    WHERE u.role='worker' AND u.brigade=? GROUP BY u.id ORDER BY COUNT(o.id),u.id LIMIT 1""",(brigade,)).fetchone()
                targets={r[0] for r in db.execute("SELECT id FROM users WHERE role='worker' AND brigade=?",(brigade,))}
            else:
                try: worker_id=int(worker_id)
                except (TypeError,ValueError): raise ApiError(400,"Исполнитель не выбран")
                worker=db.execute("SELECT id FROM users WHERE id=? AND role='worker' AND is_active=1",(worker_id,)).fetchone()
                if not worker: raise ApiError(400,"Исполнитель не найден")
                brigade=None; targets={worker["id"]}
            due = iso(utcnow()+timedelta(minutes=180 if row["priority"] == "emergency" else 480))
            db.execute("UPDATE orders SET assigned_to=?,assigned_brigade=?,status='issued',issued_at=?,due_at=?,reject_reason=NULL WHERE id=?",(worker["id"],brigade,iso(),due,order_id))
            audit(db,user["id"],order_id,"reassigned",{"from_status":row["status"],"worker_id":worker["id"],"brigade":brigade})
            notify(db,targets,order_id,f"Наряд {row['code']} назначен вам")
            db.commit()
            return self.send_json({"ok":True})

    def change_priority(self, user: sqlite3.Row, order_id: int) -> None:
        if user["role"] != "master": raise ApiError(403,"Приоритет может менять только мастер")
        body=self.read_json(5_000); priority=str(body.get("priority",""))
        if priority not in PRIORITY_LABELS: raise ApiError(400,"Выберите один из четырёх приоритетов")
        with connect(self.server.db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            row=get_visible_order(db,user,order_id)
            if not row: raise ApiError(404,"Наряд не найден")
            if row["status"] in ("executed","ai_review","closed","rejected"): raise ApiError(409,"Приоритет нельзя менять после исполнения или закрытия")
            db.execute("UPDATE orders SET priority=?,complexity=? WHERE id=?",(priority,1.5 if priority in ("high","emergency") else 1.0,order_id))
            audit(db,user["id"],order_id,"priority_changed",{"before":row["priority"],"after":priority})
            db.commit()
            return self.send_json({"ok":True,"priority":priority})

    def order_action(self, user: sqlite3.Row, order_id: int) -> None:
        body = self.read_json(50_000)
        action = str(body.get("action", ""))
        with connect(self.server.db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = get_visible_order(db, user, order_id)
            if not row:
                raise ApiError(404, "Наряд не найден")
            role, status = user["role"], row["status"]
            if role == "worker" and row["assigned_to"] != user["id"]:
                team_offer = status == "issued" and row["assigned_brigade"] and row["assigned_brigade"] == user["brigade"]
                if not team_offer or action not in ("accept", "queue", "reject"):
                    raise ApiError(403, "Изменять наряд может только текущий назначенный исполнитель")
            reason = str(body.get("reason", "")).strip()[:1000]
            allowed: dict[str, tuple[str, set[str]]] = {
                "accept": ("accepted", {"issued", "queued"}), "reject": ("rejected", {"issued"}),
                "queue": ("queued", {"issued"}), "start": ("in_progress", {"accepted", "rework"}),
                "pause": ("paused", {"in_progress"}), "resume": ("in_progress", {"paused"}),
                "complete": ("executed", {"in_progress"}), "ai_check": ("ai_review", {"executed"}),
                "request_rework": ("rework", {"ai_review"}), "close": ("closed", {"ai_review"}),
                "reissue": ("issued", {"rejected"}), "cancel": ("rejected", {"issued","accepted","queued"}),
            }
            if action not in allowed:
                raise ApiError(400, "Неизвестное действие")
            target, sources = allowed[action]
            if status not in sources:
                raise ApiError(409, f"Переход {STATUS_LABELS[status]} → {STATUS_LABELS[target]} сейчас недоступен")
            if action in ("accept", "reject", "queue", "start", "pause", "resume", "complete", "ai_check") and role != "worker":
                raise ApiError(403, "Действие доступно только назначенному исполнителю")
            if action in ("request_rework", "close", "reissue", "cancel") and role != "master":
                raise ApiError(403, "Решение доступно только мастеру")
            if role == "manager":
                raise ApiError(403, "Руководитель имеет доступ только для просмотра")
            if action in ("reject", "pause", "request_rework", "cancel") and len(reason) < 4:
                raise ApiError(400, "Укажите причину (не менее 4 символов)")
            payload: dict = {"from": status, "to": target}
            updates: dict[str, object] = {"status": target}
            if action == "accept": updates.update({"accepted_at": iso(), "assigned_to": user["id"]})
            if action == "queue": updates["assigned_to"] = user["id"]
            if action == "reject": updates["assigned_to"] = user["id"]
            if action == "cancel": updates.update({"cancelled_by_master": 1, "reject_reason": "Отменено мастером: " + reason})
            if action in ("reject", "request_rework"): updates["reject_reason"] = reason; payload["reason"] = reason
            if action == "pause": updates["pause_reason"] = reason; payload["reason"] = reason
            if action == "start": updates["started_at"] = iso()
            if action == "complete":
                text_value = str(body.get("completion_text", "")).strip()[:8000]
                hours = body.get("labor_hours")
                try: hours = float(hours)
                except (TypeError, ValueError): raise ApiError(400, "Укажите затраченное время")
                if not math.isfinite(hours) or hours <= 0 or hours > 72: raise ApiError(400, "Часы должны быть больше 0 и не более 72")
                try: fault_id = int(body.get("fault_code_id"))
                except (TypeError, ValueError): raise ApiError(400, "Выберите код неисправности")
                if not db.execute("SELECT id FROM fault_codes WHERE id=?", (fault_id,)).fetchone():
                    raise ApiError(400, "Код неисправности не найден")
                material_values = body.get("materials", [])
                if not isinstance(material_values, list): raise ApiError(400, "Материалы должны быть списком")
                materials_not_used = bool(body.get("materials_not_used"))
                if not material_values and not materials_not_used: raise ApiError(400, "Добавьте использованные материалы либо подтвердите, что материалы не использовались")
                if len(text_value) < 20: raise ApiError(400, "Опишите выполненную работу и результат (не менее 20 символов)")
                photo_rows = db.execute("SELECT COUNT(*) AS total,SUM(CASE WHEN duplicate=0 THEN 1 ELSE 0 END) AS unique_count FROM photos WHERE order_id=? AND phase='after'", (order_id,)).fetchone()
                material_ids = set()
                for item in material_values:
                    try: material_id, quantity = int(item["material_id"]), float(item["quantity"])
                    except (KeyError, TypeError, ValueError): raise ApiError(400, "Проверьте материал и количество")
                    if not math.isfinite(quantity) or quantity <= 0 or quantity > 100000 or not db.execute("SELECT id FROM materials WHERE id=?", (material_id,)).fetchone():
                        raise ApiError(400, "Количество или материал некорректны")
                    if material_id in material_ids:
                        raise ApiError(400, "Материал указан повторно: объедините количество в одной строке")
                    material_ids.add(material_id)
                updates.update({"completed_at": iso(), "labor_hours": hours, "fault_code_id": fault_id, "completion_text": text_value, "materials_not_used": int(materials_not_used)})
                db.execute("DELETE FROM order_materials WHERE order_id=?", (order_id,))
                for item in material_values:
                    db.execute("INSERT INTO order_materials(order_id,material_id,quantity) VALUES (?,?,?)",
                               (order_id, int(item["material_id"]), float(item["quantity"])))
                payload.update({"labor_hours": hours, "fault_code_id": fault_id, "materials_count": len(material_values), "materials_not_used": materials_not_used, "photos_count": photo_rows["unique_count"] or 0})
            if action == "ai_check":
                text_value = row["completion_text"] or ""
                photo_set = db.execute("SELECT duplicate,duplicate_type,perceptual_hash,metadata_json,uploaded_at FROM photos WHERE order_id=? AND phase='after'", (order_id,)).fetchall()
                material_rows = db.execute("SELECT m.sku,m.name,m.unit,om.quantity FROM order_materials om JOIN materials m ON m.id=om.material_id WHERE om.order_id=?", (order_id,)).fetchall()
                material_count = len(material_rows)
                started = parse_time(row["started_at"]); due = parse_time(row["due_at"])
                deadline_window = round((due-started).total_seconds()/3600,2) if due and started else None
                context = {"problem":row["description"],"equipment":db.execute("SELECT name FROM equipment WHERE id=?",(row["equipment_id"],)).fetchone()[0],
                           "fault_code":db.execute("SELECT code,label FROM fault_codes WHERE id=?",(row["fault_code_id"],)).fetchone()["label"] if row["fault_code_id"] else None,
                           "materials":[dict(m) for m in material_rows],"materials_not_used":bool(row["materials_not_used"]),
                           "reported_labor_hours":row["labor_hours"],"hours_until_deadline_from_start":deadline_window,
                           "unique_after_photos":sum(1 for p in photo_set if not p["duplicate"]),"work_type":row["work_type"],"completed_at":row["completed_at"]}
                # Keep the database writable while an approved external model responds.
                # The conditional re-read below makes the final transition single-winner.
                db.commit()
                reviewed = complete_review(text_value, photo_set, material_count + int(row["materials_not_used"]), row["labor_hours"], row["work_type"],context)
                db.execute("BEGIN IMMEDIATE")
                latest = get_visible_order(db, user, order_id)
                if not latest or latest["status"] != "executed":
                    raise ApiError(409, "Проверка уже выполнена или состояние наряда изменилось")
                row = latest
                reviewed["materials_check"] = {"lines":len(material_rows),"positive_quantities":all(float(m["quantity"])>0 for m in material_rows),"norm_comparison":"not available: no approved material norms in the supplied demo data"}
                reviewed["time_check"] = {"reported_labor_hours":row["labor_hours"],"hours_until_deadline_from_start":deadline_window,
                                           "compared_to_approved_norm":False,"note":"Срок наряда — контрольный срок, не норматив трудоёмкости."}
                if photo_set:
                    uploaded=max(parse_time(p["uploaded_at"]) for p in photo_set if parse_time(p["uploaded_at"]))
                    completed_at=parse_time(row["completed_at"])
                    gap=int(abs((completed_at-uploaded).total_seconds())//60) if completed_at and uploaded else None
                    reviewed["photo_check"]["upload_gap_minutes"] = gap
                    if gap is not None and gap > 60:
                        reviewed["issues"].append("Время загрузки фото более чем на час отличается от фиксации исполнения; время съёмки не подтверждено.")
                        reviewed["verdict"]="comments" if reviewed["verdict"]=="accepted" else reviewed["verdict"]
                if reviewed["verdict"] == "rework":
                    target = "rework"
                    updates["status"] = target
                    updates["reject_reason"] = "ИИ-проверка: " + "; ".join(reviewed.get("issues", []))[:900]
                updates.update({"ai_mode": reviewed["mode"], "ai_result": json.dumps(reviewed, ensure_ascii=False), "ai_checked_at": iso()})
                payload.update({"mode": reviewed["mode"], "verdict": reviewed.get("verdict"), "issues_count": len(reviewed.get("issues", [])), "summary": reviewed.get("summary", "")})
            if action == "close":
                issues = []
                if not row["completion_text"] or len(row["completion_text"]) < 20: issues.append("нет описания работы")
                if not row["fault_code_id"]: issues.append("не выбран код неисправности")
                if not row["labor_hours"] or row["labor_hours"] <= 0: issues.append("не указано время")
                material_count = db.execute("SELECT COUNT(*) FROM order_materials WHERE order_id=?", (order_id,)).fetchone()[0]
                if not material_count and not row["materials_not_used"]: issues.append("не подтверждены материалы")
                photos = db.execute("SELECT COUNT(*) FROM photos WHERE order_id=? AND phase='after' AND duplicate=0", (order_id,)).fetchone()[0]
                if row["work_type"] == "unscheduled" and not photos: issues.append("для внепланового наряда нужно фото после выполнения")
                ai_verdict = json.loads(row["ai_result"] or "{}").get("verdict")
                if ai_verdict == "rework": issues.append("результат проверки требует доработки; мастер может направить наряд на доработку")
                if issues: raise ApiError(409, "Нельзя принять наряд: " + "; ".join(issues))
                if ai_verdict == "comments" and len(reason) < 4: raise ApiError(400, "ИИ указал замечания; укажите причину решения мастера")
                updates["closed_at"] = iso()
                payload["reason"] = reason or "Окончательная приёмка мастером"
            if action == "reissue":
                updates.update({"issued_at": iso(), "due_at": iso(utcnow()+timedelta(minutes=180 if row["priority"] == "emergency" else 480)), "reject_reason": None, "cancelled_by_master": 0})
                payload["reason"] = "Повторная выдача мастером"
            sets = ",".join(f"{key}=?" for key in updates)
            payload["to"] = target
            db.execute(f"UPDATE orders SET {sets} WHERE id=?", [*updates.values(), order_id])
            audit(db, user["id"], order_id, action, payload)
            msg = f"Наряд {row['code']}: {STATUS_LABELS[target]}"
            notify(db, {row["assigned_to"], row["assigned_master_id"]}, order_id, msg)
            db.commit()
            fresh = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            return self.send_json({"order": order_dict(db, fresh), "history": self.order_history(db, order_id, user)})

    def upload_photo(self, user: sqlite3.Row, order_id: int) -> None:
        body = self.read_json(6_000_000)
        with connect(self.server.db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = get_visible_order(db, user, order_id)
            if not row: raise ApiError(404, "Наряд не найден")
            phase = str(body.get("phase", "after"))
            if phase not in ("before", "after"): raise ApiError(400,"Фаза фото не распознана")
            can_worker_upload = phase == "after" and user["role"] == "worker" and row["status"] in ("in_progress", "paused") and row["assigned_to"] == user["id"]
            can_master_upload = phase == "before" and user["role"] == "master" and row["status"] == "issued"
            if not (can_worker_upload or can_master_upload):
                raise ApiError(403, "Исполнитель добавляет фото в работе; мастер может добавить до пяти фото к выдаваемому наряду")
            if db.execute("SELECT COUNT(*) FROM photos WHERE order_id=? AND phase=?", (order_id,phase)).fetchone()[0] >= 5:
                raise ApiError(400, "Можно приложить не более пяти фотографий каждой фазы: до и после")
            data_url = str(body.get("data_url", ""))
            match = re.fullmatch(r"data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=]+)", data_url)
            if not match: raise ApiError(400, "Поддерживаются JPEG, PNG и WebP")
            mime, encoded = match.groups()
            try: raw = base64.b64decode(encoded, validate=True)
            except ValueError: raise ApiError(400, "Файл повреждён")
            if not raw or len(raw) > 4_000_000: raise ApiError(413, "Максимальный размер фото — 4 МБ")
            valid = (mime == "image/jpeg" and raw.startswith(b"\xff\xd8\xff")) or (mime == "image/png" and raw.startswith(b"\x89PNG\r\n\x1a\n")) or (mime == "image/webp" and raw.startswith(b"RIFF") and raw[8:12] == b"WEBP")
            if not valid: raise ApiError(400, "Тип изображения не совпадает с содержимым файла")
            try:
                inspected = inspect_image(raw, mime)
            except ValueError as exc:
                raise ApiError(400, str(exc))
            digest = hashlib.sha256(raw).hexdigest()
            exact_duplicate = bool(db.execute("SELECT id FROM photos WHERE sha256=? LIMIT 1", (digest,)).fetchone())
            distances = [(hamming_distance(r[0], inspected["perceptual_hash"]), r[1]) for r in db.execute("SELECT perceptual_hash,color_signature FROM photos WHERE perceptual_hash IS NOT NULL")]
            compatible_distances = []
            for distance, old_color in distances:
                if not old_color or not inspected["color_signature"]:
                    continue
                color_distance = sum(abs(int(a, 16) - int(b, 16)) for a, b in zip(old_color, inspected["color_signature"]))
                if len(old_color) == len(inspected["color_signature"]) and color_distance <= 3:
                    compatible_distances.append(distance)
            nearest_distance = min(compatible_distances) if compatible_distances else None
            similar_duplicate = not exact_duplicate and nearest_distance is not None and nearest_distance <= SIMILAR_HASH_DISTANCE
            duplicate_type = "exact" if exact_duplicate else "similar" if similar_duplicate else "none"
            duplicate = duplicate_type != "none"
            if exact_duplicate:
                inspected["verifiability_score"] = 1
            elif similar_duplicate:
                inspected["verifiability_score"] = 2
            inspected.update({"exact_duplicate": exact_duplicate, "similar_duplicate": similar_duplicate,
                              "nearest_hash_distance": nearest_distance,
                              "similarity_rule": f"dHash 64-bit; Hamming distance <= {SIMILAR_HASH_DISTANCE}"})
            ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[mime]
            file_name = re.sub(r"[^A-Za-zА-Яа-яЁё0-9._ -]", "_", str(body.get("file_name", "photo"))[:100]).strip() or "photo"
            stored_name = secrets.token_hex(16) + ext
            media_root = MEDIA.resolve()
            location = (media_root / stored_name).resolve()
            if location.parent != media_root: raise ApiError(400, "Недопустимый путь хранения файла")
            location.write_bytes(raw)
            metadata = {"declared_type": mime, "bytes": len(raw), "sha256": digest,
                        "upload_time_utc": iso(), "freshness_claim": "Не подтверждается: EXIF может отсутствовать или быть изменён; дата загрузки не является датой съёмки.",
                        "client_compressed": bool(body.get("client_compressed")),
                        "source_size_bytes_claim": body.get("source_size_bytes") if isinstance(body.get("source_size_bytes"), int) and 0 <= body.get("source_size_bytes") <= 50_000_000 else None,
                        "source_media_type_claim": body.get("source_media_type") if body.get("source_media_type") in ("image/jpeg", "image/png", "image/webp") else None,
                        "client_exif_transfer_succeeded_claim": body.get("exif_transfer_succeeded") is True,
                        **inspected}
            try:
                cur = db.execute("INSERT INTO photos(order_id,file_name,phase,media_type,file_path,size_bytes,sha256,duplicate,duplicate_type,perceptual_hash,color_signature,uploaded_at,metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                 (order_id, file_name, phase, mime, str(location), len(raw), digest, int(duplicate), duplicate_type, inspected["perceptual_hash"], inspected["color_signature"], iso(), json.dumps(metadata, ensure_ascii=False)))
                audit(db, user["id"], order_id, "photo_uploaded", {"photo_id": cur.lastrowid, "phase": phase, "duplicate": duplicate, "duplicate_type": duplicate_type, "bytes": len(raw), "client_compressed": bool(body.get("client_compressed")), "source_size_bytes_claim": metadata["source_size_bytes_claim"]})
                db.commit()
            except Exception:
                location.unlink(missing_ok=True)
                raise
            photo = db.execute("SELECT * FROM photos WHERE id=?", (cur.lastrowid,)).fetchone()
            return self.send_json({"photo": {"id": photo["id"], "file_name": photo["file_name"], "duplicate": bool(duplicate),
                                               "duplicate_type": duplicate_type, "verifiability_score": inspected["verifiability_score"],
                                               "capture_datetime": inspected["capture_datetime"], "capture_time_status": inspected["capture_time_status"],
                                               "size_bytes": len(raw), "uploaded_at": photo["uploaded_at"]}}, 201)

    def set_rating(self, user: sqlite3.Row, order_id: int) -> None:
        if user["role"] != "master": raise ApiError(403, "Оценку может менять только мастер")
        body = self.read_json(10_000)
        reason = str(body.get("reason", "")).strip()[:1000]
        with connect(self.server.db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = get_visible_order(db, user, order_id)
            if not row: raise ApiError(404, "Наряд не найден")
            if row["status"] == "closed":
                try: score = int(body.get("rating"))
                except (TypeError, ValueError): raise ApiError(400, "Качество должно быть от 1 до 5")
                if score not in range(1, 6) or len(reason) < 4: raise ApiError(400, "Оценка должна быть 1-5 и иметь понятное основание")
                db.execute("UPDATE orders SET rating=?,rating_reason=?,rated_by=? WHERE id=?", (score,reason,user["id"],order_id))
                audit(db,user["id"],order_id,"rating_adjusted",{"quality_override":score,"reason":reason})
                return self._finish_rating_update(db, score)
            if row["status"] == "rejected":
                unjustified = bool(body.get("unjustified_refusal"))
                if len(reason) < 4: raise ApiError(400,"Обоснуйте классификацию отказа мастером")
                reject_event=db.execute("SELECT id,actor_id FROM audit WHERE order_id=? AND event='reject' AND actor_id IS NOT NULL ORDER BY id DESC LIMIT 1",(order_id,)).fetchone()
                worker_id=reject_event["actor_id"] if reject_event else row["assigned_to"]
                if reject_event:
                    prior_review=db.execute("SELECT id FROM rejection_reviews WHERE reject_audit_id=?",(reject_event["id"],)).fetchone()
                    if prior_review:
                        db.execute("UPDATE rejection_reviews SET worker_id=?,classified_by=?,unjustified=?,reason=?,created_at=? WHERE id=?",
                                   (worker_id,user["id"],int(unjustified),reason,iso(),prior_review["id"]))
                    else:
                        db.execute("INSERT INTO rejection_reviews(order_id,reject_audit_id,worker_id,classified_by,unjustified,reason,created_at) VALUES (?,?,?,?,?,?,?)",
                                   (order_id,reject_event["id"],worker_id,user["id"],int(unjustified),reason,iso()))
                else:
                    db.execute("INSERT INTO rejection_reviews(order_id,reject_audit_id,worker_id,classified_by,unjustified,reason,created_at) VALUES (?,?,?,?,?,?,?)",
                               (order_id,None,worker_id,user["id"],int(unjustified),reason,iso()))
                db.execute("UPDATE orders SET unjustified_refusal=? WHERE id=?",(int(unjustified),order_id))
                audit(db,user["id"],order_id,"rejection_classified",{"reject_event_id":reject_event["id"] if reject_event else None,"worker_id":worker_id,"unjustified":unjustified,"reason":reason})
                db.commit()
                return self.send_json({"ok":True,"unjustified_refusal":unjustified})
            raise ApiError(409,"Оценка доступна для закрытого наряда, классификация отказа — для отклонённого")

    def create_repeat_link(self, user: sqlite3.Row, current_order_id: int) -> None:
        if user["role"] != "master": raise ApiError(403, "Связать повтор может только мастер")
        body = self.read_json(10_000); reason = str(body.get("reason", "")).strip()[:1000]
        try: previous_order_id = int(body.get("previous_order_id"))
        except (TypeError, ValueError): raise ApiError(400, "Выберите предыдущий наряд")
        if len(reason) < 4: raise ApiError(400, "Укажите основание связи не короче 4 символов")
        with connect(self.server.db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            current = get_visible_order(db,user,current_order_id); previous = get_visible_order(db,user,previous_order_id)
            if not current or not previous: raise ApiError(404,"Один из нарядов недоступен мастеру")
            if current["id"] == previous["id"] or current["status"] != "closed" or previous["status"] != "closed":
                raise ApiError(409,"Связь доступна только между разными закрытыми нарядами")
            if current["equipment_id"] != previous["equipment_id"] or not current["fault_code_id"] or current["fault_code_id"] != previous["fault_code_id"]:
                raise ApiError(409,"Для связи нужны одинаковые оборудование и выбранный код неисправности")
            prior_time = parse_time(previous["completed_at"] or previous["closed_at"]); repeat_time = parse_time(current["created_at"])
            if not prior_time or not repeat_time or repeat_time < prior_time or repeat_time > prior_time + timedelta(days=7):
                raise ApiError(409,"Повтор должен быть зарегистрирован в течение 7 дней после прежнего выполнения")
            prior_worker = previous["assigned_to"]
            if not prior_worker: raise ApiError(409,"У предыдущего наряда нет исполнителя для атрибуции")
            try:
                cur = db.execute("INSERT INTO repeat_links(current_order_id,previous_order_id,previous_worker_id,linked_by_master_id,reason,linked_at) VALUES (?,?,?,?,?,?)",
                    (current_order_id,previous_order_id,prior_worker,user["id"],reason,iso()))
            except sqlite3.IntegrityError: raise ApiError(409,"У текущего наряда уже есть активная связь повтора")
            link_id = cur.lastrowid
            audit(db,user["id"],current_order_id,"repeat_link_created",{"link_id":link_id,"previous_order_id":previous_order_id,"previous_worker_id":prior_worker,"reason":reason})
            audit(db,user["id"],previous_order_id,"repeat_link_attributed",{"link_id":link_id,"current_order_id":current_order_id,"worker_id":prior_worker,"reason":reason})
            db.commit()
        return self.send_json({"ok":True,"link_id":link_id,"attributed_worker_id":prior_worker})

    def revoke_repeat_link(self, user: sqlite3.Row, current_order_id: int) -> None:
        if user["role"] != "master": raise ApiError(403,"Отменить связь может только мастер")
        body = self.read_json(10_000); reason = str(body.get("reason","")).strip()[:1000]
        if len(reason) < 4: raise ApiError(400,"Укажите основание отмены не короче 4 символов")
        with connect(self.server.db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            current = get_visible_order(db,user,current_order_id)
            if not current: raise ApiError(404,"Наряд не найден")
            link = db.execute("SELECT * FROM repeat_links WHERE current_order_id=? AND active=1",(current_order_id,)).fetchone()
            if not link: raise ApiError(404,"Активная связь повтора не найдена")
            db.execute("UPDATE repeat_links SET active=0,revoked_by_master_id=?,revoked_at=?,revoke_reason=? WHERE id=?",
                (user["id"],iso(),reason,link["id"]))
            audit(db,user["id"],current_order_id,"repeat_link_revoked",{"link_id":link["id"],"previous_order_id":link["previous_order_id"],"reason":reason})
            audit(db,user["id"],link["previous_order_id"],"repeat_link_attribution_revoked",{"link_id":link["id"],"current_order_id":current_order_id,"worker_id":link["previous_worker_id"],"reason":reason})
            db.commit()
        return self.send_json({"ok":True,"revoked":True})

    def _finish_rating_update(self, db: sqlite3.Connection, score: int) -> None:
            db.commit()
            return self.send_json({"ok": True, "rating": score})

    def mark_notifications_read(self, user: sqlite3.Row) -> None:
        with connect(self.server.db_path) as db:
            db.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL", (iso(), user["id"]))
            db.commit()
        self.send_json({"ok": True})

    def static_file(self, relative: str) -> None:
        path = (STATIC / unquote(relative)).resolve()
        if STATIC.resolve() not in path.parents and path != STATIC.resolve():
            return self.send_error(404)
        if not path.is_file(): return self.send_error(404)
        content = path.read_bytes()
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix == ".webmanifest": ctype = "application/manifest+json"
        self.send_response(200)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8" if ctype.startswith(("text/", "application/javascript", "application/manifest")) else ctype)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers(); self.wfile.write(content)

    def end_headers(self) -> None:
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()


def serve_photo(handler: AppHandler, user: sqlite3.Row, photo_id: int) -> None:
    with connect(handler.server.db_path) as db:
        row = db.execute("SELECT p.*,o.assigned_to,o.assigned_master_id FROM photos p JOIN orders o ON o.id=p.order_id WHERE p.id=?", (photo_id,)).fetchone()
        if not row or not get_visible_order(db, user, row["order_id"]):
            raise ApiError(404, "Фото не найдено")
        media_root = MEDIA.resolve()
        try:
            file_path = Path(row["file_path"]).resolve(strict=True)
        except OSError:
            raise ApiError(404, "Фото не найдено")
        if file_path.parent != media_root or not file_path.is_file() or file_path.stat().st_size > 4_000_000:
            raise ApiError(404, "Фото не найдено")
        data = file_path.read_bytes()
        handler.send_response(200); handler.send_header("Content-Type", row["media_type"])
        handler.send_header("Content-Length", str(len(data))); handler.send_header("Cache-Control", "private, no-store")
        handler.send_header("X-Content-Type-Options", "nosniff"); handler.end_headers(); handler.wfile.write(data)


def patch_get_photo() -> None:
    original = AppHandler.api_get
    def api_get(self: AppHandler, path: str) -> None:
        match = re.fullmatch(r"/api/photos/(\d+)", path)
        if match:
            user = self.require_auth()
            return serve_photo(self, user, int(match.group(1)))
        return original(self, path)
    AppHandler.api_get = api_get


def patch_cookie_login() -> None:
    """Wrap login response so the opaque session token is only sent as HttpOnly cookie."""
    original = AppHandler.login
    def login(self: AppHandler) -> None:
        # Login body/auth/session setup is duplicated here to set Set-Cookie before headers.
        body = self.read_json(20_000)
        username, password = str(body.get("username", ""))[:80], str(body.get("password", ""))[:200]
        with connect(self.server.db_path) as db:
            user = db.execute("SELECT * FROM users WHERE username=? AND is_active=1", (username,)).fetchone()
            if not user or not verify_password(password, user["password_salt"], user["password_hash"]):
                raise ApiError(401, "Неверный логин или пароль")
            raw = secrets.token_urlsafe(32); token_hash = hashlib.sha256(raw.encode()).hexdigest(); csrf = secrets.token_urlsafe(24)
            expires = iso(utcnow() + timedelta(seconds=SESSION_SECONDS))
            db.execute("INSERT INTO sessions(token_hash,user_id,csrf,expires_at) VALUES (?,?,?,?)", (token_hash, user["id"], csrf, expires))
            audit(db, user["id"], None, "login", {"role": user["role"]}); db.commit()
        self.send_response(200); self.send_header("Set-Cookie", f"naryadai_session={raw}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_SECONDS}")
        self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff"); self.end_headers()
        public_user = AppHandler.user_public(user, csrf)
        data = json.dumps({"user": public_user}, ensure_ascii=False).encode()
        self.wfile.write(data)
    AppHandler.login = login


def watchdog_loop(db_path: Path, stopped: threading.Event) -> None:
    """Independent local timer worker so reminders do not depend on a page refresh."""
    interval = bounded_setting("NARYADAI_WATCHDOG_SECONDS", 5, 1, 60)
    while not stopped.wait(interval):
        try:
            with connect(db_path) as db:
                maybe_escalate(db)
        except Exception:
            # The next scheduled sweep retries; never crash the local web server.
            continue


def default_server_host() -> str:
    """Keep native runs private; container commands must opt in to a public bind."""
    return os.environ.get("NARYADAI_HOST", "127.0.0.1").strip() or "127.0.0.1"


def default_server_port() -> int:
    """Use an explicit app port first, then the host's standard PORT contract."""
    return int(os.environ.get("NARYADAI_PORT") or os.environ.get("PORT") or "8765")


def main() -> None:
    parser = argparse.ArgumentParser(description="Запуск локального MVP НарядAI")
    parser.add_argument("--host", default=default_server_host())
    parser.add_argument("--port", type=int, default=default_server_port())
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()
    init_db(args.db)
    patch_get_photo(); patch_cookie_login()
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    server.daemon_threads = True; server.db_path = Path(args.db)
    stopped = threading.Event()
    timer = threading.Thread(target=watchdog_loop,args=(server.db_path,stopped),daemon=True,name="naryadai-watchdog")
    timer.start()
    print(f"НарядAI доступен: http://{args.host}:{args.port}")
    print("Демо-пароль для всех аккаунтов: demo123 · демоданные полностью синтетические")
    try: server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt: print("\nСервер остановлен")
    finally: stopped.set(); server.server_close()


if __name__ == "__main__":
    main()
