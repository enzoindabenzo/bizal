"""
tenant_isolation_factories.py
===============================
Registry of {Model: factory(tenant) -> instance} used by
dynamic_tenant_isolation_test.py to actually create a real row for a real
tenant, so the dynamic runner can probe "can tenant B fetch tenant A's row
by id?" against a live Django test database instead of just reading source
code.

WHY A REGISTRY INSTEAD OF GENERIC INTROSPECTION
------------------------------------------------
Every tenant-scoped model inherits TenantScopedUUIDModel (uuid pk + tenant
FK, see bizal/base_models.py), so in principle a generic factory could
walk model._meta.fields and stuff in a minimal value for every
non-nullable field. In practice several models have DB-level constraints
(CheckConstraint on date ranges, unique_together, FK validators like
validate_image_type) that a blind generic factory would trip over and
silently miscreate — which would make the isolation probe itself
unreliable. An explicit, hand-written factory per model is more code but
means every object this test creates is a realistic, valid row, and a
FAIL from this suite always means a real isolation problem, never a
factory artifact.

Deliberately NOT registered here (dynamic_tenant_isolation_test.py will
report these as SKIP, with this reason): any model without an entry
below. That is the intended failure mode for "we haven't taught the
isolation probe about this model yet" — it is visible in the test output
(see the SKIP section of the report) rather than silently absent.
"""
from __future__ import annotations

import datetime
import uuid
from decimal import Decimal


def _menu_item(tenant):
    from menu.models import MenuCategory, MenuItem
    cat = MenuCategory.objects.create(tenant=tenant, name='Isolation Probe Category')
    return MenuItem.objects.create(
        tenant=tenant, category=cat, name='Isolation Probe Item', price=Decimal('10.00'),
    )


def _menu_category(tenant):
    from menu.models import MenuCategory
    return MenuCategory.objects.create(tenant=tenant, name='Isolation Probe Category')


def _product(tenant):
    from inventory.models import Product, ProductCategory
    cat = ProductCategory.objects.create(tenant=tenant, name='Probe Cat', slug=f'probe-cat-{uuid.uuid4().hex[:8]}')
    return Product.objects.create(tenant=tenant, category=cat, name='Probe Product', price=Decimal('5.00'))


def _product_category(tenant):
    from inventory.models import ProductCategory
    return ProductCategory.objects.create(tenant=tenant, name='Probe Cat', slug=f'probe-cat-{uuid.uuid4().hex[:8]}')


def _order(tenant):
    from orders.models import Order
    return Order.objects.create(tenant=tenant, order_type='takeaway', guest_name='Probe Guest')


def _booking(tenant):
    from bookings.models import Booking
    return Booking.objects.create(
        tenant=tenant, booking_type='table_reservation', guest_name='Probe Guest',
        start_date=datetime.date.today() + datetime.timedelta(days=1),
    )


def _service_provider(tenant):
    from appointments.models import ServiceProvider
    return ServiceProvider.objects.create(tenant=tenant, name='Probe Provider')


def _service(tenant):
    from appointments.models import Service
    return Service.objects.create(tenant=tenant, name='Probe Service', price=Decimal('20.00'))


def _appointment(tenant):
    from appointments.models import Appointment
    return Appointment.objects.create(
        tenant=tenant, guest_name='Probe Guest',
        date=datetime.date.today() + datetime.timedelta(days=1),
        start_time=datetime.time(10, 0), end_time=datetime.time(10, 30),
    )


def _room_type(tenant):
    from hotels.models import RoomType
    return RoomType.objects.create(tenant=tenant, name='Probe Room Type', base_price=Decimal('50.00'))


def _room(tenant):
    from hotels.models import Room
    rt = _room_type(tenant)
    return Room.objects.create(tenant=tenant, room_type=rt, room_number='P1')


def _rental_item(tenant):
    from rentals.models import RentalItem
    return RentalItem.objects.create(
        tenant=tenant, name='Probe Rental', rental_type='equipment', price_per_day=Decimal('15.00'),
    )


def _lead(tenant):
    from crm.models import Lead
    return Lead.objects.create(tenant=tenant, name='Probe Lead')


def _lead_note(tenant):
    from crm.models import LeadNote
    lead = _lead(tenant)
    return LeadNote.objects.create(tenant=tenant, lead=lead, note='Probe note')


def _blog_post(tenant):
    from blog.models import BlogPost
    return BlogPost.objects.create(tenant=tenant, title='Probe Post', body='Probe body')


def _review(tenant):
    from reviews.models import Review
    from accounts.models import User
    reviewer = User.objects.create_user(
        email=f'probe-reviewer-{uuid.uuid4().hex[:8]}@example.com', password='pass1234',
        tenant=tenant, role='customer',
    )
    return Review.objects.create(tenant=tenant, user=reviewer, rating=5, comment='Probe review')


def _room_booking(tenant):
    # hotels.RoomBooking has no `tenant` FK of its own — it's scoped
    # transitively via room.tenant (see RoomBookingDetailView.get_queryset:
    # `room__tenant=self.request.tenant`). The factory still needs a real
    # Booking row (RoomBooking.booking is a required OneToOneField), so
    # build the same minimal Booking _booking() does, just typed as a room
    # booking instead of a table reservation.
    from hotels.models import RoomBooking
    from bookings.models import Booking
    room = _room(tenant)
    booking = Booking.objects.create(
        tenant=tenant, booking_type='room_booking', guest_name='Probe Guest',
        start_date=datetime.date.today() + datetime.timedelta(days=1),
        end_date=datetime.date.today() + datetime.timedelta(days=2),
    )
    return RoomBooking.objects.create(room=room, booking=booking)


def _invoice(tenant):
    from billing.models import Invoice
    return Invoice.objects.create(tenant=tenant, customer_name='Probe Customer', status='draft')


def _contact_message(tenant):
    from contact.models import ContactMessage
    return ContactMessage.objects.create(
        tenant=tenant, name='Probe Sender', email='probe-sender@example.com', message='Probe message',
    )


def _staff_member(tenant):
    from staff.models import StaffMember
    from accounts.models import User
    user = User.objects.create_user(
        email=f'probe-staff-{uuid.uuid4().hex[:8]}@example.com', password='pass1234',
        tenant=tenant, role='staff',
    )
    return StaffMember.objects.create(tenant=tenant, user=user, role='staff')


def _staff_schedule(tenant):
    from staff.models import StaffSchedule
    staff = _staff_member(tenant)
    return StaffSchedule.objects.create(
        tenant=tenant, staff=staff, day='monday',
        start_time=datetime.time(9, 0), end_time=datetime.time(17, 0),
    )


def _storefront_page(tenant):
    from storefront.models import StorefrontPage
    return StorefrontPage.objects.create(
        tenant=tenant, slug=f'probe-page-{uuid.uuid4().hex[:8]}', title='Probe Page', body='Probe body',
    )


def _page_section(tenant):
    from storefront.models import PageSection
    return PageSection.objects.create(tenant=tenant, page_key='overview', section_type='text', title='Probe Section')


def _hero_slide(tenant):
    from storefront.models import HeroSlide
    return HeroSlide.objects.create(tenant=tenant, title='Probe Slide')


def _customer_subscription(tenant):
    from subscriptions.models import CustomerSubscription
    from accounts.models import User
    customer = User.objects.create_user(
        email=f'probe-subscriber-{uuid.uuid4().hex[:8]}@example.com', password='pass1234',
        tenant=tenant, role='customer',
    )
    return CustomerSubscription.objects.create(
        tenant=tenant, customer=customer, name='Probe Plan', price=Decimal('9.99'),
    )


def _tenant_location(tenant):
    from tenants.models import TenantLocation
    return TenantLocation.objects.create(tenant=tenant, name='Probe Branch')


FACTORIES = {
    'menu.MenuItem': _menu_item,
    'menu.MenuCategory': _menu_category,
    'inventory.Product': _product,
    'inventory.ProductCategory': _product_category,
    'orders.Order': _order,
    'bookings.Booking': _booking,
    'appointments.ServiceProvider': _service_provider,
    'appointments.Service': _service,
    'appointments.Appointment': _appointment,
    'hotels.RoomType': _room_type,
    'hotels.Room': _room,
    'rentals.RentalItem': _rental_item,
    'crm.Lead': _lead,
    'crm.LeadNote': _lead_note,
    'blog.BlogPost': _blog_post,
    'reviews.Review': _review,
    'hotels.RoomBooking': _room_booking,
    'billing.Invoice': _invoice,
    'contact.ContactMessage': _contact_message,
    'staff.StaffMember': _staff_member,
    'staff.StaffSchedule': _staff_schedule,
    'storefront.StorefrontPage': _storefront_page,
    'storefront.PageSection': _page_section,
    'storefront.HeroSlide': _hero_slide,
    'subscriptions.CustomerSubscription': _customer_subscription,
    'tenants.TenantLocation': _tenant_location,

    # Deliberately NOT registered:
    #
    # hotels.SeasonalPrice — SeasonalPriceView is a ListCreateAPIView at
    # room-types/<uuid:pk>/seasonal-prices/, where <pk> is the PARENT
    # RoomType's id (get_queryset filters `room_type_id=self.kwargs['pk']`),
    # not a SeasonalPrice's own id. The route only happens to satisfy this
    # probe's "leaf segment is literally named pk" check because of that
    # naming coincidence. If a factory were registered here, the probe would
    # substitute the SeasonalPrice's own pk into the URL as if it were a
    # RoomType id, which — since a SeasonalPrice UUID essentially never
    # collides with a real RoomType UUID — resolves to an empty
    # RoomType.DoesNotExist match. get_queryset then returns SeasonalPrice
    # objects.none() (an empty list, not a 404), which is a 200 on a
    # ListAPIView. Because this view is NOT AllowAny, that 200 would be
    # misclassified as a LEAK on every run — a false positive, not a real
    # finding. This is a genuine blind spot in the probe's route-shape
    # detection (see the RetrieveAPIView check in _view_is_detail_view()
    # below), not a coverage gap that a factory can fix; it needs a real
    # fix to the harness, tracked separately, before this route can be
    # tested safely.
    #
    # reviews.PlatformReview — not tenant-scoped at all (TimeStampedModel,
    # no `tenant` FK); it's a platform-wide review of BizAL itself, gated by
    # IsAdminUser, not by tenant. A cross-TENANT probe has nothing to test
    # here — the relevant access-control question is "is this user platform
    # staff", which is orthogonal to tenant isolation and already covered by
    # check_tenant_isolation.py's separate [admin-gated] category.
}