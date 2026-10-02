# НарядAI HTTP API · локальный MVP

API обслуживается приложением `server.py` и используется PWA и опциональным Streamlit-клиентом. Это ещё не версионированный внешний API. JSON ошибок имеет форму `{"error":"..."}`. UI должен показывать ошибку сервера, а не создавать локальную фиктивную запись.

## Сессия и защита запросов

- `GET /api/health` — неаутентифицированная проверка доступности.
- `POST /api/login` с `{"username":"...","password":"..."}` — сервер возвращает профиль, `csrf` и ставит случайный opaque session в `HttpOnly; SameSite=Strict` cookie. Сырой session token в JSON не возвращается.
- На каждом следующем запросе передавайте cookie. На `POST` также передавайте `X-CSRF-Token` из ответа входа.
- `POST /api/logout` отзываем сессию на сервере. Срок сессии MVP — 12 часов. Повторный вход нужен после перезапуска отдельного Streamlit/UI сеанса.
- Роль и область данных проверяются API на каждом маршруте. `manager` — чтение. Не рассчитывайте на скрытие кнопки как на механизм прав.

## Чтение и обновление состояния

- `GET /api/me` — текущий профиль, роли и CSRF token.
- `GET /api/bootstrap` — профиль, доступные наряды, уведомления, справочники, команда и рейтинг. PWA опрашивает endpoint каждые 4 секунды. Поддерживаются `rating_from=YYYY-MM-DD`, `rating_to=YYYY-MM-DD`, `shift_code=A|B|C` для периода рейтинга/списка смены. Смены и расписание синтетические.
- `GET /api/orders/{id}` — карточка, аудит, фото и история оборудования в серверной области доступа.
- `GET /api/photos/{id}` — байты фото при проверке права на связанный наряд.
- `GET /api/audit` — журнал; доступен мастеру в собственной области и руководителю только на чтение.
- `GET /api/reports?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD&brigade=A&shift_code=A` — произвольный период (максимум 10 лет), смена привязана к вымышленному профилю работника. Непереданные brigade/shift фильтры пустые. Пауза — интервалы pause/resume из журнала, не подтверждённый простой оборудования.

## Изменения наряда

- `POST /api/orders` — мастер создаёт наряд с `title`, `description`, `area_id`, `equipment_id`, `work_type`, `priority`, `norm_hours` и одним `worker_id` либо `brigade`.
- `POST /api/orders/{id}/action` с `action` из `accept`, `queue`, `start`, `pause`, `resume`, `reject`, `complete`, `ai_check`, `close`, `request_rework`, `cancel`, `reissue`. Передавайте `reason` при отказе, паузе, отмене и возврате. `complete` требует `completion_text`, `fault_code_id`, `labor_hours`, `materials` с количеством либо `materials_not_used=true`. Переходы и порядок решает сервер.
- `POST /api/orders/{id}/photos` принимает `{phase, file_name, data_url}`; `data_url` — JPEG/PNG/WebP base64 до 4 МБ после сжатия. Клиентские поля `client_compressed`, `source_size_bytes`, `source_media_type`, `exif_transfer_succeeded` являются недоверенными поясняющими claims, не доказательством. Сервер проверяет содержимое и дубли.
- `POST /api/orders/{id}/rating` — изменение оценки мастером с `rating` 1–5 и обязательным объяснением. Флаг из старого формата `repeat_confirmed` не создаёт атрибуцию.
- `POST /api/orders/{id}/repeat-link` — только мастер, закрытые наряды, то же оборудование/код и интервал до 7 дней; JSON содержит `previous_order_id` и основание. События записываются в обе записи. `POST /api/orders/{id}/repeat-link/revoke` снимает активную связь с обязательным основанием.
- `POST /api/notifications/read` отмечает уведомления прочитанными.

## Ограничения переносимого клиента

Native Android/Flutter может хранить cookie в защищённом хранилище и отправлять CSRF на изменяющих запросах. Отдельный веб-домен не получит CORS-разрешение в текущем локальном MVP; не добавляйте wildcard CORS. Для сетевого клиента нужны согласованный HTTPS host, учётные записи, постоянный диск и отдельная настройка push. В API пока нет OAuth, токенов интеграции, версионирования, бинарного upload endpoint или публикации наружу. ИИ и таймер работают на сервере; rules-only режим явно указывается, пока внешний адаптер не настроен.
