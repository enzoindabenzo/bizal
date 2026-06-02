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
PY = os.path.join(VENV, 'Scripts' if WIN else 'bin', 'python')
PIP = os.path.join(VENV, 'Scripts' if WIN else 'bin', 'pip')

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
else:
    print('\n📦 Virtual environment already exists — skipping.')

# ── Step 2: Install dependencies ─────────────────────────────
print('\n📥 Installing dependencies (this may take a minute)...')
run(f'"{PIP}" install -r requirements.txt -q')

# ── Step 3: Create migrations directories for all apps ───────
print('\n📂 Creating migrations directories...')
apps = [
    'accounts','tenants','billing','analytics','reviews','notifications',
    'bookings','inventory','storefront','appointments','menu','hotels',
    'rentals','crm','blog','payments','contact','staff','subscriptions',
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

# ── Step 9: Seed demo data (creates superadmin + 3 tenants) ───
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
print()
print('  Admin login:  admin@bizal.al  /  admin1234')
print()
