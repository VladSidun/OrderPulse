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
    }
    return {
        ".".join(str(part) for part in item["loc"]): messages.get(
            item["type"], "Перевірте формат і допустиме значення."
        )
        for item in error.errors()
    }
