"""
BizAL Demo Seed Script
Run: python seed.py (after setup.py)
Creates demo tenants, owners, bookings, reviews, blog posts.
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bizal.settings.local')
django.setup()

from tenants.models import Tenant, PLAN_PRO, PLAN_ENTERPRISE, PLAN_STARTER
from accounts.models import User
from reviews.models import Review
from bookings.models import Booking
from blog.models import BlogPost, BlogTag
from menu.models import MenuCategory, MenuItem
from rentals.models import RentalItem
from appointments.models import ServiceProvider, Service


print("🌱 Seeding BizAL demo data...")

# ---- Superadmin ----
superadmin, _ = User.objects.get_or_create(
    email='admin@bizal.al',
    defaults={'full_name': 'BizAL Admin', 'is_staff': True, 'is_superuser': True, 'role': 'superadmin', 'is_active': True}
)
superadmin.set_password('admin1234')
superadmin.save()
print(f"  ✓ Superadmin: admin@bizal.al / admin1234")

# ---- Tenant 1: Restaurant ----
resto, _ = Tenant.objects.get_or_create(
    slug='restorant-adriatiku',
    defaults={
        'name': 'Restorant Adriatiku',
        'site_title': 'Adriatiku — Shija e Detit',
        'tagline': 'Peshk i freskët, atmosferë unike — buzë detit të Adriatikut',
        'business_type': 'restaurant',
        'plan': PLAN_PRO,
        'is_active': True,
        'city': 'Vlorë',
        'phone': '+355 33 123 456',
        'email': 'info@adriatiku.al',
        'whatsapp': '+355691234567',
        'address': 'Rruga e Detit 12, Vlorë',
        'primary_color': '#0EA5E9',
        'accent_color': '#F97316',
        'founded_year': 2015,
        'story': 'Restorant Adriatiku u hap në vitin 2015 me dashurinë për detarin e Vlorës.',
        'business_hours': {'E Hënë - E Premte': '11:00 - 23:00', 'E Shtunë - E Diel': '10:00 - 00:00'},
    }
)

owner1, _ = User.objects.get_or_create(
    email='owner@adriatiku.al',
    defaults={'full_name': 'Arben Hoxha', 'tenant': resto, 'role': 'owner', 'is_active': True}
)
owner1.set_password('owner1234')
owner1.save()
print(f"  ✓ Tenant: restorant-adriatiku | owner@adriatiku.al / owner1234")

# Menu categories
cat1, _ = MenuCategory.objects.get_or_create(tenant=resto, name='Peshk & Fruta Deti', defaults={'order': 1})
cat2, _ = MenuCategory.objects.get_or_create(tenant=resto, name='Meze', defaults={'order': 2})

MenuItem.objects.get_or_create(tenant=resto, category=cat1, name='Levrek i Pjekur', defaults={'price': 1800, 'description': 'Me perime të stinës', 'is_available': True})
MenuItem.objects.get_or_create(tenant=resto, category=cat1, name='Karkalec me Hudhër', defaults={'price': 1500, 'description': 'Karkalec i detit me salcë hudhre', 'is_available': True})
MenuItem.objects.get_or_create(tenant=resto, category=cat2, name='Pjatë Mezesh', defaults={'price': 800, 'description': 'Djathë, ulliri, domate të thata', 'is_available': True})

# ---- Tenant 2: Car Rental ----
cars, _ = Tenant.objects.get_or_create(
    slug='hertz-albania',
    defaults={
        'name': 'Hertz Albania',
        'site_title': 'Hertz — Makina me Qira Tirana',
        'tagline': 'Flota më e madhe, çmimet më të mira në Shqipëri',
        'business_type': 'car_rental',
        'plan': PLAN_ENTERPRISE,
        'is_active': True,
        'city': 'Tiranë',
        'phone': '+355 4 234 5678',
        'email': 'info@hertz.al',
        'whatsapp': '+355697654321',
        'address': 'Rruga Kavajës 45, Tiranë',
        'primary_color': '#FFD400',
        'accent_color': '#1A1A1A',
        'founded_year': 2010,
        'business_hours': {'E Hënë - E Diel': '08:00 - 20:00'},
    }
)

owner2, _ = User.objects.get_or_create(
    email='owner@hertz.al',
    defaults={'full_name': 'Gent Berisha', 'tenant': cars, 'role': 'owner', 'is_active': True}
)
owner2.set_password('owner1234')
owner2.save()
print(f"  ✓ Tenant: hertz-albania | owner@hertz.al / owner1234")

RentalItem.objects.get_or_create(tenant=cars, name='Toyota Corolla 2023', defaults={'rental_type': 'car', 'price_per_day': 5000, 'city': 'Tiranë', 'status': 'available', 'specs': {'seats': 5, 'fuel': 'Benzinë', 'transmission': 'Automatike'}})
RentalItem.objects.get_or_create(tenant=cars, name='BMW 320i 2022', defaults={'rental_type': 'car', 'price_per_day': 8500, 'city': 'Tiranë', 'status': 'available', 'specs': {'seats': 5, 'fuel': 'Benzinë', 'transmission': 'Automatike'}})
RentalItem.objects.get_or_create(tenant=cars, name='Furgon Mercedes Sprinter', defaults={'rental_type': 'car', 'price_per_day': 9500, 'city': 'Tiranë', 'status': 'available', 'specs': {'seats': 9, 'fuel': 'Diesel', 'transmission': 'Manuale'}})

# ---- Tenant 3: Clinic ----
clinic, _ = Tenant.objects.get_or_create(
    slug='klinika-shendeti',
    defaults={
        'name': 'Klinika Shëndeti',
        'site_title': 'Klinika Shëndeti — Mjekësi Moderne',
        'tagline': 'Shëndeti juaj — prioriteti ynë',
        'business_type': 'clinic',
        'plan': PLAN_PRO,
        'is_active': True,
        'city': 'Tiranë',
        'phone': '+355 4 111 2233',
        'email': 'info@klinikashendeti.al',
        'address': 'Rruga Durrsit 78, Tiranë',
        'primary_color': '#059669',
        'accent_color': '#0EA5E9',
        'business_hours': {'E Hënë - E Premte': '08:00 - 18:00', 'E Shtunë': '09:00 - 14:00'},
    }
)

owner3, _ = User.objects.get_or_create(
    email='owner@klinikashendeti.al',
    defaults={'full_name': 'Dr. Elda Prifti', 'tenant': clinic, 'role': 'owner', 'is_active': True}
)
owner3.set_password('owner1234')
owner3.save()
print(f"  ✓ Tenant: klinika-shendeti | owner@klinikashendeti.al / owner1234")

prov1, _ = ServiceProvider.objects.get_or_create(tenant=clinic, name='Dr. Elda Prifti', defaults={'title': 'Dr.', 'specialties': 'Mjekësi e Përgjithshme, Pediatri'})
prov2, _ = ServiceProvider.objects.get_or_create(tenant=clinic, name='Dr. Alban Koci', defaults={'title': 'Dr.', 'specialties': 'Kardiologji'})

svc1, _ = Service.objects.get_or_create(tenant=clinic, name='Vizitë e Përgjithshme', defaults={'price': 2500, 'duration_minutes': 30})
svc2, _ = Service.objects.get_or_create(tenant=clinic, name='Elektrokardiogram (EKG)', defaults={'price': 3500, 'duration_minutes': 45})

# ---- Demo customer ----
customer, _ = User.objects.get_or_create(
    email='customer@demo.al',
    defaults={'full_name': 'Klient Demo', 'role': 'customer', 'is_active': True}
)
customer.set_password('customer1234')
customer.save()
print(f"  ✓ Customer: customer@demo.al / customer1234")

# ---- Reviews ----
for tenant_obj, texts in [
    (resto, [('Ushqim fantastik! Peshku i freskët dhe shërbimi i shkëlqyer.', 5), ('Atmosferë e mrekullueshme buzë detit.', 4)]),
    (cars, [('Makinë e pastër dhe shërbim i shpejtë!', 5), ('Çmim i arsyeshëm dhe staf i sjellshëm.', 4)]),
    (clinic, [('Mjekë profesionistë dhe pritje e shpejtë.', 5)]),
]:
    for comment, rating in texts:
        Review.objects.get_or_create(tenant=tenant_obj, user=customer, comment=comment, defaults={'rating': rating, 'review_type': 'business'})

# ---- Blog posts for Enterprise tenant ----
tag, _ = BlogTag.objects.get_or_create(tenant=cars, name='Udhëzime', slug='udhezime')
BlogPost.objects.get_or_create(
    tenant=cars, slug='si-te-zgjidhni-makinen-e-duhur',
    defaults={
        'title': 'Si të Zgjidhni Makinën e Duhur për Udhëtimin Tuaj',
        'excerpt': 'Këshilla praktike për zgjedhjen e automjetit ideal sipas nevojave tuaja.',
        'body': '<p>Zgjedhja e makinës së duhur për udhëtimin tuaj varet nga disa faktorë kyç...</p>',
        'status': 'published',
        'author': owner2,
        'view_count': 142,
    }
)

print("\n✅ Seed i plotë! Tenantët e disponueshëm:")
print("   → http://restorant-adriatiku.localhost:8000  (Restorant, Pro)")
print("   → http://hertz-albania.localhost:8000        (Car Rental, Enterprise)")
print("   → http://klinika-shendeti.localhost:8000     (Klinikë, Pro)")
print("\n   ose me ?tenant= param:")
print("   → http://localhost:8000?tenant=restorant-adriatiku")
print("   → http://localhost:8000?tenant=hertz-albania")
print("   → http://localhost:8000?tenant=klinika-shendeti")
print("\n   Admin: http://localhost:8000/admin  →  admin@bizal.al / admin1234")
