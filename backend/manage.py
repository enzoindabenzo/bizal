#!/usr/bin/env python
import os
import sys

def main():
    # BUGFIX: `manage.py test` was defaulting to bizal.settings.local — the
    # same settings module used for local dev (real LocMemCache, file-backed
    # sqlite db.sqlite3). LocMemCache is process-wide and NOT cleared by
    # Django's per-test transaction rollback, so TenantMiddleware's 5-minute
    # tenant cache (see tenants/middleware.py _get_tenant()) leaks a stale,
    # since-rolled-back Tenant object across test methods that reuse the same
    # slug (e.g. 'test', 'hertz') — every FK write against that stale tenant
    # then fails at teardown with "invalid foreign key ... tenant_id ...
    # does not have a corresponding value in tenants_tenant.id", and requests
    # that depend on the (correct, current) tenant's plan/is_active get wrong
    # permission results (403 where 200 was expected, etc.).
    # bizal/settings/test.py already exists specifically to avoid this
    # (DummyCache, in-memory sqlite) and pytest.ini already points pytest at
    # it — manage.py just wasn't consistent with that. Auto-selecting it
    # here for the `test` subcommand (unless the caller already set
    # DJANGO_SETTINGS_MODULE explicitly, e.g. CI setting bizal.settings.test
    # with DB_HOST for the Postgres-backed run) fixes `python manage.py test`
    # to behave the same as `pytest`.
    if 'DJANGO_SETTINGS_MODULE' not in os.environ and len(sys.argv) > 1 and sys.argv[1] == 'test':
        os.environ['DJANGO_SETTINGS_MODULE'] = 'bizal.settings.test'
    else:
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bizal.settings.local')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError("Couldn't import Django.") from exc
    execute_from_command_line(sys.argv)

if __name__ == '__main__':
    main()
