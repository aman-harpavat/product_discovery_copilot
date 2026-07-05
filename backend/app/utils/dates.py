from __future__ import annotations

from datetime import datetime, timedelta, timezone


def parse_iso_datetime(value: str) -> datetime:
    normalized = (value or "").strip()
    if not normalized:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(normalized.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def relative_window_bounds(window_value: str, *, now: datetime | None = None) -> tuple[datetime, datetime]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    amount, unit = parse_relative_window(window_value)

    if unit == "days":
        start = current - timedelta(days=amount)
    elif unit == "weeks":
        start = current - timedelta(weeks=amount)
    elif unit == "months":
        start = _subtract_months(current, amount)
    elif unit == "years":
        start = _subtract_months(current, amount * 12)
    else:  # pragma: no cover - request validation guards this already
        raise ValueError(f"Unsupported relative unit: {unit}")

    return start, current


def parse_relative_window(window_value: str) -> tuple[int, str]:
    number_str, unit = window_value.split("_", 1)
    return int(number_str), unit


def relative_window_months_equivalent(window_value: str) -> float:
    amount, unit = parse_relative_window(window_value)
    if unit == "days":
        return max(1.0 / 30.0, amount / 30.0)
    if unit == "weeks":
        return max(1.0 / 4.0, amount / 4.0)
    if unit == "months":
        return float(amount)
    if unit == "years":
        return float(amount * 12)
    raise ValueError(f"Unsupported relative unit: {unit}")


def is_within_relative_window(value: str, window_value: str, *, now: datetime | None = None) -> bool:
    record_dt = parse_iso_datetime(value)
    start, end = relative_window_bounds(window_value, now=now)
    return start <= record_dt <= end


def month_bucket(value: str) -> str:
    return parse_iso_datetime(value).strftime("%Y-%m")


def _subtract_months(value: datetime, months: int) -> datetime:
    total_months = value.year * 12 + (value.month - 1) - months
    year = total_months // 12
    month = total_months % 12 + 1
    day = min(value.day, _days_in_month(year, month))
    return value.replace(year=year, month=month, day=day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        next_month = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    current_month = datetime(year, month, 1, tzinfo=timezone.utc)
    return (next_month - current_month).days
