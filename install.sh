#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# BizAL v2 — Fresh install script
# Run from the project root (where this file lives)
# ═══════════════════════════════════════════════════════════════
set -e
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo -e "${GREEN}BizAL v2 — Fresh Install${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. Python venv ────────────────────────────────────────────
echo -e "\n${YELLOW}[1/7] Creating Python virtual environment...${NC}"
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo -e "${GREEN}  ✓ Dependencies installed${NC}"

# ── 2. Environment file ───────────────────────────────────────
echo -e "\n${YELLOW}[2/7] Setting up .env...${NC}"
if [ ! -f ../.env ]; then
    cp ../.env.example ../.env
    echo -e "${GREEN}  ✓ .env created from .env.example — fill in your values!${NC}"
else
    echo -e "  .env already exists — skipping"
fi

# ── 3. Database migrations ────────────────────────────────────
echo -e "\n${YELLOW}[3/7] Running migrations...${NC}"
# install.sh runs inside the backend/ dir with the venv active.
# manage.py already defaults to bizal.settings.local (SQLite, no Redis needed),
# so this export is just making it explicit and overridable via the environment.
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-bizal.settings.local}"
python manage.py migrate --no-input
echo -e "${GREEN}  ✓ Database migrated${NC}"

# ── 4. Seed data ──────────────────────────────────────────────
echo -e "\n${YELLOW}[4/7] Seeding demo data...${NC}"
python seed.py
echo -e "${GREEN}  ✓ Seed complete${NC}"

# ── 5. Static files ───────────────────────────────────────────
echo -e "\n${YELLOW}[5/7] Collecting static files...${NC}"
python manage.py collectstatic --no-input -q
echo -e "${GREEN}  ✓ Static files collected${NC}"

# ── 6. Verify tenant features applied ────────────────────────
echo -e "\n${YELLOW}[6/7] Verifying tenant feature application...${NC}"
python manage.py shell -c "
from tenants.models import Tenant, TenantFeature
tenants = Tenant.objects.all()
for t in tenants:
    count = TenantFeature.objects.filter(tenant=t).count()
    print(f'  {t.slug}: {count} feature flags')
"
echo -e "${GREEN}  ✓ Features verified${NC}"

# ── 7. Summary ────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}✅  BizAL v2 ready!${NC}"
echo ""
echo "Start dev servers:"
echo "  python manage.py runserver 8000   ← main domain"
echo "  python manage.py runserver 8001   ← tenant portals"
echo "  celery -A bizal worker -l info    ← task queue"
echo "  celery -A bizal beat -l info      ← scheduled tasks"
echo ""
echo "Demo tenants (visit on port 8001):"
echo "  ?tenant=restorant-adriatiku   restaurant  Pro"
echo "  ?tenant=hertz-albania         car rental  Enterprise  (3 branches)"
echo "  ?tenant=klinika-shendeti      clinic      Pro"
echo "  ?tenant=barber-kings-tirana   barbershop  Starter"
echo "  ?tenant=amos-realestate       real estate Enterprise"
echo "  ?tenant=adriatic-tours        travel      Pro"
echo "  ?tenant=ndertim-shpk          construction Trial (10d)"
echo ""
echo "Admin: http://localhost:8000/django-admin"
echo "  admin@bizal.al / <password printed above — set SEED_ADMIN_PASSWORD in .env to choose your own>"
echo ""
echo "API:"
echo "  GET  /api/tenants/marketplace/         ← public directory"
echo "  GET  /api/tenants/superadmin/trials/   ← trial status (admin)"
echo "  POST /api/tenants/<id>/grant-feature/  ← custom feature grant"
echo "  POST /api/tenants/signup/              ← new tenant signup"
echo "  GET  /api/tenants/referrals/           ← referral dashboard"
