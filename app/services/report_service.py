import csv
import io

from app.core.business_time import display_time
from app.core.labels import PRIORITY_LABELS, STATUS_LABELS
from app.core.policies import require_active, require_administrator
from app.repositories import report_repository

CSV_HEADERS = [
    "Номер",
    "Клієнт",
    "Менеджер",
    "Статус",
    "Пріоритет",
    "Створено",
    "Завершено",
    "Дедлайн",
    "Вартість",
    "Валюта",
]


def authorized_query(user, filters, visibility):
    require_active(user)
    if filters.include_archived:
        require_administrator(user)
    return report_repository.statement(user, visibility, filters)


def snapshot(session, user, filters, visibility="all"):
    query = authorized_query(user, filters, visibility)
    total, amount = report_repository.summary(session, query)
    pages = max(1, (total + filters.page_size - 1) // filters.page_size)
    page = min(filters.page, pages)
    return dict(
        total=total,
        amount=amount,
        page=page,
        pages=pages,
        rows=report_repository.rows(session, query, page=page, page_size=filters.page_size),
    )


def safe_cell(value: str) -> str:
    # Prefix suspicious text, including formulas hidden behind leading whitespace.
    # Quoting alone does not stop spreadsheet formula evaluation.
    if value.startswith(("\t", "\r", "\n")) or value.lstrip().startswith(
        ("=", "+", "-", "@", "＝", "＋", "－", "＠")
    ):
        return "'" + value
    return value


def export_csv(session, user, filters, visibility="all") -> bytes:
    query = authorized_query(user, filters, visibility)
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(CSV_HEADERS)
    for order, completed_at in report_repository.rows(session, query):
        writer.writerow(
            [
                safe_cell(str(value))
                for value in [
                    order.number,
                    order.client.name,
                    f"{order.manager.first_name} {order.manager.last_name}",
                    STATUS_LABELS[order.status.value],
                    PRIORITY_LABELS[order.priority.value],
                    display_time(order.created_at),
                    display_time(completed_at),
                    display_time(order.deadline_at),
                    format(order.total_amount, ".2f"),
                    "EUR",
                ]
            ]
        )
    return output.getvalue().encode("utf-8-sig")
