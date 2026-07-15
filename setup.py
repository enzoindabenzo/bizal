"""
BizAL Setup Script
==================
Usage (from the bizal/ folder):
  python setup.py
"""
import os
import sys
import subprocess
import platform

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, 'backend')
FRONTEND_STATIC = os.path.join(ROOT, 'frontend', 'static')
VENV = os.path.join(ROOT, 'venv')
WIN = platform.system() == 'Windows'
PY = os.path.join(VENV, 'Scripts' if WIN else 'bin', 'python' + ('.exe' if WIN else ''))

SETTINGS = 'bizal.settings.local'
env = os.environ.copy()
env['DJANGO_SETTINGS_MODULE'] = SETTINGS


def run(cmd, cwd=BACKEND, exit_on_fail=True):
    print(f'    $ {cmd}')
    result = subprocess.run(cmd, shell=True, cwd=cwd, env=env)
    if result.returncode != 0 and exit_on_fail:
        print(f'\n  ❌ Failed: {cmd}')
        sys.exit(1)
    return result.returncode


print()
print('=' * 58)
print('  BizAL — Development Setup')
print('=' * 58)

# ── Step 1: Virtual environment ──────────────────────────────
if not os.path.exists(PY):
    print('\n📦 Creating virtual environment...')
    run(f'"{sys.executable}" -m venv "{VENV}"', cwd=ROOT)
    if not os.path.exists(PY):
        print(f'\n  ❌ venv reported success but no interpreter was found at:\n     {PY}')
        print('     This usually means antivirus/security software removed files')
        print('     from the venv right after creation, or this Python install is')
        print('     missing ensurepip. Try:')
        print(f'       - deleting the "venv" folder and re-running setup.py')
        print(f'       - temporarily disabling AV real-time protection and retrying')
        print(f'       - running: "{sys.executable}" -m venv --clear "{VENV}"')
        sys.exit(1)
else:
    print('\n📦 Virtual environment already exists — skipping.')

# ── Step 2: Install dependencies ─────────────────────────────
# NOTE: invoke pip via `python -m pip` rather than the separate Scripts\pip.exe
# / bin/pip script. The standalone pip script can end up missing even when
# venv creation exits 0 (seen on Windows when AV software quarantines it, or
# with some locked-down Python builds) — `python -m pip` only needs the venv's
# own python executable, which we've just verified exists above.
print('\n📥 Installing dependencies (this may take a minute)...')
run(f'"{PY}" -m pip install --upgrade pip -q')
run(f'"{PY}" -m pip install -r requirements.txt -q')

# ── Step 3: Create migrations directories for all apps ───────
print('\n📂 Creating migrations directories...')
apps = [
    'accounts','tenants','billing','analytics','reviews','notifications',
    'bookings','inventory','storefront','appointments','menu','hotels',
    'rentals','crm','blog','payments','contact','staff','subscriptions',
    'orders','activity',
]
for app in apps:
    mig_dir = os.path.join(BACKEND, app, 'migrations')
    os.makedirs(mig_dir, exist_ok=True)
    init = os.path.join(mig_dir, '__init__.py')
    if not os.path.exists(init):
        open(init, 'w').close()
print('    ✓ All migrations directories ready.')

# ── Step 4: Create frontend/static if missing ─────────────────
os.makedirs(FRONTEND_STATIC, exist_ok=True)
gitkeep = os.path.join(FRONTEND_STATIC, '.gitkeep')
if not os.path.exists(gitkeep):
    open(gitkeep, 'w').close()

# ── Step 5: Delete stale db so we start clean ─────────────────
db_path = os.path.join(BACKEND, 'db.sqlite3')
if os.path.exists(db_path):
    print('\n🗑️  Removing old database...')
    os.remove(db_path)

# ── Step 6: Make migrations ───────────────────────────────────
print('\n📝 Creating migrations (makemigrations)...')
run(f'"{PY}" manage.py makemigrations --settings={SETTINGS}')

# ── Step 7: Run migrations ────────────────────────────────────
print('\n🗄️  Running database migrations (SQLite)...')
run(f'"{PY}" manage.py migrate --settings={SETTINGS}')

# ── Step 8: Collect static files ──────────────────────────────
print('\n📁 Collecting static files...')
run(f'"{PY}" manage.py collectstatic --noinput --settings={SETTINGS}', exit_on_fail=False)

# ── Step 9: Seed demo data (creates superadmin + 10 tenants) ──
print('\n🌱 Seeding demo data...')
run(f'"{PY}" seed.py')

# ── Done ──────────────────────────────────────────────────────
print()
print('=' * 58)
print('  ✅  Setup complete!')
print('=' * 58)
print()
print('  Start the dev servers:')
if WIN:
    print('    venv\\Scripts\\python dev.py')
else:
    print('    venv/bin/python dev.py')
print()
print('  URLs:')
print('    http://localhost:8000                               (main site)')
print('    http://localhost:8000/admin                        (admin panel)')
print('    http://localhost:8001/?tenant=hertz-albania        (car rental)')
print('    http://localhost:8001/?tenant=restorant-adriatiku  (restaurant)')
print('    http://localhost:8001/?tenant=klinika-shendeti     (clinic)')
print('    http://localhost:8001/?tenant=barber-kings-tirana  (barbershop)')
print('    http://localhost:8001/?tenant=learning-center      (language school)')
print('    http://localhost:8001/?tenant=amos-realestate      (real estate)')
print('    http://localhost:8001/?tenant=adriatic-tours       (travel agency)')
print('    http://localhost:8001/?tenant=ndertim-shpk         (construction - trial)')
print('    http://localhost:8001/?tenant=market-express       (market / retail)')
print('    http://localhost:8001/?tenant=hotel-riviera        (hotel)')
print()
print('  Admin login:  admin@bizal.al  /  <password printed above by seed.py>')
print()
