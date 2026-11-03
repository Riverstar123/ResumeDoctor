from datetime import date, datetime

import pytest

from app.business_calendar import business_month, business_today


@pytest.mark.parametrize(
    ("instant", "day"),
    [
        ("2026-10-31T15:59:59+00:00", date(2026, 10, 31)),
        ("2026-10-31T16:00:00+00:00", date(2026, 11, 1)),
        ("2026-10-31T09:00:00-07:00", date(2026, 11, 1)),
        ("2026-12-31T16:00:00+00:00", date(2027, 1, 1)),
        ("2026-02-28T16:00:00+00:00", date(2026, 3, 1)),
        ("2028-02-28T16:00:00+00:00", date(2028, 2, 29)),
        ("2028-02-29T16:00:00+00:00", date(2028, 3, 1)),
    ],
)
def test_business_date_boundaries_are_independent_of_instant_timezone(instant, day):
    now = datetime.fromisoformat(instant)
    assert business_today(now) == day
    assert business_month(now) == day.strftime("%Y-%m")
