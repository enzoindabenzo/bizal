#!/usr/bin/env python
"""
BizAL Dev Launcher
  Port 8000 → Main domain  (landing page, admin)
  Port 8001 → Tenant portal (?tenant=<slug>)

Usage: python dev.py   (from bizal/ folder)
"""
import os, sys, subprocess, platform, signal, time, threading

ROOT    = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, 'backend')
VENV    = os.path.join(ROOT, 'venv')
WIN     = platform.system() == 'Windows'
VENV_PY = os.path.join(VENV, 'Scripts' if WIN else 'bin', 'python.exe' if WIN else 'python')

if not os.path.exists(VENV_PY):
    print(f'\n  ❌ Venv not found. Run "python setup.py" first.\n')
    sys.exit(1)

ENV = os.environ.copy()
ENV['DJANGO_SETTINGS_MODULE'] = 'bizal.settings.local'

BLUE  = '\033[94m'
GREEN = '\033[92m'
RESET = '\033[0m'

print()
print('=' * 62)
print('  BizAL Dev Servers')
print('=' * 62)
print(f'  {BLUE}[MAIN  :8000]{RESET}  http://localhost:8000          (landing + admin)')
print(f'  {GREEN}[TENANT:8001]{RESET}  http://localhost:8001/?tenant=<slug>')
print()
print(f'  Demo tenants:')
print(f'  {GREEN}→{RESET}  http://localhost:8001/?tenant=restorant-adriatiku')
print(f'  {GREEN}→{RESET}  http://localhost:8001/?tenant=hertz-albania')
print(f'  {GREEN}→{RESET}  http://localhost:8001/?tenant=klinika-shendeti')
print()
print(f'  Admin: http://localhost:8000/admin  →  admin@bizal.al / admin1234')
print(f'  Ctrl+C to stop both servers.')
print('=' * 62)
print()

procs = []

def run_server(port):
    return subprocess.Popen(
        [VENV_PY, 'manage.py', 'runserver', f'0.0.0.0:{port}', '--noreload'],
        cwd=BACKEND, env=ENV,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )

def stream(proc, label, color):
    def _read():
        for line in iter(proc.stdout.readline, b''):
            print(f'{color}[{label}]{RESET} {line.decode(errors="replace").rstrip()}', flush=True)
    threading.Thread(target=_read, daemon=True).start()

try:
    p8000 = run_server(8000)
    procs.append(p8000)
    time.sleep(0.8)
    p8001 = run_server(8001)
    procs.append(p8001)

    stream(p8000, 'MAIN  :8000', BLUE)
    stream(p8001, 'TENANT:8001', GREEN)

    while all(p.poll() is None for p in procs):
        time.sleep(0.5)

except KeyboardInterrupt:
    print('\n  Stopping servers...')
finally:
    for p in procs:
        try: p.terminate()
        except: pass
    print('  Done.\n')
