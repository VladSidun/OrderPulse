from typing import Annotated

from fastapi import Depends, Request
from pydantic import ValidationError


async def read_form(request: Request) -> dict:
    form = await request.form(max_files=0, max_fields=1000)
    values = dict(form)
    values.pop("csrf_token", None)
    return values


FormValues = Annotated[dict, Depends(read_form)]


def validation_errors(error: ValidationError) -> dict[str, str]:
    messages = {
        "string_too_short": "Значення надто коротке.",
        "string_too_long": "Значення надто довге.",
        "missing": "Заповніть це поле.",
        "extra_forbidden": "Це поле не можна змінювати.",
        "greater_than": "Значення має бути більшим за нуль.",
        "greater_than_equal": "Значення не може бути від’ємним.",
        "less_than_equal": "Значення перевищує допустиму межу.",
        "too_short": "Додайте щонайменше одну позицію.",
        "too_long": "Список не може містити понад 100 позицій.",
        "enum": "Оберіть значення зі списку.",
    }
    custom_messages = {
        "Використовуйте десятковий рядок, а не float.",
        "Введіть десяткове число.",
        "Число має бути скінченним і містити не більше двох десяткових знаків.",
        "Сума позиції перевищує місткість numeric(12,2).",
        "Загальна сума перевищує місткість numeric(12,2).",
        "Введіть цілий ідентифікатор.",
        "Дата має містити часовий пояс.",
        "Версія має бути цілим числом.",
        "Початкова дата не може бути пізнішою за кінцеву.",
        "Оберіть кінцеву дату раніше 31.12.9999.",
    }
    return {
        ".".join(str(part) for part in item["loc"]): (
            str(item.get("ctx", {}).get("error"))
            if str(item.get("ctx", {}).get("error")) in custom_messages
            else messages.get(item["type"], "Перевірте формат і допустиме значення.")
        )
        for item in error.errors()
    }
