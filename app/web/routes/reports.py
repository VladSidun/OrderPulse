from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import ValidationError

from app.core.dependencies import CurrentUser, Database, csrf_token
from app.models import OrderStatus, UserRole
from app.repositories import order_list_repository
from app.schemas.report import ReportFilters
from app.services import report_service
from app.web.forms import validation_errors
from app.web.rendering import render

router = APIRouter(include_in_schema=False)


@router.get("/reports")
def reports(request: Request, session: Database, user: CurrentUser):
    csrf_token(request)
    values = dict(request.query_params)
    context = dict(
        active_page="reports",
        values=values,
        statuses=OrderStatus,
        managers=order_list_repository.managers(session),
        is_admin=user.role == UserRole.ADMIN,
    )
    try:
        filters = ReportFilters.model_validate(values)
    except ValidationError as error:
        return render(
            request, "reports.html", status_code=422, errors=validation_errors(error), **context
        )
    data = report_service.snapshot(
        session, user, filters, request.app.state.settings.manager_order_visibility
    )
    normalized = filters.model_dump(mode="json", exclude_none=True)
    normalized["include_archived"] = str(filters.include_archived).lower()
    export_values = {k: v for k, v in normalized.items() if k not in {"page", "page_size"}}

    def page_url(page):
        return "/reports?" + urlencode(normalized | {"page": page})

    return render(
        request,
        "reports.html",
        errors={},
        data=data,
        filters=filters,
        export_url="/reports/export.csv?" + urlencode(export_values),
        page_url=page_url,
        **context,
    )


@router.get("/reports/export.csv")
def export(request: Request, session: Database, user: CurrentUser):
    try:
        filters = ReportFilters.model_validate(dict(request.query_params))
    except ValidationError:
        return render(request, "error.html", status_code=422, message="Перевірте фільтри звіту.")
    content = report_service.export_csv(
        session, user, filters, request.app.state.settings.manager_order_visibility
    )
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="orders-report.csv"',
            "Cache-Control": "no-store",
        },
    )
