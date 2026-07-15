"""
manage.py sync_celery_schedule

LOW-4 FIX: Management command to re-seed django-celery-beat PeriodicTask entries
from the CELERY_BEAT_SCHEDULE setting. DatabaseScheduler only reads
CELERY_BEAT_SCHEDULE on first run; subsequent deploys that add or change
scheduled tasks are silently ignored unless the DB entries are updated.

Usage:
    python manage.py sync_celery_schedule             # add/update tasks (writes to DB)
    python manage.py sync_celery_schedule --dry-run   # preview changes without writing
    python manage.py sync_celery_schedule --clear     # delete + reseed (full reset)

Add to entrypoint.sh or deployment checklist:
    python manage.py sync_celery_schedule

This is idempotent — re-running it without --clear only adds/updates tasks;
it never removes tasks that were manually added via Django admin.

NOTE: Running without --dry-run ALWAYS writes to the database. Use --dry-run
to preview what would be created/updated without modifying any DB rows.
"""
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import transaction

# L-4 FIX: Celery's crontab() parses each field (minute/hour/day_of_week/
# day_of_month/month_of_year) into a *set of ints* representing every
# matching value — crontab(minute=0).minute is {0}, not the string '0';
# crontab().minute (i.e. '*') is the full set(range(60)). The command
# below already prefers the private `_orig_*` attributes (which hold the
# original, unparsed input) and only falls back to the public .minute/
# .hour/etc. attributes if `_orig_*` is ever removed in a future Celery
# version. That fallback previously did str(sched.minute) directly, which
# stringifies the *set* itself — str({0}) == '{0}', not '0' — so
# CrontabSchedule.objects.get_or_create() would store a value that never
# matches the same crontab on a later run (or one created via Django
# admin), creating a duplicate PeriodicTask/CrontabSchedule row every time
# this command runs without `_orig_*`.
_CRONTAB_FIELD_RANGES = {
    'minute': range(0, 60),
    'hour': range(0, 24),
    'day_of_week': range(0, 7),
    'day_of_month': range(1, 32),
    'month_of_year': range(1, 13),
}


def _stringify_crontab_field(parsed_value, field_name):
    """Convert a parsed crontab field back to django-celery-beat's expected
    string form: '*' for the full range, otherwise sorted comma-separated
    values (e.g. '0,15,30,45'). Used only as a fallback when Celery's
    private `_orig_*` attributes are unavailable — see module docstring
    above. Falls back to plain str() for any value that isn't iterable
    (e.g. if a future Celery version changes the representation again),
    so this can never raise on an unexpected type.
    """
    try:
        values = set(parsed_value)
    except TypeError:
        return str(parsed_value)
    full_range = set(_CRONTAB_FIELD_RANGES.get(field_name, ()))
    if full_range and values == full_range:
        return '*'
    return ','.join(str(v) for v in sorted(values))


class Command(BaseCommand):
    help = "Sync CELERY_BEAT_SCHEDULE entries into the django-celery-beat DB table."

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Delete all existing PeriodicTask rows before reseeding (full reset).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview what would be created/updated without writing to the database.',
        )

    def handle(self, *args, **options):
        try:
            from django_celery_beat.models import PeriodicTask, IntervalSchedule, CrontabSchedule
        except ImportError:
            self.stderr.write(self.style.ERROR(
                "django_celery_beat is not installed. "
                "Add 'django_celery_beat' to INSTALLED_APPS and run migrations."
            ))
            return

        dry_run = options['dry_run']
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be written to the database.\n"))

        if options['clear']:
            if dry_run:
                count = PeriodicTask.objects.count()
                self.stdout.write(self.style.WARNING(f"[DRY RUN] Would delete {count} existing PeriodicTask rows."))
            else:
                count, _ = PeriodicTask.objects.all().delete()
                self.stdout.write(self.style.WARNING(f"Deleted {count} existing PeriodicTask rows."))

        schedule_conf = getattr(settings, 'CELERY_BEAT_SCHEDULE', {})
        if not schedule_conf:
            self.stdout.write("CELERY_BEAT_SCHEDULE is empty — nothing to sync.")
            return

        created = updated = skipped = 0
        for name, config in schedule_conf.items():
            task = config.get('task')
            sched = config.get('schedule')
            # MED-2 FIX (v36): when Celery is not installed, base.py replaces
            # crontab() with a no-op lambda returning None, so CELERY_BEAT_SCHEDULE
            # entries have schedule=None. The isinstance(sched, crontab) check below
            # falls through to the else branch which calls sched.total_seconds(),
            # raising AttributeError on None. Skip None schedules explicitly with
            # a clear message so a Celery-less image doesn't crash entrypoint.sh.
            if task is None or sched is None:
                self.stderr.write(self.style.WARNING(
                    f"Skipping {name!r}: missing 'task' or 'schedule' "
                    f"(schedule={sched!r} — Celery may not be installed)."))
                skipped += 1
                continue

            # Build the schedule model entry
            from celery.schedules import crontab, schedule as celery_schedule
            if isinstance(sched, crontab):
                # HIGH-2 FIX: _orig_* attributes are private/undocumented Celery
                # internals that changed names between Celery 3.x and 4.x and may
                # change again. Use getattr() with a fallback to the public .minute,
                # .hour, etc. attributes (which return the parsed representation and
                # are part of the stable public API) so a Celery version bump cannot
                # silently break this command with an AttributeError.
                #
                # L-4 FIX: the fallback values (sched.minute, sched.hour, ...) are
                # sets of ints, not the original string — _stringify_crontab_field()
                # converts them back to django-celery-beat's expected string form
                # instead of stringifying the set object itself (see helper above).
                # MED-2 FIX: include timezone='UTC' in the lookup key, not in
                # defaults={}. Previously, a row created by an older
                # django-celery-beat version with timezone='' would be matched by
                # get_or_create (same minute/hour/etc.) and returned as-is, leaving
                # timezone='' on the schedule. Celery-beat then interprets empty
                # timezone as UTC but logs a warning and may shift task firing time
                # by the server's local UTC offset. Using timezone as a lookup field
                # ensures a new row with timezone='UTC' is always found or created.
                # MEDIUM-3 FIX: wrap in atomic + advisory lock to prevent duplicate
                # CrontabSchedule rows during concurrent deploys. atomic() alone does
                # not close the race — both processes can pass the get phase and each
                # succeed in create when no UNIQUE constraint exists.
                # MEDIUM-2 additional FIX: use a pg_advisory_xact_lock so only one
                # web container at a time can run the get_or_create for crontab schedules.
                # LOW-5 FIX: skip the DB write entirely in dry-run mode so --dry-run
                # truly makes no changes (previously CrontabSchedule rows were created
                # even when --dry-run was passed, violating the no-op contract).
                if dry_run:
                    self.stdout.write(
                        f"[DRY RUN] Would get_or_create CrontabSchedule for {name!r} "
                        f"(minute={str(sched._orig_minute) if hasattr(sched, '_orig_minute') else sched.minute}, "
                        f"hour={str(sched._orig_hour) if hasattr(sched, '_orig_hour') else sched.hour})"
                    )
                    db_schedule = None
                else:
                    with transaction.atomic():
                        from django.db import connection as _conn
                        # LOW-2 FIX: pg_advisory_xact_lock is PostgreSQL-only.
                        # Guard with a vendor check so the command doesn't raise
                        # DatabaseError when run against SQLite (local dev/CI).
                        if _conn.vendor == 'postgresql':
                            with _conn.cursor() as _cur:
                                _cur.execute(
                                    "SELECT pg_advisory_xact_lock(%s)",
                                    [hash('bizal_sync_crontab') & 0x7FFFFFFF]
                                )
                        db_schedule, _ = CrontabSchedule.objects.get_or_create(
                            minute=str(sched._orig_minute) if hasattr(sched, '_orig_minute')
                                else _stringify_crontab_field(sched.minute, 'minute'),
                            hour=str(sched._orig_hour) if hasattr(sched, '_orig_hour')
                                else _stringify_crontab_field(sched.hour, 'hour'),
                            day_of_week=str(sched._orig_day_of_week) if hasattr(sched, '_orig_day_of_week')
                                else _stringify_crontab_field(sched.day_of_week, 'day_of_week'),
                            day_of_month=str(sched._orig_day_of_month) if hasattr(sched, '_orig_day_of_month')
                                else _stringify_crontab_field(sched.day_of_month, 'day_of_month'),
                            month_of_year=str(sched._orig_month_of_year) if hasattr(sched, '_orig_month_of_year')
                                else _stringify_crontab_field(sched.month_of_year, 'month_of_year'),
                            timezone='UTC',
                        )
                defaults = {'crontab': db_schedule, 'interval': None}
            else:
                # Assume timedelta/seconds
                try:
                    seconds = int(sched.total_seconds()) if hasattr(sched, 'total_seconds') else int(sched)
                except Exception:
                    self.stderr.write(self.style.WARNING(f"Cannot parse schedule for {name!r}: {sched!r}"))
                    skipped += 1
                    continue
                period = IntervalSchedule.SECONDS
                # MEDIUM-3 FIX: wrap in the same transaction.atomic() guard
                # used for CrontabSchedule above. IntervalSchedule has no
                # UNIQUE constraint on (every, period), so two concurrent
                # get_or_create calls (e.g. during a rolling deploy) can both
                # pass the get phase and each succeed in create, producing
                # duplicate rows.
                # LOW-3 FIX: guard the IntervalSchedule DB write with dry_run,
                # matching the dry-run skip already present for CrontabSchedule
                # above. Previously IntervalSchedule.objects.get_or_create() ran
                # unconditionally even when --dry-run was passed, violating the
                # "no changes will be written" contract. Currently latent (all
                # CELERY_BEAT_SCHEDULE entries use crontab()), but would silently
                # write DB rows if a timedelta-based schedule were ever added.
                if dry_run:
                    self.stdout.write(
                        f"[DRY RUN] Would get_or_create IntervalSchedule for {name!r} "
                        f"(every={seconds}s, period={period})"
                    )
                    db_schedule = None
                else:
                    with transaction.atomic():
                        db_schedule, _ = IntervalSchedule.objects.get_or_create(every=seconds, period=period)
                defaults = {'interval': db_schedule, 'crontab': None}

            defaults['task'] = task
            defaults['args'] = '[]'
            defaults['kwargs'] = '{}'
            defaults['enabled'] = True

            obj, was_created = (None, None) if dry_run else PeriodicTask.objects.update_or_create(name=name, defaults=defaults)
            if dry_run:
                existing = PeriodicTask.objects.filter(name=name).exists()
                action = "create" if not existing else "update"
                self.stdout.write(f"[DRY RUN] Would {action}: {name!r} → task={task!r}")
                if not existing:
                    created += 1
                else:
                    updated += 1
            elif was_created:
                created += 1
            else:
                updated += 1

        prefix = "[DRY RUN] Would have " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}sync_celery_schedule: {created} created, {updated} updated, {skipped} skipped."
        ))
