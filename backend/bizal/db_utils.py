def set_lock_timeout(cursor, timeout='3s'):
    """
    Bound how long a concurrent caller can block on a row lock taken via
    select_for_update() inside the surrounding transaction.atomic() block.

    BUG FIX: this used to be a bare `cursor.execute("SET LOCAL lock_timeout
    = '3s'")` repeated at every select_for_update() call site (billing,
    bookings, orders, inventory, hotels, staff, appointments, payments,
    tenants). `SET LOCAL` is PostgreSQL-only syntax — production runs on
    Postgres, where this works exactly as intended, but local dev
    (bizal.settings.local) and the test suite (bizal.settings.test) both use
    SQLite, which raises `OperationalError: near "SET": syntax error` the
    instant any of those code paths run. That took down `seed.py` (via
    InvoiceLine.save()) and would have taken down the equivalent request
    handlers under any local/SQLite load test too.

    connection.vendor is 'sqlite', 'postgresql', 'mysql', etc. — checking it
    here, once, keeps every call site a single line and means new call sites
    can't reintroduce the bug by copy-pasting the raw SQL again. On SQLite
    this is a no-op: SQLite's own locking (a single writer at a time) makes
    the timeout guard meaningless there anyway, so skipping it changes
    nothing about correctness, only about which backend the app happens to
    be pointed at.
    """
    if cursor.db.vendor == 'postgresql':
        # SET does not accept a bound query parameter in PostgreSQL (it
        # needs a literal), so this is built directly rather than passed
        # as a params list. `timeout` is always a trusted literal supplied
        # by our own call sites (e.g. '3s'), never user input.
        cursor.execute(f"SET LOCAL lock_timeout = '{timeout}'")