"""Calendar dates use Beijing time; persisted timestamps and deadlines stay UTC."""

from datetime import UTC, date, datetime, timedelta, timezone

# Current Beijing civil time is UTC+8. A fixed offset also works on Windows
# without requiring an OS IANA database or an additional tzdata dependency.
BUSINESS_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")


def business_today(instant: datetime | None = None) -> date:
    value = instant if instant is not None else datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Business calendar requires a timezone-aware instant")
    return value.astimezone(BUSINESS_TIMEZONE).date()


def business_month(instant: datetime | None = None) -> str:
    return business_today(instant).strftime("%Y-%m")
