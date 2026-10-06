# НарядКонтроль · требования и границы MVP

## Источники и сверка

Матрица собрана по извлечённому пользователем тексту двух PDF и дополнительной ручной расшифровке схемы на стр. 3 кейса. Ссылки на официальные файлы:

- [Кейс №1 «Костанайские минералы»](https://drive.google.com/file/d/1J2eVhrDOY9P0eDTSuwRRru_YDsZHuHUV/view), 8 страниц.
- [Положение Qostanai AI Industry Hackathon 2026](https://drive.google.com/file/d/14FmftU-f_NvKjSGlSL-ZWzKd4eK2xdey/view), 6 страниц.

Полные тексты обоих PDF прочитаны через подключённый Google Drive-коннектор и сверены 2 октября 2026. ТЗ задаёт функциональность продукта, а положение — сроки и формат сдачи. Оборудование, сотрудники, расписание и наряды в демо — синтетические; фактические правила предприятия не добавлялись.

## Матрица покрытия

| Требование | Реализация в MVP | Статус / ограничение |
|---|---|---|
| Мастер выдаёт наряд: тип, текст, участок, оборудование из участка, исполнитель/бригада, срок, 4 приоритета | Форма выдачи, фильтр оборудования по выбранному участку, выбор сотрудника с загрузкой или бригады; фото «до» необязательно для обоих типов; мастер может добавить его позднее из карточки «Выдан»/«Очередь»; часы задают только срок | Наряд, фото, аудит и уведомление видны вместе после одного SQLite-коммита; при сбое транзакции файл удаляется. Старые записи не переписываются; мастер может добавить/заменить фото в карточке до принятия для совместимости. Подсказка выбора не является ИИ-рекомендацией. Цель ≤1 мин / ≤6 нажатий не измерена на пользователе |
| 10 статусов и журнал автора/времени | `issued → accepted/queued → accepted → in_progress ↔ paused → executed → ai_review → closed/rework → in_progress`; отказ с причиной; история доработок сохраняется повторными событиями | Сервер проверяет переходы. Переназначение отказанного и отмена доступны мастеру с записью аудита. Отмена хранит флаг и использует статус `rejected`, чтобы не вводить 11-й статус |
| Исполнитель видит очередь, срок и назначенные наряды | Отдельный экран на роль; загрузка и очередь выводятся из открытых нарядов | Текущий порядок экранов — серверная сортировка по приоритету и сроку; ручная последовательность задач/перетаскивание мастером и версионирование перестановки пока не реализованы. Локальная формулировка критерия требует видеть очередь, не задаёт управление порядком. Если полный текст кейса требует ручную последовательность, это отдельный следующий пакет. Офлайн-команды не ставятся в очередь локально и не синхронизируются |
| Мастер видит доску, исполнителей, просрочки и фильтры | Канбан, профиль работника, бригада, синтетические специализация/разряд/смена, занятость и фильтры | Учебный UTC-график 06–14/14–22/22–06 и профили вымышлены; не подтверждают фактическую смену, квалификацию или допуск |
| Принятие: обычный 10 минут, аварийный 3 минуты; предложить свободного | Серверный таймер, идемпотентная эскалация, сообщение мастеру/исполнителям; кандидат для предложения берётся из доступных синтетических профилей | Свободность не означает нужной квалификации; фактический график предприятия не настроен |
| Напоминание за 30 минут, просрочка до «Исполнено», повторы | Независимый 5-секундный таймер; напоминание до срока и повторные сообщения по переменным окружения; просрочка — отдельный флаг/событие, не статус | По умолчанию reminder=30 минут и repeat=30 минут; `NARYADAI_REMINDER_MINUTES`, `NARYADAI_REPEAT_MINUTES`. ИИ-ревью и ожидание закрытия не считаются автоматической просрочкой. Отдельное уведомление руководителю при длительной просрочке не реализовано |
| Внеплановый отчёт: работы, неисправность, материалы с количеством, фото после | Проверки текста ≥20 символов, кода из справочника, часов, количества материалов либо явного «не использовались», до 5 фото; отдельный комментарий исполнителя до 1000 символов | Комментарий исполнителя необязателен, пустая строка допустима; текст работы остаётся обязательным, комментарий мастера к окончательной приёмке — отдельным полем. Аудит хранит ключ `worker_completion_comment` при `complete`; старые записи получают `NULL`. Отправка без фото после разрешена: rules-only вердикт направляет внеплановый наряд в «Доработка». Мастер не может закрыть такой наряд без хотя бы одного уникального фото «после» |
| Текстовая ИИ-проверка и вердикт | OpenAI-совместимый серверный адаптер для `accepted/comments/rework`; без настройки ключа — явный `rules-only` с простыми локальными проверками | Текущие тесты проходили в `rules-only`. Настроенного внешнего endpoint/key/model нет, поэтому полноценное LLM-соответствие ещё не подтверждено. LLM не выдаёт допуск и не закрывает наряд |
| Проверка материалов, времени и фото | Сервер валидирует положительные количества, наличие материалов/явное отсутствие, тип/размер/дубликаты фото и разрыв между временем загрузки и фиксации исполнения; API/интерфейсы показывают фактические часы отдельно от контрольного срока и версии синтетических ориентиров | Каталог содержит только явно маркированные учебные числа для UX-показа с происхождением, единицами, work_type и equipment_type; это не нормы заказчика. Нет соответствующей записи — `unknown`, без автопени/рейтингового эффекта. Дедлайн не является нормой труда |
| Фото до/после, EXIF и оценка проверяемости 1–5 | Клиент PWA уменьшает/перекодирует изображение в JPEG до 1600 px, пытается перенести EXIF; сервер проверяет MIME, полное декодирование, SHA-256 и dHash | Хранится перекодированное фото, а не исходный файл телефона. EXIF может отсутствовать/изменяться; клиентские сведения об исходном размере/переносе метаданных — недоверенные claims. Ни сжатие, ни EXIF не доказывают свежесть/исправность |
| Отчёт наряда, паузы, оборудование | Карточка показывает таймлайн, фото, результат ИИ/rules-only, материалы и историю оборудования; пауза считается по журналу pause/resume; мастер отдельно регистрирует закрытый интервал простоя с причиной | Пауза исполнителя и зарегистрированный интервал оборудования — разные записи. Ручной интервал не подтверждён датчиком и не выводится из фото/статуса/паузы; синтетические пропуски журнала не домысливаются. Мастер видит свои записи, руководитель — все записи только для чтения |
| Отчёт по смене и руководитель | Произвольный диапазон дат, бригада и синтетический код смены; выдано/исполнено/закрыто, просроченные исполнения, текущая просрочка, фактические часы, паузы по аудиту, отдельно зарегистрированный простой оборудования, материалы и разбивка по исполнителю; руководитель только читает | Границы дат и интервалы в UTC. Перекрытия объединяются по каждому оборудованию. Фильтр бригады не применяется к оборудованию; фильтр смены ограничивает UTC-окна A/B/C. Смена нарядов использует синтетический shift_code профиля; пауза — не простой. Сводка rules-only |
| Понятный рейтинг | 0–100 за выбранный интервал дат; качество мастера 40%, срок 20%, возвраты/явно связанный повтор 20%, объём×сложность 10%, только вручную признанные необоснованные отказы 10%; доступные веса перенормируются | Повтор влияет на фактор только после ручной связи мастером тех же оборудования и кода в 7-дневном окне, с основанием и аудитом обеих записей; связь можно отменить. Старые флаги без атрибуции не снижают балл. Дата/смена профиля синтетические |
| Telegram: read-only команды списка и реальный push | Пагинация по 5 строк: исполнитель — назначенные ему, мастер — где он ответственный, руководитель — весь кабинет только для чтения; reply-кнопки без callback data, повторная проверка области доступа при отправке, inbox ID дедупликация, лимиты 120 входящих/мин, 100 ожидающих команд и 20 000 ID | Локальный fake sender и тестовые webhook работают; при полном inbox новые update ID игнорируются до обслуживания. Реальный бот, токены, внешний webhook и доставка не настроены/не проверены; это остаётся интеграционным критерием PDF |
| Android PWA / слабая сеть | Manifest, service worker, адаптивные экраны; кэшируется оболочка | Офлайн-запись и синхронизация не сделаны. Установка доступна на localhost или HTTPS; HTTP с другого устройства не даёт installable service worker. Реальное Android-устройство не было доступно для ручной проверки |
| 500+ нарядов за 3 месяца, синтетика | 540 записей истории и 10 актуальных сценариев, четыре повторяемых паттерна; 18 учётных записей | Имена и данные вымышлены; шаблоны и коды являются демонстрационными, не частью производственного справочника |

## Не подменять ИИ

В режиме без трёх настроек внешнего адаптера UI и аудит хранят `rules-only: configuration_missing`. Это локальные проверки длины/слов отчёта, заполненности, наличия/дубликатов фото и нескольких числовых условий. В сводке отчёта также указывается `rules-only`; в тестах и презентации нельзя назвать эти результаты полноценной языковой или мультимодальной проверкой.

## Разрешения и проверяемая модель

- `worker`: видит собственные и доступные его бригаде новые наряды; принимает/ставит в очередь/отклоняет с причиной, начинает/приостанавливает, записывает выполнение и загружает «после».
- `master`: видит наряды своей области выдачи, создаёт, переназначает, отменяет, меняет приоритет, классифицирует отказ, направляет на доработку, ставит оценку и выполняет единственный переход в `closed`.
- `manager`: GET-only, общая аналитика и аудит.
- Изменяющие API-запросы требуют CSRF-токен; область наряда повторно проверяется на сервере, UI-скрытие не является проверкой доступа.

Сессия использует случайный токен с хешем в SQLite, `HttpOnly`, `SameSite=Strict`, срок 12 часов. Пароли демо-пользователей хранятся как PBKDF2-HMAC-SHA256-хеши. Транспорт — loopback HTTP, без TLS и защиты от перебора; это не модель промышленного развёртывания.

## Явные правила, не заданные графиком статусов

- Отмена мастером помечается флагом и журналом, оставаясь в статусе «Отклонён»; повторная выдача переводит её в «Выдан» и обнуляет флаг.
- Переназначение допускается до принятия или после отказа исполнителя; после начала работы эта операция закрыта.
- Причина обязательна для отказа, паузы, возврата на доработку и отмены. Все циклы доработки сохраняются в audit.
- Просрочка автоматически ограничена до `executed`. Отчёт об исполнении ожидает AI/мастера без дополнительного штрафа за календарное ожидание.
- Пауза исполнителя — только накопленные интервалы по паре событий pause/resume. Это не доказательство простоя оборудования; неполная синтетическая история не домысливается.
- Простой оборудования — только введённый мастером закрытый интервал с причиной в отдельной таблице. В отчётах диапазон клипуется к UTC-окну, пересечения одного актива объединяются, строки разных активов складываются в equipment-minutes. Источник — ручная регистрация, не датчик и не подтверждение технического состояния; интервал не начисляет рейтинг/штраф работнику.

## Демонстрационные критерии для повторной проверки

`tests/test_app.py` запускает настоящий HTTP API на localhost и проверяет изоляцию ролей, CSRF, переходы, полный цикл до `closed`, rules-only, фото, дубли, таймеры, отчёты, рейтинги и ручную ссылку повтора. `tests/test_independent_security.py` и `tests/test_frontend_races.js` покрывают отдельные границы. Проверки выполняются на временной SQLite-базе; они не подтверждают Android/3G скорость, браузерную компоновку или запуск Docker.


## Разграничение ремонтного наряда и допуска

НарядКонтроль регистрирует ремонтную задачу и отчёт о выполнении. Он не выдаёт наряд-допуск, не разрешает опасную работу, не удостоверяет инструктаж и не хранит подписи за людей. Личный рассказ о бланках, списке работников и Excel отражает опыт пользователя, но не подтверждён как регламент заказчика. В MVP нет поля или workflow, который мог бы быть принят за электронное разрешение. Отсутствие допуска при отказе/паузе не штрафуется автоматически; необоснованность отказа должен вручную отметить мастер с основанием, эта отметка аудируется.

## Фото и границы уверенности

Pillow — единственная внешняя Python-зависимость (`requirements.txt`); в предоставленном Python 3.12 окружении уже установлен Pillow 12.3.0. Фото ограничено 4 МБ, 24 мегапикселями, строгим MIME/сигнатурным и декодирующим совпадением. Анимированные изображения отклоняются. PWA локально уменьшает крупное фото до 1600 px и JPEG, пытается перенести исходный EXIF. На сервере хранится обработанный файл; исходный файл телефона не сохраняется. Если EXIF не перенесён, время съёмки остаётся неизвестным. Даже сохранённый EXIF не доказывает свежесть. Имя файла не задаёт путь; файлы получают случайное имя в каталоге media и читаются только через авторизованный endpoint с повторной проверкой разрешённого каталога.

Низкая оценка проверяемости (1–3) и заявленная моделью уверенность ниже 0,60 переводят проверку в замечания; закрыть наряд можно только мастеру и с записанным объяснением. Это правило контроля workflow, а не безопасность работ. Мультимодальное сравнение содержания «до/после» и оценка качества результата не реализованы.

## Уточнение независимой проверки

Проверка от 2 октября 2026: лимит фото составляет 5 на фазу «до» и 5 на фазу «после». Прежний исполнитель сохраняет исторический просмотр, но не может изменять чужое переназначенное задание. Рейтинг учитывает возврат на доработку и от ИИ, и от мастера. Флаги повторных поломок пока не влияют на штраф: структура данных не связывает их с конкретным предыдущим ремонтом и ответственным за него исполнителем. Это незавершённая часть рейтинга, а не автоматическое обвинение следующего ремонтника. Отчёт за день остаётся неполным относительно MVP: нет выданных/отказов/просрочек, загрузки и достоверного простоя за выбранный период; фиксированные 30 дней рейтинга не заменяют смену и произвольный период.

## Состояние сдачи на 2 октября 2026

### Проверено локально

- Полный Python-набор (реальный HTTP API, временная SQLite): **25/25**.
- UI race-тесты Node: **19/19**; `node --check static/app.js`, `py_compile` и `git diff --check` проходят.
- PWA smoke на отдельном временном HTTP-сервере/свободном порту: `/sw.js` отдаётся из корня, проверен код регистрации с `scope: "/"`, `start_url`/`scope` манифеста и получение/декодирование PNG 192×192 и 512×512. Проверены маршруты и файлы; это не проверка установки в Android.
- Проверены сценарии ролей/CSRF, полный цикл статусов, фото MIME/дубли/EXIF, временные границы повторной связи, создание/отзыв связи с двумя audit-записями, диапазон отчёта и сменные фильтры.
- Локальные тестовые измерения: загрузка фото 0,213 с; видимость второй HTTP-сессии 0,170 с. Они не являются сетевым SLA.

### Не проверено

- Ручная отрисовка в реальном Edge/Chrome и на Android, адаптивность фактического устройства, установка PWA и сжатие по времени/качеству на телефоне. Клиентский код проверен Node-тестами и синтаксически.
- Сборка/запуск Docker и Streamlit. Docker CLI-команда проверки Compose не вернула результат и была остановлена; контейнеры не запускались.
- Нагрузочная/мобильная сеть, публичный API, реальный push и сквозной внешний LLM. При пустой конфигурации честный режим остаётся `rules-only`.
- PDF-презентация и видео не создавались: демосценарий и материалы нужно оформить после подтверждённой демонстрации на выбранном устройстве.

### Требует отдельной внешней настройки

- Для полноценной LLM-нормы нужен одобренный endpoint/model и секрет в защищённой среде; ключ в проекте отсутствует.
- Для удалённой работы нужны выбранный HTTPS host, постоянный volume для SQLite/фото, backup/restore и гарантированное исполнение таймера при бодрствующем сервере. Бесплатность/uptime хоста не подтверждены.
- Реальная доставка Telegram, Android-аккаунт/OAuth и публичное размещение намеренно не настраивались; read-only Telegram backend проверен только через fake transport.

Полное end-to-end production-развёртывание из этих результатов не следует.


## Additional evidence rules

A missing material row is not proof of zero use. For completed legacy work, absent rows plus `materials_not_used=0` mean unknown actual consumption and unknown variance. A zero is supported only by an explicit no-use flag with no rows. New conflicting payloads are rejected atomically. Existing conflicting database facts are preserved, labelled as a conflict, and do not produce a variance or rating adjustment.

Downtime is a separate master-recorded equipment interval, not worker pause time. Interval unions are computed in seconds before final conversion to minutes (three decimal places). Equipment type migration recognizes only exact code/name pairs emitted by the synthetic seed; other imported legacy assets remain unknown.

## P0 corrective patch · 5 October 2026

- Master reassignment UI now shows a worker/brigade selector for `issued` and `rejected` нарядs; the server still enforces master role, visibility, state, active worker and exclusive target selection. Repeat-link create/revoke handlers are bound to the rendered drawer buttons and single-flight per order.
- Before-work photos are optional during issuance for both planned and unscheduled orders. Masters can add up to five images from camera or gallery while a work order is issued or queued. Photo absence does not block issue or acceptance.
- Fresh synthetic seed rows receive their intended work type at creation. Older rows without immutable seed provenance are not migrated: code and description matches cannot prove that user-editable title, equipment, area, fault, status, assignment or type remain untouched.
- closure_comment must be a JSON string; the server trims it and requires at least four characters, rejecting null and every non-string JSON value before any write. worker_completion_comment is now a separate optional JSON string, blank allowed, limited to 1000 characters and stored on the order plus the complete audit event. Legacy rows migrate to nullable NULL; missing comment from an older client means empty. Both PWA and Streamlit show it separately. Streamlit keeps material selection outside the completion form so the first submit has its quantity widget; the UI step is 0.001, matching the API positive-quantity range.
- Delayed Telegram rows snapshot order ID/status/issue generation, expected role, assignee context and current chat. Reassignment/status change cancels pending rows; unpair/chat rebinding cancels recipient rows; delivery rechecks active role, exact chat and current order scope while holding the SQLite write lock through the fakeable send call. Stale payloads are cleared. No bot, token or external send is part of this patch.

Regression verification after the corrective changes: Python unittest 54/54, Node race suite 27/27, and Streamlit AppTest 4/4. All Telegram deliveries were tested with a local fake sender; no real Telegram request was made. Browser/device rendering and a configured external LLM remain separate verification items.

## Remaining criteria continuation · 5 October 2026

- If a before photo is included at creation it is validated and committed with the order; it may also be attached later from the issued/queued card. A worker may submit an unscheduled report without an after photo; rules-only review returns it for rework, and the master cannot close it until the report is corrected.
- The 5 October manual-queue follow-up supersedes the earlier scope note: the responsible master can move active assigned work up/down within the worker or brigade queue. The worker sees the same persisted order. Position is independent of priority and due date; new/legacy rows get a deterministic priority/deadline default until manually positioned. Reorder writes carry a per-scope revision and the full current active ID set; stale, incomplete, cross-scope, duplicate and unauthorized changes are rejected. Assignment/status/closure changes invalidate the relevant revision. Telegram remains read-only and reflects the stored positions.
- The external text-review adapter and aggregate-only shift-summary adapter already exist. The current working tests use stubs/rules-only; no real endpoint or API key was configured. To perform a real test, the owner supplies NARYADAI_LLM_ENABLED=1, an HTTPS NARYADAI_LLM_API_URL (optional; defaults to the configured Gemini-compatible endpoint), NARYADAI_LLM_API_KEY, and NARYADAI_LLM_MODEL; shift summaries additionally require NARYADAI_LLM_REPORT_SUMMARY=1 and an explicit report request. The model does not approve safety work or close orders.

## Telegram read-only list · 5 October 2026

- Added bounded `/orders [page]` and reply-keyboard navigation. Worker pages include current direct assignments; master pages include orders where they are the responsible master; manager pages use the existing read-only all-orders scope. No status mutation command exists.
- Queued order-list replies carry an assignment-scope fingerprint and recheck role, active account and chat binding immediately before send; stale role/assignment/chat work is cancelled and its payload cleared. Page controls contain no callback data and always issue a fresh scoped read.
- Webhook limits: 120 private inbound updates/minute globally, 100 pending command/pair-help messages, and a finite 20,000 update-ID inbox budget. At inbox capacity, new updates are ignored until maintenance; dedupe IDs are not auto-pruned.
- Verification for this snapshot: Python unittest 58/58, Node race suite 27/27, PWA shell smoke included in the Python suite, plus targeted PWA smoke 1/1. Telegram used local fake webhook/sender only; no bot token, provider webhook or real message was configured.

## Manual queue sequence · 5 October 2026

- `POST /api/work-queues/reorder` is a master-only atomic full-list replacement scoped to that responsible master and one worker/brigade. It does not change order status, priority, deadline, or assignment.
- A monotonically increasing revision rejects stale and concurrent changes. The server checks the exact current set of active orders inside `BEGIN IMMEDIATE`; database triggers invalidate revisions and drop saved positions on assignment/scope/closure changes.
- Bootstrap uses a single SQLite read snapshot for active IDs, positions and revision. Streamlit uses revision-specific button IDs and an immutable per-button context (full order, revision, scope and direction). A stale click on the still-rendered widget gets 409 and an explanation without retry; a delayed event after fragment refresh is discarded under its old widget ID.
- PWA and Streamlit use explicit up/down controls suitable for phones. Bootstrap exposes each position, queue label, and revision; the worker sees the same position and the manager has no reorder controls. Telegram lists saved positions as read-only.
- Migration creates empty ordering tables without rewriting existing orders. Until a master saves a queue, active rows keep deterministic priority/deadline order. Newly assigned work receives that deterministic fallback until the next full-list reorder.
