# Система обліку замовлень

Вебзастосунок для обліку клієнтів, замовлень і контролю їх статусів.

На поточному етапі реалізовано початкову конфігурацію, HTML-сторінку та endpoint перевірки працездатності. Робота з базою даних і бізнес-функції ще не реалізовані.

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
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1
```

Сторінка: http://127.0.0.1:8000. Перевірка працездатності: GET /health.

## Структура

```text
app/
  core/           конфігурація
  web/routes/     HTTP-маршрути
  web/templates/  Jinja2 HTML
  static/css/     локальні стилі
  main.py         фабрика FastAPI
tests/            перевірки
```

## Подальші етапи

PostgreSQL, міграції, авторизація, клієнти, замовлення, workflow статусів, dashboard, звіти, JSON API та Docker будуть додані послідовно. Команди для ще не реалізованих модулів не застосовуються до поточної версії.
