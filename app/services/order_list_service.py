from app.core.business_time import utc_now
from app.core.policies import require_active, require_administrator
from app.repositories import order_list_repository


def search(session, user, filters, visibility="all", *, now=None):
    require_active(user)
    if filters.archived:
        require_administrator(user)
    return order_list_repository.search(session, user, visibility, filters, now or utc_now())
