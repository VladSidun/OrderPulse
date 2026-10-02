# Система обліку замовлень

Навчальний вебзастосунок для невеликої компанії: облік клієнтів, замовлень і контроль їх статусів.

## Поточні можливості

- Фабрика FastAPI з конфігурацією через environment variables та `.env`.
- Українська початкова сторінка Jinja2, Bootstrap 5 і локальні стилі.
- `GET /health` повертає `200` і `{"status":"ok"}` без підключення до БД.
- Swagger `/docs` і OpenAPI `/openapi.json` у development/testing.
- Перевірка конфігурації: часовий пояс, валюта EUR, режим видимості замовлень.
- Захист від випадкового увімкнення debug або порожнього секрету в production.
- Синхронні SQLAlchemy-моделі користувачів, клієнтів, замовлень, позицій, історії статусів і річного лічильника номерів.
- PostgreSQL 17 у Docker Compose, Alembic initial migration, перевірки constraints та міграцій.
- Вхід і вихід, Argon2id-хеші паролів, підписана cookie-сесія та CSRF-захист.
- Перевірка активності, ролі й версії авторизації з БД на кожному захищеному запиті.
- Початковий адміністратор через окрему ідемпотентну CLI-команду.

Схема БД та авторизація готові. `/dashboard` — захищений робочий простір без показників, `/users` — сторінка перевірки доступу адміністратора без керування користувачами. Бізнес-функції додаються наступними етапами. Початкова сторінка не містить посилань на недоступні модулі. Самі ORM-моделі не створюють замовлень, не обчислюють суми й не перевіряють права.

## Стек та архітектура

Поточна версія: Python 3.12, FastAPI, Uvicorn, Pydantic Settings, Jinja2, Bootstrap 5, SQLAlchemy 2.0.54, psycopg 3.3.6, Alembic 1.20.0, PostgreSQL 17.9, pwdlib 0.3.1 / Argon2, itsdangerous 2.2.0, python-multipart 0.0.32, email-validator 2.3.0. Перевірки: pytest, pytest-cov, HTTPX2 / FastAPI TestClient, ruff. `tzdata` забезпечує IANA-часові пояси також у Windows.

Модульний моноліт зі спільними сервісами для HTML та JSON API:

```text
HTTP routes -> services -> repositories -> SQLAlchemy / PostgreSQL
```

На поточному етапі працюють системні та auth routes, конфігурація, HTML, БД й сервіси авторизації та створення адміністратора. Репозиторій виконує запити без commit; сервіс запису робить commit або повний rollback. Бізнес-логіка не розміщуватиметься в шаблонах.

## Вимоги

- Python 3.12.
- Git.
- Docker Desktop із запущеним Linux Engine та Docker Compose v2 або власна PostgreSQL 17.
- Інтернет для встановлення залежностей і Bootstrap CDN.

## Локальний запуск у Windows PowerShell

Виконуйте команди з кореня репозиторію:

```powershell
$env:PYTHONUTF8 = '1'
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e ".[dev]"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1
```

Режим UTF-8 застосовується до цієї PowerShell-сесії та дочірніх процесів; він потрібний для коректної роботи з українськими шляхами й текстом. Активація venv не обов'язкова — команди використовують його Python напряму.

Сторінка: [http://127.0.0.1:8000](http://127.0.0.1:8000). Перевірка працездатності: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health). Зупинка сервера — `Ctrl+C`.

`requirements.lock` фіксує прямі й транзитивні залежності, включно з інструментами розробки. Після встановлення lock-файла editable install з `--no-deps` додає пакет проєкту без повторного вибору версій. Build backend окремо зафіксований у `pyproject.toml`.

Наведений запуск відкриває системну сторінку та health без підключення до БД. Для входу налаштуйте PostgreSQL, застосуйте міграції, встановіть `SECRET_KEY` та створіть адміністратора за інструкціями нижче.

Для macOS/Linux відповідні команди використовують `python3.12 -m venv .venv` і `.venv/bin/python`. Локальну перевірку цієї версії виконано на Windows / Python 3.12.6.

## Конфігурація

Змінні середовища мають пріоритет над `.env`. Порожні значення в `.env` не замінюють значення за замовчуванням.

| Змінна | Значення / правило |
|---|---|
| `APP_NAME` | Назва системи, 1–100 символів |
| `APP_ENV` | `development`, `testing` або `production`; default `development` |
| `DEBUG` | Default `false`; у development-прикладі `true`; у production лише `false` |
| `SECRET_KEY` | Випадковий ключ підпису сесій, мінімум 32 символи; обов'язковий для входу в будь-якому режимі |
| `DATABASE_URL` | `postgresql+psycopg://user:password@host:port/database`; потрібний для Alembic та DB-сесій |
| `POSTGRES_USER` | Користувач локальної PostgreSQL у Compose |
| `POSTGRES_PASSWORD` | Обов'язковий пароль; приклад залишає його порожнім |
| `POSTGRES_DB` | Назва локальної БД |
| `POSTGRES_PORT` | Default `5433`; порт доступний лише на `127.0.0.1` |
| `SESSION_COOKIE_NAME` | `order_session`; назва cookie авторизації |
| `APP_TIMEZONE` | `Europe/Kyiv`; перевіряється як IANA time zone |
| `CURRENCY` | `EUR`; інших валют у базовій версії немає |
| `DEFAULT_ADMIN_EMAIL` | Email лише для явної команди seed; без значення за замовчуванням |
| `DEFAULT_ADMIN_PASSWORD` | Початковий пароль лише для seed, 8–128 символів; без значення за замовчуванням |
| `MANAGER_ORDER_VISIBILITY` | `all` або `assigned`; default `all`; застосовується після реалізації замовлень |

`.env` не зберігається в Git. Приклад не містить паролів або реальних секретів. Значення секрету й URL БД приховані в текстовому представленні налаштувань та повідомленнях валідації.

Для входу згенеруйте випадковий секрет та встановіть його як `SECRET_KEY` у локальному `.env` або environment:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```

Без ключа або з ключем коротшим за 32 символи `/login` повертає пояснення і HTTP 503; `/health` продовжує працювати. Production-конфігурація не означає готовність до публічного розгортання: бізнес-функції ще відсутні. У production cookie вимагає HTTPS.

## PostgreSQL та міграції

Compose запускає лише PostgreSQL; web-сервіс і Dockerfile додаються на етапі фінального пакування. FastAPI зараз запускайте у venv.

1. Скопіюйте `.env.example` у `.env`, якщо цього ще не зроблено.
2. Згенеруйте пароль командою генерації секрету вище. Встановіть його у `POSTGRES_PASSWORD` та URL БД. Для цього генератора символи безпечні для URL.
3. Для стандартних значень прикладу URL має вигляд `postgresql+psycopg://order_app:<ваш-пароль>@127.0.0.1:5433/order_tracking`.
4. З кореня репозиторію виконайте:

```powershell
$env:PYTHONUTF8 = '1'
docker compose config --quiet
docker compose up -d --wait postgres
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic check
```

Очікується revision `0002 (head)` та відсутність нових migration operations. Named volume `postgres_data` зберігає дані після `docker compose down`. PostgreSQL ініціалізує користувача, пароль і БД лише на порожньому volume; зміна `.env` не змінює пароль уже створеної БД.

Без Docker: створіть користувача та порожню БД у власній PostgreSQL 17, задайте `DATABASE_URL` з її адресою й виконайте ті самі Alembic-команди. `POSTGRES_*` потрібні лише для Compose. Параметри `DATABASE_URL` мають відповідати `POSTGRES_*`; Compose не синхронізує їх автоматично.

Нові зміни схеми:

```powershell
.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "describe schema change"
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Переглядайте згенеровану міграцію перед застосуванням. Уже застосовані міграції не переписуйте. `Base.metadata.create_all()` для запуску не використовується; міграції запускаються явно, а не з кожним web worker.

Цикл перевірки **тільки на порожній тестовій БД**:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic downgrade -1
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic downgrade base
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic check
```

Міграція `0001` створює шість таблиць; `0002` замінює унікальні індекси email/номера на іменовані UNIQUE constraints з їхніми індексами. Застосовану `0001` не переписано для цього уточнення. `downgrade -1` повертає `0002` до `0001`; `downgrade base` видаляє всі шість таблиць із даними. Для звичайного запуску виконуйте лише upgrade.

## Початковий адміністратор і вхід

Після `alembic upgrade head` та встановлення `SECRET_KEY` виконайте з кореня репозиторію:

```powershell
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe -m app.db.seed --email '<ваш-email>' --first-name 'Ім’я' --last-name 'Прізвище'
```

Команда запитає пароль приховано (8–128 символів). Ім’я та прізвище — 2–80 символів. Пароль не передається в аргументах CLI й не друкується. Для автоматизованого запуску можна задати `DEFAULT_ADMIN_EMAIL` та `DEFAULT_ADMIN_PASSWORD` через environment або ignored `.env`; після створення приберіть початковий пароль із конфігурації. У БД зберігається лише Argon2id-хеш. Команда не запускає міграції автоматично.

Повторний запуск для активного адміністратора з тим самим нормалізованим email зберігає пароль, імена, роль та `auth_version`. Якщо email належить менеджеру або неактивному користувачу, команда завершується з помилкою без підвищення прав чи активації. Одночасні запуски не дублюють користувача. Demo-набір і стандартні demo credentials ще відсутні.

1. Відкрийте [сторінку входу](http://127.0.0.1:8000/login).
2. Увійдіть даними створеного адміністратора; відкриється `/dashboard`.
3. Перейдіть до «Адміністрування» (`/users`); сторінка доступна лише ADMIN.
4. Натисніть «Вийти». GET `/logout` не виконує вихід.

Менеджер може відкривати `/dashboard`, але прямий GET `/users` повертає 403, а посилання адміністрування приховане. Створення менеджерів через UI з’явиться в модулі керування користувачами; автоматичні тести ролей створюють їх лише у власних тестових схемах.

### Сесії й безпека

Cookie Starlette підписана, але не зашифрована. Вона містить тільки `user_id`, `auth_version`, час початкового входу та CSRF-токен. Імена, email і паролі до cookie не записуються. HttpOnly і SameSite=Lax діють завжди; Secure — у production. [SessionMiddleware](https://starlette.dev/middleware/#sessionmiddleware)

Вхід діє максимум 8 годин від початкової авторизації; активність у браузері не подовжує цей строк. На кожному захищеному запиті користувач завантажується з БД: відсутній або неактивний користувач, застарілий `auth_version` чи прострочений вхід перенаправляють на login. Logout атомарно збільшує `auth_version` і відкликає всі раніше видані сесії користувача. Майбутні reset password, зміна ролі та деактивація повинні також підвищувати цю версію; їхніх маршрутів наразі немає.

Усі зареєстровані змінювальні HTTP-маршрути захищені CSRF, включно з login/logout. HTML передає hidden `csrf_token`; майбутні JSON-запити з cookie мають передавати `X-CSRF-Token`. Після входу сесія та CSRF-токен оновлюються. Невірний або відсутній токен дає 403 без виконання дії. `next` допускає лише локальний шлях, зокрема відхиляє закодовані зовнішні redirect.

Після помилки входу email зберігається, пароль залишається порожнім; неправильний пароль, невідомий email і неактивність дають однакове повідомлення. HTML авторизації має `Cache-Control: no-store`. Логи входу не містять email чи паролів; для помилок БД журналюється лише тип помилки, а користувач отримує загальне повідомлення без traceback.

## Схема даних

```mermaid
erDiagram
    users ||--o{ orders : manages
    clients ||--o{ orders : places
    orders ||--o{ order_items : contains
    orders ||--o{ order_status_history : has
    users ||--o{ order_status_history : changes
    order_number_counters {
        int year PK
        int last_value
    }
```

- User: ПІБ, нормалізований унікальний email, password_hash, ADMIN/MANAGER, активність, `auth_version`, timestamps.
- Client: назва, телефон, email, адреса, примітка, timestamps.
- Order: унікальний номер, клієнт, менеджер, статус, пріоритет, дедлайн, коментар, сума, архівність, `version`, timestamps.
- OrderItem: назва, quantity numeric(10,2), unit_price та line_total numeric(12,2).
- OrderStatusHistory: старий/новий статус, автор, коментар, час. NULL old_status допускає початковий NEW.
- OrderNumberCounter: рік та невід'ємне останнє значення; алгоритм видачі номерів додається разом зі створенням замовлень.

Статуси: NEW, CONFIRMED, IN_PROGRESS, READY, COMPLETED, CANCELLED. Пріоритети: LOW, NORMAL, HIGH. VARCHAR із named CHECK constraints відхиляє інші значення також у raw SQL. Кількість має бути додатною, ціни й суми — невід'ємними; numeric перевіряє місткість. Формат email та бізнес-правила реалізуються в наступних сервісах.

FK RESTRICT захищають пов'язаних клієнтів, користувачів і замовлення з історією. Позиції мають FK CASCADE та ORM delete-orphan для подальшої заміни списку; UI/API фізичного видалення сутностей немає. Історію не видаляє ORM cascade. Незмінність історії, термінальні статуси та мінімум одна позиція контролюватимуться сервісами.

Datetime зберігаються як timestamptz; DB-сесії працюють у UTC. Суми повертаються як Decimal. Server defaults задають початкові timestamps; `updated_at` оновлюється при ORM UPDATE. ORM version counter перевіряє `Order.version` та відхиляє застарілі зміни; bulk SQL його обходить. Зміни позицій мають оновлювати батьківський Order у майбутньому сервісі.

`app/db/session.py` створює синхронний engine із pool_pre_ping та прихованими SQL-параметрами. Dependency закриває сесію, виконує rollback помилки й не робить автоматичного commit. Сервіс запису відповідатиме за commit усієї бізнес-операції.

## Перевірки

```powershell
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe -m pytest --cov=app --cov-report=term-missing
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

Тести перевіряють HTTP-сторінку й `/health`, Jinja2 autoescape, доступність CSS незалежно від working directory, документацію, production-обмеження та завантаження конфігурації. Без `TEST_DATABASE_URL` PostgreSQL-тести явно пропускаються.

Для повної перевірки використайте **окрему тестову БД**, у якій користувач може створювати схеми:

```powershell
$env:TEST_DATABASE_URL = 'postgresql+psycopg://<user>:<password>@127.0.0.1:5433/<test_database>'
.\.venv\Scripts\python.exe -m pytest --cov=app --cov-report=term-missing
Remove-Item Env:TEST_DATABASE_URL
```

Кожен DB-тест створює власну випадкову схему, застосовує Alembic і видаляє лише цю схему в cleanup. Перевіряються upgrade/downgrade/upgrade, відповідність ORM міграції, enum/UNIQUE/FK/CHECK, numeric overflow, UTC, зв'язки, version conflict і rollback DB-сесій; login/logout, anonymous/inactive, ADMIN/MANAGER, CSRF для HTML/JSON, підроблена cookie, абсолютний строк входу, відкликання й повторний/конкурентний seed. SQLite не використовується. GitHub Actions виконує ruff, повний pytest і цикл міграцій на PostgreSQL 17.

Пакування Python-проєкту:

```powershell
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe -m build
```

HTML-шаблони та CSS входять у wheel. Каталог `dist` не зберігається в Git.

### Ручний smoke test

1. Запустіть Uvicorn за інструкцією вище.
2. Відкрийте `/health`: очікується `{"status":"ok"}` та HTTP 200.
3. Відкрийте `/`: український заголовок «Облік замовлень», EUR, Europe/Kyiv, повідомлення про підготовку робочого простору.
4. Перевірте завантаження `/static/css/app.css` та `/docs`; Swagger містить `/health`.
5. Перевірте сторінку на ширинах 375, 768 і 1440 px: без горизонтального прокручування, текст не обрізається.
6. Натисніть Tab: першим доступне посилання «Перейти до вмісту», фокус видимий.
7. На `/login` перевірте неправильний пароль: email зберігається, пароль порожній; правильний пароль відкриває робочий простір.
8. Перевірте `/users` як ADMIN, logout і повернення anonymous на login. Доступ менеджера та inactive перевіряється PostgreSQL-тестами.

## Структура

```text
app/
  core/           конфігурація, безпека, dependencies, помилки та політики доступу
  db/             SQLAlchemy Base, timestamps, engine, сесії та CLI seed
  models/         шість ORM-моделей та enum
  schemas/        вхідні схеми авторизації
  repositories/   параметризовані запити користувачів без commit
  services/       авторизація та створення адміністратора
  web/routes/     системні, auth та захищені HTTP-маршрути
  web/templates/  Jinja2 HTML
  static/         локальні стилі й favicon
  main.py         фабрика FastAPI
tests/            перевірки
alembic/          середовище, шаблон і версії міграцій
alembic.ini       конфігурація міграцій без секретів
docker-compose.yml PostgreSQL, healthcheck та named volume
.github/workflows/ перевірки Python та PostgreSQL у CI
pyproject.toml    метадані, залежності та налаштування інструментів
requirements.lock зафіксовані залежності
.env.example      приклад конфігурації без секретів
```

## API-документація

Development/testing: [Swagger](http://127.0.0.1:8000/docs) та [OpenAPI JSON](http://127.0.0.1:8000/openapi.json). У production обидва endpoints вимкнені. Поточний `/health` перевіряє процес застосунку, а не готовність БД.

## Подальші етапи та обмеження

Робота з клієнтами й замовленнями, workflow статусів, показники dashboard, керування користувачами, звіти, JSON API та контейнер web додаються послідовно. Команди для ще не реалізованих модулів не застосовуються до поточної версії.

- Dockerfile, web-сервіс Compose та demo seed наразі відсутні; команда створення початкового admin доступна.
- Фіксованих demo-акаунтів немає; для входу явно створіть адміністратора зі своїм паролем.
- `/ready`, CRUD клієнтів/замовлень/користувачів та `/api/v1` ще не доступні.
- Bootstrap завантажується з CDN; локальні стилі й текстова сторінка доступні без нього.
- Візуальний прохід у браузері не входить до автоматичних HTTP-тестів. Login/layout перевірено вручну на 375, 768 і 1440 px; перевірте їх повторно для свого браузера.
- Суми в моделях — Decimal у EUR, timestamps — UTC. Обчислення сум і відображення бізнес-дат у Europe/Kyiv додаються разом із замовленнями.

## Знімки екрана

Знімки функціональних сторінок будуть додані після реалізації відповідних модулів.

## Можливі майбутні розширення

Після завершення базової системи: повідомлення, вкладення, PDF-рахунки, клієнтський портал та інтеграції. Вони не входять до поточної реалізації.
