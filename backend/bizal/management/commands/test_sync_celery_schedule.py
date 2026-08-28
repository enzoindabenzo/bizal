"""
Tests for `manage.py sync_celery_schedule`.

Exercises: empty schedule, missing task/schedule (skip), crontab branch
(both with and without Celery's private _orig_* attrs), interval/timedelta
branch, dry-run for both branches, --clear, unparsable schedule, and the
django_celery_beat-not-installed guard.
"""
import builtins
from datetime import timedelta
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.db import connection

from celery.schedules import crontab

from bizal.management.commands.sync_celery_schedule import _stringify_crontab_field


def run_command(*args):
    out = StringIO()
    err = StringIO()
    call_command('sync_celery_schedule', *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


@pytest.mark.django_db
class TestSyncCeleryScheduleBasics:
    def test_empty_schedule_writes_nothing(self):
        with override_settings(CELERY_BEAT_SCHEDULE={}):
            out, _ = run_command()
        assert "nothing to sync" in out

    def test_missing_task_or_schedule_is_skipped(self):
        conf = {
            'no-task': {'task': None, 'schedule': crontab(minute=0)},
            'no-schedule': {'task': 'x.y.z', 'schedule': None},
        }
        with override_settings(CELERY_BEAT_SCHEDULE=conf):
            out, err = run_command()
        assert "2 skipped" in out
        assert "Skipping 'no-task'" in err
        assert "Skipping 'no-schedule'" in err

    def test_unparsable_interval_schedule_is_skipped(self):
        class Unparsable:
            def total_seconds(self):
                raise ValueError("boom")

        conf = {'bad-interval': {'task': 'a.b.c', 'schedule': Unparsable()}}
        with override_settings(CELERY_BEAT_SCHEDULE=conf):
            out, err = run_command()
        assert "1 skipped" in out
        assert "Cannot parse schedule" in err

    def test_django_celery_beat_not_installed_guard(self, monkeypatch):
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == 'django_celery_beat.models':
                raise ImportError("no module")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, '__import__', fake_import)
        with override_settings(CELERY_BEAT_SCHEDULE={'x': {'task': 'a', 'schedule': crontab()}}):
            out, err = run_command()
        assert "django_celery_beat is not installed" in err


@pytest.mark.django_db
class TestCrontabBranch:
    def test_crontab_created_then_updated(self):
        conf = {
            'daily-job': {'task': 'billing.tasks.mark_overdue_invoices', 'schedule': crontab(hour=1, minute=0)},
        }
        with override_settings(CELERY_BEAT_SCHEDULE=conf):
            out1, _ = run_command()
            assert "1 created" in out1
            out2, _ = run_command()
            assert "1 updated" in out2

        from django_celery_beat.models import PeriodicTask
        task = PeriodicTask.objects.get(name='daily-job')
        assert task.crontab.hour == '1'
        assert str(task.crontab.timezone) == 'UTC'

    def test_crontab_dry_run_writes_nothing(self):
        conf = {
            'dry-job': {'task': 'billing.tasks.mark_overdue_invoices', 'schedule': crontab(hour=2, minute=30)},
        }
        from django_celery_beat.models import PeriodicTask, CrontabSchedule
        with override_settings(CELERY_BEAT_SCHEDULE=conf):
            out, _ = run_command('--dry-run')
        assert "DRY RUN" in out
        assert "Would create: 'dry-job'" in out
        assert not PeriodicTask.objects.filter(name='dry-job').exists()
        assert not CrontabSchedule.objects.filter(hour='2', minute='30').exists()

    def test_crontab_dry_run_reports_update_for_existing_task(self):
        conf = {
            'existing-job': {'task': 'billing.tasks.mark_overdue_invoices', 'schedule': crontab(hour=3, minute=0)},
        }
        with override_settings(CELERY_BEAT_SCHEDULE=conf):
            run_command()  # create it for real first
            out, _ = run_command('--dry-run')
        assert "Would update: 'existing-job'" in out

    def test_crontab_fallback_without_orig_attrs(self):
        """Simulate a future Celery where _orig_* private attrs are gone."""
        sched = crontab(hour=5, minute=15)
        for attr in ('_orig_minute', '_orig_hour', '_orig_day_of_week',
                     '_orig_day_of_month', '_orig_month_of_year'):
            if hasattr(sched, attr):
                delattr(sched, attr)

        conf = {'fallback-job': {'task': 'billing.tasks.mark_overdue_invoices', 'schedule': sched}}
        with override_settings(CELERY_BEAT_SCHEDULE=conf):
            out, _ = run_command()
        assert "1 created" in out

        from django_celery_beat.models import PeriodicTask
        task = PeriodicTask.objects.get(name='fallback-job')
        assert task.crontab.hour == '5'
        assert task.crontab.minute == '15'

    def test_crontab_fallback_dry_run_without_orig_attrs(self):
        sched = crontab(hour=6, minute=0)
        for attr in ('_orig_minute', '_orig_hour'):
            if hasattr(sched, attr):
                delattr(sched, attr)

        conf = {'fallback-dry': {'task': 'billing.tasks.mark_overdue_invoices', 'schedule': sched}}
        with override_settings(CELERY_BEAT_SCHEDULE=conf):
            out, _ = run_command('--dry-run')
        assert "DRY RUN" in out


@pytest.mark.django_db
class TestIntervalBranch:
    def test_interval_schedule_created(self):
        conf = {'every-30s': {'task': 'x.y.z', 'schedule': timedelta(seconds=30)}}
        with override_settings(CELERY_BEAT_SCHEDULE=conf):
            out, _ = run_command()
        assert "1 created" in out

        from django_celery_beat.models import PeriodicTask
        task = PeriodicTask.objects.get(name='every-30s')
        assert task.interval.every == 30

    def test_interval_schedule_dry_run(self):
        from django_celery_beat.models import PeriodicTask, IntervalSchedule
        conf = {'every-45s': {'task': 'x.y.z', 'schedule': timedelta(seconds=45)}}
        with override_settings(CELERY_BEAT_SCHEDULE=conf):
            out, _ = run_command('--dry-run')
        assert "Would get_or_create IntervalSchedule" in out
        assert not PeriodicTask.objects.filter(name='every-45s').exists()
        assert not IntervalSchedule.objects.filter(every=45).exists()

    def test_interval_schedule_plain_int_seconds(self):
        """schedule can be a plain int (already seconds) with no total_seconds()."""
        conf = {'raw-int': {'task': 'x.y.z', 'schedule': 15}}
        with override_settings(CELERY_BEAT_SCHEDULE=conf):
            out, _ = run_command()
        assert "1 created" in out


@pytest.mark.django_db
class TestClearOption:
    def test_clear_deletes_existing_tasks(self):
        conf = {'job-a': {'task': 'a.b.c', 'schedule': crontab(hour=1, minute=0)}}
        with override_settings(CELERY_BEAT_SCHEDULE=conf):
            run_command()
            from django_celery_beat.models import PeriodicTask
            assert PeriodicTask.objects.filter(name='job-a').exists()
            out, _ = run_command('--clear')
        assert "Deleted" in out
        # cleared then reseeded in the same invocation
        from django_celery_beat.models import PeriodicTask
        assert PeriodicTask.objects.filter(name='job-a').exists()

    def test_stringify_crontab_field_non_iterable_falls_back_to_str(self):
        # A plain int isn't iterable -> set(5) raises TypeError -> str(5) fallback.
        assert _stringify_crontab_field(5, 'minute') == '5'

    def test_crontab_attempts_postgres_advisory_lock_when_vendor_is_postgresql(self):
        # We fake the vendor name and spy on connection.cursor() so we can
        # confirm the vendor-gated branch (the `if vendor == 'postgresql'`
        # check) actually issues a pg_advisory_xact_lock call, without
        # relying on that call failing. CI runs the test suite against a
        # real Postgres database, so the lock call succeeds rather than
        # raising (that's only true for SQLite, e.g. local dev).
        conf = {'pg-job': {'task': 'a.b.c', 'schedule': crontab(hour=4, minute=0)}}
        executed_sql = []
        real_cursor = connection.cursor

        def spy_cursor(*args, **kwargs):
            cur = real_cursor(*args, **kwargs)
            orig_execute = cur.execute

            def execute(sql, params=None):
                executed_sql.append(sql)
                return orig_execute(sql, params) if params is not None else orig_execute(sql)

            cur.execute = execute
            return cur

        with override_settings(CELERY_BEAT_SCHEDULE=conf), \
                patch.object(connection, 'vendor', 'postgresql'), \
                patch.object(connection, 'cursor', side_effect=spy_cursor):
            run_command()

        assert any('pg_advisory_xact_lock' in sql for sql in executed_sql)

    def test_clear_dry_run_does_not_delete(self):
        conf = {'job-b': {'task': 'a.b.c', 'schedule': crontab(hour=1, minute=0)}}
        with override_settings(CELERY_BEAT_SCHEDULE=conf):
            run_command()
            out, _ = run_command('--clear', '--dry-run')
        assert "[DRY RUN] Would delete" in out
        from django_celery_beat.models import PeriodicTask
        assert PeriodicTask.objects.filter(name='job-b').exists()
