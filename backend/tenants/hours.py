"""
Helpers for reading a tenant's `business_hours` JSONField.

`business_hours` is a free-form dict tenants fill in during onboarding, e.g.:

    {
        'E Hënë - E Shtunë': '09:00 - 20:00',
        'E Diel':             '10:00 - 16:00',
    }

Keys are Albanian day names (or day ranges, "Day - Day"), values are
"HH:MM - HH:MM" time ranges. Monday–Saturday commonly share one range while
Sunday has its own (shorter, or absent entirely meaning closed) — the whole
point of this module is to resolve hours *per specific weekday* rather than
flattening every range in the dict into one min/max window, which would
silently let e.g. a Sunday-only 10:00-16:00 business accept a 19:00 booking
just because Monday-Saturday goes that late.
"""
import re

# Index 0 = Monday ... 6 = Sunday, matching Python's date.weekday().
WEEKDAYS_SQ = ['E Hënë', 'E Martë', 'E Mërkurë', 'E Enjte', 'E Premte', 'E Shtunë', 'E Diel']

_TIME_RANGE_RE = re.compile(r'(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})')


def _day_index(name):
    name = (name or '').strip().lower()
    for i, d in enumerate(WEEKDAYS_SQ):
        if d.lower() == name:
            return i
    return None


def _expand_day_key(key):
    """'E Hënë - E Shtunë' -> [0,1,2,3,4,5]; 'E Diel' -> [6]; unknown -> []."""
    parts = [p.strip() for p in str(key).split(' - ')]
    if len(parts) == 1:
        idx = _day_index(parts[0])
        return [idx] if idx is not None else []
    start_idx = _day_index(parts[0])
    end_idx = _day_index(parts[-1])
    if start_idx is None or end_idx is None:
        return []
    if start_idx <= end_idx:
        return list(range(start_idx, end_idx + 1))
    # Wrap-around (e.g. a key spanning Sat -> Mon) — not used by onboarding
    # today, but handled so a manually-edited business_hours dict can't
    # silently misbehave.
    return list(range(start_idx, 7)) + list(range(0, end_idx + 1))


def hours_for_weekday(business_hours, weekday):
    """
    Resolve the (open_minutes, close_minutes) window for a specific weekday.

    `weekday` follows date.weekday(): Monday=0 .. Sunday=6.
    Returns None if the tenant has no hours configured for that day (i.e.
    closed), or if business_hours is empty/unparseable.
    """
    if not business_hours or not isinstance(business_hours, dict):
        return None
    for key, val in business_hours.items():
        if weekday not in _expand_day_key(key):
            continue
        m = _TIME_RANGE_RE.match(str(val))
        if not m:
            continue
        oh, om, ch, cm = (int(x) for x in m.groups())
        open_min = oh * 60 + om
        close_min = (24 if ch == 0 else ch) * 60 + cm  # "00:00" close = midnight/end of day
        return (open_min, close_min)
    return None


def is_open_at(business_hours, weekday, t_min):
    """
    Return True if the tenant is open at `t_min` minutes-since-midnight on
    `weekday` (Monday=0 .. Sunday=6).

    Handles two shapes of window:
      - Same-day windows, e.g. 09:00-20:00 -> open_min <= t_min <= close_min.
      - Overnight windows that cross midnight, e.g. 18:00-02:00, encoded by
        hours_for_weekday as close_min (120) < open_min (1080). Such a window
        has two parts: the evening part on `weekday` itself (t_min >= open_min)
        and an early-morning part that actually falls on the *next* calendar
        day. So checking "is `weekday` at `t_min` open" also has to look at
        *yesterday's* window, in case yesterday was an overnight window whose
        early-morning tail spills into today.

    Note: a full 24h day is stored as "00:00 - 00:00", which hours_for_weekday
    resolves to close_min=1440 (> open_min=0), so it's treated as a normal
    same-day window covering the whole day rather than as "crossing
    midnight" -- no spillover check is needed for it.
    """
    today = hours_for_weekday(business_hours, weekday)
    if today is not None:
        open_min, close_min = today
        if close_min >= open_min:
            if open_min <= t_min <= close_min:
                return True
        elif t_min >= open_min:
            # Overnight window, evening portion of `weekday`.
            return True

    prev_weekday = (weekday - 1) % 7
    prev = hours_for_weekday(business_hours, prev_weekday)
    if prev is not None:
        prev_open, prev_close = prev
        if prev_close < prev_open and t_min <= prev_close:
            # Early-morning tail of yesterday's overnight window.
            return True

    return False
