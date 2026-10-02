from enum import StrEnum

from sqlalchemy import Enum


class UserRole(StrEnum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"


class OrderStatus(StrEnum):
    NEW = "NEW"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    READY = "READY"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OrderPriority(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


def enum_column(enum_class: type[StrEnum], name: str) -> Enum:
    # VARCHAR + named CHECKs keep upgrade/downgrade free of shared PG enum types.
    return Enum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )
