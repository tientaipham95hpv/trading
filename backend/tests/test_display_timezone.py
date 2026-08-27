from datetime import UTC, datetime

from app.api.routes import _vietnam_day_start_utc


def test_vietnam_day_start_uses_previous_utc_date_before_7am() -> None:
    now = datetime(2026, 8, 27, 3, 30, tzinfo=UTC)

    assert _vietnam_day_start_utc(now) == datetime(2026, 8, 26, 17, 0, tzinfo=UTC)


def test_vietnam_day_start_rolls_over_at_5pm_utc() -> None:
    now = datetime(2026, 8, 27, 17, 0, tzinfo=UTC)

    assert _vietnam_day_start_utc(now) == datetime(2026, 8, 27, 17, 0, tzinfo=UTC)
