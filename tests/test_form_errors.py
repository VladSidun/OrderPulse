import pytest
from pydantic import ValidationError

from app.schemas.client import ClientInput
from app.schemas.order import ItemInput, OrderInput
from app.schemas.user import PasswordReset
from app.web.forms import validation_errors


@pytest.mark.parametrize(
    "schema,values,expected",
    [
        (
            ItemInput,
            {"name": "A", "quantity": "1.001", "unit_price": "1"},
            "Число має бути скінченним і містити не більше двох десяткових знаків.",
        ),
        (
            ItemInput,
            {"name": "A", "quantity": "2", "unit_price": "9999999999.99"},
            "Сума позиції перевищує місткість numeric(12,2).",
        ),
        (OrderInput, {"client_id": 1, "items": []}, "Додайте щонайменше одну позицію."),
        (PasswordReset, {"password": "short"}, "Пароль має містити 8–128 символів."),
        (PasswordReset, {"password": "x" * 129}, "Пароль має містити 8–128 символів."),
        (
            ClientInput,
            {"name": "Клієнт", "email": "private-invalid-value"},
            "Перевірте формат і допустиме значення.",
        ),
    ],
)
def test_error_messages_are_localized_and_never_echo_input(schema, values, expected):
    with pytest.raises(ValidationError) as caught:
        schema.model_validate(values)
    errors = validation_errors(caught.value)
    assert expected in errors.values()
    assert "private-invalid-value" not in str(errors)
