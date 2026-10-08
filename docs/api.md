# EnbekPlus HTTP API · локальный MVP

API обслуживается приложением `server.py` и используется PWA и опциональным Streamlit-клиентом. Это ещё не версионированный внешний API. JSON ошибок имеет форму `{"error":"..."}`. UI должен показывать ошибку сервера, а не создавать локальную фиктивную запись.

## Сессия и защита запросов

GET /api/health не требует аутентификации и возвращает строго {"ok":true,"app":"EnbekPlus","mode":"local-mvp"}. Путь endpoint и режим local-mvp сохранены.

- `GET /api/health` — неаутентифицированная проверка доступности.
- `POST /api/login` с `{"username":"...","password":"..."}` — сервер возвращает профиль, `csrf` и ставит случайный opaque session в `HttpOnly; SameSite=Strict` cookie. Сырой session token в JSON не возвращается.
- На каждом следующем запросе передавайте cookie. На `POST` также передавайте `X-CSRF-Token` из ответа входа.
- `POST /api/logout` отзываем сессию на сервере. Срок сессии MVP — 12 часов. Повторный вход нужен после перезапуска отдельного Streamlit/UI сеанса.
- Роль и область данных проверяются API на каждом маршруте. `manager` — чтение. Не рассчитывайте на скрытие кнопки как на механизм прав.

## Чтение и обновление состояния

- `GET /api/me` — текущий профиль, роли и CSRF token.
- `GET /api/bootstrap` — профиль, доступные наряды, уведомления, справочники, команда и рейтинг. PWA опрашивает endpoint каждые 4 секунды. Поддерживаются `rating_from=YYYY-MM-DD`, `rating_to=YYYY-MM-DD`, `shift_code=A|B|C` для периода рейтинга/списка смены. Смены и расписание синтетические.
- `GET /api/bootstrap` включает `constants.equipment[].equipment_type` и `constants.norm_catalog[]` с видом записи, work type, equipment type, количеством, единицей, источником, версией, комментарием и флагом `is_synthetic=1`.
- `GET /api/orders/{id}` — карточка, аудит, фото и история оборудования в серверной области доступа.
- В карточке и строках отчёта `norm_reference` описывает только учебный synthetic reference; фактические часы и `due_at` остаются отдельными полями. Если matching-каталога для сочетания work type/equipment type нет, `status="unknown"`; автоматической оценки/штрафа нет.
- `GET /api/photos/{id}` — байты фото при проверке права на связанный наряд.
- `GET /api/audit` — журнал; доступен мастеру в собственной области и руководителю только на чтение.
- `GET /api/reports?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD&brigade=A&shift_code=A` — произвольный период (максимум 10 лет), смена привязана к вымышленному профилю работника. Непереданные brigade/shift фильтры пустые. Пауза — интервалы pause/resume из журнала; простой оборудования выводится отдельно только из явных регистраций.
- `GET /api/equipment/downtime?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD&shift_code=A` — master видит собственные записи, manager — все, worker получает 403. Возвращает явные интервалы и объединённое время по оборудованию; даты ограничивают UTC-период, shift_code — UTC-окна A/B/C, фильтр бригады не применяется.

## Изменения наряда

- `POST /api/orders` — мастер создаёт наряд с `title`, `description`, `area_id`, `equipment_id`, `work_type`, `priority`, `norm_hours` и одним `worker_id` либо `brigade`. Необязательное поле `before_photos: [{file_name, data_url}, ...]` принимает 0–5 фотографий для обоих типов наряда; совместимое поле `before_photo: {file_name, data_url}` остаётся доступно старым клиентам, но его нельзя передавать вместе с массивом. Каждый файл проверяется по формату, полному декодированию, лимиту 4 МБ и точным/похожим дублям; суммарный JSON-запрос ограничен 30 МБ. При дубле выдача возвращает 409 и записывает `order_create_duplicate_photos_rejected` без имени/содержимого файла, не создавая наряд, фото-строку или media-файл. Наряд, все файлы, фото-аудит и уведомления фиксируются одной транзакцией; ошибка откатывает записи и удаляет все уже сохранённые файлы. Фото `before` можно загрузить позднее отдельным маршрутом в статусах `issued` и `queued`. Совместимый параметр `norm_hours` устанавливает только срок до дедлайна; фактические трудозатраты вводятся при `complete`, synthetic labour values на дедлайн не влияют.
- `POST /api/orders/{id}/assign` — только мастер. Переназначение допускается для статусов `issued` и `rejected` (кроме отменённых нарядов); передайте ровно одно из `worker_id` или `brigade`.
- `POST /api/equipment/downtime` — только master. JSON: `{equipment_id, started_at, ended_at, reason, idempotency_key}`; timestamps должны содержать часовой пояс. Окончание позже начала, длительность не больше 31 суток. Новый интервал отвечает 201, повтор того же ключа и тех же данных — 200 без дубля; повтор ключа с другими данными — 409. Регистрация журналируется как `equipment_downtime_registered`; вручную введённая запись не доказывает состояние машины.
- `POST /api/orders/{id}/action` с `action` из `accept`, `queue`, `start`, `pause`, `resume`, `reject`, `complete`, `ai_check`, `close`, `request_rework`, `cancel`, `reissue`. Передавайте `reason` при отказе, паузе, отмене и возврате; `close` требует отдельный `closure_comment` длиной от 4 символов. `complete` требует `completion_text`, `fault_code_id`, `labor_hours`, `materials` с количеством либо `materials_not_used=true`; необязательное `worker_completion_comment` — JSON-строка до 1000 символов, пустая строка разрешена. Старые клиенты могут не передавать комментарий. При неверном типе/длине сервер отклоняет действие до изменения статуса, материалов и аудита. Переход `accept` не требует фото `before`. Переходы и права решает сервер. При `request_rework` все активные фото `after` supersede-ятся в той же транзакции: upload-аудит и событие `photo_superseded` сохраняются, media-файлы удаляются после commit, фото перестают выдаваться API. Исполнитель может приложить новое фото после перехода в `in_progress`.
  `closure_comment` accepts only a JSON string, trimmed to 4–1000 characters; null, booleans, numbers, arrays and objects are rejected. Material quantities must be finite and positive; Streamlit accepts 0.001 steps.
- `POST /api/orders/{id}/photos` принимает `{phase, file_name, data_url}`; `data_url` — JPEG/PNG/WebP base64 до 4 МБ после сжатия. Фото `before` необязательно при выдаче обоих типов наряда; отдельный маршрут допускает загрузку до пяти фотографий `before` в статусах `issued` и `queued`. Исполнитель загружает `after` только в `in_progress`/`paused`. Клиентские поля `client_compressed`, `source_size_bytes`, `source_media_type`, `exif_transfer_succeeded` являются недоверенными поясняющими claims, не доказательством. Сервер проверяет содержимое и дубли по сохранённой истории. Точный/похожий дубль отвечает 409 и создаёт только `photo_duplicate_rejected` с фазой и типом дубля: строка фото и media-файл не создаются. Шестое уникальное активное фото фазы отвечает 400 с `photo_limit_rejected`. Старые legacy-дубли при инициализации деактивируются с `photo_legacy_duplicate_retired`; их audit и метаданные остаются, а media-файлы очищаются. Если физическая очистка ожидает повтора, загрузка временно отвечает 503. Фото и EXIF не доказывают свежесть съёмки или исправность.
- `POST /api/orders/{id}/rating` — изменение оценки мастером с `rating` 1–5 и обязательным объяснением. Флаг из старого формата `repeat_confirmed` не создаёт атрибуцию.
- `POST /api/orders/{id}/repeat-link` — только мастер, закрытые наряды, то же оборудование/код и интервал до 7 дней; JSON содержит `previous_order_id` и основание. События записываются в обе записи. `POST /api/orders/{id}/repeat-link/revoke` снимает активную связь с обязательным основанием.
- `POST /api/notifications/read` отмечает уведомления прочитанными.

## Опциональные интеграции (выключены по умолчанию)

- `GET /api/telegram/status` — состояние только текущего аккаунта и его доставки.
- `POST /api/telegram/pair` — мастер, исполнитель или руководитель получает одноразовую команду `/start CODE` со сроком 10 минут. Код хранится только хешем; webhook принимает только личный чат, сопоставленный с отправителем. Руководитель может только привязать/отвязать чат; его Telegram-команды остаются read-only.
- `POST /api/telegram/unpair` — отвязать личный чат.
- `POST /api/telegram/webhook` — Telegram webhook; передаёт JSON update и `X-Telegram-Bot-Api-Secret-Token`. Маршрут требует `NARYADAI_TELEGRAM_ENABLED=1`, bot token и secret. Настройка внешнего webhook автоматически не выполняется. Команды чтения: `/orders [страница]`, кнопки «Мои наряды», «Предыдущая страница», «Следующая страница»; размер страницы 5, постраничный контент повторно фильтруется на сервере. Изменять статусы из Telegram нельзя.
- `GET /api/reports?...&include_ai_summary=1` запрашивает дополнительную LLM-сводку только при `NARYADAI_LLM_ENABLED=1`, `NARYADAI_LLM_REPORT_SUMMARY=1`, роли мастер/руководитель и наличии не менее пяти нарядов. Без query-параметра всегда возвращается rules-only текст. Модель получает только период и агрегаты.

Telegram outbox статусы: `queued_local`, `sending`, `retrying`, `delivered`, `failed`, `uncertain`, `expired`, `cancelled`. Входной webhook дедуплицирует update ID, ограничивает приватные обновления до 120/мин на общую SQLite-базу, ожидающую очередь команд/help до 100 строк и inbox до 20 000 private update ID; при заполнении inbox новые обновления игнорируются до обслуживания. Дедуп-маркеры автоматически не удаляются, чтобы повторные обновления не исполнялись вновь. Локальная дедупликация не гарантирует exactly-once: Bot API не принимает ключ идемпотентности для `sendMessage`; если исход запроса неизвестен из-за сетевого сбоя/перезапуска, запись переходит в `uncertain` и автоматически не повторяется. Записи старше суток истекают, явный ответ 429 допускает до четырёх ограниченных попыток. Для списка нарядов очередь хранит fingerprint текущего набора назначений; смена роли, назначения или чата отменяет устаревшую доставку. Order-scoped notices привязаны к текущему назначению/status/issue generation и чату; claim и отправка сериализованы против переназначения и отвязки.

Шаблоны просрочки дополнительно включают код наряда, оборудование, участок, назначенного исполнителя, минуты до/после срока и последний bounded comment/reason. Получатели — только назначенный исполнитель и/или мастер по allowlist конкретного события; руководителю эти push-сообщения не отправляются. Поля нормализуются и ограничиваются по длине, итоговое сообщение — 280 символов, Telegram parse mode не используется. Пока нет настроек интеграции, события остаются в локальной outbox; этот патч не создаёт бота и не отправляет сообщения.

## Ограничения переносимого клиента

Native Android/Flutter может хранить cookie в защищённом хранилище и отправлять CSRF на изменяющих запросах. Отдельный веб-домен не получит CORS-разрешение в текущем локальном MVP; не добавляйте wildcard CORS. Для сетевого клиента нужны согласованный HTTPS host, учётные записи, постоянный диск и отдельная настройка push. В API пока нет OAuth, токенов интеграции, версионирования, бинарного upload endpoint или публикации наружу. ИИ и таймер работают на сервере; rules-only режим явно указывается, пока внешний адаптер не настроен.


## Evidence fields and precision

For `POST /api/orders/{id}/action` with `action=complete`, `materials_not_used` must be a JSON boolean. A value of `true` is valid only with an empty `materials` array; a contradictory request returns HTTP 400 before any completion, material, audit, or notification write. A completion must provide material rows or explicitly confirm no material use.

`norm_reference.materials_evidence_status` is `unknown` when a completed record has neither material rows nor an explicit no-use confirmation. In that case each catalog material has `actual_quantity=null` and `difference_quantity=null`. For legacy records containing both `materials_not_used=true` and material rows, the API preserves the rows in `reported_actual_materials`, reports `conflict`, exposes matching recorded quantities, and leaves differences null. Reference comparisons do not update ratings.

Equipment downtime is clipped and unioned per equipment in seconds, then `minutes` and each `downtime_minutes` total are rounded to three decimal places. Fractional-minute shift values are retained; aggregating adjacent shifts does not discard seconds.

## Manual work queue ordering

`POST /api/work-queues/reorder` accepts `{ "scope": "master:…:worker:…|brigade:…", "expected_revision": 3, "order_ids": [12, 14] }`. Only the responsible master may write. The ID list must be the complete active queue exactly once. The server compares the revision and assignment scope while holding a SQLite write lock, then records the new positions and audit events atomically. `403` means the role cannot reorder, `404` means the master/scope is not theirs or is no longer active, `409` means stale revision or an incomplete current list, and `400` means malformed/duplicate IDs.

`GET /api/bootstrap` includes `work_queues` for master and worker roles. Each group has a stable scope key, label, revision, and ordered `order_ids`; active order objects include `queue_scope`, `queue_position`, and `queue_revision`. Status and priority remain unchanged by a reorder. Assignment/status changes advance the affected queue revision so concurrent clients must refresh.

Bootstrap reads the order rows, saved positions, and revision inside one explicit SQLite read transaction. This prevents a response from returning positions from before a concurrent reorder together with its newer revision. Streamlit move buttons have revision-specific widget IDs and bind the exact immutable payload shown on screen. A stale click that reaches the still-current button submits its old revision, receives 409, shows a refresh notice, and is never retried. If a fragment refresh has replaced the button first, a delayed event carries the old widget ID and is discarded, never rebound to the latest context.
