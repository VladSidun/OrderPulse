# Система обліку замовлень

Навчальний вебзастосунок для невеликої компанії: облік клієнтів, замовлень і контроль їх статусів.

## Поточні можливості

- Фабрика FastAPI з конфігурацією через environment variables та `.env`.
- Українська початкова сторінка Jinja2, Bootstrap 5 і локальні стилі.
- `GET /health` повертає `200` і `{"status":"ok"}` без підключення до БД.
- Swagger `/docs` і OpenAPI `/openapi.json` у development/testing.
- Перевірка конфігурації: часовий пояс, валюта EUR, режим видимості замовлень.
- Захист від випадкового увімкнення debug або порожнього секрету в production.

Робота з базою даних, авторизація та бізнес-функції ще не реалізовані. Початкова сторінка не містить посилань на недоступні модулі.

## Стек та архітектура

Поточна версія: Python 3.12, FastAPI, Uvicorn, Pydantic Settings, Jinja2, Bootstrap 5. Перевірки: pytest, pytest-cov, HTTPX2 / FastAPI TestClient, ruff. `tzdata` забезпечує IANA-часові пояси також у Windows.

Модульний моноліт зі спільними сервісами для HTML та JSON API:

```text
HTTP routes -> services -> repositories -> SQLAlchemy / PostgreSQL
```

На поточному етапі працюють routes, конфігурація й HTML. Сервіси, репозиторії та БД додаються разом із відповідними функціями. Бізнес-логіка не розміщуватиметься в шаблонах.

## Вимоги

- Python 3.12.
- Git.
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

Для macOS/Linux відповідні команди використовують `python3.12 -m venv .venv` і `.venv/bin/python`. Локальну перевірку цієї версії виконано на Windows / Python 3.12.6.

## Конфігурація

Змінні середовища мають пріоритет над `.env`. Порожні значення в `.env` не замінюють значення за замовчуванням.

| Змінна | Значення / правило |
|---|---|
| `APP_NAME` | Назва системи, 1–100 символів |
| `APP_ENV` | `development`, `testing` або `production`; default `development` |
| `DEBUG` | Default `false`; у development-прикладі `true`; у production лише `false` |
| `SECRET_KEY` | На цьому етапі не використовується для сесій; у production обов'язковий, мінімум 32 символи |
| `DATABASE_URL` | Зарезервовано для БД; зараз може бути порожнім |
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

## Перевірки

```powershell
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe -m pytest --cov=app --cov-report=term-missing
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

Тести перевіряють HTTP-сторінку й `/health`, Jinja2 autoescape, доступність CSS незалежно від working directory, документацію, production-обмеження та завантаження конфігурації. На поточному етапі тести не потребують PostgreSQL.

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
  web/routes/     HTTP-маршрути
  web/templates/  Jinja2 HTML
  static/css/     локальні стилі
  main.py         фабрика FastAPI
tests/            перевірки
pyproject.toml    метадані, залежності та налаштування інструментів
requirements.lock зафіксовані залежності
.env.example      приклад конфігурації без секретів
```

## API-документація

Development/testing: [Swagger](http://127.0.0.1:8000/docs) та [OpenAPI JSON](http://127.0.0.1:8000/openapi.json). У production обидва endpoints вимкнені. Поточний `/health` перевіряє процес застосунку, а не готовність БД.

## Подальші етапи та обмеження

PostgreSQL, SQLAlchemy, Alembic, авторизація, клієнти, замовлення, workflow статусів, dashboard, звіти, JSON API та Docker будуть додані послідовно. Команди для ще не реалізованих модулів не застосовуються до поточної версії.

- Dockerfile, Docker Compose, міграції та seed наразі відсутні.
- Demo-акаунтів немає; логін ще не реалізований.
- `/ready`, бізнес-сторінки та `/api/v1` ще не доступні.
- Bootstrap завантажується з CDN; локальні стилі й текстова сторінка доступні без нього.
- Детальний візуальний прохід у браузері не входить до автоматичних HTTP-тестів.
- Гроші майбутніх замовлень обчислюватимуться через Decimal у EUR, дати зберігатимуться в UTC і показуватимуться в Europe/Kyiv.

## Знімки екрана

Знімки функціональних сторінок будуть додані після реалізації відповідних модулів.

## Можливі майбутні розширення

Після завершення базової системи: повідомлення, вкладення, PDF-рахунки, клієнтський портал та інтеграції. Вони не входять до поточної реалізації.
