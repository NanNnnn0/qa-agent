"""Cron-expression helpers for QA schedule records.

Kept free of store/service imports so the store can validate a schedule before
persisting it, and the scheduler can reuse the same next-run computation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from nanobot.qa.validation import QaValidationError


def validate_schedule_fields(cron: Any, timezone_name: Any) -> tuple[str, str]:
    """Return the normalized ``(cron, timezone)`` pair or raise a QA error."""
    expr = cron.strip() if isinstance(cron, str) else ""
    if not expr:
        raise QaValidationError("cron is required")
    try:
        from croniter import croniter

        croniter(expr)
    except Exception as exc:
        raise QaValidationError(f"invalid cron expression '{expr}': {exc}") from None
    zone = timezone_name.strip() if isinstance(timezone_name, str) else ""
    if zone:
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(zone)
        except Exception:
            raise QaValidationError(f"unknown timezone '{zone}'") from None
    return expr, zone


def iso_to_ms(value: str) -> int:
    """Convert one of this module's UTC ISO strings back to milliseconds."""
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def next_run_iso(
    cron: str,
    timezone_name: str = "",
    *,
    now_ms: int | None = None,
) -> str:
    """Return the next UTC fire time as the same ISO-8601 string the store uses."""
    from zoneinfo import ZoneInfo

    from croniter import croniter

    if now_ms is None:
        now = datetime.now(timezone.utc)
    else:
        now = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
    zone = ZoneInfo(timezone_name) if timezone_name else datetime.now().astimezone().tzinfo
    base = now.astimezone(zone)
    following = croniter(cron, base).get_next(datetime)
    return following.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
