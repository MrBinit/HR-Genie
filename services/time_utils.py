from datetime import datetime, timezone
import zoneinfo

NPT = zoneinfo.ZoneInfo("Asia/Kathmandu")

def as_aware_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)

def to_npt(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(NPT)

def fmt_npt(dt: datetime) -> str:
    # Example: 2025-08-16 03:00 PM NPT
    return to_npt(dt).strftime("%Y-%m-%d %I:%M %p NPT")

def fmt_npt_range(start: datetime, end: datetime | None) -> str:
    s = fmt_npt(start)
    return f"{s} — {fmt_npt(end)}" if end else s