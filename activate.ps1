# BizAL Dev Environment Activator
# =================================
# Usage: .\activate.ps1
# Run from the bizal\ folder.

$ErrorActionPreference = "Stop"

$ROOT     = $PSScriptRoot
$VENV     = Join-Path $ROOT "venv"
$ACTIVATE = Join-Path $VENV "Scripts\Activate.ps1"
$PYTHON   = Join-Path $VENV "Scripts\python.exe"
$BACKEND  = Join-Path $ROOT "backend"
$SETTINGS = "bizal.settings.local"

# ── Check venv exists ────────────────────────────────────────
if (-not (Test-Path $PYTHON)) {
    Write-Host ""
    Write-Host "  ❌ Virtual environment not found." -ForegroundColor Red
    Write-Host "  Run setup first:" -ForegroundColor Yellow
    Write-Host "    python setup.py" -ForegroundColor Cyan
    Write-Host ""
    exit 1
}

# ── Activate the venv ────────────────────────────────────────
& $ACTIVATE

# ── Set environment variable so manage.py always uses local settings ──
$env:DJANGO_SETTINGS_MODULE = $SETTINGS

# ── Helper functions available after activation ───────────────

function bizal-start {
    <#
    .SYNOPSIS
        Start the dev server on port 8000.
    #>
    Write-Host ""
    Write-Host "  Starting BizAL dev server on http://localhost:8000" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Main site:  http://localhost:8000" -ForegroundColor Blue
    Write-Host "  Admin:      http://localhost:8000/admin" -ForegroundColor Blue
    Write-Host "  Tenant SPA: http://hertz-albania.localhost:8000" -ForegroundColor Green
    Write-Host "  Or use:     http://localhost:8000/?tenant=hertz-albania" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Press Ctrl+C to stop." -ForegroundColor Gray
    Write-Host ""
    & $PYTHON (Join-Path $ROOT "dev.py")
}

function bizal-shell {
    <#
    .SYNOPSIS
        Open Django interactive shell.
    #>
    Set-Location $BACKEND
    & $PYTHON manage.py shell
}

function bizal-migrate {
    <#
    .SYNOPSIS
        Run makemigrations + migrate.
    #>
    Set-Location $BACKEND
    & $PYTHON manage.py makemigrations
    & $PYTHON manage.py migrate
}

function bizal-seed {
    <#
    .SYNOPSIS
        Re-run the seed script (demo tenants + superadmin).
    #>
    Set-Location $BACKEND
    & $PYTHON seed.py
}

function bizal-test {
    <#
    .SYNOPSIS
        Run the full test suite.
    #>
    param(
        [string]$App = ""
    )
    Set-Location $BACKEND
    if ($App) {
        & $PYTHON manage.py test $App --settings=bizal.settings.test
    } else {
        & $PYTHON manage.py test --settings=bizal.settings.test
    }
}

function bizal-coverage {
    <#
    .SYNOPSIS
        Run tests with coverage report.
    #>
    Set-Location $BACKEND
    & $PYTHON -m coverage run --rcfile=.coveragerc manage.py test --settings=bizal.settings.test
    & $PYTHON -m coverage report --rcfile=.coveragerc --show-missing
}

function bizal-main {
    <#
    .SYNOPSIS
        Start only the main domain server on port 8000.
    #>
    Write-Host ""
    Write-Host "  Starting main domain server on http://localhost:8000" -ForegroundColor Blue
    Write-Host "  Press Ctrl+C to stop." -ForegroundColor Gray
    Write-Host ""
    Set-Location $BACKEND
    & $PYTHON manage.py runserver 0.0.0.0:8000
}

function bizal-tenant {
    <#
    .SYNOPSIS
        Start only the tenant portal server on port 8001.
    #>
    Write-Host ""
    Write-Host "  Starting tenant portal server on http://localhost:8001" -ForegroundColor Green
    Write-Host "  Use: http://localhost:8001/?tenant=hertz-albania" -ForegroundColor Green
    Write-Host "  Press Ctrl+C to stop." -ForegroundColor Gray
    Write-Host ""
    Set-Location $BACKEND
    & $PYTHON manage.py runserver 0.0.0.0:8001
}

function bizal-urls {
    <#
    .SYNOPSIS
        Print all registered URL patterns.
    #>
    Set-Location $BACKEND
    & $PYTHON manage.py show_urls 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  Tip: pip install django-extensions to enable 'show_urls'" -ForegroundColor Yellow
        & $PYTHON manage.py shell -c "
from django.urls import get_resolver
def print_urls(resolver, prefix=''):
    for pattern in resolver.url_patterns:
        if hasattr(pattern, 'url_patterns'):
            print_urls(pattern, prefix + str(pattern.pattern))
        else:
            print(prefix + str(pattern.pattern))
print_urls(get_resolver())
"
    }
}

function bizal-superuser {
    <#
    .SYNOPSIS
        Create a new superuser interactively.
    #>
    Set-Location $BACKEND
    & $PYTHON manage.py createsuperuser
}

function bizal-collectstatic {
    <#
    .SYNOPSIS
        Collect static files (needed before running with whitenoise in prod).
    #>
    Set-Location $BACKEND
    & $PYTHON manage.py collectstatic --noinput
}

function bizal-help {
    Write-Host ""
    Write-Host "  BizAL Dev Commands" -ForegroundColor Cyan
    Write-Host "  ==================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  bizal-start        " -NoNewline -ForegroundColor Yellow
    Write-Host "Start both servers (port 8000 + 8001)"
    Write-Host "  bizal-main         " -NoNewline -ForegroundColor Yellow
    Write-Host "Start only port 8000 (main domain)"
    Write-Host "  bizal-tenant       " -NoNewline -ForegroundColor Yellow
    Write-Host "Start only port 8001 (tenant portal)"
    Write-Host "  bizal-shell        " -NoNewline -ForegroundColor Yellow
    Write-Host "Django interactive shell"
    Write-Host "  bizal-migrate      " -NoNewline -ForegroundColor Yellow
    Write-Host "makemigrations + migrate"
    Write-Host "  bizal-seed         " -NoNewline -ForegroundColor Yellow
    Write-Host "Re-seed demo data"
    Write-Host "  bizal-test         " -NoNewline -ForegroundColor Yellow
    Write-Host "Run test suite  (bizal-test accounts)"
    Write-Host "  bizal-coverage     " -NoNewline -ForegroundColor Yellow
    Write-Host "Run tests with coverage report"
    Write-Host "  bizal-urls         " -NoNewline -ForegroundColor Yellow
    Write-Host "List all API URL routes"
    Write-Host "  bizal-superuser    " -NoNewline -ForegroundColor Yellow
    Write-Host "Create a new superuser"
    Write-Host "  bizal-collectstatic" -NoNewline -ForegroundColor Yellow
    Write-Host "Collect static files"
    Write-Host "  bizal-help         " -NoNewline -ForegroundColor Yellow
    Write-Host "Show this help"
    Write-Host ""
    Write-Host "  URLs:" -ForegroundColor Gray
    Write-Host "  http://localhost:8000                     (main site)" -ForegroundColor Gray
    Write-Host "  http://localhost:8000/admin               (admin panel)" -ForegroundColor Gray
    Write-Host "  http://hertz-albania.localhost:8001       (car rental, subdomain)" -ForegroundColor Gray
    Write-Host "  http://localhost:8001/?tenant=hertz-albania (via param)" -ForegroundColor Gray
    Write-Host "  Admin: admin@bizal.al / admin1234" -ForegroundColor Gray
    Write-Host ""
}

# ── Banner ────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ██████╗ ██╗███████╗ █████╗ ██╗" -ForegroundColor Cyan
Write-Host "  ██╔══██╗██║╚══███╔╝██╔══██╗██║" -ForegroundColor Cyan
Write-Host "  ██████╔╝██║  ███╔╝ ███████║██║" -ForegroundColor Cyan
Write-Host "  ██╔══██╗██║ ███╔╝  ██╔══██║██║" -ForegroundColor Cyan
Write-Host "  ██████╔╝██║███████╗██║  ██║███████╗" -ForegroundColor Cyan
Write-Host "  ╚═════╝ ╚═╝╚══════╝╚═╝  ╚═╝╚══════╝" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Dev environment activated " -NoNewline -ForegroundColor Green
Write-Host "✓" -ForegroundColor Green
Write-Host "  Python: $PYTHON" -ForegroundColor Gray
Write-Host "  Settings: $SETTINGS" -ForegroundColor Gray
Write-Host ""
Write-Host "  Type " -NoNewline
Write-Host "bizal-start" -NoNewline -ForegroundColor Yellow
Write-Host " to launch the servers, or "
Write-Host "  Type " -NoNewline
Write-Host "bizal-help" -NoNewline -ForegroundColor Yellow
Write-Host " to see all commands."
Write-Host ""
