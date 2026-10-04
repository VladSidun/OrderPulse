from app.core.business_time import utc_now
from app.core.policies import require_active
from app.repositories import dashboard_repository


def snapshot(session, user, visibility="all", *, now=None):
    require_active(user)
    return dashboard_repository.snapshot(session, user, visibility, now or utc_now())
