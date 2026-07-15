import datetime
from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import User
from tenants.models import Tenant
from .models import Booking


def make_tenant(slug, plan='pro', active=True):
    return Tenant.objects.create(
        name=slug.replace('-', ' ').title(),
        slug=slug, plan=plan, is_active=active, business_type='restaurant',
    )


def make_user(email, tenant, role='customer'):
    return User.objects.create_user(
        email=email, password='pass1234', tenant=tenant, role=role,
    )


def make_booking(tenant, **kwargs):
    defaults = dict(
        booking_type='table_reservation',
        status='pending',
        start_date=datetime.date(2026, 9, 1),
        guest_name='Arben Hoxha',
        guest_email='arben@test.com',
        total_price=2000,
    )
    defaults.update(kwargs)
    return Booking.objects.create(tenant=tenant, **defaults)


class BookingCreateTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('testbiz')
        self.client.defaults['HTTP_HOST'] = 'testbiz.bizal.al'

    def test_anonymous_can_create_booking(self):
        resp = self.client.post('/api/bookings/', {
            'booking_type': 'table_reservation',
            'start_date': '2026-09-10',
            'guest_name': 'Besmir Koci',
            'guest_email': 'besmir@test.com',
            'guest_count': 3,
            'total_price': '1500.00',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['guest_name'], 'Besmir Koci')
        # SECURITY: total_price must NOT be accepted from the client. A table
        # reservation has no server-derivable resource price, so it defaults
        # to 0 rather than the '1500.00' the client tried to submit.
        self.assertEqual(str(resp.data['total_price']), '0.00')

    def test_booking_defaults_to_pending(self):
        resp = self.client.post('/api/bookings/', {
            'booking_type': 'table_reservation',
            'start_date': '2026-09-11',
            'guest_name': 'Lira Gashi',
            'guest_email': 'lira@test.com',
            'total_price': '800.00',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['status'], 'pending')
        # SECURITY: same as above — client-submitted total_price is ignored.
        self.assertEqual(str(resp.data['total_price']), '0.00')

    def test_booking_type_defaults_from_tenant_business_type(self):
        """booking_type is optional — the serializer fills it in based on
        the tenant's business_type (restaurant -> table_reservation)."""
        resp = self.client.post('/api/bookings/', {
            'start_date': '2026-09-12',
            'guest_name': 'Test', 'guest_email': 'test@test.com',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['booking_type'], 'table_reservation')


class BookingListTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('listbiz')
        self.other_tenant = make_tenant('otherbiz')
        self.owner = make_user('owner@listbiz.com', self.tenant, 'owner')
        self.customer = make_user('cust@listbiz.com', self.tenant, 'customer')
        self.client.defaults['HTTP_HOST'] = 'listbiz.bizal.al'

        self.bk1 = make_booking(self.tenant, guest_name='Alpha')
        self.bk2 = make_booking(self.tenant, guest_name='Beta')
        self.bk_other = make_booking(self.other_tenant, guest_name='Hidden')

    def test_owner_sees_all_tenant_bookings(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get('/api/bookings/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = [b['guest_name'] for b in ((resp.data['results'] if isinstance(resp.data, dict) else resp.data))]
        self.assertIn('Alpha', names)
        self.assertIn('Beta', names)
        self.assertNotIn('Hidden', names)

    def test_customer_only_sees_own_bookings(self):
        # Create a booking linked to the customer user
        bk_mine = make_booking(self.tenant, guest_name='Mine')
        bk_mine.user = self.customer
        bk_mine.save()
        self.client.force_authenticate(user=self.customer)
        resp = self.client.get('/api/bookings/')
        names = [b['guest_name'] for b in ((resp.data['results'] if isinstance(resp.data, dict) else resp.data))]
        self.assertIn('Mine', names)
        self.assertNotIn('Alpha', names)  # belongs to no user → not visible to customer

    def test_unauthenticated_cannot_list(self):
        resp = self.client.get('/api/bookings/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class BookingAdminUpdateTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('updatebiz')
        self.owner = make_user('owner@updatebiz.com', self.tenant, 'owner')
        self.customer = make_user('cust@updatebiz.com', self.tenant, 'customer')
        self.booking = make_booking(self.tenant)
        self.client.defaults['HTTP_HOST'] = 'updatebiz.bizal.al'

    def test_owner_can_confirm_booking(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(
            f'/api/bookings/{self.booking.pk}/admin-update/', {'status': 'confirmed'}
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'confirmed')

    def test_owner_can_add_internal_notes(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(
            f'/api/bookings/{self.booking.pk}/admin-update/',
            {'internal_notes': 'VIP table requested.'},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.internal_notes, 'VIP table requested.')

    def test_customer_cannot_admin_update(self):
        self.client.force_authenticate(user=self.customer)
        resp = self.client.patch(
            f'/api/bookings/{self.booking.pk}/admin-update/', {'status': 'confirmed'}
        )
        self.assertIn(resp.status_code, [
            status.HTTP_403_FORBIDDEN, status.HTTP_401_UNAUTHORIZED
        ])

    def test_wrong_tenant_owner_cannot_update(self):
        other_tenant = make_tenant('wrongbiz')
        other_owner = make_user('owner@wrongbiz.com', other_tenant, 'owner')
        self.client.force_authenticate(user=other_owner)
        resp = self.client.patch(
            f'/api/bookings/{self.booking.pk}/admin-update/', {'status': 'confirmed'}
        )
        # Permission denied — booking belongs to a different tenant
        self.assertIn(resp.status_code, [
            status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND
        ])


class BookingCancelTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('cancelbiz')
        self.customer = make_user('cust@cancelbiz.com', self.tenant, 'customer')
        self.client.defaults['HTTP_HOST'] = 'cancelbiz.bizal.al'

    def test_customer_can_cancel_own_booking(self):
        bk = make_booking(self.tenant, status='confirmed')
        bk.user = self.customer
        bk.save()
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post(f'/api/bookings/{bk.pk}/cancel/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        bk.refresh_from_db()
        self.assertEqual(bk.status, 'cancelled')

    def test_cannot_cancel_already_cancelled(self):
        bk = make_booking(self.tenant, status='cancelled')
        bk.user = self.customer
        bk.save()
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post(f'/api/bookings/{bk.pk}/cancel/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_cancel_completed(self):
        bk = make_booking(self.tenant, status='completed')
        bk.user = self.customer
        bk.save()
        self.client.force_authenticate(user=self.customer)
        resp = self.client.post(f'/api/bookings/{bk.pk}/cancel/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class BookingOwnershipSecurityTest(TestCase):
    """Tests for the ownership checks added during the security audit."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('secbiz')
        self.customer1 = make_user('c1@secbiz.com', self.tenant, 'customer')
        self.customer2 = make_user('c2@secbiz.com', self.tenant, 'customer')
        self.client.defaults['HTTP_HOST'] = 'secbiz.bizal.al'

    def test_customer_cannot_cancel_other_customers_booking(self):
        """A customer must not be able to cancel a booking they don't own."""
        bk = make_booking(self.tenant, status='confirmed')
        bk.user = self.customer1
        bk.save()
        self.client.force_authenticate(user=self.customer2)
        resp = self.client.post(f'/api/bookings/{bk.pk}/cancel/')
        self.assertEqual(resp.status_code, 403)
        bk.refresh_from_db()
        self.assertEqual(bk.status, 'confirmed')  # unchanged

    def test_customer_cannot_patch_other_customers_booking(self):
        """BookingDetailView PATCH must be scoped to the requesting user."""
        bk = make_booking(self.tenant, status='pending')
        bk.user = self.customer1
        bk.save()
        self.client.force_authenticate(user=self.customer2)
        resp = self.client.patch(f'/api/bookings/{bk.pk}/', {'guest_count': 99})
        self.assertEqual(resp.status_code, 404)  # not visible → 404

    def test_admin_invalid_status_rejected(self):
        """admin-update must reject statuses not in STATUS_CHOICES."""
        owner = make_user('owner@secbiz.com', self.tenant, 'owner')
        bk = make_booking(self.tenant)
        self.client.force_authenticate(user=owner)
        resp = self.client.patch(
            f'/api/bookings/{bk.pk}/admin-update/', {'status': 'typo_status'}
        )
        self.assertEqual(resp.status_code, 400)


class BookingBusinessHoursTest(TestCase):
    """Monday-Saturday and Sunday can have different posted hours — the
    start_time check must be resolved per the actual weekday being booked,
    not by merging every range in business_hours into one min/max window."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('hoursbiz')
        self.tenant.business_hours = {
            'E Hënë - E Shtunë': '09:00 - 20:00',
            'E Diel': '10:00 - 16:00',
        }
        self.tenant.save()
        self.client.defaults['HTTP_HOST'] = 'hoursbiz.bizal.al'

    def _post(self, start_date, start_time):
        return self.client.post('/api/bookings/', {
            'booking_type': 'appointment',
            'start_date': start_date,
            'start_time': start_time,
            'guest_name': 'Test Guest',
            'guest_email': 'guest@test.com',
        })

    def test_saturday_within_weekday_hours_accepted(self):
        resp = self._post('2026-09-05', '19:00')  # Saturday, within 09:00-20:00
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_sunday_within_weekday_hours_but_after_sunday_close_rejected(self):
        """19:00 is inside the Mon-Sat window but the tenant closes at 16:00
        on Sunday — this is exactly the case the old merged min/max check
        used to get wrong."""
        resp = self._post('2026-09-06', '19:00')  # Sunday
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_sunday_within_sunday_hours_accepted(self):
        resp = self._post('2026-09-06', '11:00')  # Sunday, within 10:00-16:00
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_monday_before_open_rejected(self):
        resp = self._post('2026-09-07', '07:00')  # Monday, before 09:00
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_day_with_no_entry_treated_as_closed(self):
        self.tenant.business_hours = {'E Hënë - E Premte': '09:00 - 18:00'}
        self.tenant.save()
        resp = self._post('2026-09-06', '11:00')  # Sunday, not in business_hours at all
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


# ── SECURITY FIX: server-computed total_price ──────────────────────────────
# total_price used to be a plain writable field on BookingSerializer, so any
# client (including an anonymous POST) could submit an arbitrary amount that
# later fed straight into award_points() via admin_update_booking. These
# tests lock in that total_price is now always computed server-side from the
# actual priced resource (Service.price, RentalItem.price_per_day, or
# RoomType.base_price), regardless of what the client sends.

class BookingPriceComputationTest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_appointment_price_computed_from_service_ignores_client_value(self):
        from appointments.models import Service
        tenant = make_tenant('clinicbiz')
        tenant.business_type = 'clinic'
        tenant.save()
        self.client.defaults['HTTP_HOST'] = 'clinicbiz.bizal.al'
        service = Service.objects.create(tenant=tenant, name='Checkup', price=Decimal('3500.00'))

        resp = self.client.post('/api/bookings/', {
            'booking_type': 'appointment',
            'resource_type': 'service',
            'resource_id': str(service.id),
            'start_date': '2026-09-10',
            'guest_name': 'Pacient Test',
            'guest_email': 'pacient@test.com',
            'total_price': '99999.00',  # attempted override — must be ignored
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(str(resp.data['total_price'])), Decimal('3500.00'))

    def test_rental_price_computed_from_price_per_day_times_days_with_discount(self):
        from rentals.models import RentalItem
        tenant = make_tenant('carbiz')
        tenant.business_type = 'car_rental'
        tenant.save()
        self.client.defaults['HTTP_HOST'] = 'carbiz.bizal.al'
        item = RentalItem.objects.create(
            tenant=tenant, name='Golf 7', rental_type='car',
            price_per_day=Decimal('4000.00'), status='available',
        )

        # 2026-09-10 through 2026-09-13 inclusive = 4 days (matches the
        # storefront's calcRentalDays, which is start-day inclusive).
        # 4 days falls in the 3-6 day bracket -> 5% length discount, mirroring
        # calcRentalDiscountPct() in the booking modal: 16000 * 0.95 = 15200.
        resp = self.client.post('/api/bookings/', {
            'booking_type': 'rental',
            'resource_type': 'rental_item',
            'resource_id': str(item.id),
            'start_date': '2026-09-10',
            'end_date': '2026-09-13',
            'guest_name': 'Klient Test',
            'guest_email': 'klient@test.com',
            'total_price': '1.00',  # attempted override — must be ignored
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(str(resp.data['total_price'])), Decimal('15200.00'))

    def test_room_type_resolves_to_available_room_and_computed_price(self):
        from hotels.models import RoomType, Room
        tenant = make_tenant('hotelbiz')
        tenant.business_type = 'hotel'
        tenant.save()
        self.client.defaults['HTTP_HOST'] = 'hotelbiz.bizal.al'
        rt = RoomType.objects.create(tenant=tenant, name='Deluxe', base_price=Decimal('8000.00'))
        Room.objects.create(tenant=tenant, room_type=rt, room_number='101', status='available')

        resp = self.client.post('/api/bookings/', {
            'booking_type': 'room_booking',
            'resource_type': 'room_type',
            'resource_id': str(rt.id),
            'start_date': '2026-09-10',
            'end_date': '2026-09-12',  # 2 nights
            'guest_name': 'Mysafir Test',
            'guest_email': 'mysafir@test.com',
            'total_price': '1.00',  # attempted override — must be ignored
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(str(resp.data['total_price'])), Decimal('16000.00'))
        # resource_type/resource_id should have been rewritten to the concrete room
        self.assertEqual(resp.data['resource_type'], 'room')

    def test_room_type_with_no_available_room_rejected(self):
        from hotels.models import RoomType, Room
        tenant = make_tenant('hotelbiz2')
        tenant.business_type = 'hotel'
        tenant.save()
        self.client.defaults['HTTP_HOST'] = 'hotelbiz2.bizal.al'
        rt = RoomType.objects.create(tenant=tenant, name='Suite', base_price=Decimal('10000.00'))
        Room.objects.create(tenant=tenant, room_type=rt, room_number='201', status='maintenance')

        resp = self.client.post('/api/bookings/', {
            'booking_type': 'room_booking',
            'resource_type': 'room_type',
            'resource_id': str(rt.id),
            'start_date': '2026-09-10',
            'end_date': '2026-09-12',
            'guest_name': 'Mysafir Test',
            'guest_email': 'mysafir2@test.com',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_table_reservation_has_no_derivable_price_defaults_zero(self):
        tenant = make_tenant('restobiz')
        self.client.defaults['HTTP_HOST'] = 'restobiz.bizal.al'
        resp = self.client.post('/api/bookings/', {
            'booking_type': 'table_reservation',
            'start_date': '2026-09-10',
            'guest_name': 'Test',
            'guest_email': 'test@test.com',
            'total_price': '5000.00',  # attempted override — must be ignored
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(str(resp.data['total_price'])), Decimal('0.00'))


class AdminSetTotalPriceTest(TestCase):
    """
    admin_update_booking now accepts an explicit total_price — but only for
    staff/owner (the view already enforces HasTenantRole), covering the
    table-reservation / class / event case where there's no priced resource
    for the server to derive an amount from.
    """
    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('adminpricebiz')
        self.owner = make_user('owner@adminpricebiz.com', self.tenant, 'owner')
        self.client.defaults['HTTP_HOST'] = 'adminpricebiz.bizal.al'
        self.booking = make_booking(self.tenant, total_price=0)

    def test_owner_can_set_total_price(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(f'/api/bookings/{self.booking.id}/admin-update/', {
            'total_price': '2500.00',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.total_price, Decimal('2500.00'))

    def test_negative_total_price_rejected(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(f'/api/bookings/{self.booking.id}/admin-update/', {
            'total_price': '-100.00',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
