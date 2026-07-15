"""
BizAL Demo Seed Script — Fixed & Expanded
Run inside Docker: docker compose -f docker-compose.prod.yml exec web python seed.py

Fixes applied vs previous version:
  - BlogTag.get_or_create includes tenant in lookup (unique_together = tenant+slug)
  - Lead source 'instagram' corrected to 'social' (valid choice)
  - StorefrontPage order field added
  - TenantLocation latitude/longitude populated with real Albanian coordinates
  - Tenant latitude/longitude populated for map display
  - learning-center tenant added (language_school, created via onboarding)
  - StaffMember get_or_create uses correct lookup fields
  - Full_name spacing fix (EndritRama → Endrit Rama)
  - market-express tenant added (market/retail, Starter) — products span
    normal, low, and zero stock to exercise inventory storefront states
  - hotel-riviera tenant added (hotel, Enterprise) — RoomTypes/Rooms span
    available/occupied/maintenance statuses plus seasonal pricing, for
    room-booking testing
"""
import os
import django
import secrets
from pathlib import Path

# Load .env from the project root (works on Windows where shell doesn't auto-load it)
_root = Path(__file__).resolve().parent.parent  # backend/ -> bizal/
_env_file = _root / '.env'
if _env_file.exists():
    for _line in _env_file.read_text(encoding='utf-8').splitlines():
        _line = _line.strip()
        if _line and not _line.startswith('#') and '=' in _line:
            _k, _, _v = _line.partition('=')
            os.environ.setdefault(_k.strip(), _v.strip())

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bizal.settings.local')
django.setup()

def _seed_password(env_key, label, default):
    pw = os.environ.get(env_key)
    if not pw:
        # NOTE: previously this fell back to secrets.token_urlsafe(16), which
        # generated a *new* random password on every single run of this
        # script. Since the password is unconditionally re-applied to the
        # existing seeded users (set_password()+save() runs even when
        # get_or_create() found an existing row), re-running the seed for any
        # reason silently invalidated whatever password you'd noted down
        # from the previous run — e.g. "owner@adriatiku.al / <random>" stops
        # working the moment seed.py runs again. Use a fixed, documented demo
        # password instead so credentials stay valid across re-seeds. Set
        # SEED_*_PASSWORD env vars to override this for anything beyond local
        # demo use.
        pw = default
        print(f"  [seed] {label} password not set in env — using fixed demo password: {pw}")
    return pw

ADMIN_PASSWORD    = _seed_password('SEED_ADMIN_PASSWORD',    'admin',    'Admin123*')
CUSTOMER_PASSWORD = _seed_password('SEED_CUSTOMER_PASSWORD', 'customer', 'User123*')

# Distinct per-owner demo password instead of one password shared across all
# 8 tenant owners — a shared credential meant compromising/leaking any single
# owner login effectively compromised every tenant's admin panel. Each owner
# gets its own fixed, documented demo password; SEED_OWNER_PASSWORD still
# works as a blanket override for everyone if you specifically want that.
_owner_pw_override = os.environ.get('SEED_OWNER_PASSWORD')

def _owner_password(tenant_label, default):
    if _owner_pw_override:
        return _owner_pw_override
    print(f"  [seed] owner password for {tenant_label} not set in env — using fixed demo password: {default}")
    return default

OWNER_PASSWORD_RESTO    = _owner_password('restorant-adriatiku', 'Owner2026!')
OWNER_PASSWORD_CARS     = _owner_password('hertz-albania',       'Owner2026!')
OWNER_PASSWORD_CLINIC   = _owner_password('klinika-shendeti',    'Owner2026!')
OWNER_PASSWORD_BARBER   = _owner_password('barber-kings-tirana', 'Owner2026!')
OWNER_PASSWORD_LANGSC   = _owner_password('learning-center',     'Owner2026!')
OWNER_PASSWORD_REALEST  = _owner_password('amos-realestate',     'Owner2026!')
OWNER_PASSWORD_TRAVEL   = _owner_password('adriatic-tours',      'Owner2026!')
OWNER_PASSWORD_CONSTR   = _owner_password('ndertim-shpk',        'Owner2026!')
OWNER_PASSWORD_MARKET   = _owner_password('market-express',      'Owner2026!')
OWNER_PASSWORD_HOTEL    = _owner_password('hotel-riviera',       'Owner2026!')

from tenants.models import Tenant, TenantLocation, TenantReferral, PLAN_PRO, PLAN_ENTERPRISE, PLAN_STARTER, PLAN_TRIAL
from accounts.models import User
from reviews.models import Review
from blog.models import BlogPost, BlogTag
from menu.models import MenuCategory, MenuItem
from inventory.models import ProductCategory, Product
from hotels.models import RoomType, Room, SeasonalPrice
from rentals.models import RentalItem
from appointments.models import ServiceProvider, Service
from staff.models import StaffMember, StaffSchedule
from storefront.models import HeroSlide, StorefrontPage
from crm.models import Lead
from billing.models import Invoice, InvoiceLine
from subscriptions.models import CustomerSubscription
from django.utils import timezone
import datetime as _dt

print("🌱 Seeding BizAL demo data...")

# ── Superadmin ───────────────────────────────────────────────────────────────
superadmin, _ = User.objects.get_or_create(
    email='admin@bizal.al',
    defaults={
        'full_name': 'BizAL Admin',
        'is_staff': True,
        'is_superuser': True,
        'role': 'superadmin',
        'is_active': True,
    }
)
superadmin.set_password(ADMIN_PASSWORD)
superadmin.save()
print("  ✓ Superadmin: admin@bizal.al / <SEED_ADMIN_PASSWORD>")


# ════════════════════════════════════════════════════════════════════════════
# TENANT 1 — Restaurant  (Vlorë seafront)
# Coords: Rruga e Detit, Vlorë  40.4486° N, 19.4897° E
# ════════════════════════════════════════════════════════════════════════════
resto, _ = Tenant.objects.update_or_create(
    slug='restorant-adriatiku',
    defaults={
        'name': 'Restorant Adriatiku',
        'tagline': 'Peshk i freskët, atmosferë unike — buzë detit të Adriatikut',
        'business_type': 'restaurant',
        'phone': '+355 33 123 456',
        'whatsapp': '+355691234567',
        'email': 'info@adriatiku.al',
        'address': 'Rruga e Detit 12, Vlorë',
        'city': 'Vlorë',
        'country': 'Albania',
        'latitude': 40.448600,
        'longitude': 19.489700,
        'site_title': 'Adriatiku — Shija e Detit',
        'story': (
            'Restorant Adriatiku u hap në vitin 2015 nga familja Hoxha, me një '
            'pasion të thellë për kuzhinën e detit. Çdo ditë fishermen-ët tanë '
            'lokalë sjellin peshkun e freskët direkt në kuzhinë. Mjedisi ynë '
            'romantik buzë detit të Adriatikut krijon përvojë të paharrueshme '
            'për çiftet dhe familjet. Misioni ynë: autenticitet, cilësi dhe '
            'mikpritje shqiptare.'
        ),
        'founded_year': 2015,
        'meta_description': (
            'Restorant Adriatiku — peshk i freskët dhe fruta deti buzë detit '
            'në Vlorë. Rezervoni tavolinën tuaj sot!'
        ),
        'facebook': 'https://facebook.com/restorantadriatiku',
        'instagram': 'https://instagram.com/adriatiku.vlore',
        'tiktok': 'https://tiktok.com/@adriatiku.al',
        'website': 'https://www.adriatiku.al',
        'primary_color': '#0EA5E9',
        'accent_color': '#F97316',
        'font_family': 'Poppins',
        'onboarding_step': 6,
        'onboarding_complete': True,
        'plan': PLAN_PRO,
        'is_active': True,
        'listed_on_marketplace': True,
        'marketplace_description': 'Restorant peshku dhe frutash deti buzë detit Adriatik, Vlorë.',
        'business_hours': {
            'E Hënë - E Premte': '11:00 - 23:00',
            'E Shtunë - E Diel': '10:00 - 00:00',
        },
    }
)

owner1, _ = User.objects.get_or_create(
    email='owner@adriatiku.al',
    defaults={
        'full_name': 'Arben Hoxha',
        'tenant': resto,
        'role': 'owner',
        'is_active': True,
    }
)
owner1.set_password(OWNER_PASSWORD_RESTO)
owner1.save()
print("  ✓ Tenant: restorant-adriatiku | owner@adriatiku.al")

cat1, _ = MenuCategory.objects.get_or_create(tenant=resto, name='Peshk & Fruta Deti', defaults={'order': 1})
cat2, _ = MenuCategory.objects.get_or_create(tenant=resto, name='Meze', defaults={'order': 2})
cat3, _ = MenuCategory.objects.get_or_create(tenant=resto, name='Pije', defaults={'order': 3})

MenuItem.objects.get_or_create(tenant=resto, category=cat1, name='Levrek i Pjekur', defaults={
    'price': 1800, 'description': 'Me perime të stinës dhe salcë limoni', 'is_available': True})
MenuItem.objects.get_or_create(tenant=resto, category=cat1, name='Karkalec me Hudhër', defaults={
    'price': 1500, 'description': 'Karkalec i detit me salcë hudhre dhe majdanoz', 'is_available': True})
MenuItem.objects.get_or_create(tenant=resto, category=cat1, name='Pjatë Deti e Miksuar', defaults={
    'price': 2400, 'description': 'Oktapod, kallamar, karkalec, levrek — për dy persona', 'is_available': True})
MenuItem.objects.get_or_create(tenant=resto, category=cat2, name='Pjatë Mezesh', defaults={
    'price': 800, 'description': 'Djathë, ulliri, domate të thata, bukë tradicionale', 'is_available': True})
MenuItem.objects.get_or_create(tenant=resto, category=cat2, name='Sallatë Greke', defaults={
    'price': 600, 'description': 'Domate, kastravec, ullinj, djathë feta', 'is_available': True})
MenuItem.objects.get_or_create(tenant=resto, category=cat3, name='Raki Rrushi', defaults={
    'price': 250, 'description': 'Prodhim vendor, 100ml', 'is_available': True})
MenuItem.objects.get_or_create(tenant=resto, category=cat3, name='Ujë Mineral', defaults={
    'price': 150, 'description': '500ml', 'is_available': True})


# ════════════════════════════════════════════════════════════════════════════
# TENANT 2 — Car Rental  (Tirana city centre)
# Coords: Rruga Kavajës, Tiranë  41.3305° N, 19.8233° E
# ════════════════════════════════════════════════════════════════════════════
cars, _ = Tenant.objects.update_or_create(
    slug='hertz-albania',
    defaults={
        'name': 'Hertz Albania',
        'tagline': 'Flota më e madhe, çmimet më të mira në Shqipëri',
        'business_type': 'car_rental',
        'phone': '+355 4 234 5678',
        'whatsapp': '+355697654321',
        'email': 'info@hertz.al',
        'address': 'Rruga Kavajës 45, Tiranë',
        'city': 'Tiranë',
        'country': 'Albania',
        'latitude': 41.330500,
        'longitude': 19.823300,
        'site_title': 'Hertz — Makina me Qira Tirana',
        'story': (
            'Hertz Albania operon që nga viti 2010, duke ofruar një nga flotët '
            'më moderne dhe të larmishme të automjeteve në Shqipëri. Me mbi '
            '150 automjete — nga ekonomiket deri tek SUV-et luksoze — jemi '
            'partneri ideal për udhëtime biznesi, pushime familjare dhe '
            'transferta aeroportuale. Zyrat tona janë në Tiranë, Durrës dhe '
            'Aeroportin e Rinasit.'
        ),
        'founded_year': 2010,
        'meta_description': (
            'Hertz Albania — makinë me qira në Tiranë. Flota moderne, çmime '
            'konkurruese, mbyllje 7 ditë në javë. Rezervoni online!'
        ),
        'facebook': 'https://facebook.com/hertzalbania',
        'instagram': 'https://instagram.com/hertz.albania',
        'tiktok': '',
        'website': 'https://www.hertz.al',
        'primary_color': '#FFD400',
        'accent_color': '#1A1A1A',
        'font_family': 'Montserrat',
        'onboarding_step': 6,
        'onboarding_complete': True,
        'plan': PLAN_ENTERPRISE,
        'is_active': True,
        'listed_on_marketplace': True,
        'marketplace_description': 'Flota me 150+ automjete. Makina me qira në Tiranë, Durrës dhe Rinas.',
        'business_hours': {'E Hënë - E Diel': '08:00 - 20:00'},
    }
)

owner2, _ = User.objects.get_or_create(
    email='owner@hertz.al',
    defaults={
        'full_name': 'Gent Berisha',
        'tenant': cars,
        'role': 'owner',
        'is_active': True,
    }
)
owner2.set_password(OWNER_PASSWORD_CARS)
owner2.save()
print("  ✓ Tenant: hertz-albania | owner@hertz.al")

RentalItem.objects.get_or_create(tenant=cars, name='Toyota Corolla 2023', defaults={
    'rental_type': 'car', 'price_per_day': 5000, 'city': 'Tiranë', 'status': 'available',
    'specs': {'seats': 5, 'fuel': 'Benzinë', 'transmission': 'Automatike', 'ac': True}})
RentalItem.objects.get_or_create(tenant=cars, name='BMW 320i 2022', defaults={
    'rental_type': 'car', 'price_per_day': 8500, 'city': 'Tiranë', 'status': 'available',
    'specs': {'seats': 5, 'fuel': 'Benzinë', 'transmission': 'Automatike', 'ac': True}})
RentalItem.objects.get_or_create(tenant=cars, name='Furgon Mercedes Sprinter', defaults={
    'rental_type': 'car', 'price_per_day': 9500, 'city': 'Tiranë', 'status': 'available',
    'specs': {'seats': 9, 'fuel': 'Diesel', 'transmission': 'Manuale', 'ac': True}})
RentalItem.objects.get_or_create(tenant=cars, name='Volkswagen Polo 2023', defaults={
    'rental_type': 'car', 'price_per_day': 3800, 'city': 'Tiranë', 'status': 'available',
    'specs': {'seats': 5, 'fuel': 'Benzinë', 'transmission': 'Manuale', 'ac': True}})
RentalItem.objects.get_or_create(tenant=cars, name='Hyundai Tucson 2022', defaults={
    'rental_type': 'car', 'price_per_day': 7200, 'city': 'Durrës', 'status': 'available',
    'specs': {'seats': 5, 'fuel': 'Diesel', 'transmission': 'Automatike', 'ac': True}})


# ════════════════════════════════════════════════════════════════════════════
# TENANT 3 — Clinic  (Tirana, Rruga Durrësit)
# Coords: Rruga Durrësit, Tiranë  41.3317° N, 19.8350° E
# ════════════════════════════════════════════════════════════════════════════
clinic, _ = Tenant.objects.update_or_create(
    slug='klinika-shendeti',
    defaults={
        'name': 'Klinika Shëndeti',
        'tagline': 'Shëndeti juaj — prioriteti ynë',
        'business_type': 'clinic',
        'phone': '+355 4 111 2233',
        'whatsapp': '',
        'email': 'info@klinikashendeti.al',
        'address': 'Rruga Durrësit 78, Tiranë',
        'city': 'Tiranë',
        'country': 'Albania',
        'latitude': 41.331700,
        'longitude': 19.835000,
        'site_title': 'Klinika Shëndeti — Mjekësi Moderne',
        'story': (
            'Klinika Shëndeti u themelua në vitin 2018 nga Dr. Elda Prifti me '
            'vizionin për t\'u sjellë shqiptarëve kujdes shëndetësor cilësor '
            'me standarde europiane. Ekipi ynë prej 8 mjekësh specialistë '
            'trajton mbi 60 pacientë në ditë. Disponojmë laborator të brendshëm, '
            'ultrazë, EKG dhe kabinete specialitetesh. Ofrujmë edhe vizita '
            'online për konsultimet e para.'
        ),
        'founded_year': 2018,
        'meta_description': (
            'Klinika Shëndeti Tiranë — mjekësi e përgjithshme, kardiologji, '
            'pediatri dhe më shumë. Caktoni takimin tuaj online.'
        ),
        'facebook': 'https://facebook.com/klinikashendeti',
        'instagram': 'https://instagram.com/klinika.shendeti',
        'tiktok': 'https://tiktok.com/@klinikashendeti',
        'website': '',
        'primary_color': '#059669',
        'accent_color': '#0EA5E9',
        'font_family': 'Inter',
        'onboarding_step': 6,
        'onboarding_complete': True,
        'plan': PLAN_PRO,
        'is_active': True,
        'listed_on_marketplace': True,
        'marketplace_description': 'Klinikë moderne me 8 specialistë. Caktoni takim online.',
        'business_hours': {
            'E Hënë - E Premte': '08:00 - 18:00',
            'E Shtunë': '09:00 - 14:00',
        },
    }
)

owner3, _ = User.objects.get_or_create(
    email='owner@klinikashendeti.al',
    defaults={
        'full_name': 'Dr. Elda Prifti',
        'tenant': clinic,
        'role': 'owner',
        'is_active': True,
    }
)
owner3.set_password(OWNER_PASSWORD_CLINIC)
owner3.save()
print("  ✓ Tenant: klinika-shendeti | owner@klinikashendeti.al")

prov1, _ = ServiceProvider.objects.get_or_create(tenant=clinic, name='Dr. Elda Prifti', defaults={
    'title': 'Dr.', 'specialties': 'Mjekësi e Përgjithshme, Pediatri'})
prov2, _ = ServiceProvider.objects.get_or_create(tenant=clinic, name='Dr. Alban Koci', defaults={
    'title': 'Dr.', 'specialties': 'Kardiologji'})
prov3, _ = ServiceProvider.objects.get_or_create(tenant=clinic, name='Dr. Mirela Daci', defaults={
    'title': 'Dr.', 'specialties': 'Gjinekologji'})

Service.objects.get_or_create(tenant=clinic, name='Vizitë e Përgjithshme', defaults={
    'price': 2500, 'duration_minutes': 30})
Service.objects.get_or_create(tenant=clinic, name='Elektrokardiogram (EKG)', defaults={
    'price': 3500, 'duration_minutes': 45})
Service.objects.get_or_create(tenant=clinic, name='Vizitë Pediatrike', defaults={
    'price': 2000, 'duration_minutes': 30})
Service.objects.get_or_create(tenant=clinic, name='Konsultim Kardiologjik', defaults={
    'price': 4500, 'duration_minutes': 60})


# ════════════════════════════════════════════════════════════════════════════
# TENANT 4 — Barbershop  (Tirana Blloku)
# Coords: Rruga Ismail Qemali, Bllok, Tiranë  41.3229° N, 19.8175° E
# ════════════════════════════════════════════════════════════════════════════
barber, _ = Tenant.objects.update_or_create(
    slug='barber-kings-tirana',
    defaults={
        'name': 'Barber Kings Tirana',
        'tagline': 'Prerje moderne, stil unik — për meshkujt e vërtetë',
        'business_type': 'barbershop',
        'phone': '+355 69 888 7766',
        'whatsapp': '+355698887766',
        'email': 'hello@barberkings.al',
        'address': 'Rruga Ismail Qemali 32, Blloku, Tiranë',
        'city': 'Tiranë',
        'country': 'Albania',
        'latitude': 41.322900,
        'longitude': 19.817500,
        'site_title': 'Barber Kings — Berber i Besuar i Tiranës',
        'story': (
            'Barber Kings hapi dyert e saj në zemër të Bllokut në vitin 2020. '
            'Dy berber me eksperiencë nga Milano dhe Londra ofrojnë prerje, '
            'rregullim mjekre dhe trajtime premium për flokët. Ambientet '
            'moderne dhe muzika e mirë e bëjnë çdo vizitë një përvojë të '
            'veçantë. Walk-in welcome — ose rezervo online në 60 sekonda.'
        ),
        'founded_year': 2020,
        'meta_description': (
            'Barber Kings Tirana — berber modern në Bllok. Prerje, mjekër, '
            'trajtime premium. Rezervo online!'
        ),
        'facebook': 'https://facebook.com/barberkingstirana',
        'instagram': 'https://instagram.com/barber.kings.tirana',
        'tiktok': 'https://tiktok.com/@barberkingstirana',
        'website': '',
        'primary_color': '#18181B',
        'accent_color': '#D4AF37',
        'font_family': 'Montserrat',
        'onboarding_step': 6,
        'onboarding_complete': True,
        'plan': PLAN_STARTER,
        'is_active': True,
        'business_hours': {
            'E Hënë - E Shtunë': '09:00 - 20:00',
            'E Diel': '10:00 - 16:00',
        },
    }
)

owner4, _ = User.objects.get_or_create(
    email='owner@barberkings.al',
    defaults={
        'full_name': 'Endrit Rama',
        'tenant': barber,
        'role': 'owner',
        'is_active': True,
    }
)
owner4.set_password(OWNER_PASSWORD_BARBER)
owner4.save()
print("  ✓ Tenant: barber-kings-tirana | owner@barberkings.al")

prov_b1, _ = ServiceProvider.objects.get_or_create(tenant=barber, name='Endrit Rama', defaults={
    'title': '', 'specialties': 'Prerje klasike, Fade, Mjekër'})
prov_b2, _ = ServiceProvider.objects.get_or_create(tenant=barber, name='Aldo Gjoka', defaults={
    'title': '', 'specialties': 'Prerje moderne, Skin fade, Trajtime koke'})

Service.objects.get_or_create(tenant=barber, name='Prerje Flokësh', defaults={
    'price': 1200, 'duration_minutes': 30})
Service.objects.get_or_create(tenant=barber, name='Rregullim Mjekre', defaults={
    'price': 800, 'duration_minutes': 20})
Service.objects.get_or_create(tenant=barber, name='Prerje + Mjekër', defaults={
    'price': 1800, 'duration_minutes': 45})
Service.objects.get_or_create(tenant=barber, name='Trajtim Koke (Hair Treatment)', defaults={
    'price': 2500, 'duration_minutes': 60})


# ════════════════════════════════════════════════════════════════════════════
# TENANT 5 — Language School  (Tirana, Rruga e Elbasanit)
# Coords: Rruga e Elbasanit, Tiranë  41.3260° N, 19.8290° E
# ════════════════════════════════════════════════════════════════════════════
langschool, _ = Tenant.objects.update_or_create(
    slug='learning-center',
    defaults={
        'name': 'Learning Center',
        'tagline': 'Mëso gjuhë të huaja — hap dyert e botës',
        'business_type': 'language_school',
        'phone': '+355 4 300 4455',
        'whatsapp': '+355693004455',
        'email': 'info@learningcenter.al',
        'address': 'Rruga e Elbasanit 54, Tiranë',
        'city': 'Tiranë',
        'country': 'Albania',
        'latitude': 41.326000,
        'longitude': 19.829000,
        'site_title': 'Learning Center — Shkollë Gjuhësh Tiranë',
        'story': (
            'Learning Center u hap në vitin 2019 me misionin për t\'u ofruar '
            'shqiptarëve mësimdhënie moderne të gjuhëve të huaja. Ofrojmë '
            'kurse anglisht, italisht, gjermanisht, frëngjisht dhe spanjisht '
            'në nivele A1–C2. Mësuesit tanë janë certifikuar në Cambridge, '
            'Goethe-Institut dhe Institut Français. Klasa të vogla (max 8 '
            'studentë), orare fleksibël dhe mësime online.'
        ),
        'founded_year': 2019,
        'meta_description': (
            'Learning Center Tiranë — kurse gjuhësh të huaja. Anglisht, '
            'italisht, gjermanisht, frëngjisht. Regjistrohu sot!'
        ),
        'facebook': 'https://facebook.com/learningcenter.al',
        'instagram': 'https://instagram.com/learningcenter.tirana',
        'tiktok': 'https://tiktok.com/@learningcenter.al',
        'website': '',
        'primary_color': '#6366F1',
        'accent_color': '#F59E0B',
        'font_family': 'Nunito',
        'onboarding_step': 6,
        'onboarding_complete': True,
        'plan': PLAN_PRO,
        'is_active': True,
        'listed_on_marketplace': True,
        'marketplace_description': 'Kurse gjuhësh të huaja A1–C2. Anglisht, italisht, gjermanisht, frëngjisht.',
        'business_hours': {
            'E Hënë - E Premte': '09:00 - 20:00',
            'E Shtunë': '10:00 - 15:00',
        },
    }
)

owner_lc, _ = User.objects.get_or_create(
    email='owner@learningcenter.al',
    defaults={
        'full_name': 'Mirela Gjoka',
        'tenant': langschool,
        'role': 'owner',
        'is_active': True,
    }
)
owner_lc.set_password(OWNER_PASSWORD_LANGSC)
owner_lc.save()
print("  ✓ Tenant: learning-center | owner@learningcenter.al")

prov_lc1, _ = ServiceProvider.objects.get_or_create(tenant=langschool, name='Prof. Sara Kelmendi', defaults={
    'title': 'Prof.', 'specialties': 'Anglisht, Frëngjisht (Cambridge CELTA)'})
prov_lc2, _ = ServiceProvider.objects.get_or_create(tenant=langschool, name='Prof. Marco Rossi', defaults={
    'title': 'Prof.', 'specialties': 'Italisht (madrelingua, DITALS)'})
prov_lc3, _ = ServiceProvider.objects.get_or_create(tenant=langschool, name='Prof. Klaus Weber', defaults={
    'title': 'Prof.', 'specialties': 'Gjermanisht (Goethe-Institut C2)'})

Service.objects.get_or_create(tenant=langschool, name='Kurs Anglisht — Bazë (A1-A2)', defaults={
    'price': 8000, 'duration_minutes': 90})
Service.objects.get_or_create(tenant=langschool, name='Kurs Anglisht — Mesëm (B1-B2)', defaults={
    'price': 9000, 'duration_minutes': 90})
Service.objects.get_or_create(tenant=langschool, name='Kurs Italisht', defaults={
    'price': 8500, 'duration_minutes': 90})
Service.objects.get_or_create(tenant=langschool, name='Kurs Gjermanisht', defaults={
    'price': 9500, 'duration_minutes': 90})
Service.objects.get_or_create(tenant=langschool, name='Kurs Frëngjisht', defaults={
    'price': 8500, 'duration_minutes': 90})
Service.objects.get_or_create(tenant=langschool, name='Mësim Privat (1 orë)', defaults={
    'price': 2500, 'duration_minutes': 60})


# ════════════════════════════════════════════════════════════════════════════
# TENANT 6 — Real Estate  (Tirana, Rruga Abdyl Frashëri)
# Coords: Rruga Abdyl Frashëri, Tiranë  41.3275° N, 19.8220° E
# ════════════════════════════════════════════════════════════════════════════
realestate, _ = Tenant.objects.update_or_create(
    slug='amos-realestate',
    defaults={
        'name': 'Amos Real Estate',
        'tagline': 'Prona juaj e ëndrrave — e gjejmë ne',
        'business_type': 'real_estate',
        'phone': '+355 4 555 7788',
        'whatsapp': '+355695557788',
        'email': 'info@amos.al',
        'address': 'Rruga Abdyl Frashëri 22, Tiranë',
        'city': 'Tiranë',
        'country': 'Albania',
        'latitude': 41.327500,
        'longitude': 19.822000,
        'site_title': 'Amos Real Estate — Shitje & Qira Pronash',
        'story': (
            'Amos Real Estate operon nga 2012 me mbi 500 prona të shitura. '
            'Specializohemi në apartamente, vila, lokale biznesi dhe tokë '
            'ndërtimore në Tiranë, Durrës dhe Rivierën Shqiptare. '
            'Ekipi ynë prej 12 agjentësh ofron vlerësim falas dhe '
            'shoqërim deri në nënshkrimin e kontratës.'
        ),
        'founded_year': 2012,
        'meta_description': 'Amos Real Estate — shitje, blerje dhe qira pronash në Shqipëri. Konsultim falas.',
        'facebook': 'https://facebook.com/amosrealestate',
        'instagram': 'https://instagram.com/amos.realestate',
        'primary_color': '#1E3A5F',
        'accent_color': '#C9A84C',
        'font_family': 'Playfair Display',
        'onboarding_step': 6,
        'onboarding_complete': True,
        'plan': PLAN_ENTERPRISE,
        'is_active': True,
        'listed_on_marketplace': True,
        'marketplace_description': 'Agjensi imobiliare me mbi 10 vjet përvojë. Specializuar në prona premium.',
        'business_hours': {'E Hënë - E Premte': '09:00 - 18:00', 'E Shtunë': '10:00 - 14:00'},
    }
)
owner_re, _ = User.objects.get_or_create(
    email='owner@amos.al',
    defaults={'full_name': 'Amos Cani', 'tenant': realestate, 'role': 'owner', 'is_active': True}
)
owner_re.set_password(OWNER_PASSWORD_REALEST)
owner_re.save()
print("  ✓ Tenant: amos-realestate | owner@amos.al")


# ════════════════════════════════════════════════════════════════════════════
# TENANT 7 — Travel Agency  (Tirana, Rruga e Kavajës)
# Coords: Rruga e Kavajës 88, Tiranë  41.3340° N, 19.8180° E
# ════════════════════════════════════════════════════════════════════════════
travel, _ = Tenant.objects.update_or_create(
    slug='adriatic-tours',
    defaults={
        'name': 'Adriatic Tours',
        'tagline': 'Eksperienca të paharrueshme — brenda dhe jashtë Shqipërisë',
        'business_type': 'travel_agency',
        'phone': '+355 4 222 9900',
        'whatsapp': '+355692229900',
        'email': 'info@adriatictours.al',
        'address': 'Rruga e Kavajës 88, Tiranë',
        'city': 'Tiranë',
        'country': 'Albania',
        'latitude': 41.334000,
        'longitude': 19.818000,
        'site_title': 'Adriatic Tours — Agjenci Udhëtimesh',
        'story': (
            'Adriatic Tours është agjencia juaj e besueshme e udhëtimeve '
            'nga 2016. Ofrojmë paketa turistike të personalizuara për '
            'Europë, Azi dhe destinacione ekzotike. Specializohemi në '
            'ture grupore, muaj mjalti, dhe udhëtime biznesi.'
        ),
        'founded_year': 2016,
        'meta_description': 'Adriatic Tours — paketa udhëtimesh, visa, sigurime udhëtimi. Kontaktoni sot!',
        'facebook': 'https://facebook.com/adriatictours.al',
        'instagram': 'https://instagram.com/adriatictours',
        'primary_color': '#0077B6',
        'accent_color': '#00B4D8',
        'font_family': 'Nunito',
        'onboarding_step': 6,
        'onboarding_complete': True,
        'plan': PLAN_PRO,
        'is_active': True,
        'listed_on_marketplace': True,
        'marketplace_description': 'Paketa turistike për çdo buxhet. Ekspertë të vizave dhe sigurimeve.',
        'business_hours': {'E Hënë - E Premte': '09:00 - 18:00'},
    }
)
owner_tr, _ = User.objects.get_or_create(
    email='owner@adriatictours.al',
    defaults={'full_name': 'Blerta Musa', 'tenant': travel, 'role': 'owner', 'is_active': True}
)
owner_tr.set_password(OWNER_PASSWORD_TRAVEL)
owner_tr.save()
print("  ✓ Tenant: adriatic-tours | owner@adriatictours.al")


# ════════════════════════════════════════════════════════════════════════════
# TENANT 8 — Construction (Trial)  (Tirana, Rruga Myslym Shyri)
# Coords: Rruga Myslym Shyri, Tiranë  41.3358° N, 19.8244° E
# ════════════════════════════════════════════════════════════════════════════
construction, _ = Tenant.objects.update_or_create(
    slug='ndertim-shpk',
    defaults={
        'name': 'Ndërtim SHPK',
        'tagline': 'Çdo projekt — me cilësi dhe në kohë',
        'business_type': 'construction',
        'phone': '+355 69 700 4411',
        'whatsapp': '+355697004411',
        'email': 'info@ndertim.al',
        'address': 'Rruga Myslym Shyri 10, Tiranë',
        'city': 'Tiranë',
        'country': 'Albania',
        'latitude': 41.335800,
        'longitude': 19.824400,
        'site_title': 'Ndërtim SHPK — Kontraktor i Besueshëm',
        'story': (
            'Ndërtim SHPK ka 20 vjet eksperiencë në ndërtim banesash, '
            'lokalesh biznesi dhe infrastrukture. Ekip prej 45 profesionistësh, '
            'pajisje moderne dhe materiale cilësore europiane.'
        ),
        'founded_year': 2004,
        'meta_description': 'Ndërtim SHPK — kontraktor ndërtimi në Tiranë. Projekte banesore dhe komerciale.',
        'primary_color': '#F97316',
        'accent_color': '#1C1917',
        'font_family': 'Inter',
        'onboarding_step': 6,
        'onboarding_complete': True,
        'plan': PLAN_TRIAL,
        'is_active': True,
        'trial_ends_at': timezone.now() + _dt.timedelta(days=10),
        'business_hours': {'E Hënë - E Premte': '07:00 - 17:00'},
    }
)
owner_co, _ = User.objects.get_or_create(
    email='owner@ndertim.al',
    defaults={'full_name': 'Mëhill Krasniqi', 'tenant': construction, 'role': 'owner', 'is_active': True}
)
owner_co.set_password(OWNER_PASSWORD_CONSTR)
owner_co.save()
print("  ✓ Tenant: ndertim-shpk | owner@ndertim.al  [TRIAL — 10 ditë mbeten]")

# Services for real estate / travel agency / construction — these business
# types previously had zero Service rows, so the booking/consultation flow
# (and the "Shërbime" tab) could not be tested at all on these tenants.
Service.objects.update_or_create(tenant=realestate, name='Vlerësim Falas i Pronës', defaults={
    'price': 0, 'duration_minutes': 45})
Service.objects.update_or_create(tenant=realestate, name='Shoqërim për Shikim Prone', defaults={
    'price': 2000, 'duration_minutes': 60})
Service.objects.update_or_create(tenant=realestate, name='Konsultim Shitje/Blerje', defaults={
    'price': 2500, 'duration_minutes': 30})

Service.objects.get_or_create(tenant=travel, name='Konsultim Paketë Turistike', defaults={
    'price': 0, 'duration_minutes': 30})
Service.objects.get_or_create(tenant=travel, name='Asistencë Vize', defaults={
    'price': 1500, 'duration_minutes': 30})
Service.objects.get_or_create(tenant=travel, name='Sigurim Udhëtimi', defaults={
    'price': 1000, 'duration_minutes': 20})

Service.objects.get_or_create(tenant=construction, name='Vlerësim Projekti Falas', defaults={
    'price': 0, 'duration_minutes': 60})
Service.objects.get_or_create(tenant=construction, name='Konsultim Arkitekturor', defaults={
    'price': 3000, 'duration_minutes': 45})
Service.objects.get_or_create(tenant=construction, name='Matje dhe Preventiv', defaults={
    'price': 0, 'duration_minutes': 90})


# ════════════════════════════════════════════════════════════════════════════
# TENANT 9 — Market / General Shop (retail category)  (Shkodër)
# Coords: Rruga 13 Dhjetori, Shkodër  42.0685° N, 19.5126° E
#
# No retail-category tenant existed anywhere in the seed data before this —
# the inventory/product/stock storefront pages (which every retail-category
# business type shares — market, pharmacy, electronics, clothing, etc.) had
# never been exercised through seed.py. Products below deliberately span
# normal stock, at-threshold low stock, a custom per-product threshold, and
# zero stock, to exercise the low-stock/out-of-stock storefront states.
# ════════════════════════════════════════════════════════════════════════════
market, _ = Tenant.objects.update_or_create(
    slug='market-express',
    defaults={
        'name': 'Market Express',
        'tagline': 'Gjithçka që ju nevojitet, në një vend — çdo ditë',
        'business_type': 'market',
        'phone': '+355 22 246 800',
        'whatsapp': '+355692460080',
        'email': 'info@marketexpress.al',
        'address': 'Rruga 13 Dhjetori 22, Shkodër',
        'city': 'Shkodër',
        'country': 'Albania',
        'latitude': 42.068500,
        'longitude': 19.512600,
        'site_title': 'Market Express — Dyqan Ushqimor & Shtëpiak',
        'story': (
            'Market Express shërben familjet e Shkodrës që nga 2018 me '
            'produkte ushqimore, higjienike dhe shtëpiake të freskëta çdo '
            'ditë. Furnizohemi drejtpërdrejt nga prodhues vendas dhe '
            'shpërndarës të besuar për të garantuar çmimin më të mirë.'
        ),
        'founded_year': 2018,
        'meta_description': (
            'Market Express — dyqan ushqimor në Shkodër me produkte të '
            'freskëta dhe çmime konkurruese. Porosit online ose ejani vetë!'
        ),
        'facebook': 'https://facebook.com/marketexpress.shkoder',
        'instagram': 'https://instagram.com/marketexpress.al',
        'primary_color': '#16A34A',
        'accent_color': '#FACC15',
        'font_family': 'Inter',
        'onboarding_step': 6,
        'onboarding_complete': True,
        'plan': PLAN_STARTER,
        'is_active': True,
        'listed_on_marketplace': True,
        'marketplace_description': 'Dyqan ushqimor dhe shtëpiak në Shkodër.',
        'business_hours': {
            'E Hënë - E Shtunë': '07:30 - 21:00',
            'E Diel': '08:00 - 14:00',
        },
    }
)
owner_market, _ = User.objects.get_or_create(
    email='owner@marketexpress.al',
    defaults={'full_name': 'Gjergj Malaj', 'tenant': market, 'role': 'owner', 'is_active': True}
)
owner_market.set_password(OWNER_PASSWORD_MARKET)
owner_market.save()
print("  ✓ Tenant: market-express | owner@marketexpress.al")

pcat_pantry, _  = ProductCategory.objects.get_or_create(tenant=market, slug='ushqime-bazike', defaults={'name': 'Ushqime Bazike'})
pcat_dairy, _   = ProductCategory.objects.get_or_create(tenant=market, slug='bulmet', defaults={'name': 'Bulmet'})
pcat_house, _   = ProductCategory.objects.get_or_create(tenant=market, slug='shtepiak', defaults={'name': 'Artikuj Shtëpiakë'})

Product.objects.get_or_create(tenant=market, category=pcat_pantry, name='Vaj Ulliri Ekstra Virgjër 1L', defaults={
    'sku': 'MKT-OIL-001', 'price': 950, 'stock': 40, 'description': 'Prodhim vendor, shtypje e ftohtë', 'is_active': True, 'is_featured': True})
Product.objects.get_or_create(tenant=market, category=pcat_pantry, name='Miell Gruri 1kg', defaults={
    'sku': 'MKT-FLR-001', 'price': 120, 'stock': 85, 'description': 'Miell për bukë dhe pjekje', 'is_active': True})
Product.objects.get_or_create(tenant=market, category=pcat_pantry, name='Oriz Basmati 1kg', defaults={
    'sku': 'MKT-RCE-001', 'price': 280, 'stock': 4, 'low_stock_threshold': 10, 'description': 'Import, cilësi premium', 'is_active': True})
Product.objects.get_or_create(tenant=market, category=pcat_dairy, name='Djathë i Bardhë 500g', defaults={
    'sku': 'MKT-CHS-001', 'price': 450, 'stock': 15, 'description': 'Djathë lope, prodhim ditor', 'is_active': True})
Product.objects.get_or_create(tenant=market, category=pcat_dairy, name='Kos Fshati 1L', defaults={
    'sku': 'MKT-YOG-001', 'price': 200, 'stock': 2, 'low_stock_threshold': 5, 'description': 'Kos natyral pa aditivë', 'is_active': True})
Product.objects.get_or_create(tenant=market, category=pcat_dairy, name='Gjalpë 250g', defaults={
    'sku': 'MKT-BUT-001', 'price': 320, 'stock': 0, 'description': 'Përkohësisht i shitur, rimbushje javën tjetër', 'is_active': True})
Product.objects.get_or_create(tenant=market, category=pcat_house, name='Deterxhent Rrobash 3L', defaults={
    'sku': 'MKT-DET-001', 'price': 780, 'stock': 22, 'description': 'Për të gjitha llojet e rrobave', 'is_active': True})
Product.objects.get_or_create(tenant=market, category=pcat_house, name='Letra Tualeti (Paketë 12)', defaults={
    'sku': 'MKT-TIS-001', 'price': 560, 'stock': 60, 'description': '3-shtresore, super e butë', 'is_active': True, 'is_featured': True})

HeroSlide.objects.get_or_create(tenant=market, order=0, defaults={
    'title': 'Market Express — Freskia Çdo Ditë',
    'subtitle': 'Produkte ushqimore dhe shtëpiake me çmimet më të mira në Shkodër',
    'cta_label': 'Shiko Produktet',
    'cta_url': '/products',
    'is_active': True,
})


# ════════════════════════════════════════════════════════════════════════════
# TENANT 10 — Hotel / Guesthouse (food/hospitality category — room testing)
# Coords: Sarandë Riviera, Rruga Skënderbeu  39.8756° N, 20.0053° E
#
# The `hotels` app (RoomType / Room / SeasonalPrice / RoomBooking overlap
# logic) had a full test suite but no seed tenant ever exercised it end to
# end through the storefront + booking flow. Rooms below deliberately span
# 'available', 'occupied', and 'maintenance' statuses so the room-status
# storefront states and overlap-detection booking flow can all be tried.
# ════════════════════════════════════════════════════════════════════════════
hotel, _ = Tenant.objects.update_or_create(
    slug='hotel-riviera',
    defaults={
        'name': 'Hotel Riviera',
        'tagline': 'Pamje mbi detin Jon, çdo dhomë, çdo mëngjes',
        'business_type': 'hotel',
        'phone': '+355 852 22 300',
        'whatsapp': '+355692230033',
        'email': 'rezervime@hotelriviera.al',
        'address': 'Rruga Skënderbeu 8, Sarandë',
        'city': 'Sarandë',
        'country': 'Albania',
        'latitude': 39.875600,
        'longitude': 20.005300,
        'site_title': 'Hotel Riviera — Sarandë',
        'story': (
            'Hotel Riviera ndodhet në bregdetin e Sarandës, me pamje '
            'direkte mbi detin Jon dhe ishullin e Korfuzit. Që nga 2012 '
            'kemi mikpritur mijëra vizitorë vendas dhe të huaj, duke '
            'ofruar dhoma komode, mëngjes tradicional dhe shërbim '
            'personal 24/7.'
        ),
        'founded_year': 2012,
        'meta_description': (
            'Hotel Riviera Sarandë — dhoma me pamje nga deti, mëngjes i '
            'përfshirë, në zemër të bregdetit shqiptar.'
        ),
        'facebook': 'https://facebook.com/hotelriviera.sarande',
        'instagram': 'https://instagram.com/hotelriviera.al',
        'website': 'https://www.hotelriviera.al',
        'primary_color': '#0369A1',
        'accent_color': '#FDE68A',
        'font_family': 'Poppins',
        'onboarding_step': 6,
        'onboarding_complete': True,
        'plan': PLAN_ENTERPRISE,
        'is_active': True,
        'listed_on_marketplace': True,
        'marketplace_description': 'Hotel buzë detit në Sarandë, pamje nga Korfuzi.',
        'business_hours': {'E Hënë - E Diel': '00:00 - 23:59 (Recepsion 24/7)'},
    }
)
owner_hotel, _ = User.objects.get_or_create(
    email='owner@hotelriviera.al',
    defaults={'full_name': 'Vjollca Dema', 'tenant': hotel, 'role': 'owner', 'is_active': True}
)
owner_hotel.set_password(OWNER_PASSWORD_HOTEL)
owner_hotel.save()
print("  ✓ Tenant: hotel-riviera | owner@hotelriviera.al")

rt_single, _ = RoomType.objects.get_or_create(tenant=hotel, name='Dhomë Single', defaults={
    'description': 'Dhomë ekonomike për 1 person, pamje nga qyteti', 'capacity': 1,
    'base_price': 35.00, 'amenities': ['WiFi', 'TV', 'Klimë']})
rt_double, _ = RoomType.objects.get_or_create(tenant=hotel, name='Dhomë Double — Pamje Deti', defaults={
    'description': 'Dhomë dopio me ballkon dhe pamje direkte nga deti Jon', 'capacity': 2,
    'base_price': 65.00, 'amenities': ['WiFi', 'TV', 'Klimë', 'Ballkon', 'Mini-bar']})
rt_suite, _ = RoomType.objects.get_or_create(tenant=hotel, name='Suite Familjare', defaults={
    'description': 'Suite me dy dhoma gjumi, ideale për familje deri në 4 persona', 'capacity': 4,
    'base_price': 110.00, 'amenities': ['WiFi', 'TV', 'Klimë', 'Ballkon', 'Mini-bar', 'Kuzhinë e vogël']})

Room.objects.get_or_create(tenant=hotel, room_type=rt_single, room_number='101', defaults={'floor': 1, 'status': 'available'})
Room.objects.get_or_create(tenant=hotel, room_type=rt_single, room_number='102', defaults={'floor': 1, 'status': 'occupied'})
Room.objects.get_or_create(tenant=hotel, room_type=rt_double, room_number='201', defaults={'floor': 2, 'status': 'available'})
Room.objects.get_or_create(tenant=hotel, room_type=rt_double, room_number='202', defaults={'floor': 2, 'status': 'available'})
Room.objects.get_or_create(tenant=hotel, room_type=rt_double, room_number='203', defaults={'floor': 2, 'status': 'maintenance', 'notes': 'Riparim klime, kthehet të Hënën'})
Room.objects.get_or_create(tenant=hotel, room_type=rt_suite, room_number='301', defaults={'floor': 3, 'status': 'available'})

SeasonalPrice.objects.get_or_create(tenant=hotel, room_type=rt_double, name='Sezoni Veror (Qershor–Shtator)', defaults={
    'start_date': _dt.date(2026, 6, 1), 'end_date': _dt.date(2026, 9, 30), 'price': 95.00})
SeasonalPrice.objects.get_or_create(tenant=hotel, room_type=rt_suite, name='Sezoni Veror (Qershor–Shtator)', defaults={
    'start_date': _dt.date(2026, 6, 1), 'end_date': _dt.date(2026, 9, 30), 'price': 160.00})

HeroSlide.objects.get_or_create(tenant=hotel, order=0, defaults={
    'title': 'Zgjohuni me Pamjen e Detit Jon',
    'subtitle': 'Dhoma komode buzë bregdetit të Sarandës — mëngjes i përfshirë',
    'cta_label': 'Rezervo Dhomën',
    'cta_url': '/bookings',
    'is_active': True,
})
Service.objects.get_or_create(tenant=hotel, name='Mëngjes i Përfshirë', defaults={
    'price': 0, 'duration_minutes': 60})
Service.objects.get_or_create(tenant=hotel, name='Transferim Aeroport (Aeroporti Rinas)', defaults={
    'price': 4500, 'duration_minutes': 180})


# ════════════════════════════════════════════════════════════════════════════
# Demo customer
# ════════════════════════════════════════════════════════════════════════════
customer, _ = User.objects.get_or_create(
    email='customer@demo.al',
    defaults={'full_name': 'Klient Demo', 'role': 'customer', 'is_active': True}
)
customer.set_password(CUSTOMER_PASSWORD)
customer.save()
print("  ✓ Customer: customer@demo.al")


# ════════════════════════════════════════════════════════════════════════════
# Reviews
# ════════════════════════════════════════════════════════════════════════════
for tenant_obj, texts in [
    (resto, [
        ('Ushqim fantastik! Peshku i freskët dhe shërbimi i shkëlqyer. Do të kthehem patjetër!', 5),
        ('Atmosferë e mrekullueshme buzë detit. Karkaleci me hudhër ishte i jashtëzakonshëm.', 5),
        ('Çmimet janë të arsyeshme për cilësinë që ofrojnë. Rekomandoj pjatën e detit.', 4),
    ]),
    (cars, [
        ('Makinë e pastër dhe shërbim i shpejtë! Corolla ishte në gjendje të shkëlqyer.', 5),
        ('Çmim i arsyeshëm dhe staf i sjellshëm. Procedura e marrjes ishte e shpejtë.', 4),
        ('BMW ishte perfekte për udhëtimin e biznesit. Patjetër do ta zgjedh sërish.', 5),
    ]),
    (clinic, [
        ('Mjekë profesionistë dhe pritje e shpejtë. Dr. Prifti ishte shumë e kujdesshme.', 5),
        ('Klinikë moderne me pajisje të reja. Shërbim i shkëlqyer, rekomandoj!', 5),
        ('Dr. Alban Koci më shpjegoi çdo detaj të EKG-së me durim. Shumë profesional.', 5),
    ]),
    (barber, [
        ('Prerja më e mirë që kam bërë ndonjëherë! Endrit është maestro i vërtetë.', 5),
        ('Ambiente modern dhe relaksues. Aldo bëri punë të shkëlqyer me mjekrën time.', 4),
        ('Rezervimi online ishte i thjeshtë dhe u prita vetëm 5 minuta. Do të kthehem.', 5),
    ]),
    (langschool, [
        ('Mësuese të shkëlqyera dhe metodë moderne. Anglishten e mësova në 6 muaj!', 5),
        ('Prof. Marco është fantastik. Italishten e mësoj me kënaqësi çdo ditë.', 5),
        ('Klasa të vogla, vëmendje individuale. Rekomandoj për çdo nivel.', 4),
    ]),
    (realestate, [
        ('Ekip shumë profesional, na gjetën apartamentin perfekt brenda 2 javësh.', 5),
        ('Vlerësim i shpejtë dhe transparent i pronës sonë. Shumë të kënaqur.', 5),
        ('Agjentja ishte e durueshme dhe na shoqëroi në çdo shikim prone.', 4),
    ]),
    (travel, [
        ('Paketa në Greqi ishte organizuar në mënyrë perfekte, asnjë problem!', 5),
        ('Na ndihmuan me vizën brenda pak ditësh. Shërbim shumë i shpejtë.', 5),
        ('Çmime të mira dhe staf i përgjegjshëm gjatë gjithë udhëtimit.', 4),
    ]),
    (construction, [
        ('Punë cilësore dhe brenda afatit të premtuar. Rekomandoj fuqimisht.', 5),
        ('Ekipi ishte i organizuar dhe na mbajti të informuar gjatë gjithë projektit.', 4),
        ('Preventivi ishte i saktë, pa kosto të fshehura shtesë gjatë ndërtimit.', 5),
    ]),
    (market, [
        ('Çmime të mira dhe produkte gjithmonë të freskëta. Dyqani im i preferuar në Shkodër.', 5),
        ('Stafi shumë i sjellshëm, gjej gjithçka që më nevojitet për shtëpinë.', 4),
        ('Vaji i ullirit është i shkëlqyer, produkt vendor cilësor.', 5),
    ]),
    (hotel, [
        ('Pamja nga deti ishte mahnitëse! Dhoma e pastër dhe mëngjesi shumë i mirë.', 5),
        ('Personel shumë i vëmendshëm, na ndihmuan me transferimin nga aeroporti.', 5),
        ('Vendndodhje perfekte pranë plazhit, do të kthehemi patjetër verën tjetër.', 4),
    ]),
]:
    for comment, rating in texts:
        Review.objects.get_or_create(
            tenant=tenant_obj, user=customer, comment=comment,
            defaults={'rating': rating, 'review_type': 'business', 'is_approved': True}
        )


# ════════════════════════════════════════════════════════════════════════════
# Blog posts (Enterprise tenant — Hertz)
# FIX: BlogTag.get_or_create must include tenant in lookup (unique_together)
# ════════════════════════════════════════════════════════════════════════════
tag_udhezime, _ = BlogTag.objects.get_or_create(tenant=cars, slug='udhezime', defaults={'name': 'Udhëzime'})
tag_tips, _     = BlogTag.objects.get_or_create(tenant=cars, slug='keshilla', defaults={'name': 'Këshilla'})

BlogPost.objects.get_or_create(
    tenant=cars, slug='si-te-zgjidhni-makinen-e-duhur',
    defaults={
        'title': 'Si të Zgjidhni Makinën e Duhur për Udhëtimin Tuaj',
        'excerpt': 'Këshilla praktike për zgjedhjen e automjetit ideal sipas nevojave tuaja.',
        'body': (
            '<h2>Faktorët kryesorë</h2>'
            '<p>Zgjedhja e makinës së duhur varet nga numri i pasagjerëve, '
            'distanca e udhëtimit dhe lloji i rrugës. Për rrugë malore '
            'rekomandojmë SUV, ndërsa për qytet ekonomiket janë ideale.</p>'
            '<h2>Buxheti</h2>'
            '<p>Llogaritni koston totale: qiraja ditore × numri i ditëve + '
            'karburanti + sigurim. Shpesh paketat javore ofrojnë kursime '
            'deri 30%.</p>'
            '<h2>Sigurimi</h2>'
            '<p>Gjithmonë merrni sigurimin Collision Damage Waiver (CDW) për '
            'qetësi mendore gjatë udhëtimit.</p>'
        ),
        'status': 'published',
        'author': owner2,
        'view_count': 142,
    }
)

BlogPost.objects.get_or_create(
    tenant=cars, slug='destinacionet-me-te-bukura-shqiperi',
    defaults={
        'title': '5 Destinacionet Më të Bukura të Shqipërisë që Duhet t\'i Vizitoni',
        'excerpt': 'Nga Riviera Shqiptare deri tek Alpet — udhëzues i plotë.',
        'body': (
            '<p>Shqipëria fsheh thesare natyrore të paçmueshme. Me makinën '
            'tuaj të marrë me qira nga Hertz Albania, mund t\'i eksploroni '
            'të gjitha me komoditet.</p>'
            '<ol>'
            '<li><strong>Riviera Shqiptare</strong> — plazhe kristalore nga '
            'Saranda deri në Vlorë</li>'
            '<li><strong>Alpet Shqiptare</strong> — natyrë e egër dhe fshatrat '
            'e veriut</li>'
            '<li><strong>Berat</strong> — qyteti i 1000 dritareve, UNESCO</li>'
            '<li><strong>Gjirokastër</strong> — kalaja osmane dhe bazari</li>'
            '<li><strong>Liqeni i Ohrit</strong> — bukuri natyrore ndërkufitare</li>'
            '</ol>'
        ),
        'status': 'published',
        'author': owner2,
        'view_count': 89,
    }
)

tag_re_tips, _   = BlogTag.objects.get_or_create(tenant=realestate, slug='keshilla', defaults={'name': 'Këshilla'})
tag_re_treg, _   = BlogTag.objects.get_or_create(tenant=realestate, slug='tregu', defaults={'name': 'Tregu Imobiliar'})

BlogPost.objects.get_or_create(
    tenant=realestate, slug='si-te-vleresoni-pronen-para-shitjes',
    defaults={
        'title': 'Si të Vlerësoni Pronën Tuaj Para Shitjes',
        'excerpt': 'Faktorët që ndikojnë më shumë në çmimin e shitjes së një apartamenti apo vile.',
        'body': (
            '<h2>Lokacioni mbetet faktori #1</h2>'
            '<p>Afërsia me qendrën, shkollat dhe transportin publik ndikon '
            'deri në 40% të vlerës së pronës. Pronat në Bllok apo pranë '
            'detit në Rivierën Shqiptare vazhdojnë të kenë kërkesën më të '
            'lartë.</p>'
            '<h2>Gjendja dhe rinovimi</h2>'
            '<p>Një apartament i rinovuar shitet mesatarisht 15-20% më shtrenjtë '
            'se një i pa-rinovuar në të njëjtën zonë. Investimet e vogla si '
            'bojë dhe dysheme kthejnë vlerë të shpejtë.</p>'
            '<h2>Vlerësimi profesional</h2>'
            '<p>Ekipi ynë ofron vlerësim falas bazuar në transaksionet e '
            'fundit të krahasueshme në zonën tuaj. Kontaktoni për një '
            'takim.</p>'
        ),
        'status': 'published',
        'author': owner_re,
        'view_count': 64,
    }
)

BlogPost.objects.get_or_create(
    tenant=realestate, slug='cfare-duhet-te-dini-para-blerjes-se-apartamentit',
    defaults={
        'title': 'Çfarë Duhet të Dini Para Blerjes së Apartamentit të Parë',
        'excerpt': 'Udhëzues praktik për dokumentacionin, financimin dhe negocimin.',
        'body': (
            '<h2>Kontrolloni dokumentacionin</h2>'
            '<p>Sigurohuni që prona ka çertifikatë pronësie të pastër dhe '
            'nuk ka hipotekë të papaguar. Agjentët tanë verifikojnë çdo '
            'dokument para se ta rekomandojnë një pronë.</p>'
            '<h2>Buxheti dhe financimi</h2>'
            '<p>Përveç çmimit të pronës, llogaritni edhe tarifat noteriale, '
            'taksën e regjistrimit dhe komisionin e agjencisë — zakonisht '
            '2-3% të vlerës totale.</p>'
            '<h2>Negocimi</h2>'
            '<p>Çmimi i kërkuar rrallë është çmimi final. Ekipi ynë '
            'negocion në emrin tuaj për të siguruar kushtet më të mira.</p>'
        ),
        'status': 'published',
        'author': owner_re,
        'view_count': 51,
    }
)


# ════════════════════════════════════════════════════════════════════════════
# Staff
# FIX: StaffMember lookup uses (tenant, user) which is the natural unique pair
# ════════════════════════════════════════════════════════════════════════════
sm_resto, _ = StaffMember.objects.get_or_create(
    tenant=resto, user=owner1,
    defaults={'role': 'manager', 'position': 'Restaurant Manager', 'is_active': True}
)
for day, start, end in [
    ('monday',    '09:00', '17:00'),
    ('tuesday',   '09:00', '17:00'),
    ('wednesday', '09:00', '17:00'),
    ('thursday',  '09:00', '17:00'),
    ('friday',    '09:00', '22:00'),
    ('saturday',  '10:00', '23:00'),
]:
    StaffSchedule.objects.get_or_create(
        tenant=resto, staff=sm_resto, day=day,
        defaults={'start_time': start, 'end_time': end}
    )

sm_lc, _ = StaffMember.objects.get_or_create(
    tenant=langschool, user=owner_lc,
    defaults={'role': 'manager', 'position': 'Director', 'is_active': True}
)


# ════════════════════════════════════════════════════════════════════════════
# Storefront hero slides & pages
# FIX: StorefrontPage includes order field
# ════════════════════════════════════════════════════════════════════════════
HeroSlide.objects.get_or_create(tenant=resto, order=0, defaults={
    'title': 'Mirë se vini në Restorant Adriatiku',
    'subtitle': 'Ushqim i freskët buzë detit Adriatik',
    'cta_label': 'Rezervo tavolinën',
    'cta_url': '/bookings',
    'is_active': True,
})
HeroSlide.objects.get_or_create(tenant=resto, order=1, defaults={
    'title': 'Peshk i freskët çdo ditë',
    'subtitle': 'Fishermen-ët tanë sjellin gjuetinë direkt në kuzhinën tonë',
    'cta_label': 'Shiko menunë',
    'cta_url': '/menu',
    'is_active': True,
})
HeroSlide.objects.get_or_create(tenant=cars, order=0, defaults={
    'title': 'Makina me Qira — Tiranë & Tërë Shqipëria',
    'subtitle': 'Mbi 150 automjete. Rezervim online i menjëhershëm.',
    'cta_label': 'Rezervo tani',
    'cta_url': '/rentals',
    'is_active': True,
})
HeroSlide.objects.get_or_create(tenant=clinic, order=0, defaults={
    'title': 'Kujdesi për Shëndetin Tuaj Fillon Këtu',
    'subtitle': 'Ekip i specializuar. Pajisje moderne. Trajtim human.',
    'cta_label': 'Cakto takim',
    'cta_url': '/appointments',
    'is_active': True,
})
HeroSlide.objects.get_or_create(tenant=barber, order=0, defaults={
    'title': 'Prerja Perfekte — Çdo Herë',
    'subtitle': 'Berber profesionistë në zemër të Bllokut, Tiranë',
    'cta_label': 'Rezervo tani',
    'cta_url': '/appointments',
    'is_active': True,
})
HeroSlide.objects.get_or_create(tenant=langschool, order=0, defaults={
    'title': 'Hap Dyert e Botës me Gjuhë të Huaja',
    'subtitle': 'Anglisht · Italisht · Gjermanisht · Frëngjisht · Spanjisht',
    'cta_label': 'Regjistrohu tani',
    'cta_url': '/appointments',
    'is_active': True,
})
HeroSlide.objects.get_or_create(tenant=construction, order=0, defaults={
    'title': '20 Vjet Eksperiencë në Ndërtim',
    'subtitle': 'Projekte banesore, komerciale dhe infrastrukturore me ekip profesional',
    'cta_label': 'Na Kontaktoni',
    'cta_url': '/contact',
    'is_active': True,
})
HeroSlide.objects.get_or_create(tenant=construction, order=1, defaults={
    'title': 'Cilësi Europiane, Çmime Shqiptare',
    'subtitle': 'Materiale nga furnitorët më të mirë europianë. Garanci 5 vjet.',
    'cta_label': 'Shiko Projektet',
    'cta_url': '/#services',
    'is_active': True,
})

StorefrontPage.objects.get_or_create(tenant=construction, slug='projektet', defaults={
    'title': 'Projektet Tona', 'order': 1,
    'body': '<h2>Portofoli i Projekteve</h2><p>Mbi 200 projekte të përfunduara me sukses në të gjithë Shqipërinë.</p>',
    'is_published': True,
})

StorefrontPage.objects.get_or_create(tenant=resto, slug='rreth-nesh', defaults={
    'title': 'Rreth Nesh', 'order': 1,
    'body': (
        '<p>Restorant Adriatiku u themelua në 2015 nga familja Hoxha, '
        'me dashurinë për ushqimin e detit dhe mikpritjen shqiptare. '
        'Sot jemi destinacioni i preferuar i të gjithë atyre që duan '
        'peshk të freskët dhe atmosferë autentike buzë detit.</p>'
    ),
    'is_published': True,
})
StorefrontPage.objects.get_or_create(tenant=cars, slug='rreth-nesh', defaults={
    'title': 'Rreth Hertz Albania', 'order': 1,
    'body': (
        '<p>Hertz Albania është lider i tregut të makinave me qira '
        'në Shqipëri. Me zyra në Tiranë, Durrës dhe Aeroportin e '
        'Rinasit, ofrojmë shërbim 24/7 për clientët tanë.</p>'
    ),
    'is_published': True,
})
StorefrontPage.objects.get_or_create(tenant=langschool, slug='rreth-nesh', defaults={
    'title': 'Rreth Learning Center', 'order': 1,
    'body': (
        '<p>Learning Center ofron kurse gjuhësh të huaja që nga 2019. '
        'Metodologjia jonë komunikative dhe mësuesit e certifikuar '
        'ndërkombëtarisht garantojnë progres të shpejtë dhe të '
        'matshëm. Bashkohuni me mbi 500 studentët tanë!</p>'
    ),
    'is_published': True,
})


# ════════════════════════════════════════════════════════════════════════════
# CRM leads
# FIX: source 'instagram' → 'social' (valid LEAD_SOURCE choice)
# ════════════════════════════════════════════════════════════════════════════
Lead.objects.get_or_create(tenant=cars, name='Arben Hoxha', defaults={
    'email': 'arben@example.com',
    'phone': '+355 69 123 4567',
    'source': 'website',
    'status': 'new',
    'notes': 'Interested in weekly rental for business travel.',
})
Lead.objects.get_or_create(tenant=cars, name='Elona Shehu', defaults={
    'email': 'elona@example.com',
    'source': 'referral',
    'status': 'qualified',
    'notes': 'Referred by existing customer. Needs SUV for mountain trip.',
})
Lead.objects.get_or_create(tenant=clinic, name='Besnik Çela', defaults={
    'email': 'besnik@example.com',
    'phone': '+355 69 555 0011',
    'source': 'social',
    'status': 'new',
    'notes': 'Interesohet për paketën mujore të shëndetit.',
})
Lead.objects.get_or_create(tenant=langschool, name='Drita Basha', defaults={
    'email': 'drita@example.com',
    'phone': '+355 69 777 3322',
    'source': 'social',
    'status': 'new',
    'notes': 'Interesohet për kurs anglisht B1-B2, orare pasdite.',
})


# ════════════════════════════════════════════════════════════════════════════
# Billing
# ════════════════════════════════════════════════════════════════════════════
inv, _ = Invoice.objects.get_or_create(
    tenant=cars, invoice_number='INV-001',
    defaults={
        'customer': customer,
        'customer_name': 'Demo Customer',
        'status': 'sent',
        'notes': '3-day car rental — Toyota Corolla',
    }
)
InvoiceLine.objects.get_or_create(
    tenant=cars, invoice=inv, description='Toyota Corolla — 3 ditë',
    defaults={'quantity': 3, 'unit_price': 45.00}
)

inv2, _ = Invoice.objects.get_or_create(
    tenant=clinic, invoice_number='INV-002',
    defaults={
        'customer': customer,
        'customer_name': 'Demo Customer',
        'status': 'paid',
        'notes': 'Vizitë e Përgjithshme + EKG',
    }
)
InvoiceLine.objects.get_or_create(
    tenant=clinic, invoice=inv2, description='Vizitë e Përgjithshme',
    defaults={'quantity': 1, 'unit_price': 25.00}
)
InvoiceLine.objects.get_or_create(
    tenant=clinic, invoice=inv2, description='Elektrokardiogram (EKG)',
    defaults={'quantity': 1, 'unit_price': 35.00}
)

inv3, _ = Invoice.objects.get_or_create(
    tenant=langschool, invoice_number='INV-003',
    defaults={
        'customer': customer,
        'customer_name': 'Demo Customer',
        'status': 'paid',
        'notes': 'Kurs Anglisht B1-B2',
    }
)
InvoiceLine.objects.get_or_create(
    tenant=langschool, invoice=inv3, description='Kurs Anglisht — Mesëm (B1-B2) × 1 muaj',
    defaults={'quantity': 1, 'unit_price': 90.00}
)


# ════════════════════════════════════════════════════════════════════════════
# Customer subscriptions
# ════════════════════════════════════════════════════════════════════════════
CustomerSubscription.objects.get_or_create(
    tenant=clinic, customer=customer, name='Paketa Mujore Shëndetësi',
    defaults={
        'description': 'Vizita të rregullta mujore + konsultime pa kosto shtesë',
        'price': 2500.00,
        'frequency': 'monthly',
        'status': 'active',
    }
)
CustomerSubscription.objects.get_or_create(
    tenant=langschool, customer=customer, name='Kurs Anglisht — Abonim Mujor',
    defaults={
        'description': 'Aksès i pakufizuar në klasat e anglishtes',
        'price': 9000.00,
        'frequency': 'monthly',
        'status': 'active',
    }
)


# ════════════════════════════════════════════════════════════════════════════
# Multi-location for Hertz (Enterprise) — with real coordinates
# Tiranë qendra: 41.3305° N, 19.8233° E
# Durrës Bulevardi Epidamn: 41.3233° N, 19.4413° E
# Rinas Airport: 41.4147° N, 19.7206° E
# ════════════════════════════════════════════════════════════════════════════
TenantLocation.objects.get_or_create(
    tenant=cars, name='Hertz Tiranë — Qendra',
    defaults={
        'address': 'Rruga Kavajës 45, Tiranë',
        'city': 'Tiranë',
        'phone': '+355 4 234 5678',
        'latitude': 41.330500,
        'longitude': 19.823300,
        'is_primary': True,
        'is_active': True,
    }
)
TenantLocation.objects.get_or_create(
    tenant=cars, name='Hertz Durrës',
    defaults={
        'address': 'Bulevardi Epidamn 12, Durrës',
        'city': 'Durrës',
        'phone': '+355 52 123 456',
        'latitude': 41.323300,
        'longitude': 19.441300,
        'is_primary': False,
        'is_active': True,
    }
)
TenantLocation.objects.get_or_create(
    tenant=cars, name='Hertz Aeroporti Rinasi',
    defaults={
        'address': 'Aeroporti Ndërkombëtar Tiranë, Rinas',
        'city': 'Rinas',
        'phone': '+355 4 381 9999',
        'latitude': 41.414700,
        'longitude': 19.720600,
        'is_primary': False,
        'is_active': True,
    }
)
print("  ✓ TenantLocations: Hertz — 3 dega me koordinata reale")


# ════════════════════════════════════════════════════════════════════════════
# Referral demo
# ════════════════════════════════════════════════════════════════════════════
Tenant.objects.filter(slug='hertz-albania').update(referral_code='HERTZ001')

ref_record, created = TenantReferral.objects.get_or_create(
    referrer=cars, referred=travel,
    defaults={'credit_amount': 10.00, 'applied': False}
)
if created:
    ref_record.apply_credit()
    print("  ✓ Referral: hertz-albania → adriatic-tours (€10 kredit aplikuar)")


print("\n✅ Seed KOMPLET!")
print("\nTenantët:")
print("   restorant-adriatiku   — Restaurant,      Pro,        Vlorë     40.4486°N 19.4897°E")
print("   hertz-albania         — Car Rental,       Enterprise, Tiranë    41.3305°N 19.8233°E  (3 dega)")
print("   klinika-shendeti      — Clinic,           Pro,        Tiranë    41.3317°N 19.8350°E")
print("   barber-kings-tirana   — Barbershop,       Starter,    Tiranë    41.3229°N 19.8175°E")
print("   learning-center       — Language School,  Pro,        Tiranë    41.3260°N 19.8290°E")
print("   amos-realestate       — Real Estate,      Enterprise, Tiranë    41.3275°N 19.8220°E")
print("   adriatic-tours        — Travel Agency,    Pro,        Tiranë    41.3340°N 19.8180°E")
print("   ndertim-shpk          — Construction,     Trial,      Tiranë    41.3358°N 19.8244°E")
print("   market-express        — Market (retail),  Starter,    Shkodër   42.0685°N 19.5126°E")
print("   hotel-riviera         — Hotel,             Enterprise, Sarandë   39.8756°N 20.0053°E  (6 dhoma)")
print("\nAdmin: http://localhost:8000/admin → admin@bizal.al")
print("Faqet: http://localhost:8001/?tenant=<slug>")
print("\nKredencialet e hyrjes (login credentials):")
print(f"   Superadmin : admin@bizal.al           / {ADMIN_PASSWORD}")
print("   Owners (secila tenante ka fjalëkalimin e vet):")
print(f"     owner@adriatiku.al       (restorant-adriatiku)  / {OWNER_PASSWORD_RESTO}")
print(f"     owner@hertz.al           (hertz-albania)        / {OWNER_PASSWORD_CARS}")
print(f"     owner@klinikashendeti.al (klinika-shendeti)     / {OWNER_PASSWORD_CLINIC}")
print(f"     owner@barberkings.al     (barber-kings-tirana)  / {OWNER_PASSWORD_BARBER}")
print(f"     owner@learningcenter.al  (learning-center)      / {OWNER_PASSWORD_LANGSC}")
print(f"     owner@amos.al            (amos-realestate)      / {OWNER_PASSWORD_REALEST}")
print(f"     owner@adriatictours.al   (adriatic-tours)       / {OWNER_PASSWORD_TRAVEL}")
print(f"     owner@ndertim.al         (ndertim-shpk)         / {OWNER_PASSWORD_CONSTR}")
print(f"     owner@marketexpress.al   (market-express)       / {OWNER_PASSWORD_MARKET}")
print(f"     owner@hotelriviera.al    (hotel-riviera)        / {OWNER_PASSWORD_HOTEL}")
print(f"   Customer   : user@user.com         / {CUSTOMER_PASSWORD}")
print("\n   Tenant admin panel: http://localhost:8001/admin/?tenant=<slug>")
print("   (e.g. http://localhost:8001/admin/?tenant=restorant-adriatiku, login owner@adriatiku.al)")
