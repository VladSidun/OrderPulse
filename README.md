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

Схема БД готова; авторизація та бізнес-функції ще не реалізовані. Початкова сторінка не містить посилань на недоступні модулі. Самі ORM-моделі не створюють замовлень, не обчислюють суми й не перевіряють права.

## Стек та архітектура

Поточна версія: Python 3.12, FastAPI, Uvicorn, Pydantic Settings, Jinja2, Bootstrap 5, SQLAlchemy 2.0.54, psycopg 3.3.6, Alembic 1.20.0, PostgreSQL 17.9. Перевірки: pytest, pytest-cov, HTTPX2 / FastAPI TestClient, ruff. `tzdata` забезпечує IANA-часові пояси також у Windows.

Модульний моноліт зі спільними сервісами для HTML та JSON API:

```text
HTTP routes -> services -> repositories -> SQLAlchemy / PostgreSQL
```

На поточному етапі працюють системні routes, конфігурація, HTML та основа БД. Сервіси й репозиторії додаються разом із відповідними функціями. Бізнес-логіка не розміщуватиметься в шаблонах.

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

Наведений запуск відкриває системну сторінку та health без БД. Для використання DB-сесій спочатку налаштуйте PostgreSQL і застосуйте міграцію нижче.

Для macOS/Linux відповідні команди використовують `python3.12 -m venv .venv` і `.venv/bin/python`. Локальну перевірку цієї версії виконано на Windows / Python 3.12.6.

## Конфігурація

Змінні середовища мають пріоритет над `.env`. Порожні значення в `.env` не замінюють значення за замовчуванням.

| Змінна | Значення / правило |
|---|---|
| `APP_NAME` | Назва системи, 1–100 символів |
| `APP_ENV` | `development`, `testing` або `production`; default `development` |
| `DEBUG` | Default `false`; у development-прикладі `true`; у production лише `false` |
| `SECRET_KEY` | На цьому етапі не використовується для сесій; у production обов'язковий, мінімум 32 символи |
| `DATABASE_URL` | `postgresql+psycopg://user:password@host:port/database`; потрібний для Alembic та DB-сесій |
| `POSTGRES_USER` | Користувач локальної PostgreSQL у Compose |
| `POSTGRES_PASSWORD` | Обов'язковий пароль; приклад залишає його порожнім |
| `POSTGRES_DB` | Назва локальної БД |
| `POSTGRES_PORT` | Default `5433`; порт доступний лише на `127.0.0.1` |
| `SESSION_COOKIE_NAME` | `order_session`; зарезервовано для авторизації |
| `APP_TIMEZONE` | `Europe/Kyiv`; перевіряється як IANA time zone |
| `CURRENCY` | `EUR`; інших валют у базовій версії немає |
| `MANAGER_ORDER_VISIBILITY` | `all` або `assigned`; default `all`; застосовується після реалізації замовлень |

`.env` не зберігається в Git. Приклад не містить паролів або реальних секретів. Значення секрету й URL БД приховані в текстовому представленні налаштувань та повідомленнях валідації.

Для майбутнього production-середовища згенеруйте випадковий секрет і передайте його через environment:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```

Production-конфігурація не означає готовність поточної версії до публічного розгортання: бізнес-функції та авторизація ще відсутні.

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

Кожен DB-тест створює власну випадкову схему, застосовує Alembic і видаляє лише цю схему в cleanup. Перевіряються upgrade/downgrade/upgrade, відповідність ORM міграції, enum/UNIQUE/FK/CHECK, numeric overflow, UTC, зв'язки, version conflict і rollback сесій. SQLite не використовується. GitHub Actions виконує ruff, повний pytest і цикл міграцій на PostgreSQL 17.

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

## Структура

```text
app/
  core/           конфігурація
  db/             SQLAlchemy Base, timestamps, engine та сесії
  models/         шість ORM-моделей та enum
  web/routes/     HTTP-маршрути
  web/templates/  Jinja2 HTML
  static/css/     локальні стилі
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

Авторизація, робота з клієнтами й замовленнями, workflow статусів, dashboard, звіти, JSON API та контейнер web додаються послідовно. Команди для ще не реалізованих модулів не застосовуються до поточної версії.

- Dockerfile, web-сервіс Compose та seed наразі відсутні.
- Demo-акаунтів немає; логін ще не реалізований.
- `/ready`, бізнес-сторінки та `/api/v1` ще не доступні.
- Bootstrap завантажується з CDN; локальні стилі й текстова сторінка доступні без нього.
- Детальний візуальний прохід у браузері не входить до автоматичних HTTP-тестів.
- Суми в моделях — Decimal у EUR, timestamps — UTC. Обчислення сум і відображення бізнес-дат у Europe/Kyiv додаються разом із замовленнями.

## Знімки екрана

Знімки функціональних сторінок будуть додані після реалізації відповідних модулів.

## Можливі майбутні розширення

Після завершення базової системи: повідомлення, вкладення, PDF-рахунки, клієнтський портал та інтеграції. Вони не входять до поточної реалізації.
