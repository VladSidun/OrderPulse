from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

KYIV = ZoneInfo("Europe/Kyiv")


def utc_now() -> datetime:
    return datetime.now(UTC)


def calendar_bounds(start: date | None, end: date | None):
    lower = datetime.combine(start, time.min, KYIV).astimezone(UTC) if start else None
    upper = (
        datetime.combine(end + timedelta(days=1), time.min, KYIV).astimezone(UTC) if end else None
    )
    return lower, upper


def parse_local_deadline(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        local = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Введіть дату й час у форматі РРРР-ММ-ДД ГГ:ХХ.") from exc
    if local.tzinfo is not None:
        raise ValueError("У формі введіть місцевий час Europe/Kyiv без часового поясу.")
    candidates = set()
    for fold in (0, 1):
        aware = local.replace(tzinfo=KYIV, fold=fold)
        utc = aware.astimezone(UTC)
        if utc.astimezone(KYIV).replace(tzinfo=None) == local:
            candidates.add(utc)
    if len(candidates) != 1:
        raise ValueError(
            "Цей місцевий час не існує або неоднозначний через перехід літнього часу. "
            "Оберіть інший час."
        )
    return candidates.pop()


def local_input(value: datetime | None) -> str:
    return value.astimezone(KYIV).strftime("%Y-%m-%dT%H:%M") if value else ""


def display_time(value: datetime | None) -> str:
    return value.astimezone(KYIV).strftime("%d.%m.%Y %H:%M") if value else "—"
